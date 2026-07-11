from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_enhanced_kma_binding_exports_recorder_reader_api() -> None:
    source = (PROJECT_ROOT / "native" / "kmA_enhanced.cpp").read_text(
        encoding="utf-8"
    )

    assert '"read_raw"' in source
    assert '"read_mouse_delta"' in source
    assert '"host_vidpid"' in source
    assert "PyInit_kmA" in source


def test_build_helper_creates_setuptools_extension_for_vendor_sources(tmp_path) -> None:
    vendor_dir = tmp_path / "kmboxdll"
    vendor_dir.mkdir()
    for name in ("kmboxApi.cpp", "hid.c", "hidapi.h", "kmbox.h"):
        (vendor_dir / name).write_text("", encoding="utf-8")

    helper = _load_build_helper()

    extension = helper.create_extension(vendor_dir)

    assert extension.name == "kmA"
    assert [Path(source).name for source in extension.sources] == [
        "kmA_enhanced.cpp",
        "kmboxApi.cpp",
        "hid.c",
    ]
    assert Path(extension.include_dirs[0]) == vendor_dir
    assert {"setupapi", "hid"}.issubset(set(extension.libraries))
    assert extension.language == "c++"


def _load_build_helper():
    path = PROJECT_ROOT / "native" / "build_kma.py"
    spec = importlib.util.spec_from_file_location("build_kma", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
