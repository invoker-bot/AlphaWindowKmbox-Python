# AlphaWindow kmbox Plugin

Generic kmbox recording input plugin for AlphaWindow.

The plugin registers the `kmbox` recording input method through the
`alphawindow.plugins` entry point. It records kmbox mouse movement as
AlphaWindow `mouse_delta` labels and leaves the target window selection to
AlphaWindow itself.

## Device Type Detection

The plugin supports `device_type=auto`, `hid`, and `kmbox_a`.

`auto` probes the notify-capable HID kmbox first, then probes kmboxA through the
optional `kmA` Python extension. HID devices support recording input capture.
The stock `kmA` modules bundled with the reference kmboxA package can be used
for connection detection. An enhanced `kmA` binding that exposes
`read_mouse_delta(timeout_ms)` is required for kmboxA recorder input capture;
see `native/`.

The status probe does not enable mouse lock or notify capture:

```powershell
python -c "from alphawindow_kmbox import kmbox_connection_status; print(kmbox_connection_status())"
```

AlphaWindow can also surface this probe through plugin status metadata.

## Development

```powershell
python -m pip install -e .[test]
pytest -q
```

Local tests use `../AlphaWindow-Python/src` so this project can be developed
against the adjacent AlphaWindow checkout while the recording input plugin
protocol is being integrated.

## License

MIT

## Publishing

Publishing is handled by `.github/workflows/publish.yml`.

- Push a `v*` tag, or run the workflow manually from GitHub Actions.
- Set the repository secret `PYPI_API_TOKEN` to a PyPI API token.
- The workflow runs tests, builds the package, checks the distribution metadata,
  and uploads the artifacts to PyPI.
