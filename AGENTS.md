# AGENTS.md

## Project Scope

This repository contains `alphawindow-kmbox`, a generic kmbox recording input
plugin for AlphaWindow. Keep the package focused on kmbox hardware input
capture and AlphaWindow plugin registration.

Do not add CSGO-specific, game-specific, process-name-specific, or
window-title-specific behavior here. Target selection belongs to AlphaWindow;
this plugin only supplies a recording input source.

## Development

- Use Python 3.11+.
- Package code lives under `src/alphawindow_kmbox/`.
- Tests live under `tests/`.
- The plugin is discovered through the `alphawindow.plugins` entry point.
- Local tests expect the adjacent AlphaWindow checkout at
  `../AlphaWindow-Python/src` while the recording input plugin protocol is
  being integrated.

## Verification

Run:

```powershell
pytest -q
```

For behavior changes, add or update tests first. The important behavior is that
kmbox movement is recorded as AlphaWindow `mouse_delta` labels, with hardware
state restored on close.

## Safety

kmbox mouse lock and notify state are global hardware settings. Any code that
enables them must restore `NOTIFY_NONE` and `LOCK_NONE` during shutdown or error
handling.
