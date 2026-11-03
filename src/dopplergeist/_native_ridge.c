#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>
#include <string.h>

static int
get_vector(PyObject *object, Py_buffer *view)
{
    if (PyObject_GetBuffer(object, view, PyBUF_FORMAT | PyBUF_ND | PyBUF_STRIDES) < 0) {
        return -1;
    }
    if (view->ndim != 1 || view->itemsize != (Py_ssize_t)sizeof(double) ||
        view->shape == NULL || view->strides == NULL || view->format == NULL ||
        strcmp(view->format, "d") != 0) {
        PyBuffer_Release(view);
        view->obj = NULL;
        PyErr_SetString(PyExc_TypeError, "expected a native float64 vector");
        return -1;
    }
    return 0;
}

static double
at(const Py_buffer *view, Py_ssize_t index)
{
    double value;
    memcpy(&value, (const char *)view->buf + index * view->strides[0], sizeof(value));
    return value;
}

static double
clip(double value, double lower, double upper)
{
    if (value < lower) return lower;
    if (value > upper) return upper;
    return value;
}

/* Match NumPy's float64 reduction tree rather than a serial running sum. */
static double
pairwise_sum(const double *values, Py_ssize_t count)
{
    if (count < 8) {
        double result = -0.0;
        for (Py_ssize_t i = 0; i < count; ++i) result += values[i];
        return result;
    }
    if (count <= 128) {
        double r0 = values[0], r1 = values[1], r2 = values[2], r3 = values[3];
        double r4 = values[4], r5 = values[5], r6 = values[6], r7 = values[7];
        Py_ssize_t i = 8;
        for (; i < count - count % 8; i += 8) {
            r0 += values[i]; r1 += values[i + 1];
            r2 += values[i + 2]; r3 += values[i + 3];
            r4 += values[i + 4]; r5 += values[i + 5];
            r6 += values[i + 6]; r7 += values[i + 7];
        }
        double result = ((r0 + r1) + (r2 + r3)) + ((r4 + r5) + (r6 + r7));
        for (; i < count; ++i) result += values[i];
        return result;
    }
    Py_ssize_t half = count / 2;
    half -= half % 8;
    return pairwise_sum(values, half) + pairwise_sum(values + half, count - half);
}

static double
scalar_square(double value)
{
    /* Python float ** 2 calls libm pow. Keep that rounding, not x * x. */
    volatile double exponent = 2.0;
    return pow(value, exponent);
}

static void
source_fit(const Py_buffer *factor, const Py_buffer *u, const Py_buffer *y,
           const double *effective, double *scratch, Py_ssize_t count,
           double lower, double upper, double cap, double prior,
           double *f0, double *drift)
{
    *f0 = NAN;
    *drift = NAN;
    double *a_terms = scratch, *r_terms = scratch + count;
    double *b_terms = scratch + 2 * count, *d_terms = scratch + 3 * count;
    double *s_terms = scratch + 4 * count;

    for (Py_ssize_t i = 0; i < count; ++i) {
        double fi = at(factor, i), ui = at(u, i), yi = at(y, i);
        double wi = effective[i], factor2 = fi * fi;
        double wf = wi * fi, wf2 = wi * factor2;
        a_terms[i] = wf2;
        r_terms[i] = wf * yi;
        if (cap != 0.0) {
            b_terms[i] = wf2 * ui;
            d_terms[i] = wf2 * (ui * ui);
            s_terms[i] = (wf * ui) * yi;
        }
    }
    double a = 0.0 + pairwise_sum(a_terms, count);
    double r = 0.0 + pairwise_sum(r_terms, count);
    if (!(a > 0.0) || !isfinite(a) || !isfinite(r) || !isfinite(prior)) return;
    if (cap == 0.0) {
        *f0 = clip(r / a, lower, upper);
        *drift = 0.0;
        return;
    }

    double b = 0.0 + pairwise_sum(b_terms, count);
    double d = (0.0 + pairwise_sum(d_terms, count)) + prior;
    double s = 0.0 + pairwise_sum(s_terms, count);
    double determinant = a * d - b * b;
    if (!(determinant > 0.0) || !isfinite(determinant) ||
        !isfinite(b) || !isfinite(d) || !isfinite(s)) return;
    double unconstrained_f = (r * d - s * b) / determinant;
    double unconstrained_drift = (s * a - r * b) / determinant;
    if (!isfinite(unconstrained_f) || !isfinite(unconstrained_drift)) return;
    if (lower <= unconstrained_f && unconstrained_f <= upper && fabs(unconstrained_drift) <= cap) {
        *f0 = unconstrained_f;
        *drift = unconstrained_drift;
        return;
    }

    double candidate_f[4] = {lower, upper, 0.0, 0.0};
    double candidate_drift[4] = {
        clip((s - b * lower) / d, -cap, cap),
        clip((s - b * upper) / d, -cap, cap), -cap, cap
    };
    candidate_f[2] = clip((r - b * candidate_drift[2]) / a, lower, upper);
    candidate_f[3] = clip((r - b * candidate_drift[3]) / a, lower, upper);

    double best_cost = INFINITY;
    for (int candidate = 0; candidate < 4; ++candidate) {
        for (Py_ssize_t i = 0; i < count; ++i) {
            double fi = at(factor, i), ui = at(u, i), yi = at(y, i);
            double residual = fi * (candidate_f[candidate] + candidate_drift[candidate] * ui) - yi;
            double residual2 = residual * residual;
            scratch[i] = effective[i] * residual2;
        }
        double cost = (0.0 + pairwise_sum(scratch, count)) +
            prior * (candidate_drift[candidate] * candidate_drift[candidate]);
        if (!isfinite(cost)) {
            *f0 = NAN;
            *drift = NAN;
            return;
        }
        if (cost < best_cost) {
            best_cost = cost;
            *f0 = candidate_f[candidate];
            *drift = candidate_drift[candidate];
        }
    }
}

static PyObject *
fit_irls(PyObject *self, PyObject *args)
{
    PyObject *objects[4];
    double lower, upper, cap, sigma;
    Py_ssize_t independent_samples;
    Py_buffer views[4] = {{0}};
    int acquired = 0;
    double *effective = NULL;
    PyObject *result = NULL;

    if (!PyArg_ParseTuple(args, "OOOOddddn", &objects[0], &objects[1],
                          &objects[2], &objects[3], &lower, &upper, &cap,
                          &sigma, &independent_samples)) {
        return NULL;
    }
    for (int i = 0; i < 4; ++i) {
        if (get_vector(objects[i], &views[i]) < 0) goto done;
        ++acquired;
    }
    Py_ssize_t count = views[0].shape[0];
    if (count == 0 || views[1].shape[0] != count || views[2].shape[0] != count ||
        views[3].shape[0] != count || !isfinite(lower) || !isfinite(upper) ||
        lower > upper || !isfinite(cap) || cap < 0.0 || !isfinite(sigma) ||
        sigma <= 0.0 || independent_samples < 1) {
        PyErr_SetString(PyExc_ValueError, "invalid robust ridge-fit inputs");
        goto done;
    }
    if ((size_t)count > SIZE_MAX / (6 * sizeof(double))) {
        PyErr_NoMemory();
        goto done;
    }
    effective = PyMem_Malloc((size_t)count * 6 * sizeof(double));
    if (effective == NULL) {
        PyErr_NoMemory();
        goto done;
    }
    int valid = 1;
    for (Py_ssize_t i = 0; i < count; ++i) {
        double fi = at(&views[0], i), ui = at(&views[1], i);
        double yi = at(&views[2], i), wi = at(&views[3], i);
        if (!isfinite(fi) || fi <= 0.0 || !isfinite(ui) || !isfinite(yi) ||
            !isfinite(wi) || wi <= 0.0) {
            valid = 0;
            break;
        }
        effective[i] = wi;
    }
    if (!valid) {
        Py_INCREF(Py_None);
        result = Py_None;
        goto done;
    }

    double f0 = NAN, drift = NAN, loss = NAN, rmse = NAN, outlier_fraction = NAN;
    double *scratch = effective + count;
    double prior = cap == 0.0 ? 0.0 : scalar_square(2.0 * sigma / cap);
    double loss_scale = 2.0 * scalar_square(sigma);
    valid = 1;
    Py_BEGIN_ALLOW_THREADS
    for (int iteration = 0; iteration < 6; ++iteration) {
        source_fit(&views[0], &views[1], &views[2], effective, scratch, count,
                   lower, upper, cap, prior, &f0, &drift);
        if (!isfinite(f0) || !isfinite(drift)) {
            valid = 0;
            break;
        }
        if (iteration == 5) break;
        for (Py_ssize_t i = 0; i < count; ++i) {
            double residual = at(&views[0], i) * (f0 + drift * at(&views[1], i)) - at(&views[2], i);
            double scaled = residual / sigma;
            if (!isfinite(residual)) {
                valid = 0;
                break;
            }
            effective[i] = at(&views[3], i) / sqrt(1.0 + scaled * scaled);
        }
        if (!valid) break;
    }
    if (valid) {
        double *loss_terms = scratch, *squared_terms = scratch + count;
        double *outlier_terms = scratch + 2 * count, *weight_terms = scratch + 3 * count;
        for (Py_ssize_t i = 0; i < count; ++i) {
            double residual = at(&views[0], i) * (f0 + drift * at(&views[1], i)) - at(&views[2], i);
            double wi = at(&views[3], i), scaled = residual / sigma;
            loss_terms[i] = (loss_scale * (sqrt(1.0 + scaled * scaled) - 1.0)) * wi;
            squared_terms[i] = (residual * residual) * wi;
            outlier_terms[i] = fabs(residual) > 3.0 * sigma ? wi : 0.0;
            weight_terms[i] = wi;
        }
        double loss_sum = 0.0 + pairwise_sum(loss_terms, count);
        double squared_sum = 0.0 + pairwise_sum(squared_terms, count);
        double outlier_sum = 0.0 + pairwise_sum(outlier_terms, count);
        double weight_sum = 0.0 + pairwise_sum(weight_terms, count);
        double penalty = cap ? scalar_square(2.0 * sigma * drift / cap) /
                               (double)independent_samples : 0.0;
        loss = loss_sum / weight_sum;
        rmse = sqrt(squared_sum / weight_sum);
        outlier_fraction = outlier_sum / weight_sum;
        loss = -sqrt(loss + penalty);
        valid = isfinite(loss) && isfinite(rmse) && isfinite(outlier_fraction);
    }
    Py_END_ALLOW_THREADS

    if (valid) result = Py_BuildValue("(ddddd)", loss, f0, drift, rmse, outlier_fraction);
    else {
        Py_INCREF(Py_None);
        result = Py_None;
    }

done:
    PyMem_Free(effective);
    for (int i = 0; i < acquired; ++i) PyBuffer_Release(&views[i]);
    return result;
}

static PyMethodDef methods[] = {
    {"fit_irls", fit_irls, METH_VARARGS, "Run six robust ridge-fit iterations in C."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_native_ridge", NULL, -1, methods
};

PyMODINIT_FUNC
PyInit__native_ridge(void)
{
    return PyModule_Create(&module);
}
