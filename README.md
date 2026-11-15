# Comfy Kicker (modular)

Run from this directory:

```bash
python comfy_kicker.py
```

Install/update the desktop launcher:

```bash
python comfy_kicker.py --install-desktop
```

This writes `~/.local/share/applications/comfy-kicker.desktop` with the
correct `Exec`/`Path`, marks it executable (trusted on KDE/GNOME) and refreshes
the desktop database / trust flags when the tools are available, so the entry
works from the application menu right away.

## Modules

- `comfy_kicker.py` — executable entry point.
- `comfy_kicker_app/common.py` — shared imports, settings, constants and log rules.
- `comfy_kicker_app/launcher.py` — ComfyUI discovery, config, browser and launch helpers.
- `comfy_kicker_app/monitor.py` — queue and workflow monitoring panels.
- `comfy_kicker_app/widgets.py` — flag rows, collapsible sections, per-session log panes.
- `comfy_kicker_app/session.py` — one ComfyUI process per GPU tab (own port and GPU).
- `comfy_kicker_app/panel.py` — the dedicated per-GPU session panel (one tab each).
- `comfy_kicker_app/ui.py` — main window: common folder row + session tabs.
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

Known cards get a product photo next to their name in both GPU pickers
(matched on vendor/model in `GPU_IMAGES` in `common.py`; photos live in
`comfy_kicker_app/assets/`): the ASUS card photo is the RTX 3090, the PNY
photo is the RTX 4070 Ti Super.

## Per-GPU session tabs

The window has one **common row** at the top — ComfyUI folder and venv folder —
shared by both GPUs. Below it, one **dedicated tab per GPU** (the tab shows the
GPU's name and product photo once detected). Everything else lives inside each
tab and is fully independent per session:

- GPU radio picker (defaulting to a GPU different from the other tab's), with
  **Refresh GPUs** on each tab;
- its own flags (Favorites / All other flags), presets, sound, prefix / extra
  arguments / environment, command preview and Launch / Stop / Restart;
- its own log with its own filter checkboxes, auto-scroll and Open Log;
- its own `--port` (the second tab defaults to 8288), so the two servers never
  collide;
- its own workflow-timing panel polling that session's port;
- its own **Open in browser** button, opening that session's URL
  (`http://127.0.0.1:<port>`) with the shared browser choice in a new window /
  app window.

Each tab is tinted with its own accent theme (`PANEL_THEMES` in `panel.py`:
green for the first GPU tab, blue for the second — frame, section borders,
section toggles, checked GPU radio and the Launch button), so the two panels
are easy to tell apart at a glance. The second tab is hidden and disabled until
ComfyUI is launched or launching on the first tab (it stays visible while a
session 2 process is running, so it can never become unreachable).

Each tab starts its own ComfyUI process from the same venv and folder — no
second venv is needed. The chosen GPU is isolated per process via
`CUDA_VISIBLE_DEVICES`, so each session sees its GPU as CUDA device 0.
Launching with the same GPU or port as the other running session only logs a
warning. Both sessions are stopped when the window is closed; each tab's state
is saved under `sessions` in the config.

Note: the Magik TtC API ports 8189–8198 are shared; if both sessions run the
Magik TtC custom node, only one can bind them — use the per-tab workflow panel
(ComfyUI's own API on each session's port) instead.
