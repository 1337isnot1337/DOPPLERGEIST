#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <math.h>
#include <stdlib.h>

typedef struct {
    Py_ssize_t row;
    double lower, upper, start;
} Passage;

typedef struct {
    PyObject *event;
    Py_ssize_t count;
    Passage *passages;
} Group;

typedef struct {
    Py_ssize_t cursor, count, next, depth;
    Passage **options;
    double lower, upper;
} Frame;

typedef struct {
    Py_ssize_t group;
    Passage *passage;
} Match;

static int reserve(Py_ssize_t *work, Py_ssize_t units, Py_ssize_t limit)
{
    if (units > limit - *work) {
        PyErr_SetString(PyExc_ValueError,
                        "Association work/storage budget exceeded; search is incomplete");
        return -1;
    }
    *work += units;
    return 0;
}

static int row_order(const void *left, const void *right)
{
    Py_ssize_t a = (*(Passage *const *)left)->row;
    Py_ssize_t b = (*(Passage *const *)right)->row;
    return (a > b) - (a < b);
}

static int push_frame(Frame *frame, Py_ssize_t cursor, Group *group,
                      double lower, double upper, Py_ssize_t depth,
                      double option_lower, double option_upper,
                      Py_ssize_t *work, Py_ssize_t limit)
{
    Py_ssize_t lo = 0, hi = group->count;
    while (lo < hi) {
        Py_ssize_t mid = lo + (hi-lo)/2;
        if (group->passages[mid].upper < option_lower) lo = mid+1;
        else hi = mid;
    }
    Py_ssize_t first = lo;
    lo = 0; hi = group->count;
    while (lo < hi) {
        Py_ssize_t mid = lo + (hi-lo)/2;
        if (option_upper < group->passages[mid].lower) hi = mid;
        else lo = mid+1;
    }
    Py_ssize_t count = lo > first ? lo-first : 0;
    Py_ssize_t bits = 0;
    for (Py_ssize_t n = count; n; n >>= 1) ++bits;
    if (count && (count > limit / bits || reserve(work, count*bits, limit) < 0)) {
        if (!PyErr_Occurred())
            PyErr_SetString(PyExc_ValueError,
                            "Association work/storage budget exceeded; search is incomplete");
        return -1;
    }
    Passage **options = NULL;
    if (count) {
        options = PyMem_Malloc((size_t)count * sizeof(*options));
        if (options == NULL) { PyErr_NoMemory(); return -1; }
        for (Py_ssize_t i = 0; i < count; ++i) options[i] = &group->passages[first+i];
        qsort(options, (size_t)count, sizeof(*options), row_order);
    }
    *frame = (Frame){cursor, count, 0, depth, options, lower, upper};
    return 0;
}

static int append_candidate(PyObject *candidates, PyObject *records, PyObject *point,
                            Group *groups, Match *path, Py_ssize_t depth,
                            double lower, double upper)
{
    PyObject *passes = PyTuple_New(depth), *indices = PyList_New(depth);
    PyObject *bounds = NULL, *candidate = NULL;
    int status = -1;
    if (passes == NULL || indices == NULL) goto done;
    for (Py_ssize_t i = 0; i < depth; ++i) {
        PyObject *record = PyList_GET_ITEM(records, path[i].passage->row);
        PyObject *event = groups[path[i].group].event;
        Py_INCREF(record); PyTuple_SET_ITEM(passes, i, record);
        Py_INCREF(event); PyList_SET_ITEM(indices, i, event);
    }
    bounds = Py_BuildValue("[dd]", lower, upper);
    candidate = PyDict_New();
    if (bounds == NULL || candidate == NULL ||
        PyDict_SetItemString(candidate, "point_id", point) < 0 ||
        PyDict_SetItemString(candidate, "passes", passes) < 0 ||
        PyDict_SetItemString(candidate, "event_indices", indices) < 0 ||
        PyDict_SetItemString(candidate, "recording_start_bounds_s", bounds) < 0) goto done;
    status = PyList_Append(candidates, candidate);
done:
    Py_XDECREF(passes); Py_XDECREF(indices); Py_XDECREF(bounds); Py_XDECREF(candidate);
    return status;
}

static PyObject *enumerate_point(PyObject *self, PyObject *args)
{
    (void)self;
    PyObject *records, *identities, *input, *point, *candidates, *anchor;
    Py_ssize_t minimum, maximum, candidate_limit, work;
    double lower, upper;
    if (!PyArg_ParseTuple(args, "OOOOOddOnnnn", &records, &identities, &input,
                          &point, &candidates, &lower, &upper, &anchor,
                          &minimum, &maximum, &candidate_limit, &work)) return NULL;
    if (!PyList_Check(records) || !PyList_Check(identities) || !PyList_Check(input) ||
        !PyList_Check(candidates) || PyList_GET_SIZE(records) != PyList_GET_SIZE(identities) ||
        minimum < 1 || maximum < minimum || candidate_limit < 1 || work < 0) {
        PyErr_SetString(PyExc_ValueError, "invalid association traversal inputs");
        return NULL;
    }
    /* Keep unusual/non-finite inputs on the existing Python implementation. */
    if (candidate_limit > PY_SSIZE_T_MAX/20 || isnan(lower) || isnan(upper)) Py_RETURN_NONE;
    Py_ssize_t limit = candidate_limit*20, count = PyList_GET_SIZE(input);
    if (!count) Py_RETURN_NONE;
    int anchored = anchor != Py_None;
    double anchor_lower = lower, anchor_upper = upper;
    if (anchored && !PyArg_ParseTuple(anchor, "dd", &anchor_lower, &anchor_upper)) return NULL;
    Group *groups = PyMem_Calloc((size_t)count, sizeof(*groups));
    Frame *frames = PyMem_Calloc((size_t)count, sizeof(*frames));
    Match *path = PyMem_Calloc((size_t)count, sizeof(*path));
    PyObject *used = PySet_New(NULL), *result = NULL;
    Py_ssize_t frame_count = 0, depth = 0, examined = 0;
    if (!groups || !frames || !path || !used) { PyErr_NoMemory(); goto done; }
    for (Py_ssize_t i = 0; i < count; ++i) {
        PyObject *group = PyList_GET_ITEM(input, i), *starts, *ends, *rows, *centers;
        if (!PyArg_ParseTuple(group, "OOOOO", &groups[i].event, &starts, &ends, &rows, &centers)) goto done;
        if (!PyList_Check(starts) || !PyList_Check(ends) || !PyList_Check(rows) || !PyList_Check(centers)) {
            PyErr_SetString(PyExc_TypeError, "association interval arrays must be lists"); goto done;
        }
        Py_ssize_t n = PyList_GET_SIZE(rows);
        if (PyList_GET_SIZE(starts) != n || PyList_GET_SIZE(ends) != n || PyList_GET_SIZE(centers) != n) {
            PyErr_SetString(PyExc_ValueError, "association interval lengths differ"); goto done;
        }
        groups[i].count = n;
        groups[i].passages = PyMem_Calloc((size_t)n, sizeof(Passage));
        if (!groups[i].passages && n) { PyErr_NoMemory(); goto done; }
        for (Py_ssize_t j = 0; j < n; ++j) {
            Passage *p = &groups[i].passages[j];
            p->row = PyLong_AsSsize_t(PyList_GET_ITEM(rows, j));
            p->lower = PyFloat_AsDouble(PyList_GET_ITEM(starts, j));
            p->upper = PyFloat_AsDouble(PyList_GET_ITEM(ends, j));
            p->start = PyFloat_AsDouble(PyList_GET_ITEM(centers, j));
            if (PyErr_Occurred()) goto done;
            if (p->row < 0 || p->row >= PyList_GET_SIZE(records)) {
                PyErr_SetString(PyExc_ValueError, "association row is outside the supplied table"); goto done;
            }
            if (!isfinite(p->lower) || !isfinite(p->upper) || !isfinite(p->start)) {
                result = Py_NewRef(Py_None); goto done;
            }
        }
    }
    if (push_frame(&frames[0], 0, &groups[0], lower, upper, 0,
                   anchor_lower, anchor_upper, &work, limit) < 0) goto done;
    frame_count = 1;
    while (frame_count) {
        Frame *frame = &frames[frame_count-1];
        while (depth > frame->depth) {
            if (PySet_Discard(used, PyList_GET_ITEM(identities, path[--depth].passage->row)) < 0) goto done;
        }
        if (frame->next > frame->count) {
            PyMem_Free(frame->options); frame->options = NULL; --frame_count; continue;
        }
        Passage *passage = frame->next < frame->count ? frame->options[frame->next] : NULL;
        ++frame->next;
        if (reserve(&work, 1, limit) < 0) goto done;
        double lo = frame->lower, hi = frame->upper;
        Py_ssize_t cursor = frame->cursor;
        if (passage) {
            PyObject *identity = PyList_GET_ITEM(identities, passage->row);
            int present = PySet_Contains(used, identity);
            if (present < 0) goto done;
            if (present) continue;
            if (!depth && anchored && !(anchor_lower <= passage->start && passage->start < anchor_upper)) continue;
            if (lo < passage->lower) lo = passage->lower;
            if (hi > passage->upper) hi = passage->upper;
            if (lo > hi) continue;
            path[depth++] = (Match){cursor, passage};
            if (PySet_Add(used, identity) < 0) goto done;
        }
        Py_ssize_t following = cursor+1;
        if (depth+count-following < minimum) continue;
        if (following < count && depth < maximum) {
            double option_lower = !depth && anchored ? anchor_lower : lo;
            double option_upper = !depth && anchored ? anchor_upper : hi;
            if (push_frame(&frames[frame_count], following, &groups[following], lo, hi, depth,
                           option_lower, option_upper, &work, limit) < 0) goto done;
            ++frame_count; continue;
        }
        if (depth < minimum) continue;
        ++examined;
        if (PyList_GET_SIZE(candidates) >= candidate_limit) {
            PyErr_SetString(PyExc_ValueError, "Association candidate budget exceeded; search is incomplete"); goto done;
        }
        if (reserve(&work, depth, limit) < 0 ||
            append_candidate(candidates, records, point, groups, path, depth, lo, hi) < 0) goto done;
    }
    result = Py_BuildValue("nn", examined, work);
done:
    if (frames) for (Py_ssize_t i = 0; i < count; ++i) PyMem_Free(frames[i].options);
    if (groups) for (Py_ssize_t i = 0; i < count; ++i) PyMem_Free(groups[i].passages);
    PyMem_Free(groups); PyMem_Free(frames); PyMem_Free(path); Py_XDECREF(used);
    return result;
}

static PyMethodDef methods[] = {
    {"enumerate_point", enumerate_point, METH_VARARGS, "Enumerate indexed subset associations for one receiver."},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_native_association", NULL, -1, methods,
    NULL, NULL, NULL, NULL
};
PyMODINIT_FUNC PyInit__native_association(void) { return PyModule_Create(&module); }
