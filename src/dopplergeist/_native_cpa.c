/* Optional exact-order CPA neighbour reduction. No NumPy C headers.
 * Keep the Python spatial query, endpoint spline solver and row construction.
 * This loop removes the expanded observer indices and temporary N-by-3 arrays.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <fenv.h>
#include <math.h>
#include <stdint.h>
#include <string.h>

typedef struct { unsigned long long successful_calls; } module_state;

/* NumPy reduces the three coordinates in order. Do not reassociate or fuse
 * these additions and multiplications; setup.py disables both optimizations.
 */
static double sum3(double a, double b, double c) {
    return ((0.0 + a) + b) + c;
}

static double distance2(const double *position, const double *observer) {
    double x = position[0] - observer[0];
    double y = position[1] - observer[1];
    double z = position[2] - observer[2];
    return sum3(x*x, y*y, z*z);
}

static int project(const double *first, const double *last,
                   const double *observer, double *fraction, double *squared) {
    double delta[3], residual[3], projected[3];
    for (int j = 0; j < 3; ++j) {
        delta[j] = last[j] - first[j];
        residual[j] = first[j] - observer[j];
    }
    double length2 = sum3(delta[0]*delta[0], delta[1]*delta[1], delta[2]*delta[2]);
    double dot = sum3(residual[0]*delta[0], residual[1]*delta[1], residual[2]*delta[2]);
    double denominator = length2 < 1e-12 ? 1e-12 : length2;
    double f = -dot / denominator;
    if (!isfinite(length2) || !isfinite(dot) || !isfinite(f)) return 0;
    if (f < 0.0) f = 0.0;
    else if (f > 1.0) f = 1.0;
    for (int j = 0; j < 3; ++j)
        projected[j] = residual[j] + f*delta[j];
    *squared = sum3(projected[0]*projected[0], projected[1]*projected[1],
                    projected[2]*projected[2]);
    *fraction = f;
    return isfinite(*squared);
}

static int reduce_graph(const double *position, Py_ssize_t position_count,
                        const double *observers, Py_ssize_t observer_count,
                        const Py_ssize_t *counts, const Py_ssize_t *sample,
                        Py_ssize_t sample_count, Py_ssize_t *endpoints,
                        Py_ssize_t *indices, double *values, Py_ssize_t capacity,
                        Py_ssize_t *sizes) {
    Py_ssize_t base = 0;
    for (Py_ssize_t oi = 0; oi < observer_count; ++oi) {
        Py_ssize_t count = counts[oi];
        if (count < 0 || count > sample_count-base) return 0;
        const Py_ssize_t *samples = sample + base;
        const double *observer = observers + 3*oi;
        for (int j = 0; j < 3; ++j) if (!isfinite(observer[j])) return 0;
        for (Py_ssize_t j = 0; j < count; ++j)
            if (samples[j] < 0 || samples[j] >= position_count) return 0;
        base += count;
        if (!count) continue;
        double previous = distance2(position + 3*samples[0], observer);
        if (!isfinite(previous)) return 0;
        if (count == 1) continue;
        double current = distance2(position + 3*samples[1], observer);
        if (!isfinite(current)) return 0;
        if (samples[0] == 0 && samples[1] == 1 && previous <= current)
            endpoints[sizes[0]++] = oi;
        for (Py_ssize_t j = 1; j < count-1; ++j) {
            double following = distance2(position + 3*samples[j+1], observer);
            if (!isfinite(following)) return 0;
            Py_ssize_t k = samples[j];
            if (samples[j-1] == k-1 && samples[j+1] == k+1
                    && current <= previous && current < following) {
                double fraction[2], squared[2];
                if (!project(position + 3*(k-1), position + 3*k, observer,
                             fraction, squared)
                        || !project(position + 3*k, position + 3*(k+1), observer,
                                    fraction+1, squared+1)) return 0;
                /* np.argmin selects the first edge on an exact tie. */
                int edge = squared[1] < squared[0];
                Py_ssize_t out = sizes[2]++;
                if (out >= capacity) return 0;
                indices[out] = oi;
                indices[capacity+out] = edge ? k : k-1;
                values[out] = fraction[edge];
                values[capacity+out] = squared[edge];
            }
            previous = current;
            current = following;
        }
        if (samples[count-1] == position_count-1
                && samples[count-2] == position_count-2 && current <= previous)
            endpoints[observer_count+sizes[1]++] = oi;
    }
    return base == sample_count;
}

static int view_array(PyObject *object, Py_buffer *view, int integer, int writable) {
    int flags = PyBUF_FORMAT | PyBUF_ND | PyBUF_STRIDES;
    if (writable) flags |= PyBUF_WRITABLE;
    if (PyObject_GetBuffer(object, view, flags) < 0) return 0;
    size_t size = integer ? sizeof(Py_ssize_t) : sizeof(double);
    if (view->itemsize != (Py_ssize_t)size || !view->format
            || !PyBuffer_IsContiguous(view, 'C')
            || (uintptr_t)view->buf % size != 0) return 0;
    if (!integer) return strcmp(view->format, "d") == 0;
    return strlen(view->format) == 1 && strchr("nliq", view->format[0]) != NULL;
}

static int matrix_shape(const Py_buffer *view, Py_ssize_t rows, Py_ssize_t columns) {
    return view->ndim == 2 && view->shape[0] == rows && view->shape[1] == columns;
}

static int disjoint(const Py_buffer *a, const Py_buffer *b) {
    uintptr_t first = (uintptr_t)a->buf, second = (uintptr_t)b->buf;
    if (a->len < 0 || b->len < 0
            || (uintptr_t)a->len > UINTPTR_MAX-first
            || (uintptr_t)b->len > UINTPTR_MAX-second) return 0;
    return !a->len || !b->len || first+(uintptr_t)a->len <= second
        || second+(uintptr_t)b->len <= first;
}

static PyObject *select_edges(PyObject *self, PyObject *args) {
    PyObject *objects[7];
    Py_buffer views[7] = {{0}};
    Py_ssize_t sizes[3] = {0, 0, 0};
    int success = 0;
    if (!PyArg_ParseTuple(args, "OOOOOOO", &objects[0], &objects[1], &objects[2],
                          &objects[3], &objects[4], &objects[5], &objects[6])) return NULL;
    if (fegetround() != FE_TONEAREST) Py_RETURN_NONE;
    for (int i = 0; i < 7; ++i)
        if (!view_array(objects[i], views+i, i >= 2 && i <= 5, i >= 4)) goto done;
    for (int i = 4; i < 7; ++i)
        for (int j = 0; j < i; ++j)
            if (!disjoint(views+i, views+j)) goto done;
    if (views[0].ndim != 2 || views[0].shape[0] < 2 || views[0].shape[1] != 3
            || views[1].ndim != 2 || views[1].shape[1] != 3
            || views[2].ndim != 1 || views[2].shape[0] != views[1].shape[0]
            || views[3].ndim != 1
            || !matrix_shape(views+4, 2, views[1].shape[0])
            || !matrix_shape(views+5, 2, views[3].shape[0]/2)
            || !matrix_shape(views+6, 2, views[3].shape[0]/2)) goto done;
    /* Failed probes leave NumPy's warning/exception behavior to the reference
     * path. Do not leak the probe's floating-point flags into that fallback.
     */
    fenv_t previous_environment;
    if (fegetenv(&previous_environment) != 0) goto done;
    Py_BEGIN_ALLOW_THREADS
    if (feclearexcept(FE_ALL_EXCEPT) == 0) {
        success = reduce_graph(views[0].buf, views[0].shape[0], views[1].buf,
                               views[1].shape[0], views[2].buf, views[3].buf,
                               views[3].shape[0], views[4].buf, views[5].buf,
                               views[6].buf, views[3].shape[0]/2, sizes);
        if (fetestexcept(FE_INVALID | FE_DIVBYZERO | FE_OVERFLOW)) success = 0;
    }
    if (fesetenv(&previous_environment) != 0) success = 0;
    Py_END_ALLOW_THREADS
done:
    for (int i = 0; i < 7; ++i) if (views[i].obj) PyBuffer_Release(views+i);
    if (PyErr_Occurred()) PyErr_Clear();
    if (!success) Py_RETURN_NONE;
    ((module_state *)PyModule_GetState(self))->successful_calls++;
    return Py_BuildValue("nnn", sizes[0], sizes[1], sizes[2]);
}

static PyObject *successful_calls(PyObject *self, PyObject *unused) {
    return PyLong_FromUnsignedLongLong(((module_state *)PyModule_GetState(self))->successful_calls);
}

static PyMethodDef methods[] = {
    {"select", select_edges, METH_VARARGS, "Reduce a canonical sorted CPA neighbour graph."},
    {"successful_calls", successful_calls, METH_NOARGS, "Count successful native CPA reductions."},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_native_cpa", NULL, sizeof(module_state), methods
};
PyMODINIT_FUNC PyInit__native_cpa(void) { return PyModule_Create(&module); }
