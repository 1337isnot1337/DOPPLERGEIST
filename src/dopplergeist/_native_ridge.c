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

static void
source_fit(const Py_buffer *factor, const Py_buffer *u, const Py_buffer *y,
           const double *effective, Py_ssize_t count,
           double lower, double upper, double cap, double sigma,
           double *f0, double *drift)
{
    double a = 0.0, r = 0.0, b = 0.0, d = 0.0, s = 0.0;
    double prior = cap == 0.0 ? 0.0 : (2.0 * sigma / cap) * (2.0 * sigma / cap);

    for (Py_ssize_t i = 0; i < count; ++i) {
        double fi = at(factor, i), ui = at(u, i), yi = at(y, i);
        double wi = effective[i], factor2 = fi * fi;
        double wf = wi * fi, wf2 = wi * factor2;
        a += wf2;
        r += wf * yi;
        if (cap != 0.0) {
            b += wf2 * ui;
            d += wf2 * ui * ui;
            s += wf * ui * yi;
        }
    }
    if (cap == 0.0) {
        *f0 = clip(r / a, lower, upper);
        *drift = 0.0;
        return;
    }

    d += prior;
    double determinant = a * d - b * b;
    double unconstrained_f = (r * d - s * b) / determinant;
    double unconstrained_drift = (s * a - r * b) / determinant;
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
        double cost = prior * candidate_drift[candidate] * candidate_drift[candidate];
        for (Py_ssize_t i = 0; i < count; ++i) {
            double fi = at(factor, i), ui = at(u, i), yi = at(y, i);
            double residual = fi * (candidate_f[candidate] + candidate_drift[candidate] * ui) - yi;
            double residual2 = residual * residual;
            cost += effective[i] * residual2;
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
    effective = PyMem_Malloc((size_t)count * sizeof(double));
    if (effective == NULL) {
        PyErr_NoMemory();
        goto done;
    }
    int valid = 1;
    for (Py_ssize_t i = 0; i < count; ++i) {
        double fi = at(&views[0], i), ui = at(&views[1], i);
        double yi = at(&views[2], i), wi = at(&views[3], i);
        if (!isfinite(fi) || !isfinite(ui) || !isfinite(yi) || !isfinite(wi) || wi <= 0.0) {
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
    valid = 1;
    Py_BEGIN_ALLOW_THREADS
    for (int iteration = 0; iteration < 6; ++iteration) {
        source_fit(&views[0], &views[1], &views[2], effective, count,
                   lower, upper, cap, sigma, &f0, &drift);
        if (!isfinite(f0) || !isfinite(drift)) {
            valid = 0;
            break;
        }
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
        double loss_sum = 0.0, squared_sum = 0.0, outlier_sum = 0.0, weight_sum = 0.0;
        for (Py_ssize_t i = 0; i < count; ++i) {
            double residual = at(&views[0], i) * (f0 + drift * at(&views[1], i)) - at(&views[2], i);
            double wi = at(&views[3], i), scaled = residual / sigma;
            loss_sum += wi * (2.0 * (sigma * sigma) * (sqrt(1.0 + scaled * scaled) - 1.0));
            squared_sum += wi * residual * residual;
            if (fabs(residual) > 3.0 * sigma) outlier_sum += wi;
            weight_sum += wi;
        }
        double penalty = cap ? (2.0 * sigma * drift / cap) * (2.0 * sigma * drift / cap) /
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
