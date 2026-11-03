/* Optional exact-order acoustic solver for canonical float64 buffers.
 * NumPy/SciPy remain the reference path for unsupported representations and
 * all exceptional arithmetic. No NumPy C headers or runtime compilation.
 */
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <fenv.h>
#include <string.h>

/* Compile without contraction or reassociation.  SciPy PPoly uses
 * increasing powers, not Horner evaluation.  Preserve that arithmetic exactly.
 */
static size_t interval_at(const double *x, size_t m, double value) {
    size_t lo = 0, hi = m - 1;
    if (value == x[m]) return m - 1;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;
        if (value < x[mid + 1]) hi = mid;
        else lo = mid + 1;
    }
    return lo;
}

static int evaluate(const double *coefficients, const double *x, size_t m,
                    size_t width, double origin, double t, double *values) {
    double relative = t - origin;
    if (!(relative >= x[0] && relative <= x[m])) return 1;
    size_t i = interval_at(x, m, relative);
    double s = relative - x[i];
    double z = 1.0;
    for (size_t j = 0; j < width; ++j) values[j] = 0.0;
    for (size_t k = 0; k < 4; ++k) {
        for (size_t j = 0; j < width; ++j)
            values[j] = values[j] + coefficients[((3-k)*m+i)*width+j]*z;
        if (k < 3) z *= s;
    }
    return 0;
}



static double clip(double t, double start, double end) {
    if (t < start) return start;
    if (t > end) return end;
    return t;
}

static double norm3(const double *a) {
    return sqrt((a[0]*a[0] + a[1]*a[1]) + a[2]*a[2]);
}

static int kinematics(const double *coefficients, const double *x,
                      size_t m, double origin, double tau, const double *observer,
                      double *distance, double *radial) {
    double values[6], delta[3];
    if (evaluate(coefficients, x, m, 6, origin, tau, values)) return 1;
    for (size_t j = 0; j < 3; ++j) delta[j] = values[j] - observer[j];
    *distance = norm3(delta);
    *radial = (((0.0 + delta[0]*values[3]) + delta[1]*values[4])
               + delta[2]*values[5]) / *distance;
    return !isfinite(*distance) || !isfinite(*radial) || *distance == 0.0;
}

static int dg_acoustic(const double *t, size_t n, const double *observer,
                const double *p, const double *x, size_t m,
                const double *packed, const double *packed_x, size_t packed_m,
                double origin, double start, double end, double c,
                double arrival_start, double arrival_end,
                double *factor, double *tau, double *distance) {
    if (n == 0 || m == 0 || m > 4096) return 1;
    for (size_t i = 0; i < n; ++i) {
        double position[3], delta[3];
        if (!isfinite(t[i])) return 1;
        if (evaluate(p, x, m, 3, origin, clip(t[i], start, end), position)) return 1;
        for (size_t j = 0; j < 3; ++j) delta[j] = position[j] - observer[j];
        double initial_distance = norm3(delta);
        if (!isfinite(initial_distance)) return 1;
        double initial_delay = initial_distance/c;
        double estimate = t[i] - initial_delay;
        if (!isfinite(initial_delay) || !isfinite(estimate)) return 1;
        tau[i] = clip(estimate, start, end);
    }
    int unchanged = 0;
    for (size_t iteration = 0; iteration < 10; ++iteration) {
        unchanged = 1;
        double maximum = 0.0;
        for (size_t i = 0; i < n; ++i) {
            if (kinematics(packed, packed_x, packed_m, origin, tau[i], observer, distance+i, factor+i)) return 1;
            double derivative = 1.0 + factor[i]/c;
            if (!isfinite(derivative) || !(derivative > 0.0)) return 1;
            double correction = ((tau[i] - t[i]) + distance[i]/c)/derivative;
            if (!isfinite(correction)) return 1;
            double estimate = tau[i] - correction;
            if (!isfinite(estimate)) return 1;
            double updated = clip(estimate, start, end);
            if (updated != tau[i]) unchanged = 0;
            tau[i] = updated;
            double absolute = fabs(correction);
            if (absolute > maximum) maximum = absolute;
        }
        if (maximum < 1e-7 || unchanged) break;
    }
    if (!unchanged) {
        for (size_t i = 0; i < n; ++i) {
            if (kinematics(packed, packed_x, packed_m, origin, tau[i], observer, distance+i, factor+i)) return 1;
        }
    }
    for (size_t i = 0; i < n; ++i) {
        double radial = factor[i];
        double denominator = c+radial;
        if (!isfinite(denominator)) return 1;
        factor[i] = c/denominator;
        double derivative = 1.0 + radial/c;
        if (!isfinite(factor[i]) || !isfinite(derivative) || !(derivative > 0.0)) return 1;
        double residual = ((tau[i]-t[i])+distance[i]/c)/derivative;
        if (!isfinite(residual)) return 1;
        int supported = t[i] >= arrival_start && t[i] <= arrival_end;
        double spacing = nextafter(t[i],copysign(INFINITY,t[i])) - t[i];
        double tolerance = fmax(1e-7,4.0*fabs(spacing));
        if (!isfinite(tolerance)) return 1;
        if (supported && fabs(residual) > tolerance) return 1;
        if (!supported) factor[i] = tau[i] = distance[i] = NAN;
    }
    return 0;
}
#define PY_SSIZE_T_CLEAN
#include <Python.h>

typedef struct { unsigned long long successful_calls; } module_state;

static int view_double(PyObject *object, Py_buffer *view, int writable) {
    int flags = PyBUF_FORMAT | PyBUF_ND | PyBUF_STRIDES;
    if (writable) flags |= PyBUF_WRITABLE;
    if (PyObject_GetBuffer(object, view, flags) < 0) return 0;
    return view->itemsize == (Py_ssize_t)sizeof(double)
        && view->format && strcmp(view->format, "d") == 0
        && PyBuffer_IsContiguous(view, 'C')
        && (uintptr_t)view->buf % sizeof(double) == 0;
}

static int same_shape(const Py_buffer *a, const Py_buffer *b) {
    if (a->ndim != b->ndim) return 0;
    for (int i = 0; i < a->ndim; ++i)
        if (a->shape[i] != b->shape[i]) return 0;
    return 1;
}

static int spline_shape(const Py_buffer *c, const Py_buffer *x, int width) {
    return c->ndim == 3 && x->ndim == 1
        && c->shape[0] == 4 && c->shape[2] == width
        && c->shape[1] > 0 && c->shape[1] <= 4096
        && x->shape[0] == c->shape[1] + 1;
}

static int increasing_knots(const Py_buffer *view) {
    const double *x = view->buf;
    for (Py_ssize_t i = 0; i < view->shape[0]-1; ++i)
        if (!isfinite(x[i]) || !(x[i] < x[i+1])) return 0;
    return isfinite(x[view->shape[0]-1]);
}

static PyObject *solve(PyObject *self, PyObject *args) {
    PyObject *objects[9];
    Py_buffer views[9] = {{0}};
    double origin, start, end, c, arrival_start, arrival_end;
    int success = 0;
    if (!PyArg_ParseTuple(args,"OOOOOOddddddOOO",
            &objects[0],&objects[1],&objects[2],&objects[3],&objects[4],&objects[5],
            &origin,&start,&end,&c,&arrival_start,&arrival_end,
            &objects[6],&objects[7],&objects[8])) return NULL;
    if (fegetround() != FE_TONEAREST || !isfinite(origin) || !isfinite(start)
            || !isfinite(end) || start > end || !isfinite(c) || c <= 0.0)
        Py_RETURN_FALSE;
    for (int i = 0; i < 9; ++i)
        if (!view_double(objects[i], views+i, i >= 6)) goto done;
    if (views[0].len <= 0 || views[1].ndim != 1 || views[1].shape[0] != 3
            || !spline_shape(views+2,views+3,3)
            || !spline_shape(views+4,views+5,6)
            || !increasing_knots(views+3) || !increasing_knots(views+5)) goto done;
    for (int i = 6; i < 9; ++i)
        if (!same_shape(views,views+i)) goto done;
    const double *observer = views[1].buf;
    for (int j = 0; j < 3; ++j) if (!isfinite(observer[j])) goto done;
    /* A failed probe must not leak arithmetic flags into the NumPy fallback. */
    fenv_t previous_environment;
    if (fegetenv(&previous_environment) != 0) goto done;
    Py_BEGIN_ALLOW_THREADS
    success = !dg_acoustic(views[0].buf,(size_t)(views[0].len/sizeof(double)),
        observer,views[2].buf,views[3].buf,(size_t)views[2].shape[1],
        views[4].buf,views[5].buf,(size_t)views[4].shape[1],origin,start,end,c,
        arrival_start,arrival_end,views[6].buf,views[7].buf,views[8].buf);
    if (fesetenv(&previous_environment) != 0) success = 0;
    Py_END_ALLOW_THREADS
done:
    for (int i = 0; i < 9; ++i) if (views[i].obj) PyBuffer_Release(views+i);
    if (PyErr_Occurred()) PyErr_Clear();
    if (success) ((module_state *)PyModule_GetState(self))->successful_calls++;
    return PyBool_FromLong(success);
}

static PyObject *successful_calls(PyObject *self, PyObject *unused) {
    return PyLong_FromUnsignedLongLong(((module_state *)PyModule_GetState(self))->successful_calls);
}

static PyMethodDef methods[] = {
    {"solve", solve, METH_VARARGS, "Solve a canonical float64 acoustic batch."},
    {"successful_calls", successful_calls, METH_NOARGS, "Count successful native numerical solves."},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_native_acoustic", NULL, sizeof(module_state), methods
};
PyMODINIT_FUNC PyInit__native_acoustic(void) { return PyModule_Create(&module); }
