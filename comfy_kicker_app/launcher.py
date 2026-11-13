"""ComfyUI discovery, configuration, browser and launch helpers."""
from .common import *

def _fmt_secs(s):
    return f"{int(s // 60)}m {s % 60:04.1f}s" if s >= 60 else f"{s:.2f}s"

# Runs inside the ComfyUI venv: imports the real parser and dumps it as JSON.
INTROSPECT = r'''
import sys, json, enum, argparse
sys.path.insert(0, sys.argv[1])
import comfy.cli_args as c
def plain(v):
    if isinstance(v, enum.Enum):
        v = v.value
    return v if isinstance(v, (str, int, float)) and not isinstance(v, bool) else None
gid = {id(a): i for i, g in enumerate(c.parser._mutually_exclusive_groups) for a in g._group_actions}
flags = []
for a in c.parser._actions:
    if not a.option_strings or a.option_strings[0] in ("-h", "--help") or a.help == argparse.SUPPRESS:
        continue
    name = type(a).__name__
    flags.append(dict(
        flag=a.option_strings[0], help=a.help or "",
        kind="bool" if name in ("_StoreTrueAction", "_StoreFalseAction") else "value",
        nargs=a.nargs, choices=[str(x) for x in a.choices] if a.choices else None,
        metavar=a.metavar if isinstance(a.metavar, str) else None,
        group=gid.get(id(a)), append=(name == "_AppendAction"),
        default=plain(a.default), const=plain(a.const)))
fast = [e.value for e in c.PerformanceFeature] if hasattr(c, "PerformanceFeature") else []
print(json.dumps(dict(flags=flags, fast_options=fast)))
'''


GPU_INTROSPECT = r'''
import json
try:
    import torch
    devices = []
    if torch.cuda.is_available():
        for index in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(index)
            devices.append({
                "index": index,
                "name": torch.cuda.get_device_name(index),
                "memory": int(props.total_memory),
            })
    print(json.dumps({"gpus": devices}))
except Exception as exc:
    print(json.dumps({"gpus": [], "error": str(exc)}))
'''

def detect_gpus(py, comfy_dir, extra_env=None):
    """Detect CUDA devices using the exact Python environment ComfyUI will use.

    Indices are CUDA logical indices after CUDA_VISIBLE_DEVICES is applied. Each
    result also carries the corresponding visibility token used to isolate it
    for the ComfyUI process.
    """
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    visible = env.get("CUDA_VISIBLE_DEVICES")
    tokens = [part.strip() for part in visible.split(",")] if visible is not None else None
    try:
        result = subprocess.run(
            [py, "-c", GPU_INTROSPECT], capture_output=True, text=True,
            timeout=30, cwd=comfy_dir or None, env=env, check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr.strip().splitlines() or [f"exit code {result.returncode}"])[-1]
            return [], f"GPU detection failed: {detail}"
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        devices = payload.get("gpus", [])
        for device in devices:
            index = int(device["index"])
            device["visibility_token"] = (tokens[index] if tokens and index < len(tokens) else str(index))
        if devices:
            return devices, f"Detected {len(devices)} CUDA GPU(s)"
        return [], payload.get("error") or "No CUDA GPUs detected; ComfyUI will use its default device selection"
    except Exception as exc:  # noqa: BLE001
        return [], f"GPU detection failed: {exc}"


def spec(flag, help, kind="bool", nargs=None, group=None, default=None, const=None, choices=None):
    return dict(flag=flag, help=help, kind=kind, nargs=nargs, choices=choices, metavar=None,
                group=group, append=False, default=default, const=const)


def fallback_data():
    """Minimal built-in list, used when discovery from the install fails."""
    return dict(flags=[
        spec("--listen", "IP address(es) to listen on. Blank = all interfaces.", "value", "?", default="127.0.0.1", const="0.0.0.0,::"),
        spec("--port", "Set the listen port.", "value", default=8188),
        spec("--disable-auto-launch", "Disable auto launching the browser."),
        spec("--preview-method", "Default preview method for sampler nodes.", "value", choices=["none", "auto", "latent2rgb", "taesd"], default="none"),
        spec("--use-pytorch-cross-attention", "Use the pytorch 2.0 cross attention function.", group=1),
        spec("--use-sage-attention", "Use sage attention.", group=1),
        spec("--use-flash-attention", "Use FlashAttention.", group=1),
        spec("--disable-xformers", "Disable xformers."),
        spec("--highvram", "Keep models in GPU memory after use.", group=2),
        spec("--lowvram", "Low VRAM mode.", group=2),
        spec("--novram", "When lowvram isn't enough.", group=2),
        spec("--reserve-vram", "VRAM in GB to reserve for the OS/other software.", "value"),
        spec("--disable-smart-memory", "Aggressively offload to RAM instead of keeping models in VRAM."),
        spec("--fast-disk", "Force disk-backed dynamic loading and offload."),
        spec("--cache-none", "Reduced RAM/VRAM usage; executes every node on each run."),
        spec("--fast", "Experimental optimizations; no sub-options enables everything.", "value", "*"),
    ], fast_options=["fp16_accumulation", "fp8_matrix_mult", "cublas_ops", "autotune"])


def discover(py, comfy_dir):
    """Returns (data, note). Falls back to the built-in list on any failure."""
    try:
        r = subprocess.run([py, "-c", INTROSPECT, comfy_dir], capture_output=True, text=True, timeout=30, cwd=comfy_dir)
        if r.returncode == 0:
            return json.loads(r.stdout.strip().splitlines()[-1]), "flags loaded from your ComfyUI install"
        err = (r.stderr.strip().splitlines() or ["unknown error"])[-1]
    except Exception as e:  # noqa: BLE001
        err = str(e)
    return fallback_data(), f"flag discovery failed ({err}); using built-in list"


def _split(text):
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def load_config():
    try:
        return json.loads(CONFIG.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _desktop_entry(path):
    """Minimal [Desktop Entry] parser (unlocalized keys only)."""
    ent, inside = {}, False
    try:
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("["):
                if inside:
                    break
                inside = line == "[Desktop Entry]"
            elif inside and "=" in line and not line.startswith("#"):
                k, _, val = line.partition("=")
                ent.setdefault(k.strip(), val.strip())
    except OSError:
        pass
    return ent


def find_browsers():
    """Installed web browsers as {desktop-file name: entry}: any visible app that handles http links."""
    home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    sys_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
    dirs = [home / "applications", *(Path(d) / "applications" for d in sys_dirs if d),
            Path("/var/lib/flatpak/exports/share/applications"), home / "flatpak/exports/share/applications"]
    found, seen = {}, set()
    for d in dirs:
        for f in sorted(d.glob("*.desktop")) if d.is_dir() else []:
            if f.name in seen:  # earlier (user) dirs override later ones
                continue
            seen.add(f.name)
            e = _desktop_entry(f)
            if (e.get("Type") == "Application" and e.get("Exec")
                    and e.get("NoDisplay", "").lower() != "true" and e.get("Hidden", "").lower() != "true"
                    and "x-scheme-handler/http" in e.get("MimeType", "").split(";")):
                found[f.name] = e
    return dict(sorted(found.items(), key=lambda kv: kv[1].get("Name", kv[0]).lower()))


def browser_icon(entry):
    """Use the browser's installed desktop icon, including Flatpak exports."""
    icon_name = entry.get("Icon", "")
    if icon_name and Path(icon_name).is_absolute():
        icon = QIcon(icon_name)
        if not icon.isNull():
            return icon
    names = [icon_name] if icon_name else []
    identity = (entry.get("Name", "") + " " + entry.get("Exec", "")).lower()
    for brand, aliases in (
        ("librewolf", ["librewolf"]), ("floorp", ["floorp"]),
        ("zen", ["zen-browser"]), ("firefox", ["firefox", "firefox-esr"]),
        ("brave", ["brave-browser", "brave"]),
        ("chromium", ["chromium", "chromium-browser"]),
        ("chrome", ["google-chrome", "google-chrome-stable"]),
        ("vivaldi", ["vivaldi", "vivaldi-stable"]),
        ("opera", ["opera"]), ("edge", ["microsoft-edge"]),
        ("tor browser", ["tor-browser"]),
    ):
        if brand in identity:
            names.extend(aliases)
            break
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    roots = [data_home, *(Path(d) for d in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if d),
             Path("/var/lib/flatpak/exports/share"), data_home / "flatpak/exports/share"]
    for name in dict.fromkeys(names):
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
        if not name or "/" in name:
            continue
        # Fallback when Qt's current icon theme omits hicolor/app icons.
        for root in roots:
            for folder in [root / "pixmaps", *(root / "icons/hicolor" / size / "apps"
                            for size in ("scalable", "48x48", "64x64", "128x128", "256x256", "32x32", "24x24", "16x16"))]:
                for suffix in ("", ".svg", ".png", ".xpm"):
                    path = folder / (name + suffix)
                    if path.is_file():
                        icon = QIcon(str(path))
                        if not icon.isNull():
                            return icon
    return QIcon.fromTheme("web-browser", QIcon.fromTheme("applications-internet"))


def browser_family(entry):
    identity = (entry.get("Name", "") + " " + entry.get("Exec", "")).lower()
    if any(name in identity for name in ("helium", "chromium", "chrome", "brave", "vivaldi", "opera", "microsoft-edge", "microsoft edge")):
        return "chromium"
    if any(name in identity for name in ("firefox", "librewolf", "floorp", "zen-browser", "zen browser")):
        return "firefox"
    return "other"


def browser_command(exec_line, url, app=False, family="other", shortcut=False):
    """Build argv without a shell; preserve wrapper/profile arguments."""
    argv, used = [], False
    for tok in _split(exec_line):
        if re.search(r"%[uUfF]", tok):
            if app and family == "chromium" and not shortcut:
                continue
            used = True
            tok = re.sub(r"%[uUfF]", lambda _: url, tok)
        tok = re.sub(r"%[ikcdDnNvm]", "", tok).replace("%%", "%")
        if tok:
            argv.append(tok)
    if not argv:
        raise ValueError("Empty browser command")
    if app and not shortcut and family == "chromium":
        argv = [arg for arg in argv if not arg.startswith(("--app=", "--app-id=")) and arg != "--new-window"]
        argv.append("--app=" + url)
    else:
        if app and not shortcut and family == "firefox" and "--new-window" not in argv:
            argv.append("--new-window")
        if not used and not shortcut:
            argv.append(url)
    return argv


def launch_entry(exec_line, url, app=False, family="other", shortcut=False):
    subprocess.Popen(browser_command(exec_line, url, app, family, shortcut), start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _fp(e):
    """Stable fingerprint of an API entry; keeps client-deleted cards hidden across polls."""
    d = e.get("duration")
    dur = f"{d:.2f}" if isinstance(d, (int, float)) else str(d)
    return f"{e.get('end_time')}|{dur}|{','.join(map(str, e.get('files') or []))}"


def _dur(e):
    try:
        return float(e.get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


def _fmt_dur(s):
    if not s or s <= 0:
        return "—"
    return f"{s:.1f}s" if s < 60 else f"{int(s // 60)}m {int(s % 60):02d}s"


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default



__all__ = [name for name in globals() if not name.startswith("__")]
