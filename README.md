# Comfy Kicker (modular)

Run from this directory:

```bash
python comfy_kicker.py
```

Install/update the desktop launcher:

```bash
python comfy_kicker.py --install-desktop
```

## Modules

- `comfy_kicker.py` — executable entry point.
- `comfy_kicker_app/common.py` — shared imports, settings, constants and log rules.
- `comfy_kicker_app/launcher.py` — ComfyUI discovery, config, browser and launch helpers.
- `comfy_kicker_app/monitor.py` — queue and workflow monitoring panels.
- `comfy_kicker_app/session.py` — second ComfyUI session (own process, port and GPU).
- `comfy_kicker_app/ui.py` — reusable UI widgets and main window.
- `comfy_kicker_app/main.py` — startup, single-instance guard and desktop integration.

The package directory must remain alongside `comfy_kicker.py`.

## Log filter behavior

- No filter boxes checked: show every log line.
- One or more, but not all, checked: show lines matching the selected categories.
- All filter boxes checked: show classified lines only; unclassified/verbose lines are hidden.

## GPU selection

Comfy Kicker detects CUDA devices using the configured ComfyUI virtual
environment's PyTorch installation. Detected devices appear as mutually
exclusive radio buttons; the selected device is saved in the application
configuration. Use **Refresh GPUs** after changing the ComfyUI environment or
CUDA visibility settings.

The selected device is isolated for the ComfyUI process with
`CUDA_VISIBLE_DEVICES`, so ComfyUI sees the selected GPU as its CUDA device 0.
The `--cuda-device` option is hidden from the launcher. If no CUDA device can
be detected, no selection is forced and ComfyUI retains its normal default.

## Second session (other GPU)

The **Second session (other GPU)** section starts a second ComfyUI process from
the same venv and the same ComfyUI folder — no second venv is needed — while
sharing the discovered flags, extra arguments, environment and prefix. Only two
things are per-session:

- **Port** (default 8288): session 2 forces its own `--port`, so it never
  collides with session 1's `--port`. Keep the two ports different.
- **GPU**: its own radio-button picker, defaulting to a GPU different from
  session 1's. The choice is applied per process via `CUDA_VISIBLE_DEVICES`, so
  each session sees its GPU as CUDA device 0. Launching with the same GPU or
  port as a running session 1 only logs a warning.

Each session has its own log tab (the log filter checkboxes apply to both), its
own workflow-timing panel tab (polling that session's port), its own status
label, and its own **Open in browser** button, which opens that session's URL
(`http://127.0.0.1:<port>`) with the selected browser in a new window / app
window — the same browser as session 1 by default. Both sessions are stopped
when the window is closed. Port and GPU choices are saved in the config.

Note: the Magik TtC API ports 8189–8198 are shared; if both sessions run the
Magik TtC custom node, only one can bind them — use the per-session workflow
panel (ComfyUI's own API on each session's port) instead.
