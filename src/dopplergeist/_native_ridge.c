#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>
#include <string.h>

typedef struct {
    PyObject *validation_keys[16];
} RidgeModuleState;

static const char *validation_names[] = {
    "support_fraction", "score", "f0_hz", "source_drift_hz", "source_drift_hz_s",
    "source_reference_emission_time_s", "source_span_s", "drift_bound_hz", "rmse_hz",
    "outlier_fraction", "sample_count", "independent_sample_count", "optimizer_success",
    "f0_range_hz", "quality", "source_drift_fraction"
};

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

/* Only ordinary string-keyed dictionaries enter the fast validator. A custom
 * key or container can execute Python during lookup and keeps the Python path. */
static int
plain_dictionary(PyObject *object)
{
    if (!PyDict_CheckExact(object)) return 0;
    Py_ssize_t position = 0;
    PyObject *key, *value;
    while (PyDict_Next(object, &position, &key, &value)) {
        if (!PyUnicode_CheckExact(key)) return 0;
    }
    return 1;
}

static PyObject *
sequence_item(PyObject *sequence, Py_ssize_t index)
{
    return PyList_CheckExact(sequence) ? PyList_GET_ITEM(sequence, index) :
                                       PyTuple_GET_ITEM(sequence, index);
}

/* Return 0 for valid evidence, a positive first-failure code, or -1 for
 * Python fallback. Both public native interfaces share the same interned keys
 * and exact-type guards. No evidence is cached or trusted because a fitter
 * produced it; every call checks its current values. */
static int
ridge_event_reason(RidgeModuleState *state, PyObject *diagnostics, PyObject *scores,
                   PyObject *frequencies, PyObject *events)
{
    if (!PyList_CheckExact(diagnostics) || !PyList_CheckExact(scores) ||
        !PyList_CheckExact(frequencies) ||
        !(PyList_CheckExact(events) || PyTuple_CheckExact(events))) return -1;
    Py_ssize_t count = PyList_GET_SIZE(diagnostics);
    Py_ssize_t event_count = PyList_CheckExact(events) ? PyList_GET_SIZE(events) :
                                                     PyTuple_GET_SIZE(events);
    if (PyList_GET_SIZE(scores) != count || PyList_GET_SIZE(frequencies) != count ||
        event_count != count) return -1;

    for (Py_ssize_t i = 0; i < count; ++i) {
        PyObject *diagnostic = PyList_GET_ITEM(diagnostics, i);
        PyObject *event = sequence_item(events, i);
        PyObject *score_object = PyList_GET_ITEM(scores, i);
        PyObject *frequency_object = PyList_GET_ITEM(frequencies, i);
        if (!plain_dictionary(diagnostic) || !plain_dictionary(event) ||
            !PyFloat_CheckExact(score_object) || !PyFloat_CheckExact(frequency_object)) {
            return -1;
        }
        double values[10];
        for (int j = 0; j < 10; ++j) {
            PyObject *value = PyDict_GetItem(diagnostic, state->validation_keys[j]);
            if (value == NULL || !PyFloat_CheckExact(value)) return -1;
            values[j] = PyFloat_AS_DOUBLE(value);
        }
        PyObject *samples = PyDict_GetItem(diagnostic, state->validation_keys[10]);
        PyObject *independent = PyDict_GetItem(diagnostic, state->validation_keys[11]);
        if (samples == NULL || independent == NULL ||
            !PyLong_CheckExact(samples) || !PyLong_CheckExact(independent)) return -1;
        Py_ssize_t sample_count = PyLong_AsSsize_t(samples);
        if (PyErr_Occurred()) { PyErr_Clear(); return -1; }
        Py_ssize_t independent_count = PyLong_AsSsize_t(independent);
        if (PyErr_Occurred()) { PyErr_Clear(); return -1; }
        PyObject *optimizer = PyDict_GetItem(diagnostic, state->validation_keys[12]);
        if (optimizer != NULL && !PyBool_Check(optimizer)) return -1;
        PyObject *bounds = PyDict_GetItem(event, state->validation_keys[13]);
        if (bounds == NULL || !(PyList_CheckExact(bounds) || PyTuple_CheckExact(bounds))) {
            return -1;
        }
        Py_ssize_t size = PyList_CheckExact(bounds) ? PyList_GET_SIZE(bounds) : PyTuple_GET_SIZE(bounds);
        if (size != 2) return -1;
        PyObject *low_object = sequence_item(bounds, 0), *high_object = sequence_item(bounds, 1);
        if (!PyFloat_CheckExact(low_object) || !PyFloat_CheckExact(high_object)) return -1;
        double low = PyFloat_AS_DOUBLE(low_object), high = PyFloat_AS_DOUBLE(high_object);
        double fraction = 0.02;
        PyObject *quality = PyDict_GetItem(event, state->validation_keys[14]);
        if (quality != NULL) {
            if (!plain_dictionary(quality)) return -1;
            PyObject *configured = PyDict_GetItem(quality, state->validation_keys[15]);
            if (configured != NULL) {
                if (!PyFloat_CheckExact(configured)) return -1;
                fraction = PyFloat_AS_DOUBLE(configured);
            }
        }
        double score = PyFloat_AS_DOUBLE(score_object), frequency = PyFloat_AS_DOUBLE(frequency_object);
        if (!isfinite(values[0]) || values[0] != 1.0) return 1;
        int finite = isfinite(score) && isfinite(frequency);
        for (int j = 1; j < 10; ++j) finite = finite && isfinite(values[j]);
        if (!finite) return 2;
        if (independent_count < 1 || independent_count > sample_count || sample_count < 10 ||
            values[6] <= 0.0 || values[7] < 0.0 || values[8] < 0.0 ||
            !(0.0 <= values[9] && values[9] <= 1.0) || values[2] <= 0.0 || values[1] > 0.0) {
            return 3;
        }
        if (optimizer == Py_False) return 4;
        if (score != values[1] || frequency != values[2]) return 5;
        if (!isfinite(low) || !isfinite(high) || !(0.0 < low && low <= high) ||
            !(low <= frequency && frequency <= high) || !isfinite(fraction) ||
            !(0.0 <= fraction && fraction <= 0.1)) return 6;
        double drift = values[3], cap = values[7];
        if (!(low * fraction <= cap && cap <= high * fraction) || fabs(drift) > cap) {
            return 7;
        }
        if (fabs(values[4] * values[6] - drift) > 1e-12 + 1e-12 * fabs(drift)) {
            return 8;
        }
    }
    return 0;
}

/* Diagnostic compatibility API: preserve first-failure codes and tuple events.
 * Score summation and association arithmetic remain in Python. */
static PyObject *
event_fit_reason(PyObject *self, PyObject *args)
{
    PyObject *diagnostics, *scores, *frequencies, *events;
    RidgeModuleState *state = PyModule_GetState(self);
    if (state == NULL) return NULL;
    if (!PyArg_ParseTuple(args, "OOOO", &diagnostics, &scores, &frequencies, &events)) {
        return NULL;
    }
    int reason = ridge_event_reason(state, diagnostics, scores, frequencies, events);
    if (reason < 0) Py_RETURN_NONE;
    return PyLong_FromLong(reason);
}

/* Positive-only upstream API. Invalid or noncanonical inputs retain Python's
 * original failure ordering, custom behavior, and unbounded-integer semantics.
 * Its outer event container remains an exact list, as on upstream main. */
static PyObject *
valid_ridge_events(PyObject *self, PyObject *args)
{
    PyObject *diagnostics, *scores, *frequencies, *events;
    RidgeModuleState *state = PyModule_GetState(self);
    if (state == NULL) return NULL;
    if (!PyArg_ParseTuple(args, "OOOO", &diagnostics, &scores, &frequencies, &events)) {
        return NULL;
    }
    if (!PyList_CheckExact(events)) Py_RETURN_FALSE;
    return PyBool_FromLong(ridge_event_reason(state, diagnostics, scores, frequencies, events) == 0);
}

static PyMethodDef methods[] = {
    {"fit_irls", fit_irls, METH_VARARGS, "Run six robust ridge-fit iterations in C."},
    {"event_fit_reason", event_fit_reason, METH_VARARGS, "Validate canonical per-event fit evidence, or request Python fallback."},
    {"valid_ridge_events", valid_ridge_events, METH_VARARGS,
     "Recognize valid canonical ridge evidence; other inputs retain Python validation."},
    {NULL, NULL, 0, NULL}
};

static int
ridge_traverse(PyObject *module, visitproc visit, void *arg)
{
    RidgeModuleState *state = PyModule_GetState(module);
    for (int i = 0; i < 16; ++i) Py_VISIT(state->validation_keys[i]);
    return 0;
}

static int
ridge_clear(PyObject *module)
{
    RidgeModuleState *state = PyModule_GetState(module);
    for (int i = 0; i < 16; ++i) Py_CLEAR(state->validation_keys[i]);
    return 0;
}

static void
ridge_free(void *module)
{
    ridge_clear((PyObject *)module);
}

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_native_ridge", NULL, sizeof(RidgeModuleState), methods,
    NULL, ridge_traverse, ridge_clear, ridge_free
};

PyMODINIT_FUNC
PyInit__native_ridge(void)
{
    PyObject *created = PyModule_Create(&module);
    if (created == NULL) return NULL;
    RidgeModuleState *state = PyModule_GetState(created);
    for (int i = 0; i < 16; ++i) {
        state->validation_keys[i] = PyUnicode_InternFromString(validation_names[i]);
        if (state->validation_keys[i] == NULL) {
            Py_DECREF(created);
            return NULL;
        }
    }
    return created;
}
