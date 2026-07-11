#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <stdint.h>
#include <vector>

#include <windows.h>

#include "hidapi.h"
#include "kmbox.h"

extern hid_device *fd_kmbox;
extern HANDLE m_hMutex_lock;

static int clamp_ushort(unsigned int value) {
    if (value > 0xffff) {
        PyErr_SetString(PyExc_ValueError, "value must fit in unsigned short");
        return -1;
    }
    return static_cast<int>(value);
}

static int clamp_uchar(unsigned int value) {
    if (value > 0xff) {
        PyErr_SetString(PyExc_ValueError, "value must fit in unsigned char");
        return -1;
    }
    return static_cast<int>(value);
}

static int clamp_short(int value) {
    if (value < -32768 || value > 32767) {
        PyErr_SetString(PyExc_ValueError, "value must fit in signed short");
        return 0;
    }
    return 1;
}

static PyObject *py_init(PyObject *, PyObject *args) {
    unsigned int vid = 0;
    unsigned int pid = 0;
    if (!PyArg_ParseTuple(args, "II:init", &vid, &pid)) {
        return nullptr;
    }
    int vid_value = clamp_ushort(vid);
    int pid_value = clamp_ushort(pid);
    if (vid_value < 0 || pid_value < 0) {
        return nullptr;
    }
    return PyLong_FromLong(KM_init(
        static_cast<unsigned short>(vid_value),
        static_cast<unsigned short>(pid_value)));
}

static PyObject *py_press(PyObject *, PyObject *args) {
    unsigned int key = 0;
    if (!PyArg_ParseTuple(args, "I:press", &key)) {
        return nullptr;
    }
    int value = clamp_uchar(key);
    if (value < 0) {
        return nullptr;
    }
    return PyLong_FromLong(KM_press(static_cast<unsigned char>(value)));
}

static PyObject *py_keydown(PyObject *, PyObject *args) {
    unsigned int key = 0;
    if (!PyArg_ParseTuple(args, "I:keydown", &key)) {
        return nullptr;
    }
    int value = clamp_uchar(key);
    if (value < 0) {
        return nullptr;
    }
    return PyLong_FromLong(KM_down(static_cast<unsigned char>(value)));
}

static PyObject *py_keyup(PyObject *, PyObject *args) {
    unsigned int key = 0;
    if (!PyArg_ParseTuple(args, "I:keyup", &key)) {
        return nullptr;
    }
    int value = clamp_uchar(key);
    if (value < 0) {
        return nullptr;
    }
    return PyLong_FromLong(KM_up(static_cast<unsigned char>(value)));
}

static PyObject *py_button_call(
    PyObject *args,
    const char *name,
    int (*callback)(unsigned char)) {
    unsigned int state = 0;
    if (!PyArg_ParseTuple(args, "I", &state)) {
        return nullptr;
    }
    int value = clamp_uchar(state);
    if (value < 0) {
        return nullptr;
    }
    return PyLong_FromLong(callback(static_cast<unsigned char>(value)));
}

static PyObject *py_left(PyObject *, PyObject *args) {
    return py_button_call(args, "left", KM_left);
}

static PyObject *py_middle(PyObject *, PyObject *args) {
    return py_button_call(args, "middle", KM_middle);
}

static PyObject *py_right(PyObject *, PyObject *args) {
    return py_button_call(args, "right", KM_right);
}

static PyObject *py_side1(PyObject *, PyObject *args) {
    return py_button_call(args, "side1", KM_side1);
}

static PyObject *py_side2(PyObject *, PyObject *args) {
    return py_button_call(args, "side2", KM_side2);
}

static PyObject *py_wheel(PyObject *, PyObject *args) {
    return py_button_call(args, "wheel", KM_wheel);
}

static PyObject *py_move(PyObject *, PyObject *args) {
    int x = 0;
    int y = 0;
    if (!PyArg_ParseTuple(args, "ii:move", &x, &y)) {
        return nullptr;
    }
    if (!clamp_short(x) || !clamp_short(y)) {
        return nullptr;
    }
    return PyLong_FromLong(KM_move(
        static_cast<short>(x),
        static_cast<short>(y)));
}

static int read_raw_bytes(std::vector<unsigned char> *buffer, int timeout_ms) {
    if (fd_kmbox == nullptr || m_hMutex_lock == nullptr) {
        return 0;
    }
    int ret = 0;
    Py_BEGIN_ALLOW_THREADS
    WaitForSingleObject(m_hMutex_lock, INFINITE);
    ret = hid_read_timeout(
        fd_kmbox,
        buffer->data(),
        buffer->size(),
        timeout_ms);
    ReleaseMutex(m_hMutex_lock);
    Py_END_ALLOW_THREADS
    return ret;
}

static PyObject *py_read_raw(PyObject *, PyObject *args, PyObject *kwargs) {
    int timeout_ms = 10;
    int length = 65;
    static char *keywords[] = {
        const_cast<char *>("timeout_ms"),
        const_cast<char *>("length"),
        nullptr,
    };
    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "|ii:read_raw",
            keywords,
            &timeout_ms,
            &length)) {
        return nullptr;
    }
    if (length <= 0 || length > 4096) {
        PyErr_SetString(PyExc_ValueError, "length must be between 1 and 4096");
        return nullptr;
    }

    std::vector<unsigned char> buffer(static_cast<size_t>(length), 0);
    int ret = read_raw_bytes(&buffer, timeout_ms);
    if (ret < 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        return nullptr;
    }
    if (ret == 0) {
        Py_RETURN_NONE;
    }
    return PyBytes_FromStringAndSize(
        reinterpret_cast<const char *>(buffer.data()),
        ret);
}

static int signed_u8(unsigned char value) {
    return static_cast<int>(static_cast<int8_t>(value));
}

static int signed_le16(const unsigned char *data) {
    uint16_t value = static_cast<uint16_t>(data[0])
        | (static_cast<uint16_t>(data[1]) << 8);
    return static_cast<int>(static_cast<int16_t>(value));
}

static int parse_mouse_delta(
    const unsigned char *data,
    int length,
    int *dx,
    int *dy) {
    if (length >= 10 && data[1] == 0xbb && data[2] == 0x03) {
        *dx = signed_le16(data + 6);
        *dy = signed_le16(data + 8);
        return *dx != 0 || *dy != 0;
    }

    if (length >= 3 && length <= 4) {
        *dx = signed_u8(data[1]);
        *dy = signed_u8(data[2]);
        return *dx != 0 || *dy != 0;
    }

    if (length >= 5 && length <= 8) {
        *dx = signed_u8(data[2]);
        *dy = signed_u8(data[3]);
        return *dx != 0 || *dy != 0;
    }

    return 0;
}

static PyObject *py_read_mouse_delta(PyObject *, PyObject *args, PyObject *kwargs) {
    int timeout_ms = 10;
    static char *keywords[] = {
        const_cast<char *>("timeout_ms"),
        nullptr,
    };
    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "|i:read_mouse_delta",
            keywords,
            &timeout_ms)) {
        return nullptr;
    }

    std::vector<unsigned char> buffer(65, 0);
    int ret = read_raw_bytes(&buffer, timeout_ms);
    if (ret < 0) {
        PyErr_SetFromErrno(PyExc_OSError);
        return nullptr;
    }
    if (ret == 0) {
        Py_RETURN_NONE;
    }

    int dx = 0;
    int dy = 0;
    if (!parse_mouse_delta(buffer.data(), ret, &dx, &dy)) {
        Py_RETURN_NONE;
    }
    return Py_BuildValue("(ii)", dx, dy);
}

static PyObject *py_host_vidpid(PyObject *, PyObject *args, PyObject *kwargs) {
    int rw = 0;
    unsigned int vidpid = 0;
    unsigned int hiddid = 0;
    unsigned int mtype = 0;
    static char *keywords[] = {
        const_cast<char *>("rw"),
        const_cast<char *>("vidpid"),
        const_cast<char *>("hiddid"),
        const_cast<char *>("mtype"),
        nullptr,
    };
    if (!PyArg_ParseTupleAndKeywords(
            args,
            kwargs,
            "|iIII:host_vidpid",
            keywords,
            &rw,
            &vidpid,
            &hiddid,
            &mtype)) {
        return nullptr;
    }

    int ret = KM_HostVidpid(rw, &vidpid, &hiddid, &mtype);
    if (ret != 0) {
        return Py_BuildValue(
            "{s:i,s:I,s:I,s:I}",
            "ret",
            ret,
            "vidpid",
            vidpid,
            "hiddid",
            hiddid,
            "mtype",
            mtype);
    }
    return Py_BuildValue(
        "{s:i,s:I,s:I,s:I}",
        "ret",
        ret,
        "vidpid",
        vidpid,
        "hiddid",
        hiddid,
        "mtype",
        mtype);
}

static PyObject *script_detail_to_dict(const script_detail_t *script) {
    return Py_BuildValue(
        "{s:I,s:I,s:I,s:I,s:i,s:y#}",
        "onoff",
        script->Onoff,
        "start_addr",
        script->StartAddr,
        "length",
        script->Length,
        "run_count",
        script->RunCnt,
        "exist",
        script->Exist,
        "name",
        script->Name,
        static_cast<Py_ssize_t>(sizeof(script->Name)));
}

static PyObject *py_read_script(PyObject *, PyObject *) {
    kmbox_t km = {};
    int ret = KM_Readscript(&km);
    PyObject *scripts = PyList_New(5);
    if (scripts == nullptr) {
        return nullptr;
    }
    for (Py_ssize_t i = 0; i < 5; ++i) {
        PyObject *item = script_detail_to_dict(&km.script[i]);
        if (item == nullptr) {
            Py_DECREF(scripts);
            return nullptr;
        }
        PyList_SET_ITEM(scripts, i, item);
    }

    PyObject *result = Py_BuildValue(
        "{s:i,s:I,s:I,s:I,s:I,s:I,s:O}",
        "ret",
        ret,
        "new_board_flag",
        km.NewBoardFlag,
        "default_vid",
        km.defaultVID,
        "default_pid",
        km.defaultPID,
        "total_size",
        km.TotalSize,
        "used_size",
        km.UsedSize,
        "scripts",
        scripts);
    Py_DECREF(scripts);
    return result;
}

static PyObject *py_is_open(PyObject *, PyObject *) {
    if (fd_kmbox == nullptr) {
        Py_RETURN_FALSE;
    }
    Py_RETURN_TRUE;
}

static PyObject *py_close(PyObject *, PyObject *) {
    if (fd_kmbox != nullptr) {
        hid_close(fd_kmbox);
        fd_kmbox = nullptr;
    }
    Py_RETURN_NONE;
}

static PyMethodDef methods[] = {
    {"init", py_init, METH_VARARGS, "init(vid, pid) -> int"},
    {"press", py_press, METH_VARARGS, "press(key) -> int"},
    {"keydown", py_keydown, METH_VARARGS, "keydown(key) -> int"},
    {"keyup", py_keyup, METH_VARARGS, "keyup(key) -> int"},
    {"left", py_left, METH_VARARGS, "left(state) -> int"},
    {"middle", py_middle, METH_VARARGS, "middle(state) -> int"},
    {"right", py_right, METH_VARARGS, "right(state) -> int"},
    {"side1", py_side1, METH_VARARGS, "side1(state) -> int"},
    {"side2", py_side2, METH_VARARGS, "side2(state) -> int"},
    {"wheel", py_wheel, METH_VARARGS, "wheel(delta) -> int"},
    {"move", py_move, METH_VARARGS, "move(dx, dy) -> int"},
    {
        "read_raw",
        reinterpret_cast<PyCFunction>(py_read_raw),
        METH_VARARGS | METH_KEYWORDS,
        "read_raw(timeout_ms=10, length=65) -> bytes | None",
    },
    {
        "read_mouse_delta",
        reinterpret_cast<PyCFunction>(py_read_mouse_delta),
        METH_VARARGS | METH_KEYWORDS,
        "read_mouse_delta(timeout_ms=10) -> tuple[int, int] | None",
    },
    {
        "host_vidpid",
        reinterpret_cast<PyCFunction>(py_host_vidpid),
        METH_VARARGS | METH_KEYWORDS,
        "host_vidpid(rw=0, vidpid=0, hiddid=0, mtype=0) -> dict",
    },
    {"read_script", py_read_script, METH_NOARGS, "read_script() -> dict"},
    {"is_open", py_is_open, METH_NOARGS, "is_open() -> bool"},
    {"close", py_close, METH_NOARGS, "close() -> None"},
    {nullptr, nullptr, 0, nullptr},
};

static PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "kmA",
    "Enhanced kmboxA Python binding with recorder read support.",
    -1,
    methods,
};

PyMODINIT_FUNC PyInit_kmA(void) {
    return PyModule_Create(&module);
}
