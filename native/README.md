# Enhanced kmA Binding

`kmA_enhanced.cpp` is a CPython extension source for building an enhanced
`kmA.pyd` against the kmboxA vendor sources.

It keeps the existing public functions used by the current `kmA` module:

- `init`
- `move`
- `press`
- `keydown`
- `keyup`
- `left`
- `middle`
- `right`
- `side1`
- `side2`
- `wheel`

It also adds the recorder-facing functions consumed by `alphawindow-kmbox`:

- `read_raw(timeout_ms=10, length=65) -> bytes | None`
- `read_mouse_delta(timeout_ms=10) -> tuple[int, int] | None`
- `host_vidpid(rw=0, vidpid=0, hiddid=0, mtype=0) -> dict`
- `read_script() -> dict`
- `is_open() -> bool`
- `close() -> None`

Build it with the Python build helper. It uses `setuptools.build_ext`, which
uses Python's MSVC discovery and does not require `cl.exe` to be manually added
to a normal PowerShell `PATH`.

```powershell
python native\build_kma.py `
  --vendor-dir C:\Path\To\kmboxA\kmboxdll `
  --output-dir C:\Path\To\kmboxA\python_pyd
```

When `--output-dir` is omitted, the helper writes to a sibling `python_pyd`
folder when that folder exists, otherwise to `native/build`.

After building, point the plugin's `kmbox_a_module_path` setting at the folder
containing the enhanced `kmA` module. `kmbox_connection_status()` will then
report `supports_recording_input=True` for connected kmboxA devices.
