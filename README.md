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
