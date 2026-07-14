from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from alphawindow.recording import RecordingLabel
from alphawindow.types import (
    BackendCompatibilityError,
    Capability,
    InputMode,
    Operation,
    WindowSnapshot,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_imports_local_project_package() -> None:
    import alphawindow_kmbox

    module_path = Path(alphawindow_kmbox.__file__).resolve()

    assert module_path.is_relative_to(PROJECT_ROOT / "src")


def test_kmbox_plugin_registers_recording_input_method() -> None:
    from alphawindow_kmbox import alphawindow_recording_input_capture_methods

    methods = alphawindow_recording_input_capture_methods()

    assert len(methods) == 1
    assert methods[0].name == "kmbox"
    assert methods[0].metadata["plugin_id"] == "kmbox"
    assert methods[0].metadata["connection_status"] == {
        "kind": "hardware_probe",
        "probe": "kmbox_connection_status",
    }
    schema = methods[0].metadata["property_schema"]
    assert schema["device_type"] == {
        "type": "string",
        "label": "Device type",
        "default": "auto",
        "enum": ["auto", "hid", "kmbox_a"],
    }


def test_kmbox_plugin_registers_replay_input_method() -> None:
    from alphawindow_kmbox import alphawindow_input_methods

    class FakeDevice:
        def __init__(self) -> None:
            self.opened = False
            self.closed = False
            self.moves = []

        def open(self) -> bool:
            self.opened = True
            return True

        def close(self) -> None:
            self.closed = True

        def move_relative(self, dx: int, dy: int) -> None:
            self.moves.append((dx, dy))

    device = FakeDevice()
    methods = alphawindow_input_methods()

    assert len(methods) == 1
    method = methods[0]
    assert method.name == "kmbox"
    assert method.mode is InputMode.FOREGROUND
    assert method.capabilities == frozenset({Capability.GLOBAL_INPUT})
    assert method.metadata["plugin_id"] == "kmbox"

    backend = method.create_backend(kmbox_factory=lambda **_options: device)
    target = WindowSnapshot(hwnd=1, title="target", rect=(0, 0, 100, 100), dpi=96)
    result = backend.perform(
        target,
        Operation(kind="mouse_delta", metadata={"dx": 12, "dy": -7}),
    )
    backend.close()

    assert device.opened is True
    assert device.moves == [(12, -7)]
    assert device.closed is True
    assert result.executed is True
    assert result.backend == "kmbox"
    assert result.details == {"hwnd": 1}


def test_kmbox_detect_devices_filters_vid_pid_and_device_id() -> None:
    from alphawindow_kmbox import detect_kmbox_devices

    class FakeHid:
        def __init__(self) -> None:
            self.closed = False

        def enum_device(self) -> list[str]:
            return [
                r"\\?\hid#vid_1c1f&pid_c18a&mi_00#primary",
                r"\\?\hid#vid_1c1f&pid_c18a&mi_00#secondary",
                r"\\?\hid#vid_ffff&pid_c18a&mi_00#other",
            ]

        def close(self) -> None:
            self.closed = True

    hid = FakeHid()

    devices = detect_kmbox_devices(
        device_id="secondary",
        hid_factory=lambda: hid,
    )

    assert hid.closed is True
    assert devices == [
        {
            "device_path": r"\\?\hid#vid_1c1f&pid_c18a&mi_00#secondary",
            "vid": "0x1c1f",
            "pid": "0xc18a",
        }
    ]


def test_kmbox_connection_status_opens_version_probe_without_mouse_lock() -> None:
    from alphawindow_kmbox import kmbox_connection_status

    class FakeHid:
        def __init__(self) -> None:
            self.handle = None
            self.writes = []
            self.closed = False

        def enum_device(self) -> list[str]:
            return [r"\\?\HID#VID_1C1F&PID_C18A&MI_00#device"]

        def open(self, _path: str) -> bool:
            self.handle = object()
            return True

        def write(self, data: list[int]) -> int:
            self.writes.append(data)
            return len(data)

        def read(self, _length: int, _timeout_ms: int | None) -> bytes:
            return bytes([31, 3, 1, 2, 7] + [0] * 59)

        def close(self) -> None:
            self.closed = True
            self.handle = None

    hid = FakeHid()

    status = kmbox_connection_status(hid_factory=lambda: hid)

    assert status == {
        "supported": True,
        "connected": True,
        "device_count": 1,
        "device_type": "hid",
        "supports_recording_input": True,
        "model": 2,
        "version": 7,
    }
    assert hid.closed is True
    assert [write[2] for write in hid.writes] == [1]


def test_kmbox_connection_status_auto_prefers_hid_device_type() -> None:
    from alphawindow_kmbox import kmbox_connection_status

    class FakeHid:
        def __init__(self) -> None:
            self.handle = None

        def enum_device(self) -> list[str]:
            return [r"\\?\hid#vid_1c1f&pid_c18a&mi_00#device"]

        def open(self, _path: str) -> bool:
            self.handle = object()
            return True

        def write(self, _data: list[int]) -> int:
            return 64

        def read(self, _length: int, _timeout_ms: int | None) -> bytes:
            return bytes([31, 3, 1, 2, 7] + [0] * 59)

        def close(self) -> None:
            self.handle = None

    class UnusedKmboxAModule:
        def init(self, _vid: int, _pid: int) -> int:
            raise AssertionError("kmboxA probe should not run when HID is present")

    status = kmbox_connection_status(
        device_type="auto",
        hid_factory=FakeHid,
        kmbox_a_module=UnusedKmboxAModule(),
    )

    assert status["connected"] is True
    assert status["device_type"] == "hid"
    assert status["supports_recording_input"] is True


def test_kmbox_connection_status_auto_detects_kmbox_a_device_type() -> None:
    from alphawindow_kmbox import kmbox_connection_status

    class MissingHid:
        def enum_device(self) -> list[str]:
            return []

        def close(self) -> None:
            pass

    class FakeKmboxAModule:
        def __init__(self) -> None:
            self.calls = []

        def init(self, vid: int, pid: int) -> int:
            self.calls.append((vid, pid))
            return 0

    module = FakeKmboxAModule()

    status = kmbox_connection_status(
        device_type="auto",
        hid_factory=MissingHid,
        kmbox_a_module=module,
        kmbox_a_vid="0x04d8",
        kmbox_a_pid="0x003f",
    )

    assert module.calls == [(0x04D8, 0x003F)]
    assert status == {
        "supported": True,
        "connected": True,
        "device_count": 1,
        "device_type": "kmbox_a",
        "supports_recording_input": False,
    }


def test_kmbox_connection_status_reports_enhanced_kmbox_a_capture_support() -> None:
    from alphawindow_kmbox import kmbox_connection_status

    class EnhancedKmboxAModule:
        def init(self, _vid: int, _pid: int) -> int:
            return 0

        def read_mouse_delta(self, _timeout_ms: int):
            return None

    status = kmbox_connection_status(
        device_type="kmbox_a",
        kmbox_a_module=EnhancedKmboxAModule(),
    )

    assert status == {
        "supported": True,
        "connected": True,
        "device_count": 1,
        "device_type": "kmbox_a",
        "supports_recording_input": True,
    }


def test_kmbox_notification_decoder_returns_signed_relative_delta() -> None:
    from alphawindow_kmbox import decode_mouse_notification

    assert decode_mouse_notification(bytes([0x18, 0x00, 0x0C, 0xFF, 0xF9])) == (
        12,
        -7,
    )
    assert decode_mouse_notification(bytes([0x00, 0x00, 0x0C, 0xFF, 0xF9])) is None
    assert decode_mouse_notification(bytes([0x18, 0x00])) is None


def test_kmbox_recording_controls_capture_mouse_delta_without_window_specific_state() -> None:
    from alphawindow_kmbox import KmboxRecordingControls

    class FakeDevice:
        def __init__(self) -> None:
            self.opened = False
            self.closed = False
            self.locked = []
            self.notified = []
            self.moves = []
            self.reads = 0

        def open(self) -> bool:
            self.opened = True
            return True

        def configure_mouse_passthrough(self) -> None:
            self.locked.append("x_y")
            self.notified.append("x_y")

        def restore_mouse_passthrough(self) -> None:
            self.notified.append("none")
            self.locked.append("none")

        def is_open(self) -> bool:
            return self.opened and not self.closed and self.reads == 0

        def read_notify(self, timeout_ms: int):
            assert timeout_ms == 10
            self.reads += 1
            return bytes([0x18, 0x00, 0x0C, 0xFF, 0xF9])

        def move_relative(self, dx: int, dy: int) -> None:
            self.moves.append((dx, dy))

        def close(self) -> None:
            self.closed = True

    class ImmediateThread:
        def __init__(self, *, target, daemon: bool) -> None:
            self.target = target
            self.daemon = daemon
            self.started = False

        def start(self) -> None:
            self.started = True
            self.target()

        def join(self, timeout=None) -> None:
            return None

    class BaseControls:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.started = False
            self.capture_enabled = kwargs["capture_inputs"]

        def start(self) -> None:
            self.started = True

        def close(self) -> None:
            pass

        def set_input_capture_enabled(self, enabled: bool) -> None:
            self.capture_enabled = bool(enabled)

    device = FakeDevice()
    emitted = []
    session = SimpleNamespace(
        record_mouse_delta=lambda dx, dy: RecordingLabel(
            t=0.1,
            type="mouse_delta",
            fields={"mode": "relative_delta", "dx": dx, "dy": dy},
        )
    )

    controls = KmboxRecordingControls(
        session_provider=lambda: session,
        on_resume=lambda: None,
        on_pause=lambda: None,
        on_stop=lambda: None,
        on_label=emitted.append,
        capture_inputs=True,
        kmbox_factory=lambda **_options: device,
        base_controls_factory=BaseControls,
        thread_factory=ImmediateThread,
    )

    controls.start()
    controls.close()

    assert device.opened is True
    assert device.locked == ["x_y", "none"]
    assert device.notified == ["x_y", "none"]
    assert device.moves == [(12, -7)]
    assert [label.to_json_dict() for label in emitted] == [
        {
            "t": 0.1,
            "type": "mouse_delta",
            "mode": "relative_delta",
            "dx": 12,
            "dy": -7,
        }
    ]
    assert controls.base_controls.started is True
    assert controls.base_controls.capture_enabled is True


def test_kmbox_recording_controls_closes_base_controls_when_device_not_found() -> None:
    from alphawindow_kmbox import KmboxRecordingControls

    class MissingDevice:
        def open(self) -> bool:
            return False

    class BaseControls:
        def __init__(self, **_kwargs) -> None:
            self.started = False
            self.closed = False

        def start(self) -> None:
            self.started = True

        def close(self) -> None:
            self.closed = True

        def set_input_capture_enabled(self, _enabled: bool) -> None:
            pass

    controls = KmboxRecordingControls(
        session_provider=lambda: None,
        on_resume=lambda: None,
        on_pause=lambda: None,
        capture_inputs=True,
        kmbox_factory=lambda **_options: MissingDevice(),
        base_controls_factory=BaseControls,
    )

    try:
        controls.start()
    except BackendCompatibilityError as exc:
        assert str(exc) == "kmbox device was not found"
    else:
        raise AssertionError("controls.start() should fail when kmbox is missing")

    assert controls.base_controls.started is True
    assert controls.base_controls.closed is True


def test_kmbox_recording_controls_rolls_back_base_capture_when_enable_fails() -> None:
    from alphawindow_kmbox import KmboxRecordingControls

    class MissingDevice:
        def open(self) -> bool:
            return False

    class BaseControls:
        def __init__(self, **kwargs) -> None:
            self.capture_enabled = kwargs["capture_inputs"]

        def start(self) -> None:
            pass

        def close(self) -> None:
            pass

        def set_input_capture_enabled(self, enabled: bool) -> None:
            self.capture_enabled = bool(enabled)

    controls = KmboxRecordingControls(
        session_provider=lambda: None,
        on_resume=lambda: None,
        on_pause=lambda: None,
        capture_inputs=False,
        kmbox_factory=lambda **_options: MissingDevice(),
        base_controls_factory=BaseControls,
    )
    controls.start()

    try:
        controls.set_input_capture_enabled(True)
    except BackendCompatibilityError as exc:
        assert str(exc) == "kmbox device was not found"
    else:
        raise AssertionError("enabling capture should fail when kmbox is missing")

    assert controls.capture_inputs is False
    assert controls.base_controls.capture_enabled is False
    assert controls.device is None
    assert controls.thread is None


def test_kmbox_recording_controls_restore_device_when_configuration_fails() -> None:
    from alphawindow_kmbox import KmboxRecordingControls

    class FailingDevice:
        def __init__(self) -> None:
            self.opened = False
            self.restored = False
            self.closed = False

        def open(self) -> bool:
            self.opened = True
            return True

        def configure_mouse_passthrough(self) -> None:
            raise RuntimeError("configuration failed")

        def restore_mouse_passthrough(self) -> None:
            self.restored = True

        def close(self) -> None:
            self.closed = True

    class BaseControls:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            pass

        def close(self) -> None:
            pass

        def set_input_capture_enabled(self, _enabled: bool) -> None:
            pass

    device = FailingDevice()
    controls = KmboxRecordingControls(
        session_provider=lambda: None,
        on_resume=lambda: None,
        on_pause=lambda: None,
        capture_inputs=True,
        kmbox_factory=lambda **_options: device,
        base_controls_factory=BaseControls,
    )

    try:
        controls.start()
    except RuntimeError as exc:
        assert str(exc) == "configuration failed"
    else:
        raise AssertionError("controls.start() should propagate configuration failure")

    assert device.opened is True
    assert device.restored is True
    assert device.closed is True
    assert controls.device is None
    assert controls.thread is None


def test_kmbox_recording_controls_restore_device_when_thread_start_fails() -> None:
    from alphawindow_kmbox import KmboxRecordingControls

    class Device:
        def __init__(self) -> None:
            self.opened = False
            self.configured = False
            self.restored = False
            self.closed = False

        def open(self) -> bool:
            self.opened = True
            return True

        def configure_mouse_passthrough(self) -> None:
            self.configured = True

        def restore_mouse_passthrough(self) -> None:
            self.restored = True

        def close(self) -> None:
            self.closed = True

    class FailingThread:
        def __init__(self, *, target, daemon: bool) -> None:
            self.target = target
            self.daemon = daemon

        def start(self) -> None:
            raise RuntimeError("thread start failed")

        def join(self, timeout=None) -> None:
            raise AssertionError("failed thread should not be joined")

    class BaseControls:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            pass

        def close(self) -> None:
            pass

        def set_input_capture_enabled(self, _enabled: bool) -> None:
            pass

    device = Device()
    controls = KmboxRecordingControls(
        session_provider=lambda: None,
        on_resume=lambda: None,
        on_pause=lambda: None,
        capture_inputs=True,
        kmbox_factory=lambda **_options: device,
        base_controls_factory=BaseControls,
        thread_factory=FailingThread,
    )

    try:
        controls.start()
    except RuntimeError as exc:
        assert str(exc) == "thread start failed"
    else:
        raise AssertionError("controls.start() should propagate thread failure")

    assert device.opened is True
    assert device.configured is True
    assert device.restored is True
    assert device.closed is True
    assert controls.device is None
    assert controls.thread is None


def test_kmbox_recording_controls_auto_detects_kmbox_a_as_unsupported_capture() -> None:
    from alphawindow_kmbox import KmboxRecordingControls

    class MissingHid:
        def enum_device(self) -> list[str]:
            return []

        def close(self) -> None:
            pass

    class FakeKmboxAModule:
        def init(self, _vid: int, _pid: int) -> int:
            return 0

        def move(self, _dx: int, _dy: int) -> int:
            return 0

    class BaseControls:
        def __init__(self, **_kwargs) -> None:
            self.closed = False

        def start(self) -> None:
            pass

        def close(self) -> None:
            self.closed = True

        def set_input_capture_enabled(self, _enabled: bool) -> None:
            pass

    controls = KmboxRecordingControls(
        session_provider=lambda: None,
        on_resume=lambda: None,
        on_pause=lambda: None,
        capture_inputs=True,
        device_type="auto",
        hid_factory=MissingHid,
        kmbox_a_module=FakeKmboxAModule(),
        base_controls_factory=BaseControls,
    )

    try:
        controls.start()
    except BackendCompatibilityError as exc:
        assert str(exc) == "kmboxA does not support recording input capture"
    else:
        raise AssertionError("kmboxA should not be used as recording input capture")

    assert controls.base_controls.closed is True
    assert controls.device is None
    assert controls.thread is None


def test_kmbox_recording_controls_records_kmbox_a_delta_with_enhanced_binding() -> None:
    from alphawindow_kmbox import KmboxRecordingControls

    class EnhancedKmboxAModule:
        def __init__(self) -> None:
            self.calls = []
            self.moves = []
            self.open = False

        def init(self, vid: int, pid: int) -> int:
            self.calls.append(("init", vid, pid))
            self.open = True
            return 0

        def read_mouse_delta(self, timeout_ms: int):
            self.calls.append(("read_mouse_delta", timeout_ms))
            if self.open:
                self.open = False
                return (5, -3)
            return None

        def is_open(self) -> bool:
            return self.open

        def move(self, dx: int, dy: int) -> int:
            self.moves.append((dx, dy))
            return 0

    class ImmediateThread:
        def __init__(self, *, target, daemon: bool) -> None:
            self.target = target
            self.daemon = daemon

        def start(self) -> None:
            self.target()

        def join(self, timeout=None) -> None:
            return None

    class BaseControls:
        def __init__(self, **kwargs) -> None:
            self.capture_enabled = kwargs["capture_inputs"]
            self.closed = False

        def start(self) -> None:
            pass

        def close(self) -> None:
            self.closed = True

        def set_input_capture_enabled(self, enabled: bool) -> None:
            self.capture_enabled = bool(enabled)

    module = EnhancedKmboxAModule()
    emitted = []
    session = SimpleNamespace(
        record_mouse_delta=lambda dx, dy: RecordingLabel(
            t=0.2,
            type="mouse_delta",
            fields={"mode": "relative_delta", "dx": dx, "dy": dy},
        )
    )

    controls = KmboxRecordingControls(
        session_provider=lambda: session,
        on_resume=lambda: None,
        on_pause=lambda: None,
        on_stop=lambda: None,
        on_label=emitted.append,
        capture_inputs=True,
        device_type="kmbox_a",
        kmbox_a_module=module,
        kmbox_a_vid="0x04d8",
        kmbox_a_pid="0x003f",
        base_controls_factory=BaseControls,
        thread_factory=ImmediateThread,
    )

    controls.start()
    controls.close()

    assert module.calls == [
        ("init", 0x04D8, 0x003F),
        ("read_mouse_delta", 10),
    ]
    assert module.moves == [(5, -3)]
    assert [label.to_json_dict() for label in emitted] == [
        {
            "t": 0.2,
            "type": "mouse_delta",
            "mode": "relative_delta",
            "dx": 5,
            "dy": -3,
        }
    ]
