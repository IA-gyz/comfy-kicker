"""Second ComfyUI session: its own process, port and GPU, sharing the install and flags."""
from PySide6.QtCore import QObject

from .common import *
from .launcher import _split


class ComfySession(QObject):
    """An additional ComfyUI process launched from the same venv/install as session 1.

    Shares the discovered flag rows, extra/env/prefix fields and browser settings of the
    main window, but forces its own --port and its own CUDA_VISIBLE_DEVICES token, so both
    sessions can run side by side on different GPUs. Output goes to session 2's log tab.
    """
    output = Signal(str)
    stateChanged = Signal()

    KILL_AFTER_MS = 8000

    def __init__(self, kicker):
        super().__init__(kicker)
        self.k = kicker
        self.port = 8288
        self.gpu_index, self.gpu_token = None, None
        self._restart = False
        self._ready, self._tail = False, ""  # server-up flag and a short output tail to spot the ready marker
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(lambda e: self.output.emit(f"[kicker] process error: {e}\n"))
        self.proc.errorOccurred.connect(lambda _e: self.stateChanged.emit())  # FailedToStart emits no finished()
        self._kill_timer = QTimer(self)  # escalates a stuck Stop to SIGKILL; cancelled when the process exits
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._force_kill)

    def running(self):
        return self.proc.state() != QProcess.ProcessState.NotRunning

    def endpoint(self):
        """This session's ComfyUI URL (its own port on 127.0.0.1, tls flag respected)."""
        return self.k.monitor_endpoint(self.port)

    def flag_args(self):
        """Shared flags with --port replaced by this session's port."""
        out, skip = [], False
        for arg in self.k.flag_args():
            if skip:
                skip = False
                continue
            if arg == "--port":
                skip = True
                continue
            if arg.startswith("--port="):
                continue
            out.append(arg)
        return out + ["--port", str(self.port)]

    def env_pairs(self):
        pairs = self.k.env_pairs()
        if self.gpu_token is not None:
            pairs = [(key, value) for key, value in pairs if key != "CUDA_VISIBLE_DEVICES"]
            pairs.append(("CUDA_VISIBLE_DEVICES", str(self.gpu_token)))
        return pairs

    def launch_command(self):
        prefix = _split(self.k.prefix_edit.text())
        command = [self.k.python_path(), str(Path(self.k.comfy_edit.text().strip()) / "main.py"), *self.flag_args()]
        if prefix:
            # env is a real executable here, so assignments follow the wrapper.
            pairs = [f"{key}={value}" for key, value in self.env_pairs()]
            return [*prefix, "env", *pairs, *command]
        return command

    def command_str(self):
        prefix = _split(self.k.prefix_edit.text())
        if prefix:
            return shlex.join(self.launch_command())
        env = "".join(f"{key}={shlex.quote(value)} " for key, value in self.env_pairs())
        return f"{env}{shlex.join(self.launch_command())}"

    def launch(self):
        if self.running():
            return
        k = self.k
        comfy, venv = k.comfy_edit.text().strip(), k.venv_edit.text().strip()
        if not (Path(comfy) / "main.py").exists() or not Path(k.python_path()).exists():
            self.output.emit("[kicker] Check the ComfyUI folder (needs main.py) and the venv folder (needs bin/python).\n")
            return
        if k._running() and str(k.flag_port()) == str(self.port):
            self.output.emit(f"[kicker] warning: port {self.port} is already used by session 1; pick another port\n")
        if k._running() and k.selected_gpu_token is not None and str(self.gpu_token) == str(k.selected_gpu_token):
            self.output.emit(f"[kicker] warning: both sessions would use CUDA device {self.gpu_token}; pick the other GPU\n")
        env = QProcessEnvironment.systemEnvironment()
        env.insert("VIRTUAL_ENV", venv)
        env.insert("PATH", f"{venv}/bin:" + env.value("PATH"))
        env.insert("PYTHONUNBUFFERED", "1")
        env.remove("PYTHONHOME")
        if not _split(k.prefix_edit.text()):
            for key, val in k.env_pairs():
                env.insert(key, val)
        if self.gpu_token is not None:
            env.insert("CUDA_VISIBLE_DEVICES", str(self.gpu_token))
        self.proc.setProcessEnvironment(env)
        self.proc.setWorkingDirectory(comfy)
        self._ready, self._tail = False, ""
        self.output.emit(f"[kicker] {self.command_str()}\n")
        command = self.launch_command()
        self.proc.start(command[0], command[1:])
        self.stateChanged.emit()

    def stop(self):
        if self.running():
            self.proc.terminate()
            self._kill_timer.start(self.KILL_AFTER_MS)

    def _force_kill(self):
        if self.running():
            self.output.emit(f"[kicker] ComfyUI (session 2) did not stop within {self.KILL_AFTER_MS // 1000}s; killing it\n")
            self.proc.kill()

    def restart(self):
        if self.running():
            self._restart = True
            self.stop()
        else:
            self.launch()

    def _read(self):
        text = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        if not self._ready:
            self._tail = (self._tail + text)[-200:]
            self._ready = bool(READY_RE.search(self._tail))
        self.output.emit(text)
        self.stateChanged.emit()

    def _finished(self, code, _status):
        self._kill_timer.stop()  # a late kill must never hit a freshly relaunched process
        self.output.emit(bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace"))  # flush trailing output
        self.output.emit(f"\n[kicker] ComfyUI (session 2) exited (code {code})\n")
        self.stateChanged.emit()
        if self._restart:
            self._restart = False
            self.launch()


__all__ = [name for name in globals() if not name.startswith("__")]
