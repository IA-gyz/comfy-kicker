"""Application startup, single-instance guard and desktop integration."""
from .common import *
from .ui import Kicker
import tempfile

def install_desktop():
    d = Path.home() / ".local/share/applications"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "comfy-kicker.desktop"
    entrypoint = Path(__file__).resolve().parent.parent / "comfy_kicker.py"
    f.write_text("[Desktop Entry]\nType=Application\nName=Comfy Kicker\nComment=ComfyUI launcher\n"
                 f'Exec="{sys.executable}" "{entrypoint}"\n'
                 "Icon=applications-graphics\nCategories=Graphics;Development;\nTerminal=false\n")
    print(f"Wrote {f}")

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
