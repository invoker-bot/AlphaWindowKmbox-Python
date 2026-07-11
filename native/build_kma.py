from __future__ import annotations

import argparse
from pathlib import Path

from setuptools import Distribution, Extension
from setuptools.command.build_ext import build_ext


NATIVE_DIR = Path(__file__).resolve().parent
REQUIRED_VENDOR_FILES = ("kmboxApi.cpp", "hid.c", "hidapi.h", "kmbox.h")


def create_extension(vendor_dir: str | Path) -> Extension:
    vendor_path = validate_vendor_dir(vendor_dir)
    return Extension(
        "kmA",
        sources=[
            str(NATIVE_DIR / "kmA_enhanced.cpp"),
            str(vendor_path / "kmboxApi.cpp"),
            str(vendor_path / "hid.c"),
        ],
        include_dirs=[str(vendor_path)],
        libraries=["setupapi", "hid"],
        language="c++",
        extra_compile_args=["/std:c++17", "/EHsc"],
    )


def validate_vendor_dir(vendor_dir: str | Path) -> Path:
    vendor_path = Path(vendor_dir).resolve()
    missing = [
        str(vendor_path / name)
        for name in REQUIRED_VENDOR_FILES
        if not (vendor_path / name).exists()
    ]
    if missing:
        raise FileNotFoundError(
            "kmboxA vendor source directory is missing required file(s): "
            + ", ".join(missing)
        )
    return vendor_path


def build_extension(
    *,
    vendor_dir: str | Path,
    output_dir: str | Path | None = None,
    build_temp: str | Path | None = None,
    dry_run: bool = False,
) -> list[Path]:
    vendor_path = validate_vendor_dir(vendor_dir)
    output_path = Path(output_dir).resolve() if output_dir else _default_output_dir(vendor_path)
    temp_path = (
        Path(build_temp).resolve()
        if build_temp
        else output_path / "build-temp"
    )
    output_path.mkdir(parents=True, exist_ok=True)
    temp_path.mkdir(parents=True, exist_ok=True)

    distribution = Distribution(
        {
            "name": "kmA-enhanced",
            "ext_modules": [create_extension(vendor_path)],
        }
    )
    command = build_ext(distribution)
    command.ensure_finalized()
    command.build_lib = str(output_path)
    command.build_temp = str(temp_path)
    command.force = True
    command.dry_run = dry_run
    command.run()
    return [Path(output).resolve() for output in command.get_outputs()]


def _default_output_dir(vendor_dir: Path) -> Path:
    sibling_python_pyd = vendor_dir.parent / "python_pyd"
    if sibling_python_pyd.exists():
        return sibling_python_pyd.resolve()
    return (NATIVE_DIR / "build").resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the enhanced kmA CPython extension with setuptools build_ext. "
            "This uses Python's MSVC discovery instead of requiring cl.exe on PATH."
        )
    )
    parser.add_argument(
        "--vendor-dir",
        required=True,
        help="Path to the kmboxA kmboxdll source directory.",
    )
    parser.add_argument(
        "--output-dir",
        help=(
            "Directory for the built kmA .pyd. Defaults to a sibling python_pyd "
            "folder when present, otherwise native/build."
        ),
    )
    parser.add_argument(
        "--build-temp",
        help="Temporary build directory. Defaults under the output directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ask build_ext to print/prepare commands without compiling.",
    )
    args = parser.parse_args(argv)

    outputs = build_extension(
        vendor_dir=args.vendor_dir,
        output_dir=args.output_dir,
        build_temp=args.build_temp,
        dry_run=args.dry_run,
    )
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
