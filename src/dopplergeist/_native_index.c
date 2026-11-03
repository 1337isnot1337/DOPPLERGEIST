/* Exact canonical JSON-column extraction, without NumPy's C API.
 * The Python path owns JSON decoding and all dtype/trajectory conversion.
 * This optional helper only validates built-in types and collects references.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>

#define COLUMN_COUNT 10

static const char *column_names[COLUMN_COUNT] = {
    "time_s", "lat", "lon", "alt_m", "east_mps", "north_mps", "up_mps",
    "typecode", "altitude_basis", "aircraft_class"
};

typedef struct {
    unsigned long long successful_calls;
} module_state;

static PyObject *payload_columns(PyObject *self, PyObject *records) {
    PyObject *keys[COLUMN_COUNT] = {NULL};
    PyObject *columns[COLUMN_COUNT] = {NULL};
    PyObject *result = NULL;
    int present[COLUMN_COUNT] = {0};
    if (!PyList_CheckExact(records) || PyList_GET_SIZE(records) == 0)
        Py_RETURN_NONE;
    Py_ssize_t count = PyList_GET_SIZE(records);
    for (int j = 0; j < COLUMN_COUNT; ++j) {
        keys[j] = PyUnicode_InternFromString(column_names[j]);
        if (!keys[j]) goto done;
        if (j < 4) {
            columns[j] = PyList_New(count);
            if (!columns[j]) goto done;
            present[j] = 1;
        }
    }
    for (Py_ssize_t i = 0; i < count; ++i) {
        PyObject *row = PyList_GET_ITEM(records, i);
        if (!PyDict_CheckExact(row)) goto unsupported;
        /* JSON dictionaries have plain string keys. Other mappings keep the
         * original Python path, including custom equality/hash behavior. */
        Py_ssize_t position = 0;
        PyObject *key, *value;
        while (PyDict_Next(row, &position, &key, &value))
            if (!PyUnicode_CheckExact(key)) goto unsupported;
        for (int j = 0; j < COLUMN_COUNT; ++j) {
            value = PyDict_GetItemWithError(row, keys[j]);
            if (!value && PyErr_Occurred()) goto done;
            if (j >= 4 && i == 0) {
                present[j] = value != NULL;
                if (present[j]) {
                    columns[j] = PyList_New(count);
                    if (!columns[j]) goto done;
                }
            }
            if (!present[j]) {
                if (value) goto unsupported;
                continue;
            }
            if (!value) goto unsupported;
            if (j < 4) {
                if (!PyFloat_CheckExact(value)) goto unsupported;
            } else if (j < 7) {
                if (value != Py_None && !PyFloat_CheckExact(value)) goto unsupported;
            } else if (!PyUnicode_CheckExact(value)) {
                goto unsupported;
            }
            /* Each list slot is initially NULL and filled once. */
            PyList_SET_ITEM(columns[j], i, Py_NewRef(value));
        }
    }
    result = PyTuple_New(COLUMN_COUNT);
    if (!result) goto done;
    for (int j = 0; j < COLUMN_COUNT; ++j) {
        PyTuple_SET_ITEM(result, j, columns[j] ? columns[j] : Py_NewRef(Py_None));
        columns[j] = NULL;  /* Tuple owns these references now. */
    }
    ((module_state *)PyModule_GetState(self))->successful_calls++;
    goto done;
unsupported:
    result = Py_NewRef(Py_None);
done:
    for (int j = 0; j < COLUMN_COUNT; ++j) {
        Py_XDECREF(columns[j]);
        Py_XDECREF(keys[j]);
    }
    return result;
}

static PyObject *successful_calls(PyObject *self, PyObject *unused) {
    return PyLong_FromUnsignedLongLong(((module_state *)PyModule_GetState(self))->successful_calls);
}

static PyMethodDef methods[] = {
    {"payload_columns", payload_columns, METH_O,
     "Collect exact canonical recorded columns, or return None for Python fallback."},
    {"successful_calls", successful_calls, METH_NOARGS,
     "Count successful canonical column extractions."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_native_index", NULL, sizeof(module_state), methods
};

PyMODINIT_FUNC PyInit__native_index(void) { return PyModule_Create(&module); }
