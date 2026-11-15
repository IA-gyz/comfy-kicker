"""Application startup, single-instance guard and desktop integration."""
from .common import *
from .ui import Kicker
import tempfile

def _exec_arg(path):
    """Desktop Entry Exec argument: quote only when it contains whitespace
    (some launchers mishandle always-quoted Exec)."""
    s = str(path)
    return f'"{s}"' if re.search(r"\s", s) else s

def install_desktop():
    d = Path.home() / ".local/share/applications"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "comfy-kicker.desktop"
    entrypoint = Path(__file__).resolve().parent.parent / "comfy_kicker.py"
    f.write_text("[Desktop Entry]\n"
                 "Type=Application\n"
                 "Name=Comfy Kicker\n"
                 "Comment=ComfyUI launcher\n"
                 f"Exec={_exec_arg(sys.executable)} {_exec_arg(entrypoint)}\n"
                 f"Path={entrypoint.parent}\n"
                 "Icon=applications-graphics\n"
                 "Categories=Graphics;Development;\n"
                 "Terminal=false\n"
                 "StartupNotify=true\n")
    # The executable bit marks the entry trusted, so KDE/GNOME actually launch it.
    f.chmod(0o755)
    print(f"Wrote {f}")
    udb = shutil.which("update-desktop-database")  # refresh the menu cache when available
    if udb:
        subprocess.run([udb, str(d)], check=False)
    gio = shutil.which("gio")  # GNOME: explicit trust flag
    if gio:
        subprocess.run([gio, "set", str(f), "metadata::trusted", "true"], check=False)

def claim_instance(app):
    """One launcher per user; later launches only activate its existing window."""
    runtime = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation)
    directory = Path(runtime) / "comfy-kicker" if runtime else Path(tempfile.gettempdir()) / f"comfy-kicker-{os.getuid()}"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    endpoint = str(directory / "launcher.sock")
    lock = QLockFile(str(directory / "launcher.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        socket = QLocalSocket()
        socket.connectToServer(endpoint)
        if socket.waitForConnected(1500):
            socket.disconnectFromServer()
            print("Comfy Kicker is already open; activating its window.")
        else:
            print("Comfy Kicker is already running or starting; no second window was opened.")
        return False
    server = QLocalServer(app)
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    QLocalServer.removeServer(endpoint)  # safe only after owning the process lock
    if not server.listen(endpoint):
        print("Cannot start Comfy Kicker activation service: " + server.errorString(), file=sys.stderr)
        lock.unlock()
        return False
    def activate():
        while server.hasPendingConnections():
            connection = server.nextPendingConnection()
            connection.close()
            connection.deleteLater()
        window = getattr(app, "_main_window", None)
        if window is not None:
            window._show_from_tray()
    server.newConnection.connect(activate)
    app._instance_lock, app._instance_server = lock, server
    app.aboutToQuit.connect(server.close)
    return True

def main():
    if "--install-desktop" in sys.argv:
        return install_desktop()
    app = QApplication(sys.argv)
    app.setApplicationName("Comfy Kicker")
    if not claim_instance(app):
        return
    if (Path.home() / ".local/share/applications/comfy-kicker.desktop").exists():
        app.setDesktopFileName("comfy-kicker")  # lets Plasma match the window to the launcher entry
    w = Kicker()
    app._main_window = w
    w.show()
    sys.exit(app.exec())
