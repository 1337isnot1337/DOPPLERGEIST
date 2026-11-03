#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>
#include <stdint.h>
#include <string.h>

typedef struct {
    unsigned long long scalar_calls, scalar_successes;
    unsigned long long batch_calls, batch_rows, batch_successful_rows;
} ridge_state;

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

/* One numerical implementation serves scalar and batch entry points. The caller
 * owns the six scratch vectors, so a batch does not allocate them per clock. */
static int
fit_row(const Py_buffer *views, Py_ssize_t count, double lower, double upper,
        double cap, double sigma, Py_ssize_t independent_samples,
        double *effective, double *output)
{
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
    if (!valid) return 0;

    double f0 = NAN, drift = NAN, loss = NAN, rmse = NAN, outlier_fraction = NAN;
    double *scratch = effective + count;
    double prior = cap == 0.0 ? 0.0 : scalar_square(2.0 * sigma / cap);
    double loss_scale = 2.0 * scalar_square(sigma);
    valid = 1;
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
    output[0] = loss;
    output[1] = f0;
    output[2] = drift;
    output[3] = rmse;
    output[4] = outlier_fraction;
    return valid;
}

static PyObject *
fit_irls(PyObject *self, PyObject *args)
{
    ridge_state *state = PyModule_GetState(self);
    ++state->scalar_calls;
    PyObject *objects[4];
    double lower, upper, cap, sigma, output[5];
    Py_ssize_t independent_samples;
    Py_buffer views[4] = {{0}};
    int acquired = 0;
    double *effective = NULL;
    PyObject *result = NULL;

    if (!PyArg_ParseTuple(args, "OOOOddddn", &objects[0], &objects[1],
                          &objects[2], &objects[3], &lower, &upper, &cap,
                          &sigma, &independent_samples)) return NULL;
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
    int valid;
    Py_BEGIN_ALLOW_THREADS
    valid = fit_row(views, count, lower, upper, cap, sigma, independent_samples,
                    effective, output);
    Py_END_ALLOW_THREADS
    if (valid) {
        ++state->scalar_successes;
        result = Py_BuildValue("(ddddd)", output[0], output[1], output[2], output[3], output[4]);
    }
    else {
        Py_INCREF(Py_None);
        result = Py_None;
    }

done:
    PyMem_Free(effective);
    for (int i = 0; i < acquired; ++i) PyBuffer_Release(&views[i]);
    return result;
}

static int
get_matrix(PyObject *object, Py_buffer *view, int writable)
{
    int flags = PyBUF_FORMAT | PyBUF_ND | PyBUF_STRIDES;
    if (writable) flags |= PyBUF_WRITABLE;
    if (PyObject_GetBuffer(object, view, flags) < 0) return -1;
    if (view->ndim != 2 || view->itemsize != (Py_ssize_t)sizeof(double) ||
        view->shape == NULL || view->strides == NULL || view->format == NULL ||
        strcmp(view->format, "d") != 0 || !PyBuffer_IsContiguous(view, 'C')) {
        PyBuffer_Release(view);
        view->obj = NULL;
        PyErr_SetString(PyExc_TypeError, "expected a contiguous native float64 matrix");
        return -1;
    }
    return 0;
}

/* Include the holes between strided elements. A conservative span is enough to
 * prove that writing a result cannot change a later row's input. */
static int
buffer_span(const Py_buffer *view, uintptr_t *begin, uintptr_t *end)
{
    uintptr_t low = (uintptr_t)view->buf, high = low;
    if (view->buf == NULL || view->itemsize <= 0) return 0;
    for (int axis = 0; axis < view->ndim; ++axis) {
        if (view->shape[axis] <= 0 ||
            (view->suboffsets != NULL && view->suboffsets[axis] >= 0)) return 0;
        Py_ssize_t stride = view->strides[axis];
        uintptr_t magnitude = stride >= 0 ? (uintptr_t)stride :
                              (uintptr_t)(-(stride + 1)) + 1;
        uintptr_t steps = (uintptr_t)(view->shape[axis] - 1);
        if (magnitude != 0 && steps > UINTPTR_MAX / magnitude) return 0;
        uintptr_t offset = steps * magnitude;
        if (stride < 0) {
            if (low < offset) return 0;
            low -= offset;
        } else {
            if (high > UINTPTR_MAX - offset) return 0;
            high += offset;
        }
    }
    if (high > UINTPTR_MAX - (uintptr_t)view->itemsize) return 0;
    *begin = low;
    *end = high + (uintptr_t)view->itemsize;
    return 1;
}

static PyObject *
fit_irls_batch(PyObject *self, PyObject *args)
{
    ridge_state *state = PyModule_GetState(self);
    ++state->batch_calls;
    PyObject *objects[6];
    Py_buffer views[6] = {{0}};
    double lower, upper, sigma;
    Py_ssize_t independent_samples;
    int acquired = 0, valid = 1;
    double *scratch = NULL;
    PyObject *result = NULL;
    if (!PyArg_ParseTuple(args, "OOOOOdddnO", &objects[0], &objects[1], &objects[2],
                          &objects[3], &objects[4], &lower, &upper, &sigma,
                          &independent_samples, &objects[5])) return NULL;
    for (int i = 0; i < 6; ++i) {
        int status = (i < 2 || i == 5) ? get_matrix(objects[i], &views[i], i == 5) :
                                               get_vector(objects[i], &views[i]);
        if (status < 0) goto done;
        ++acquired;
    }
    Py_ssize_t rows = views[0].shape[0], count = views[0].shape[1];
    if (rows == 0 || count == 0 || views[1].shape[0] != rows || views[1].shape[1] != count ||
        views[2].shape[0] != count || views[3].shape[0] != count || views[4].shape[0] != rows ||
        views[5].shape[0] != rows || views[5].shape[1] != 5 ||
        !isfinite(lower) || !isfinite(upper) || lower > upper ||
        !isfinite(sigma) || sigma <= 0.0 || independent_samples < 1) {
        PyErr_SetString(PyExc_ValueError, "invalid robust ridge-fit batch inputs");
        goto done;
    }
    uintptr_t output_begin, output_end;
    if (!buffer_span(&views[5], &output_begin, &output_end)) {
        PyErr_SetString(PyExc_ValueError, "unsupported robust ridge-fit output buffer");
        goto done;
    }
    for (int i = 0; i < 5; ++i) {
        uintptr_t input_begin, input_end;
        if (!buffer_span(&views[i], &input_begin, &input_end) ||
            (output_begin < input_end && input_begin < output_end)) {
            PyErr_SetString(PyExc_ValueError, "robust ridge-fit output must not overlap inputs");
            goto done;
        }
    }
    if ((size_t)count > SIZE_MAX / (6 * sizeof(double))) {
        PyErr_NoMemory();
        goto done;
    }
    scratch = PyMem_Malloc((size_t)count * 6 * sizeof(double));
    if (scratch == NULL) {
        PyErr_NoMemory();
        goto done;
    }
    Py_buffer row_views[4] = {views[0], views[1], views[2], views[3]};
    row_views[0].strides = views[0].strides + 1;
    row_views[1].strides = views[1].strides + 1;
    state->batch_rows += (unsigned long long)rows;
    Py_BEGIN_ALLOW_THREADS
    for (Py_ssize_t row = 0; row < rows; ++row) {
        double cap = at(&views[4], row), output[5];
        if (!isfinite(cap) || cap < 0.0) {
            valid = 0;
            break;
        }
        row_views[0].buf = (char *)views[0].buf + row * views[0].strides[0];
        row_views[1].buf = (char *)views[1].buf + row * views[1].strides[0];
        if (!fit_row(row_views, count, lower, upper, cap, sigma,
                     independent_samples, scratch, output)) {
            valid = 0;
            break;
        }
        memcpy((char *)views[5].buf + row * views[5].strides[0], output, sizeof(output));
    }
    Py_END_ALLOW_THREADS
    if (valid) state->batch_successful_rows += (unsigned long long)rows;
    result = PyBool_FromLong(valid);
done:
    PyMem_Free(scratch);
    for (int i = 0; i < acquired; ++i) PyBuffer_Release(&views[i]);
    return result;
}

static PyObject *
fit_statistics(PyObject *self, PyObject *unused)
{
    ridge_state *state = PyModule_GetState(self);
    return Py_BuildValue("{sK,sK,sK,sK,sK}",
                        "scalar_calls", state->scalar_calls,
                        "scalar_successes", state->scalar_successes,
                        "batch_calls", state->batch_calls,
                        "batch_rows", state->batch_rows,
                        "batch_successful_rows", state->batch_successful_rows);
}

/* This is a positive-only shortcut for the Python evidence validator. Any
 * noncanonical or invalid value returns False, so Python retains its original
 * error reason, ordering, subclass behavior and unbounded-integer semantics.
 * No fit, score threshold or association arithmetic is performed here. */
static int
plain_string_dict(PyObject *object)
{
    if (!PyDict_CheckExact(object)) return 0;
    PyObject *key, *value;
    Py_ssize_t position = 0;
    while (PyDict_Next(object, &position, &key, &value)) {
        if (!PyUnicode_CheckExact(key)) return 0;
    }
    return 1;
}

static int
exact_finite_float(PyObject *object, double *value)
{
    if (object == NULL || !PyFloat_CheckExact(object)) return 0;
    *value = PyFloat_AS_DOUBLE(object);
    return isfinite(*value);
}

static PyObject *
valid_ridge_events(PyObject *self, PyObject *args)
{
    PyObject *diagnostics, *scores, *frequencies, *events;
    if (!PyArg_ParseTuple(args, "OOOO", &diagnostics, &scores, &frequencies, &events)) {
        return NULL;
    }
    if (!PyList_CheckExact(diagnostics) || !PyList_CheckExact(scores) ||
        !PyList_CheckExact(frequencies) || !PyList_CheckExact(events)) Py_RETURN_FALSE;
    Py_ssize_t count = PyList_GET_SIZE(events);
    if (PyList_GET_SIZE(diagnostics) != count || PyList_GET_SIZE(scores) != count ||
        PyList_GET_SIZE(frequencies) != count) Py_RETURN_FALSE;

    static const char *fields[] = {
        "support_fraction", "score", "f0_hz", "source_drift_hz", "source_drift_hz_s",
        "source_reference_emission_time_s", "source_span_s", "drift_bound_hz",
        "rmse_hz", "outlier_fraction"
    };
    for (Py_ssize_t index = 0; index < count; ++index) {
        PyObject *diagnostic = PyList_GET_ITEM(diagnostics, index);
        PyObject *event = PyList_GET_ITEM(events, index);
        if (!plain_string_dict(diagnostic) || !plain_string_dict(event)) Py_RETURN_FALSE;
        double values[10], score, frequency;
        for (int field = 0; field < 10; ++field) {
            if (!exact_finite_float(PyDict_GetItemString(diagnostic, fields[field]),
                                    &values[field])) Py_RETURN_FALSE;
        }
        if (!exact_finite_float(PyList_GET_ITEM(scores, index), &score) ||
            !exact_finite_float(PyList_GET_ITEM(frequencies, index), &frequency)) Py_RETURN_FALSE;
        if (values[0] != 1.0 || values[6] <= 0.0 || values[7] < 0.0 || values[8] < 0.0 ||
            values[9] < 0.0 || values[9] > 1.0 || values[2] <= 0.0 || values[1] > 0.0 ||
            score != values[1] || frequency != values[2]) Py_RETURN_FALSE;

        PyObject *samples = PyDict_GetItemString(diagnostic, "sample_count");
        PyObject *independent = PyDict_GetItemString(diagnostic, "independent_sample_count");
        if (samples == NULL || independent == NULL || !PyLong_CheckExact(samples) ||
            !PyLong_CheckExact(independent)) Py_RETURN_FALSE;
        Py_ssize_t n = PyLong_AsSsize_t(samples);
        if (n == -1 && PyErr_Occurred()) {
            PyErr_Clear();
            Py_RETURN_FALSE;
        }
        Py_ssize_t k = PyLong_AsSsize_t(independent);
        if (k == -1 && PyErr_Occurred()) {
            PyErr_Clear();
            Py_RETURN_FALSE;
        }
        if (n < 10 || k < 1 || k > n) Py_RETURN_FALSE;
        PyObject *optimizer = PyDict_GetItemString(diagnostic, "optimizer_success");
        if (optimizer != NULL && optimizer != Py_True) Py_RETURN_FALSE;

        PyObject *bounds = PyDict_GetItemString(event, "f0_range_hz");
        if (bounds == NULL || !(PyList_CheckExact(bounds) || PyTuple_CheckExact(bounds))) Py_RETURN_FALSE;
        int tuple_bounds = PyTuple_CheckExact(bounds);
        Py_ssize_t bounds_count = tuple_bounds ? PyTuple_GET_SIZE(bounds) : PyList_GET_SIZE(bounds);
        if (bounds_count != 2) Py_RETURN_FALSE;
        double lower, upper, fraction = 0.02;
        if (!exact_finite_float(tuple_bounds ? PyTuple_GET_ITEM(bounds, 0) : PyList_GET_ITEM(bounds, 0), &lower) ||
            !exact_finite_float(tuple_bounds ? PyTuple_GET_ITEM(bounds, 1) : PyList_GET_ITEM(bounds, 1), &upper)) Py_RETURN_FALSE;
        PyObject *quality = PyDict_GetItemString(event, "quality");
        if (quality != NULL) {
            if (!plain_string_dict(quality)) Py_RETURN_FALSE;
            PyObject *configured = PyDict_GetItemString(quality, "source_drift_fraction");
            if (configured != NULL && !exact_finite_float(configured, &fraction)) Py_RETURN_FALSE;
        }
        if (!(0.0 < lower && lower <= upper && lower <= frequency && frequency <= upper &&
              0.0 <= fraction && fraction <= 0.1)) Py_RETURN_FALSE;
        double drift = values[3], cap = values[7];
        if (!(lower * fraction <= cap && cap <= upper * fraction) || fabs(drift) > cap) Py_RETURN_FALSE;
        if (fabs(values[4] * values[6] - drift) > 1e-12 + 1e-12 * fabs(drift)) Py_RETURN_FALSE;
    }
    Py_RETURN_TRUE;
}

static PyMethodDef methods[] = {
    {"fit_irls", fit_irls, METH_VARARGS, "Run six robust ridge-fit iterations in C."},
    {"fit_irls_batch", fit_irls_batch, METH_VARARGS,
     "Run the same robust fit for contiguous clock rows with shared scratch storage."},
    {"fit_statistics", fit_statistics, METH_NOARGS, "Read native fit operation counters."},
    {"valid_ridge_events", valid_ridge_events, METH_VARARGS,
     "Recognize valid canonical ridge evidence; other inputs retain Python validation."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_native_ridge", NULL, sizeof(ridge_state), methods
};

PyMODINIT_FUNC
PyInit__native_ridge(void)
{
    return PyModule_Create(&module);
}
