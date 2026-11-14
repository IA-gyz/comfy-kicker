"""Main window: the common ComfyUI/venv row on top, one dedicated tab per GPU session."""
from .common import *
from .launcher import *
from .panel import SessionPanel


class Kicker(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Comfy Kicker")
        self.resize(1400, 1010)
        self.cfg = load_config()
        self._migrate_config()
        self.gpus = []
        self._build_ui()
        self.reload_flags()
        self._health_nam = QNetworkAccessManager(self)
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(1000)
        self._health_timer.timeout.connect(self._probe_server)
        self._health_timer.start()
        self._probe_server()
        self._refresh_tray()

    def _migrate_config(self):
        """Move legacy flat config keys into per-session sub-dicts (one per GPU tab)."""
        sessions = self.cfg.get("sessions")
        if isinstance(sessions, list) and len(sessions) == 2 and all(isinstance(s, dict) for s in sessions):
            return
        legacy_keys = ("state", "prefix", "extra", "env", "presets", "favorite_flags", "gpu_device",
                       "flags_expanded", "log_expanded", "ttc_visible", "workflow_monitor", "sound")
        s1 = {key: value for key in legacy_keys if (value := self.cfg.get(key)) is not None}
        s2 = dict(s1)
        old_s2 = self.cfg.get("session2", {})
        port = old_s2.get("port", 8288) if isinstance(old_s2, dict) else 8288
        if isinstance(old_s2, dict) and old_s2.get("gpu_device") is not None:
            s2["gpu_device"] = old_s2["gpu_device"]
        state2 = dict(s1.get("state") or {})
        if "--port" not in state2:
            state2["--port"] = {"on": True, "val": str(port)}
        s2["state"] = state2
        s2["port_defaulted"] = True
        self.cfg["sessions"] = [s1, s2]

    # ---------- UI ----------
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        comfy = self.cfg.get("comfy_dir") or (str(Path.home() / "ComfyUI") if (Path.home() / "ComfyUI").is_dir() else "")
        venv = self.cfg.get("venv_dir") or next((str(Path(comfy) / d) for d in ("venv", ".venv") if comfy and (Path(comfy) / d).is_dir()), "")
        self.comfy_edit, self.venv_edit = QLineEdit(comfy), QLineEdit(venv)
        folder_row = QHBoxLayout()  # the only row common to both GPU panels
        folder_row.setSpacing(12)
        for label, edit in (("ComfyUI folder", self.comfy_edit), ("venv folder", self.venv_edit)):
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setMinimumWidth(100)
            btn = QPushButton("Browse…")
            btn.clicked.connect(lambda _=False, e=edit: self._browse(e))
            edit.editingFinished.connect(self.reload_flags)
            row.addWidget(lbl)
            row.addWidget(edit, 1)
            row.addWidget(btn)
            if folder_row.count():
                separator = QFrame()
                separator.setFixedWidth(2)
                separator.setStyleSheet("background-color: #697386;")
                separator.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
                folder_row.addSpacing(6)
                folder_row.addWidget(separator)
                folder_row.addSpacing(6)
            folder_row.addLayout(row, 1)
        v.addLayout(folder_row)

        self.session_tabs = QTabWidget()
        self.session_tabs.tabBar().setIconSize(QSize(48, 17))
        self.panels = [SessionPanel(self, 0), SessionPanel(self, 1)]
        for i, p in enumerate(self.panels):
            self.session_tabs.addTab(p, f"Session {i + 1}")
        v.addWidget(self.session_tabs, 1)

    def _browse(self, edit):
        d = QFileDialog.getExistingDirectory(self, "Select folder", edit.text() or str(Path.home()))
        if d:
            edit.setText(d)
            self.reload_flags()

    def python_path(self):
        return str(Path(self.venv_edit.text().strip()) / "bin" / "python")

    def other_panel(self, panel):
        return self.panels[1 - panel.idx]

    def _update_tab(self, panel):
        """The tab shows the selected GPU's name and product photo when known."""
        idx = panel.s.gpu_index if panel.s.gpu_index is not None else -1
        dev = next((d for d in self.gpus if int(d["index"]) == idx), None)
        name = str(dev["name"]) if dev else ""
        self.session_tabs.setTabText(panel.idx, name or f"Session {panel.idx + 1}")
        icon = QIcon()
        img = gpu_image(name) if name else None
        if img is not None:
            candidate = QIcon(str(img))
            if not candidate.isNull():
                icon = candidate
        self.session_tabs.tabBar().setTabIcon(panel.idx, icon)

    # ---------- flags / GPUs (discovered once, per-panel state) ----------
    def reload_flags(self):
        comfy, venv = self.comfy_edit.text().strip(), self.venv_edit.text().strip()
        py = Path(venv) / "bin" / "python"
        if comfy and venv and py.exists() and (Path(comfy) / "comfy" / "cli_args.py").exists():
            data, note = discover(str(py), comfy)
        else:
            data, note = fallback_data(), "set valid ComfyUI + venv folders to load flags from your install; using built-in list"
        for p in self.panels:
            p._log(f"[kicker] {note}\n")
            p.rebuild(data)
        self.refresh_gpus()

    def refresh_gpus(self):
        """Re-detect CUDA devices in ComfyUI's own Python environment, once for both panels."""
        py = self.python_path()
        comfy = self.comfy_edit.text().strip()
        if not Path(py).is_file():
            devices, note = [], "Set a valid ComfyUI venv to detect CUDA GPUs"
        else:
            extra_env = dict(self.panels[0].env_pairs()) if hasattr(self.panels[0], "env_edit") else None
            devices, note = detect_gpus(py, comfy, extra_env)
        self.gpus = devices
        available = {int(device["index"]) for device in devices}
        chosen = []
        for i, p in enumerate(self.panels):
            previous = p.cfg.get("gpu_device")
            try:
                previous = int(previous) if previous is not None else None
            except (TypeError, ValueError):
                previous = None
            if previous is None and i == 0:
                # First migration: honor an old --cuda-device value when it maps to a visible index.
                old = p.cfg.get("state", {}).get("--cuda-device", {})
                if old.get("on"):
                    try:
                        previous = int(str(old.get("val", "")).strip())
                    except (TypeError, ValueError):
                        previous = None
            selected = previous if previous in available else None
            if selected is None and devices:
                if i == 0:
                    selected = int(devices[0]["index"])
                else:
                    # The second tab defaults to a GPU different from the first tab's.
                    others = [int(d["index"]) for d in devices if int(d["index"]) not in chosen]
                    selected = others[0] if others else int(devices[0]["index"])
            chosen.append(selected)
            p.fill_gpus(devices, note, selected)
        for p in self.panels:
            p._log(f"[kicker] {note}\n")

    # ---------- health probe (both sessions) ----------
    def _probe_server(self):
        for p in self.panels:
            req = QNetworkRequest(QUrl(p.endpoint() + "/system_stats"))
            req.setTransferTimeout(1500)
            rep = self._health_nam.get(req)
            rep.finished.connect(lambda r=rep, p=p: p._health_reply(r))

    # ---------- browser (shared choice; each panel opens its own port) ----------
    def _browser_menu(self, panel):
        if not hasattr(self, "browsers"):
            self.browsers = find_browsers()
            saved = self.cfg.get("browser", "")
            self.browser = saved if saved in self.browsers else ""  # uninstalled -> system default
        menu = QMenu(panel)
        group = QActionGroup(menu)
        entries = [("", "System default"), *((k, e.get("Name", k)) for k, e in self.browsers.items())]
        for bid, name in entries:
            act = menu.addAction(name)
            act.setIcon(browser_icon(self.browsers.get(bid, {})))
            act.setCheckable(True)
            act.setChecked(bid == self.browser)
            group.addAction(act)
            act.triggered.connect(lambda _=False, b=bid: self._set_browser(b))
        menu.addSeparator()
        panel.app_mode_action = menu.addAction("Open as app")
        panel.app_mode_action.setCheckable(True)
        panel.app_mode_action.toggled.connect(self._set_app_mode)
        menu.addAction("Choose installed web-app shortcut…", self._choose_app_shortcut)
        menu.addAction("Forget web-app shortcut", self._forget_app_shortcut)
        menu.aboutToShow.connect(lambda: self._update_open_tip(panel))
        self._update_open_tip(panel)
        return menu

    def _set_browser(self, bid):
        self.browser = bid
        self.cfg["browser"] = bid
        for p in self.panels:
            self._update_open_tip(p)
        self.save_config()

    def _set_app_mode(self, enabled):
        self.cfg.setdefault("browser_app_modes", {})[self.browser] = enabled
        for p in self.panels:
            self._update_open_tip(p)
        self.save_config()

    def _choose_app_shortcut(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose this browser's ComfyUI web-app shortcut",
                    str(Path.home() / ".local/share/applications"), "Desktop shortcuts (*.desktop)")
        if not path:
            return
        entry = _desktop_entry(Path(path))
        if entry.get("Type") != "Application" or not entry.get("Exec"):
            QMessageBox.warning(self, "Web-app shortcut", "Choose an Application desktop shortcut with an Exec command.")
            return
        self.cfg.setdefault("browser_app_shortcuts", {})[self.browser] = path
        self._set_app_mode(True)

    def _forget_app_shortcut(self):
        self.cfg.setdefault("browser_app_shortcuts", {}).pop(self.browser, None)
        for p in self.panels:
            self._update_open_tip(p)
        self.save_config()

    def _update_open_tip(self, panel):
        selected = self.browser
        if not selected:
            try:
                result = subprocess.run(["xdg-settings", "get", "default-web-browser"],
                                        capture_output=True, text=True, timeout=2, check=False)
                selected = result.stdout.strip() if result.returncode == 0 else ""
            except (OSError, subprocess.TimeoutExpired):
                selected = ""
        entry = self.browsers.get(selected, {})
        self._resolved_browser = entry
        enabled = self.cfg.get("browser_app_modes", {}).get(self.browser, False)
        panel.app_mode_action.blockSignals(True)
        panel.app_mode_action.setChecked(enabled)
        panel.app_mode_action.blockSignals(False)
        panel.btn_open.setText("Open as app" if enabled else "Open in browser")
        name = entry.get("Name", "system default")
        mode = f"system default ({name})" if not self.browser and entry else name
        panel.btn_open.setIcon(browser_icon(entry))
        shortcut = self.cfg.get("browser_app_shortcuts", {}).get(self.browser)
        behavior = "Normal browser mode"
        if enabled:
            behavior = ("Installed web-app shortcut (uses its saved address)" if shortcut else
                        "Dedicated app window" if browser_family(entry) == "chromium" else
                        "App mode unavailable: opens a normal browser window")
        panel.btn_open.setToolTip(f"Opens with: {mode}\n{behavior}\nUse the arrow to choose browser and app mode.")

    def _open_url(self, panel, url):
        self._update_open_tip(panel)
        entry = self._resolved_browser
        app_mode = self.cfg.get("browser_app_modes", {}).get(self.browser, False)
        shortcut = self.cfg.get("browser_app_shortcuts", {}).get(self.browser) if app_mode else None
        try:
            if shortcut:
                saved = _desktop_entry(Path(shortcut))
                if not saved.get("Exec"):
                    raise ValueError("Web-app shortcut missing or invalid: " + shortcut)
                launch_entry(saved["Exec"], url, shortcut=True)
                return
            if entry.get("Exec"):
                family = browser_family(entry)
                if app_mode and family != "chromium":
                    panel._log("[kicker] App mode unavailable for this browser; opening a normal browser window.\n")
                launch_entry(entry["Exec"], url, app=app_mode, family=family)
                return
        except (OSError, ValueError) as exc:
            panel._log(f"[kicker] Browser/app launch failed ({exc}); opening system default.\n")
        QDesktopServices.openUrl(QUrl(url))

    # ---------- tray ----------
    def _refresh_tray(self):
        panels = getattr(self, "panels", [])
        if not panels:
            return
        runs = [p for p in panels if p.s.running()]
        onl = [p for p in panels if p._server_online]
        if onl:
            dot, label = "#2ecc71", f"{len(onl)} of {len(panels)} sessions online"
        elif runs:
            dot, label = "#f1c40f", f"{len(runs)} starting / restarting"
        else:
            dot, label = "#e74c3c", "All sessions stopped"
        self._set_taskbar_status(dot, label)

    def _set_taskbar_status(self, color, label):
        if getattr(self, "_taskbar_color", None) != color:
            icon = QIcon()
            for size in (16, 22, 24, 32, 48, 64, 128):
                pixmap = QPixmap(size, size)
                pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#171b24"))
                painter.drawEllipse(0, 0, size, size)
                inset = max(1, size // 10)
                painter.setBrush(QColor(color))
                painter.drawEllipse(inset, inset, size - 2 * inset, size - 2 * inset)
                painter.end()
                icon.addPixmap(pixmap)
            self._taskbar_icon = icon
            self._taskbar_color = color
            self.setWindowIcon(icon)
            QApplication.instance().setWindowIcon(icon)
        if not hasattr(self, "_status_tray"):
            self._status_tray = QSystemTrayIcon(self._taskbar_icon, self)
            self._status_tray.activated.connect(self._activate_status_tray)
            menu = QMenu(self)
            menu.addAction("Open Comfy Kicker", self._show_from_tray)
            self._status_tray.setContextMenu(menu)
            self._status_tray.setToolTip("Comfy Kicker — " + label)
            self._status_tray.show()
        if hasattr(self, "_status_tray"):
            self._status_tray.setIcon(self._taskbar_icon)
            self._status_tray.setToolTip("Comfy Kicker — " + label)

    def _activate_status_tray(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._show_from_tray()

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ---------- persistence ----------
    def save_config(self):
        for p in self.panels:
            p.push_cfg()
        self.cfg.update(comfy_dir=self.comfy_edit.text().strip(), venv_dir=self.venv_edit.text().strip(),
                        sessions=[p.cfg for p in self.panels])
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(self.cfg, indent=2))

    def closeEvent(self, e):
        running = [p for p in self.panels if p.s.running()]
        if running:
            if QMessageBox.question(self, "Comfy Kicker", "ComfyUI is still running. Stop it and quit?") != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            for p in running:
                p.s._restart = False
                p.s.proc.terminate()
                if not p.s.proc.waitForFinished(8000):
                    p.s.proc.kill()
                    p.s.proc.waitForFinished(2000)
        self.save_config()
        if hasattr(self, "_status_tray"):
            self._status_tray.hide()
        e.accept()
