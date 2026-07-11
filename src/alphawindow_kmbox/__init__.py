from __future__ import annotations

import ctypes
import importlib
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_char,
    c_char_p,
    c_ubyte,
    c_ulong,
    c_ushort,
    c_void_p,
    create_string_buffer,
    pointer,
)
import enum
import platform
import sys
import threading
from typing import Any, Callable

from alphawindow.plugins import PluginRecordingInputCaptureMethod, hookimpl
from alphawindow.recording import PynputRecordingControls
from alphawindow.types import BackendCompatibilityError


DEFAULT_VID = 0x1C1F
DEFAULT_PID = 0xC18A
DEFAULT_KMBOX_A_VID = 0x04D8
DEFAULT_KMBOX_A_PID = 0x003F
DEVICE_TYPE_AUTO = "auto"
DEVICE_TYPE_HID = "hid"
DEVICE_TYPE_KMBOX_A = "kmbox_a"
SUPPORTED_DEVICE_TYPES = (DEVICE_TYPE_AUTO, DEVICE_TYPE_HID, DEVICE_TYPE_KMBOX_A)


class ELockMouse(enum.IntEnum):
    LOCK_NONE = 0x00
    LOCK_X_Y = 0x18


class ENotifyMouse(enum.IntEnum):
    NOTIFY_NONE = 0x00
    NOTIFY_X_Y = 0x18


def decode_mouse_notification(
    payload: bytes | bytearray | list[int],
) -> tuple[int, int] | None:
    data = bytes(payload)
    if len(data) != 5:
        return None
    flags = data[0]
    if not flags & ENotifyMouse.NOTIFY_X_Y.value:
        return None
    dx = int.from_bytes(data[1:3], byteorder="big", signed=True)
    dy = int.from_bytes(data[3:5], byteorder="big", signed=True)
    return dx, dy


def detect_kmbox_devices(
    *,
    vid: int | str = DEFAULT_VID,
    pid: int | str = DEFAULT_PID,
    device_id: str | None = None,
    hid_factory: Callable[[], Any] | None = None,
) -> list[dict[str, Any]]:
    if sys.platform != "win32" and hid_factory is None:
        return []
    vid_value = _parse_int(vid)
    pid_value = _parse_int(pid)
    vidpid = f"#vid_{vid_value:04x}&pid_{pid_value:04x}&"
    device_filter = str(device_id or "")
    hid = (hid_factory or _HidDevice)()
    try:
        paths = hid.enum_device()
    finally:
        close = getattr(hid, "close", None)
        if callable(close):
            close()
    devices = []
    for path in paths:
        normalized = path.lower()
        if vidpid not in normalized:
            continue
        if device_filter and device_filter not in path:
            continue
        devices.append(
            {
                "device_path": path,
                "vid": f"0x{vid_value:04x}",
                "pid": f"0x{pid_value:04x}",
            }
        )
    return devices


def kmbox_connection_status(
    *,
    device_type: str = DEVICE_TYPE_AUTO,
    vid: int | str = DEFAULT_VID,
    pid: int | str = DEFAULT_PID,
    device_id: str | None = None,
    hid_factory: Callable[[], Any] | None = None,
    kmbox_a_vid: int | str = DEFAULT_KMBOX_A_VID,
    kmbox_a_pid: int | str = DEFAULT_KMBOX_A_PID,
    kmbox_a_module: Any | None = None,
    kmbox_a_module_path: str | None = None,
    **options: Any,
) -> dict[str, Any]:
    device_type = _normalize_device_type(device_type)
    if device_type == DEVICE_TYPE_HID:
        return _hid_connection_status(
            vid=vid,
            pid=pid,
            device_id=device_id,
            hid_factory=hid_factory,
        )
    if device_type == DEVICE_TYPE_KMBOX_A:
        return _kmbox_a_connection_status(
            vid=kmbox_a_vid,
            pid=kmbox_a_pid,
            module=kmbox_a_module,
            module_path=kmbox_a_module_path,
        )

    hid_status = _hid_connection_status(
        vid=vid,
        pid=pid,
        device_id=device_id,
        hid_factory=hid_factory,
    )
    if hid_status.get("connected"):
        return hid_status
    kmbox_a_status = _kmbox_a_connection_status(
        vid=kmbox_a_vid,
        pid=kmbox_a_pid,
        module=kmbox_a_module,
        module_path=kmbox_a_module_path,
    )
    if kmbox_a_status.get("connected"):
        return kmbox_a_status
    return {
        "supported": bool(hid_status.get("supported"))
        or bool(kmbox_a_status.get("supported")),
        "connected": False,
        "device_count": 0,
        "device_type": DEVICE_TYPE_AUTO,
        "supports_recording_input": False,
        "candidates": {
            DEVICE_TYPE_HID: hid_status,
            DEVICE_TYPE_KMBOX_A: kmbox_a_status,
        },
    }


def _hid_connection_status(
    *,
    vid: int | str = DEFAULT_VID,
    pid: int | str = DEFAULT_PID,
    device_id: str | None = None,
    hid_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    if sys.platform != "win32" and hid_factory is None:
        return {
            "supported": False,
            "connected": False,
            "device_count": 0,
            "device_type": DEVICE_TYPE_HID,
            "supports_recording_input": True,
        }
    try:
        devices = detect_kmbox_devices(
            vid=vid,
            pid=pid,
            device_id=device_id,
            hid_factory=hid_factory,
        )
        if not devices:
            return {
                "supported": True,
                "connected": False,
                "device_count": 0,
                "device_type": DEVICE_TYPE_HID,
                "supports_recording_input": True,
            }
        device = KmboxHidDevice(
            vid=vid,
            pid=pid,
            device_id=device_id,
            hid_factory=hid_factory,
        )
        try:
            connected = device.open()
            status = {
                "supported": True,
                "connected": connected,
                "device_count": len(devices),
                "device_type": DEVICE_TYPE_HID,
                "supports_recording_input": True,
            }
            if connected:
                status["model"] = device.model
                status["version"] = device.version
            return status
        finally:
            device.close()
    except Exception as exc:
        return {
            "supported": True,
            "connected": False,
            "device_count": 0,
            "device_type": DEVICE_TYPE_HID,
            "supports_recording_input": True,
            "error": str(exc),
        }


def _kmbox_a_connection_status(
    *,
    vid: int | str = DEFAULT_KMBOX_A_VID,
    pid: int | str = DEFAULT_KMBOX_A_PID,
    module: Any | None = None,
    module_path: str | None = None,
) -> dict[str, Any]:
    try:
        kmbox_a = module or _load_kmbox_a_module(module_path)
    except Exception as exc:
        return {
            "supported": False,
            "connected": False,
            "device_count": 0,
            "device_type": DEVICE_TYPE_KMBOX_A,
            "supports_recording_input": False,
            "error": str(exc),
        }
    try:
        connected = int(kmbox_a.init(_parse_int(vid), _parse_int(pid))) == 0
        supports_recording_input = _kmbox_a_supports_recording_input(kmbox_a)
    except Exception as exc:
        return {
            "supported": True,
            "connected": False,
            "device_count": 0,
            "device_type": DEVICE_TYPE_KMBOX_A,
            "supports_recording_input": False,
            "error": str(exc),
        }
    return {
        "supported": True,
        "connected": connected,
        "device_count": 1 if connected else 0,
        "device_type": DEVICE_TYPE_KMBOX_A,
        "supports_recording_input": supports_recording_input,
    }


def _load_kmbox_a_module(module_path: str | None = None) -> Any:
    if module_path:
        sys.path.insert(0, module_path)
        try:
            return importlib.import_module("kmA")
        finally:
            try:
                sys.path.remove(module_path)
            except ValueError:
                pass
    return importlib.import_module("kmA")


class KmboxRecordingControls:
    def __init__(
        self,
        *,
        session_provider: Callable[[], Any | None],
        on_resume: Callable[[], None],
        on_pause: Callable[[], None],
        on_stop: Callable[[], None] | None = None,
        on_label: Callable[[Any], None] | None = None,
        dispatch: Callable[[Callable[[], None]], None] | None = None,
        capture_inputs: bool = True,
        kmbox_factory: Callable[..., Any] | None = None,
        base_controls_factory: Callable[..., Any] | None = None,
        thread_factory: Callable[..., Any] = threading.Thread,
        read_timeout_ms: int = 10,
        passthrough: bool = True,
        **device_options: Any,
    ) -> None:
        self.session_provider = session_provider
        self.on_label = on_label
        self.dispatch = dispatch
        self.capture_inputs = bool(capture_inputs)
        self.kmbox_factory = kmbox_factory
        self.thread_factory = thread_factory
        self.read_timeout_ms = int(read_timeout_ms)
        self.passthrough = _coerce_bool(passthrough)
        self.device_options = dict(device_options)
        self.device: Any | None = None
        self.thread: Any | None = None
        self.base_controls = self._create_base_controls(
            base_controls_factory=base_controls_factory,
            session_provider=session_provider,
            on_resume=on_resume,
            on_pause=on_pause,
            on_stop=on_stop,
            on_label=on_label,
            dispatch=dispatch,
            capture_inputs=self.capture_inputs,
        )
        self._running = False

    def start(self) -> None:
        try:
            self.base_controls.start()
            if self.capture_inputs:
                self._start_device()
        except BaseException:
            self._stop_device()
            self.base_controls.close()
            raise

    def close(self) -> None:
        self._stop_device()
        self.base_controls.close()

    def set_input_capture_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled:
            previous_enabled = self.capture_inputs
            previous_device = self.device
            try:
                self._start_device()
                self.base_controls.set_input_capture_enabled(True)
            except BaseException:
                if previous_device is None:
                    self._stop_device()
                self.capture_inputs = previous_enabled
                if not previous_enabled:
                    self.base_controls.set_input_capture_enabled(False)
                raise
            self.capture_inputs = True
            return
        self.capture_inputs = False
        try:
            self.base_controls.set_input_capture_enabled(False)
        finally:
            self._stop_device()

    def _create_base_controls(
        self,
        *,
        base_controls_factory: Callable[..., Any] | None,
        **options: Any,
    ) -> Any:
        if base_controls_factory is not None:
            return base_controls_factory(**options)
        return PynputRecordingControls(
            **options,
            mouse_listener_factory=_click_only_mouse_listener_factory,
        )

    def _start_device(self) -> None:
        if self.device is not None:
            return
        device = self._create_device()
        if not device.open():
            raise BackendCompatibilityError("kmbox device was not found")
        try:
            device.configure_mouse_passthrough()
            self.device = device
            self._running = True
            self.thread = self.thread_factory(target=self._read_loop, daemon=True)
            self.thread.start()
        except BaseException:
            self._running = False
            self.device = None
            self.thread = None
            try:
                device.restore_mouse_passthrough()
            finally:
                device.close()
            raise

    def _create_device(self) -> Any:
        if self.kmbox_factory is not None:
            return self.kmbox_factory(**self.device_options)
        return create_kmbox_device(**self.device_options)

    def _stop_device(self) -> None:
        device = self.device
        if device is None:
            return
        self._running = False
        try:
            device.restore_mouse_passthrough()
        finally:
            device.close()
            thread = self.thread
            self.device = None
            self.thread = None
        if thread is not None:
            thread.join(timeout=1.0)

    def _read_loop(self) -> None:
        assert self.device is not None
        while self._running and self.device.is_open():
            payload = self.device.read_notify(self.read_timeout_ms)
            if not payload:
                continue
            delta = decode_mouse_notification(payload)
            if delta is None:
                continue
            dx, dy = delta
            session = self.session_provider()
            if session is not None:
                label = session.record_mouse_delta(dx, dy)
                if label is not None and self.on_label is not None:
                    self._dispatch(lambda: self.on_label(label))
            if self.passthrough:
                self.device.move_relative(dx, dy)

    def _dispatch(self, callback: Callable[[], None]) -> None:
        if self.dispatch is None:
            callback()
            return
        self.dispatch(callback)


class KmboxHidDevice:
    def __init__(
        self,
        *,
        vid: int | str = DEFAULT_VID,
        pid: int | str = DEFAULT_PID,
        device_id: str | None = None,
        hid_factory: Callable[[], Any] | None = None,
        **_options: Any,
    ) -> None:
        if sys.platform != "win32" and hid_factory is None:
            raise BackendCompatibilityError(
                "kmbox HID capture is only supported on Windows"
            )
        self.vid = _parse_int(vid)
        self.pid = _parse_int(pid)
        self.device_id = device_id
        self.hid = (hid_factory or _HidDevice)()
        self.model = 0
        self.version = 0

    def open(self) -> bool:
        vidpid = f"#vid_{self.vid:04x}&pid_{self.pid:04x}&"
        for device_path in self.hid.enum_device():
            if vidpid not in device_path.lower():
                continue
            if self.device_id and self.device_id not in device_path:
                continue
            if not self.hid.open(device_path):
                continue
            version = self._get_version()
            if not version:
                self.close()
                continue
            self.model = version[0]
            self.version = version[1]
            return True
        return False

    def close(self) -> None:
        self.hid.close()

    def is_open(self) -> bool:
        return self.hid.handle is not None

    def configure_mouse_passthrough(self) -> None:
        self.set_wait_response(True)
        self.lock_mouse(ELockMouse.LOCK_X_Y)
        self.notify_mouse(ENotifyMouse.NOTIFY_X_Y)

    def restore_mouse_passthrough(self) -> None:
        self.notify_mouse(ENotifyMouse.NOTIFY_NONE)
        self.lock_mouse(ELockMouse.LOCK_NONE)

    def read_notify(self, timeout_ms: int) -> bytes | None:
        return self._read_data_timeout_promise(43, timeout_ms)

    def move_relative(self, dx: int, dy: int) -> None:
        self._mouse_event(91, dx, dy)

    def set_wait_response(self, _wait: bool) -> None:
        self._write_cmd(34)
        self._read_data_timeout_promise(39, 10)

    def lock_mouse(self, option: ELockMouse) -> None:
        self._write_cmd(25, [int(option)])
        self._read_data_timeout_promise(39, 10)

    def notify_mouse(self, option: ENotifyMouse) -> None:
        self._write_cmd(26, [int(option)])
        self._read_data_timeout_promise(39, 10)

    def _get_version(self) -> bytes | None:
        self._write_cmd(1)
        return self._read_data_timeout_promise(1, 10)

    def _write_cmd(self, cmd: int, data: list[int] | None = None) -> int:
        if self.hid.handle is None:
            return -1
        if data and len(data) > 61:
            return -2
        buf = [32, 1, int(cmd)]
        if data:
            buf[1] = len(data) + 1
            buf.extend(data)
        buf.extend([0xFF] * (64 - len(buf)))
        ret = self.hid.write(buf)
        if ret < 0:
            self.close()
        return ret

    def _read_data_timeout(
        self,
        timeout_ms: int | None = None,
    ) -> tuple[int, bytes] | None:
        if self.hid.handle is None:
            return None
        try:
            ret = self.hid.read(64, timeout_ms)
        except OSError:
            self.close()
            return None
        if ret and ret[0] == 31:
            return ret[2], ret[3 : ret[1] + 2]
        return None

    def _read_data_timeout_promise(
        self,
        cmd: int,
        timeout_ms: int | None = None,
    ) -> bytes | None:
        for _index in range(10):
            ret = self._read_data_timeout(timeout_ms)
            if ret and ret[0] == cmd:
                return ret[1]
        return None

    def _mouse_event(self, event: int, dx: int = 0, dy: int = 0) -> None:
        if not -32768 <= dx <= 32767 or not -32768 <= dy <= 32767:
            return
        cmd = [0xFF] * 12
        cmd[0] = event
        cmd[1] = (dx >> 8) & 0xFF
        cmd[2] = dx & 0xFF
        cmd[3] = (dy >> 8) & 0xFF
        cmd[4] = dy & 0xFF
        self._write_cmd(16, cmd)
        self._read_data_timeout_promise(20, 10)


class KmboxADevice:
    def __init__(
        self,
        *,
        kmbox_a_vid: int | str = DEFAULT_KMBOX_A_VID,
        kmbox_a_pid: int | str = DEFAULT_KMBOX_A_PID,
        kmbox_a_module: Any | None = None,
        kmbox_a_module_path: str | None = None,
        **_options: Any,
    ) -> None:
        self.vid = _parse_int(kmbox_a_vid)
        self.pid = _parse_int(kmbox_a_pid)
        self.module = kmbox_a_module
        self.module_path = kmbox_a_module_path
        self._opened = False

    def open(self) -> bool:
        module = self.module or _load_kmbox_a_module(self.module_path)
        self.module = module
        self._opened = int(module.init(self.vid, self.pid)) == 0
        return self._opened

    def close(self) -> None:
        self._opened = False

    def is_open(self) -> bool:
        if self.module is not None:
            is_open = getattr(self.module, "is_open", None)
            if callable(is_open):
                return self._opened and bool(is_open())
        return self._opened

    def configure_mouse_passthrough(self) -> None:
        if not _kmbox_a_supports_recording_input(self.module):
            raise BackendCompatibilityError(
                "kmboxA does not support recording input capture"
            )

    def restore_mouse_passthrough(self) -> None:
        return None

    def read_notify(self, timeout_ms: int) -> bytes | None:
        if self.module is None:
            return None
        read_mouse_delta = getattr(self.module, "read_mouse_delta", None)
        if not callable(read_mouse_delta):
            return None
        delta = read_mouse_delta(int(timeout_ms))
        if delta is None:
            return None
        dx, dy = delta
        return _encode_mouse_notification(int(dx), int(dy))

    def move_relative(self, dx: int, dy: int) -> None:
        if self.module is not None:
            self.module.move(int(dx), int(dy))


def create_kmbox_device(
    *,
    device_type: str = DEVICE_TYPE_AUTO,
    **options: Any,
) -> Any:
    device_type = _normalize_device_type(device_type)
    if device_type == DEVICE_TYPE_HID:
        return KmboxHidDevice(**options)
    if device_type == DEVICE_TYPE_KMBOX_A:
        return KmboxADevice(**options)
    status = kmbox_connection_status(device_type=DEVICE_TYPE_AUTO, **options)
    if status.get("device_type") == DEVICE_TYPE_KMBOX_A:
        return KmboxADevice(**options)
    return KmboxHidDevice(**options)


class GUID(Structure):
    _fields_ = [
        ("Data1", c_ulong),
        ("Data2", c_ushort),
        ("Data3", c_ushort),
        ("Data4", c_ubyte * 8),
    ]


class SP_DEVICE_INTERFACE_DATA(Structure):
    _fields_ = [
        ("cbSize", c_ulong),
        ("InterfaceClassGuid", GUID),
        ("Flags", c_ulong),
        ("Reserved", c_ulong),
    ]


def _sp_data_a_factory(length: int) -> type[Structure]:
    class SP_DEVICE_INTERFACE_DETAIL_DATA_A(Structure):
        _fields_ = [("cbSize", c_ulong), ("DevicePath", c_char * (length - 4))]

    return SP_DEVICE_INTERFACE_DETAIL_DATA_A


class _HidDevice:
    def __init__(self) -> None:
        self.setupapi_dll = ctypes.WinDLL("setupapi.dll")
        info_value = [
            c_ulong(0x4D1E55B2),
            c_ushort(0xF16F),
            c_ushort(0x11CF),
            (c_ubyte * 8)(0x88, 0xCB, 0x00, 0x11, 0x11, 0x00, 0x00, 0x30),
        ]
        self.interface_class_guid = GUID(*info_value)
        self.handle: int | None = None
        self.setupapi_dll.SetupDiGetClassDevsA.restype = c_void_p
        self.setupapi_dll.SetupDiEnumDeviceInterfaces.argtypes = (
            c_void_p,
            c_void_p,
            POINTER(GUID),
            c_ulong,
            POINTER(SP_DEVICE_INTERFACE_DATA),
        )

    def enum_device(self) -> list[str]:
        result: list[str] = []
        device_info_set = self.setupapi_dll.SetupDiGetClassDevsA(
            pointer(self.interface_class_guid),
            None,
            None,
            0x12,
        )
        if device_info_set == -1:
            return result
        device_index = 0
        while True:
            if platform.architecture()[0] == "64bit":
                info_value = [c_ulong(32), self.interface_class_guid, 0, 0]
            else:
                info_value = [c_ulong(28), self.interface_class_guid, 0, 0]
            interface_data = SP_DEVICE_INTERFACE_DATA(*info_value)
            ret = self.setupapi_dll.SetupDiEnumDeviceInterfaces(
                device_info_set,
                None,
                pointer(self.interface_class_guid),
                device_index,
                byref(interface_data),
            )
            if not ret:
                break
            required_size = c_ulong(0)
            sp_data_a = _sp_data_a_factory(8)
            self.setupapi_dll.SetupDiGetDeviceInterfaceDetailA.argtypes = (
                c_void_p,
                POINTER(SP_DEVICE_INTERFACE_DATA),
                POINTER(sp_data_a),
                c_ulong,
                POINTER(c_ulong),
                c_void_p,
            )
            self.setupapi_dll.SetupDiGetDeviceInterfaceDetailA(
                device_info_set,
                pointer(interface_data),
                None,
                0,
                byref(required_size),
                None,
            )
            sp_data_a = _sp_data_a_factory(required_size.value)
            self.setupapi_dll.SetupDiGetDeviceInterfaceDetailA.argtypes = (
                c_void_p,
                POINTER(SP_DEVICE_INTERFACE_DATA),
                POINTER(sp_data_a),
                c_ulong,
                POINTER(c_ulong),
                c_void_p,
            )
            cb_size = 8 if platform.architecture()[0] == "64bit" else 5
            detail_data = sp_data_a(cb_size, b"")
            ret = self.setupapi_dll.SetupDiGetDeviceInterfaceDetailA(
                device_info_set,
                pointer(interface_data),
                byref(detail_data),
                required_size,
                None,
                None,
            )
            if ret:
                path = detail_data.DevicePath.decode("gbk")
                if "pid" in path and "&mi_00#" in path:
                    result.append(path)
            device_index += 1
        return result

    def open(self, path: str) -> bool:
        handle = ctypes.windll.kernel32.CreateFileA(
            c_char_p(bytes(path, "gbk")),
            0xC0000000,
            3,
            None,
            3,
            0x00000080,
            0,
        )
        if handle == -1:
            return False
        self.handle = handle
        return True

    def close(self) -> None:
        if self.handle:
            ctypes.windll.kernel32.CancelIo(self.handle)
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None

    def write(self, data: list[int]) -> int:
        if self.handle is None:
            return -1
        return int(
            ctypes.windll.kernel32.WriteFile(
                self.handle,
                c_char_p(bytes(bytearray(data))),
                len(data),
                None,
                None,
            )
        )

    def read(self, length: int, _timeout_ms: int | None) -> bytes | None:
        if self.handle is None:
            return None
        buf = create_string_buffer(length)
        bytes_read = c_ulong(0)
        ret = ctypes.windll.kernel32.ReadFile(
            self.handle,
            buf,
            length,
            byref(bytes_read),
            None,
        )
        if ret:
            return bytes(buf)
        return None


@hookimpl
def alphawindow_recording_input_capture_methods():
    return [
        PluginRecordingInputCaptureMethod(
            name="kmbox",
            factory=KmboxRecordingControls,
            description="record generic kmbox relative mouse input",
            metadata={
                "plugin_id": "kmbox",
                "plugin_name": "kmbox",
                "connection_status": {
                    "kind": "hardware_probe",
                    "probe": "kmbox_connection_status",
                },
                "_connection_status_probe": kmbox_connection_status,
                "property_schema": {
                    "device_type": {
                        "type": "string",
                        "label": "Device type",
                        "default": "auto",
                        "enum": ["auto", "hid", "kmbox_a"],
                    },
                    "device_id": {
                        "type": "string",
                        "label": "Device path contains",
                        "default": "",
                    },
                    "kmbox_a_vid": {
                        "type": "string",
                        "label": "kmboxA VID",
                        "default": "0x04d8",
                    },
                    "kmbox_a_pid": {
                        "type": "string",
                        "label": "kmboxA PID",
                        "default": "0x003f",
                    },
                    "kmbox_a_module_path": {
                        "type": "string",
                        "label": "kmboxA module path",
                        "default": "",
                    },
                    "passthrough": {
                        "type": "boolean",
                        "label": "Pass through movement",
                        "default": True,
                    },
                    "read_timeout_ms": {
                        "type": "number",
                        "label": "Read timeout ms",
                        "default": 10,
                    },
                },
            },
        )
    ]


def _click_only_mouse_listener_factory(**callbacks: Any) -> Any:
    from pynput import mouse

    return mouse.Listener(on_click=callbacks.get("on_click"))


def _parse_int(value: int | str) -> int:
    if isinstance(value, int):
        return value
    value = value.strip()
    return int(value, 16 if value.lower().startswith("0x") else 10)


def _normalize_device_type(value: Any) -> str:
    device_type = str(value or DEVICE_TYPE_AUTO).strip().lower()
    if device_type in {"", "default"}:
        return DEVICE_TYPE_AUTO
    if device_type in {"kmboxa", "kmbox-a", "a"}:
        return DEVICE_TYPE_KMBOX_A
    if device_type not in SUPPORTED_DEVICE_TYPES:
        raise ValueError(f"unsupported kmbox device type: {value!r}")
    return device_type


def _kmbox_a_supports_recording_input(module: Any | None) -> bool:
    return callable(getattr(module, "read_mouse_delta", None))


def _encode_mouse_notification(dx: int, dy: int) -> bytes:
    return bytes(
        [
            ENotifyMouse.NOTIFY_X_Y.value,
            (dx >> 8) & 0xFF,
            dx & 0xFF,
            (dy >> 8) & 0xFF,
            dy & 0xFF,
        ]
    )


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


__all__ = [
    "KmboxADevice",
    "KmboxHidDevice",
    "KmboxRecordingControls",
    "create_kmbox_device",
    "detect_kmbox_devices",
    "decode_mouse_notification",
    "kmbox_connection_status",
    "alphawindow_recording_input_capture_methods",
]
