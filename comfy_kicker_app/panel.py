"""One GPU session panel: a dedicated tab with its own GPU, flags, log, args and monitor."""
from .common import *
from .launcher import *
from .monitor import WorkflowPanel
from .session import ComfySession
from .widgets import CollapsibleSection, FastRow, FlagRow, LogPane


class SessionPanel(QWidget):
    """A whole launcher panel for one GPU/session. Only the ComfyUI folder / venv
    row (owned by the Kicker window) is shared between the two panels."""

    def __init__(self, kicker, idx):
        super().__init__()
        self.k = kicker
        self.idx = idx
        self.cfg = kicker.cfg["sessions"][idx]  # this session's config sub-dict
        self.rows, self.groups, self.other = {}, {}, []
        self._loading = False
        self.filter_mask, self.filter_classified_only = 0, False  # active bits; all boxes means classified-only mode
        self._server_online = False
        self._build_ui()
        self.s = ComfySession(self)  # this session's ComfyUI process: own GPU, port and log
        self.s.output.connect(self._log)
        self.s.stateChanged.connect(self._sync_buttons)
        self._sync_buttons()

    # ---------- UI ----------
    def _build_ui(self):
        outer = QVBoxLayout(self)

        gpu_row = QHBoxLayout()
        gpu_row.addWidget(QLabel("ComfyUI GPU:"))
        self.gpu_status = QLabel("Detecting CUDA GPUs…")
        gpu_row.addWidget(self.gpu_status)
        self.gpu_container = QWidget()
        self.gpu_layout = QHBoxLayout(self.gpu_container)
        self.gpu_layout.setContentsMargins(0, 0, 0, 0)
        self.gpu_layout.setSpacing(12)
        self.gpu_group = QButtonGroup(self)
        self.gpu_group.setExclusive(True)
        gpu_row.addWidget(self.gpu_container, 1)
        self.gpu_refresh = QPushButton("Refresh GPUs")
        self.gpu_refresh.setToolTip("Re-detect CUDA GPUs using the configured ComfyUI Python environment.")
        self.gpu_refresh.clicked.connect(self.k.refresh_gpus)
        gpu_row.addWidget(self.gpu_refresh)
        outer.addLayout(gpu_row)

        pr = QHBoxLayout()
        pr.addWidget(QLabel("Preset"))
        self.presets = QComboBox()
        self.presets.setMinimumWidth(200)
        pr.addWidget(self.presets)
        for text, fn in (("Load", self.load_preset), ("Save as…", self.save_preset), ("Delete", self.delete_preset),
                         ("Reload flags", self.k.reload_flags)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            pr.addWidget(b)
        pr.addStretch(1)

        sound_row = QHBoxLayout()
        self._build_sound_area(sound_row)
        sound_row.addStretch(1)
        self._fill_presets()

        hsplit = QSplitter(Qt.Orientation.Horizontal)
        hsplit.setHandleWidth(4)
        leftw = QWidget()
        v = QVBoxLayout(leftw)
        v.setContentsMargins(0, 0, 12, 0)
        v.addLayout(pr)
        v.addLayout(sound_row)

        split = QSplitter()
        split.setOrientation(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)
        self.tabs = QTabWidget()
        self.logpane = LogPane()
        flags_body = QWidget()
        flags_layout = QVBoxLayout(flags_body)
        flags_layout.setContentsMargins(0, 0, 0, 0)
        flag_filter_row = QHBoxLayout()
        self.show_selected_flags = QCheckBox("Show enabled only")
        self.show_selected_flags.setToolTip(
            "When enabled, show only flags whose checkboxes are currently enabled. "
            "Turn it off to see all available flags again."
        )
        self.show_selected_flags.toggled.connect(self._apply_flag_selection_filter)
        flag_filter_row.addWidget(self.show_selected_flags)
        flag_filter_row.addStretch(1)
        flags_layout.addLayout(flag_filter_row)
        flags_layout.addWidget(self.tabs, 1)
        self.flags_section = CollapsibleSection("Flags", flags_body, self.cfg.get("flags_expanded", True))
        split.addWidget(self.flags_section)
        logbox = QWidget()
        lv = QVBoxLayout(logbox)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.logpane, 1)
        fr = QHBoxLayout()
        lbl = QLabel("Show only:")
        lbl.setToolTip("Tick one or more categories to show matching lines only. Check All or untick all to show every line.")
        fr.addWidget(lbl)
        self.filter_all = QCheckBox("Check All")
        self.filter_all.setToolTip("Check or uncheck every log filter")
        fr.addWidget(self.filter_all)
        self.filter_boxes = []
        for bit, label, _rx in FILTER_RULES:
            cb = QCheckBox(label)
            cb.toggled.connect(lambda _=False: self._apply_filter())
            fr.addWidget(cb)
            self.filter_boxes.append((bit, cb))
        self.filter_all.toggled.connect(self._toggle_all_filters)
        fr.addStretch(1)
        lv.addLayout(fr)
        self.log_section = CollapsibleSection("Log", logbox, self.cfg.get("log_expanded", True))
        split.addWidget(self.log_section)
        split.setSizes([480, 440])
        v.addWidget(split, 1)

        self.prefix_edit = QLineEdit(self.cfg.get("prefix", ""))
        self.prefix_edit.setPlaceholderText("command before environment assignments, e.g. nice -n 10")
        self.extra, self.env_edit = QLineEdit(self.cfg.get("extra", "")), QLineEdit(self.cfg.get("env", ""))
        self.extra.setPlaceholderText("anything not listed, e.g. --verbose DEBUG")
        self.env_edit.setPlaceholderText("KEY=VALUE KEY2=VALUE2   (e.g. PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True)")
        self.env_edit.editingFinished.connect(self.k.refresh_gpus)
        for label, edit in (("Prefix arguments", self.prefix_edit), ("Extra arguments", self.extra), ("Environment", self.env_edit)):
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setMinimumWidth(100)
            row.addWidget(lbl)
            row.addWidget(edit, 1)
            edit.textChanged.connect(self.update_preview)
            flags_layout.addLayout(row)

        self.preview = QLineEdit()
        self.preview.setReadOnly(True)
        self.preview.setStyleSheet("QLineEdit { font-family: monospace; color: #800080; background-color: #000000; }")
        command_row = QHBoxLayout()
        command_row.addWidget(self.preview, 1)
        self.command_copy = QToolButton()
        self.command_copy.setIcon(QIcon.fromTheme("edit-copy"))
        if self.command_copy.icon().isNull():
            self.command_copy.setText("⧉")
        self.command_copy.setToolTip("Copy launch command")
        self.command_copy.setAccessibleName("Copy launch command")
        self.command_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.command_str()))
        command_row.addWidget(self.command_copy)
        v.insertLayout(2, command_row)  # between the sound row and the flags/log splitter
        self.sections_splitter = split
        self.sections_layout = v
        self._section_spacer = QWidget()
        self._section_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        v.addWidget(self._section_spacer, 1)
        self._section_spacer.hide()
        self.flags_section.toggle.toggled.connect(self._arrange_sections)
        self.log_section.toggle.toggled.connect(self._arrange_sections)
        self._arrange_sections()

        hsplit.addWidget(leftw)
        self.ttc = WorkflowPanel(self.endpoint, self.cfg.get("workflow_monitor"))  # polls this session's own port
        self.ttc.setTitle("")
        self.timing_shell = QFrame()
        self.timing_shell.setObjectName("timingPanel")
        timing_bg = self.palette().window().color().darker(140).name()
        self.timing_shell.setStyleSheet(f"QFrame#timingPanel {{ background: {timing_bg}; border: 1px solid #697386; border-radius: 4px; }}")
        timing_layout = QVBoxLayout(self.timing_shell)
        self.btn_ttc = QToolButton()
        self.btn_ttc.setAutoRaise(True)
        self.btn_ttc.setCheckable(True)
        self.btn_ttc.setChecked(self.cfg.get("ttc_visible", True))
        self.btn_ttc.setText("Workflow timing  " + ("▸" if self.btn_ttc.isChecked() else "▾"))
        self.btn_ttc.setToolTip("Expand or collapse workflow timing")
        self.btn_ttc.toggled.connect(lambda on: self.btn_ttc.setText("Workflow timing  " + ("▸" if on else "▾")))
        self.btn_ttc.toggled.connect(self._toggle_timing)
        timing_header = QHBoxLayout()
        timing_header.addStretch(1)
        timing_header.addWidget(self.btn_ttc)
        timing_layout.addLayout(timing_header)
        timing_layout.addWidget(self.ttc, 1)
        hsplit.addWidget(self.timing_shell)
        hsplit.setChildrenCollapsible(False)
        hsplit.setStretchFactor(0, 1)
        hsplit.setStretchFactor(1, 0)
        self.main_splitter = hsplit
        self._timing_sizes = [890, 500]
        hsplit.setSizes(self._timing_sizes)
        outer.addWidget(hsplit, 1)
        self.ttc.batchFinished.connect(self._play_batch_sound)
        self.ttc.set_background_poll(self.sound_enabled.isChecked())
        self.ttc.setVisible(self.btn_ttc.isChecked())
        self.timing_shell.setVisible(self.btn_ttc.isChecked())

        bar = QHBoxLayout()
        self.btn_launch, self.btn_stop = QPushButton("Launch"), QPushButton("Stop")
        self.btn_restart = QPushButton("Restart")
        self.btn_launch.setText("▶  Launch")
        self.btn_stop.setText("■  Stop")
        self.btn_restart.setText("⇻  Restart")
        designs = (
            (self.btn_launch, "#16845b", "#20a472", "#116747", "#16845b", "#ffffff"),
            (self.btn_stop, "#202632", "#382931", "#492c35", "#e87979", "#f29a9a"),
            (self.btn_restart, "#202632", "#25364d", "#294361", "#71a5ed", "#93bcf3"),
        )
        for button, bg, hover, pressed, border, fg in designs:
            button.setMinimumHeight(36)
            button.setMinimumWidth(112)
            button.setStyleSheet(f"""
                QPushButton {{ background-color: {bg}; color: {fg};
                    border: 1px solid {border}; border-radius: 6px;
                    padding: 6px 14px; font-weight: 600; }}
                QPushButton:hover {{ background-color: {hover}; }}
                QPushButton:pressed {{ background-color: {pressed}; }}
                QPushButton:focus {{ border: 2px solid {fg}; padding: 5px 13px; }}
                QPushButton:disabled {{ background-color: #252934; color: #727887;
                    border: 1px solid #424856; }}
            """)
        self.btn_open = QToolButton()  # split button: click = open this session, arrow = choose browser (shared)
        self.btn_open.setText("Open in browser")
        self.btn_open.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_open.setIconSize(QSize(24, 24))
        self.btn_open.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.btn_open.setMinimumHeight(self.btn_launch.sizeHint().height())
        self.btn_open.setMenu(self.k._browser_menu(self))
        self.btn_launch.clicked.connect(self.launch)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_restart.clicked.connect(self.restart)
        self.btn_open.clicked.connect(self.open_browser)
        self.status = QLabel("Stopped")
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.btn_log = QPushButton("Open Log")
        self.btn_log.clicked.connect(self.open_log)
        self.btn_log_end = QPushButton("↓ Auto-scroll")
        self.btn_log_end.setCheckable(True)
        self.btn_log_end.setChecked(True)
        self.btn_log_end.setToolTip(
            "Auto-scroll ON: keep the embedded log pinned to the newest output.\n"
            "Turn OFF to scroll/read older output freely; new lines will not move the view."
        )
        self.btn_log_end.setAccessibleName("Toggle automatic log scrolling")
        self.btn_log_end.toggled.connect(self.set_log_auto_scroll)
        self.btn_timer_widget = QPushButton("Open Timer Widget")
        self.btn_timer_widget.setToolTip("Open the floating Workflow ETA panel, or activate it if already open")
        self.btn_timer_widget.clicked.connect(self.open_timer_widget)
        sound_row.addWidget(self.btn_open)
        sound_row.addWidget(self.btn_log)
        sound_row.addWidget(self.btn_log_end)
        sound_row.addWidget(self.btn_timer_widget)
        for b in (self.btn_launch, self.btn_stop, self.btn_restart):
            bar.addWidget(b)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar.addWidget(self.status, 1)
        self.monitor_status = QLabel("Monitor: waiting")
        self.ttc.monitorStatus.connect(self.monitor_status.setText)
        bar.addWidget(self.monitor_status)
        v.addLayout(bar)

    def _toggle_timing(self, expanded):
        if not expanded:
            sizes = self.main_splitter.sizes()
            if len(sizes) == 2 and sizes[1] > 0:
                self._timing_sizes = sizes
        self.ttc.setVisible(expanded)
        self.timing_shell.setVisible(expanded)
        if expanded:
            self.main_splitter.setSizes(self._timing_sizes)

    def _arrange_sections(self, *_):
        flags_on = self.flags_section.toggle.isChecked()
        log_on = self.log_section.toggle.isChecked()
        both_closed = not flags_on and not log_on
        splitter = self.sections_splitter
        if both_closed:
            height = self.flags_section.maximumHeight() + self.log_section.maximumHeight() + splitter.handleWidth()
            splitter.setFixedHeight(height)
            self.sections_layout.setStretchFactor(splitter, 0)
            self._section_spacer.show()
        else:
            splitter.setMinimumHeight(0)
            splitter.setMaximumHeight(16777215)
            self.sections_layout.setStretchFactor(splitter, 1)
            self._section_spacer.hide()
            total = max(splitter.height(), 500)
            flags_height = self.flags_section.maximumHeight() if not flags_on else total
            log_height = self.log_section.maximumHeight() if not log_on else total
            splitter.setSizes([flags_height, log_height])

    def _build_sound_area(self, layout):
        sound = self.cfg.get("sound", {})
        self.sound_path = str(sound.get("file", ""))
        area = QFrame()
        area.setObjectName("playSoundArea")
        dark = area.palette().window().color().lightness() < 128
        border = "#7b8496" if dark else "#697386"
        area.setStyleSheet(f"QFrame#playSoundArea {{ border: 1px solid {border}; border-radius: 4px; }}")
        row = QHBoxLayout(area)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(6)
        self.sound_enabled = QCheckBox("Play sound")
        self.sound_enabled.setChecked(bool(sound.get("enabled", False)))
        self.sound_file_btn = QPushButton("None")
        self.sound_file_btn.setMinimumWidth(100)
        self.sound_file_btn.setMaximumWidth(220)
        self.sound_volume = QDoubleSpinBox()
        self.sound_volume.setRange(0.0, 1.0)
        self.sound_volume.setDecimals(2)
        self.sound_volume.setSingleStep(0.05)
        try:
            volume = float(sound.get("volume", 0.5))
            if not 0.0 <= volume <= 1.0:
                volume = 0.5
        except (TypeError, ValueError):
            volume = 0.5
        self.sound_volume.setValue(volume)
        self.sound_volume.setToolTip("Playback volume relative to system volume: 0 is silent, 1 is maximum")
        self.sound_test_btn = QPushButton("Test")
        self.sound_test_btn.setToolTip("Play the selected sound at the chosen volume")
        self.sound_test_btn.clicked.connect(lambda: self._play_sound())
        for widget in (self.sound_enabled, self.sound_file_btn,
                       QLabel("Volume"), self.sound_volume, self.sound_test_btn):
            row.addWidget(widget)
        layout.addWidget(area)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(volume)
        self.sound_player = QMediaPlayer(self)
        self.sound_player.setAudioOutput(self.audio_output)
        self.sound_player.errorOccurred.connect(lambda *_: self._log(
            f"[kicker] Sound playback failed: {self.sound_player.errorString()}\n"))
        self.sound_file_btn.clicked.connect(self._choose_sound_file)
        self.sound_volume.valueChanged.connect(self.audio_output.setVolume)
        self.sound_enabled.toggled.connect(self._sound_toggled)
        self._update_sound_filename()

    def _update_sound_filename(self):
        name = Path(self.sound_path).name if self.sound_path else "None"
        self.sound_file_btn.setText(name)
        self.sound_file_btn.setToolTip(self.sound_path or "Select a sound file")
        self.sound_test_btn.setEnabled(bool(self.sound_path))

    def _choose_sound_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose sound file", self.sound_path or str(Path.home()),
                    "All files (*);;Sound files (*.wav *.mp3 *.ogg *.oga *.flac *.m4a *.aac *.opus)",
                    selectedFilter="All files (*)", options=QFileDialog.Option.DontUseNativeDialog)
        if path:
            self.sound_path = path
            self._update_sound_filename()
            self.k.save_config()

    def _sound_toggled(self, enabled):
        if not enabled:
            self.sound_player.stop()
        if hasattr(self, "ttc"):
            self.ttc.set_background_poll(enabled)

    def _play_batch_sound(self):
        if self.sound_enabled.isChecked():
            self._play_sound()

    def _play_sound(self):
        if not self.sound_path or self.sound_volume.value() <= 0:
            return
        if not Path(self.sound_path).is_file():
            self._log(f"[kicker] Sound file not found: {self.sound_path}\n")
            return
        self.sound_player.stop()
        self.audio_output.setVolume(self.sound_volume.value())
        self.sound_player.setSource(QUrl.fromLocalFile(str(Path(self.sound_path).resolve())))
        self.sound_player.play()

    @staticmethod
    def _scroll(w):
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(w)
        return sa

    # ---------- flags ----------
    def rebuild(self, data):
        self._last_flag_data = data
        state = getattr(self, "_rebuild_current_state", None) or (self.collect_state() if self.rows else self.cfg.get("state", {}))
        self._rebuild_current_state = None
        self.rows, self.groups = {}, {}
        for s in data["flags"]:
            if s["flag"] in HIDDEN:
                continue
            r = FastRow(s, data["fast_options"]) if s["flag"] == "--fast" and data["fast_options"] else FlagRow(s)
            r.changed.connect(self._on_changed)
            self.rows[s["flag"]] = r
            if r.group is not None:
                self.groups.setdefault(r.group, []).append(r)
        while self.tabs.count():
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            w.deleteLater()

        defaults = [f for _title, group_flags in FAVORITES for f in group_flags]
        saved_favorites = self.cfg.get("favorite_flags")
        favorite_flags = set(saved_favorites if isinstance(saved_favorites, list) else defaults)
        # Keep a stable default category ordering, then group user-added favorites separately.
        favw, used = QWidget(), set()
        fav = QVBoxLayout(favw)
        for title, flags in FAVORITES:
            rows = [self.rows[f] for f in flags if f in self.rows and f in favorite_flags]
            if rows:
                box = QGroupBox(title)
                bl = QVBoxLayout(box)
                for r in rows:
                    bl.addWidget(r)
                    used.add(r.flag)
                fav.addWidget(box)
        extra_favs = [self.rows[f] for f in sorted(favorite_flags) if f in self.rows and f not in used]
        if extra_favs:
            box = QGroupBox("Other favorites")
            bl = QVBoxLayout(box)
            for r in extra_favs:
                bl.addWidget(r)
                used.add(r.flag)
            fav.addWidget(box)
        fav.addStretch(1)
        self._favorite_flags = favorite_flags
        # A row is created once and appears on exactly one tab; its star can move it between tabs.
        for r in self.rows.values():
            r.favoriteRequested.connect(self._set_favorite)
            r.favorite_btn.setText("★" if r.flag in favorite_flags else "☆")
            r.favorite_btn.setToolTip("Remove from Favorites" if r.flag in favorite_flags else "Add to Favorites")
        self.tabs.addTab(self._scroll(favw), "Favorites")

        page, lw = QWidget(), QWidget()
        pl, ll = QVBoxLayout(page), QVBoxLayout(lw)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search flags…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.other = [self.rows[f] for f in sorted(self.rows) if f not in used]
        for r in self.other:
            ll.addWidget(r)
        ll.addStretch(1)
        pl.addWidget(self.search)
        pl.addWidget(self._scroll(lw))
        self.tabs.addTab(page, f"All other flags ({len(self.other)})")
        self.apply_state(state)
        self._apply_flag_selection_filter()
        if self.idx == 1 and not self.cfg.get("port_defaulted") and "--port" in self.rows:
            # The second session needs its own port; default it to 8288 once.
            self.rows["--port"].from_state({"on": True, "val": "8288"})
            self.cfg["port_defaulted"] = True
            self.update_preview()

    def _set_favorite(self, flag, make_favorite):
        favorites = set(getattr(self, "_favorite_flags", set()))
        if make_favorite:
            favorites.add(flag)
        else:
            favorites.discard(flag)
        self.cfg["favorite_flags"] = sorted(favorites)
        state = self.collect_state()
        self._rebuild_current_state = state
        self.rebuild(self._last_flag_data)
        self.k.save_config()

    def _filter(self, text):
        t = text.lower().strip()
        for r in self.other:
            r.setVisible(not t or t in r.flag.lower() or t in r.spec["help"].lower())

    def _on_changed(self, row):
        if self._loading:
            return
        if row.enabled and row.group is not None:
            for o in self.groups[row.group]:
                if o is not row and o.enabled:
                    o.set_enabled(False)
        self.update_preview()
        self._apply_flag_selection_filter()

    def _apply_flag_selection_filter(self, *_):
        """Hide unchecked flag rows when the selected-only view is active."""
        if not hasattr(self, "rows"):
            return
        selected_only = (hasattr(self, "show_selected_flags")
                         and self.show_selected_flags.isChecked())
        for row in self.rows.values():
            row.setVisible(not selected_only or row.enabled)

    def collect_state(self):
        out = {}
        for f, r in self.rows.items():
            st = r.to_state()
            if st["on"] or st["val"]:
                out[f] = st
        return out

    def apply_state(self, state):
        self._loading = True
        for r in self.rows.values():
            r.set_enabled(False)
        for f, st in state.items():
            if f in self.rows:
                self.rows[f].from_state(st)
        self._loading = False
        self.update_preview()

    # ---------- presets ----------
    def _fill_presets(self):
        self.presets.clear()
        self.presets.addItems(sorted(self.cfg.get("presets", {})))

    def save_preset(self):
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:", text=self.presets.currentText())
        if ok and name.strip():
            self.cfg.setdefault("presets", {})[name.strip()] = dict(
                state=self.collect_state(), prefix=self.prefix_edit.text(), extra=self.extra.text(), env=self.env_edit.text())
            self.k.save_config()
            self._fill_presets()
            self.presets.setCurrentText(name.strip())

    def load_preset(self):
        p = self.cfg.get("presets", {}).get(self.presets.currentText())
        if p:
            self.prefix_edit.setText(p.get("prefix", ""))
            self.extra.setText(p.get("extra", ""))
            self.env_edit.setText(p.get("env", ""))
            self.apply_state(p.get("state", {}))

    def delete_preset(self):
        if self.cfg.get("presets", {}).pop(self.presets.currentText(), None) is not None:
            self.k.save_config()
            self._fill_presets()

    # ---------- GPU selection ----------
    def fill_gpus(self, devices, note, selected):
        """Fill this panel's GPU radio picker from the detected devices."""
        self.gpu_status.setText(note if not devices else note + ":")
        self.gpu_status.setStyleSheet("" if devices else "color: palette(placeholder-text);")
        if selected is None:
            self.s.gpu_index, self.s.gpu_token = None, None
        self._fill_gpu_picker(self.gpu_layout, self.gpu_group, devices, selected, self._gpu_selected)
        if selected is not None:
            self.cfg["gpu_device"] = selected
        self.update_preview()
        self.k._update_tab(self)

    def _fill_gpu_picker(self, layout, group, devices, selected, on_select):
        """Rebuild one GPU radio picker from the detected devices."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                if isinstance(widget, QRadioButton):
                    group.removeButton(widget)
                widget.deleteLater()
        for device in devices:
            index = int(device["index"])
            memory_gb = device["memory"] / (1024 ** 3)
            label = f"CUDA {index} · {device['name']} · {memory_gb:.0f} GB"
            radio = QRadioButton(label)
            radio.setToolTip(
                f"CUDA logical device {index}\n{device['name']}\n"
                f"{memory_gb:.1f} GiB total VRAM\n"
                "Comfy Kicker will expose only this GPU to ComfyUI on the next launch."
            )
            group.addButton(radio, index)
            layout.addWidget(radio)
            img = gpu_image(device["name"])
            if img is not None:
                icon = QIcon(str(img))
                if not icon.isNull():
                    radio.setIcon(icon)
                    radio.setIconSize(QSize(64, 22))  # wide product photo beside the name
            radio.toggled.connect(lambda checked, idx=index: on_select(idx, checked))
            if index == selected:
                radio.setChecked(True)
        layout.addStretch(1)

    def _gpu_selected(self, index, checked):
        if not checked:
            return
        device = next((item for item in self.k.gpus if int(item["index"]) == index), None)
        if device is None:
            return
        self.s.gpu_index = index
        self.s.gpu_token = device["visibility_token"]
        self.cfg["gpu_device"] = index
        self.update_preview()
        self.k._update_tab(self)

    # ---------- command ----------
    def flag_args(self):
        out = []
        for r in self.rows.values():
            out += r.args()
        return out + _split(self.extra.text())

    def env_pairs(self):
        return [tuple(t.split("=", 1)) for t in _split(self.env_edit.text()) if "=" in t]

    def effective_env_pairs(self):
        pairs = self.env_pairs()
        if self.s.gpu_token is not None:
            pairs = [(key, value) for key, value in pairs if key != "CUDA_VISIBLE_DEVICES"]
            pairs.append(("CUDA_VISIBLE_DEVICES", str(self.s.gpu_token)))
        return pairs

    def flag_port(self):
        """This session's --port value from its own flag rows."""
        args = self.flag_args()
        for i, arg in enumerate(args):
            if arg == "--port" and i + 1 < len(args):
                return args[i + 1]
            if arg.startswith("--port="):
                return arg.split("=", 1)[1]
        return "8188"

    def endpoint(self, override=None):
        """This session's ComfyUI URL (its own port on 127.0.0.1, tls flag respected)."""
        if getattr(self, "s", None) is not None and self.s.running() and getattr(self, "_monitor_base", None):
            base = QUrl(self._monitor_base)
        else:
            args = self.flag_args()
            port, tls = "8188", False
            for i, arg in enumerate(args):
                if arg == "--port" and i + 1 < len(args):
                    port = args[i + 1]
                elif arg.startswith("--port="):
                    port = arg.split("=", 1)[1]
                if arg == "--tls-keyfile" or arg.startswith("--tls-keyfile="):
                    tls = True
            base = QUrl(f"{'https' if tls else 'http'}://127.0.0.1:{port}")
        if override is not None:
            base.setPort(override)
        return base.toString().rstrip("/")

    def launch_command(self):
        prefix = _split(self.prefix_edit.text())
        command = [self.k.python_path(), str(Path(self.k.comfy_edit.text().strip()) / "main.py"), *self.flag_args()]
        if prefix:
            # env is a real executable here, so assignments follow the wrapper.
            pairs = [f"{key}={value}" for key, value in self.effective_env_pairs()]
            return [*prefix, "env", *pairs, *command]
        return command

    def command_str(self):
        prefix = _split(self.prefix_edit.text())
        if prefix:
            return shlex.join(self.launch_command())
        env = "".join(f"{key}={shlex.quote(value)} " for key, value in self.effective_env_pairs())
        return f"{env}{shlex.join(self.launch_command())}"

    def update_preview(self):
        if self._loading:
            return
        if hasattr(self, "preview"):
            self.preview.setText(self.command_str())
            self.preview.setCursorPosition(0)

    # ---------- process ----------
    def launch(self):
        if self.s.running():
            return
        comfy, venv = self.k.comfy_edit.text().strip(), self.k.venv_edit.text().strip()
        if not (Path(comfy) / "main.py").exists() or not Path(self.k.python_path()).exists():
            QMessageBox.warning(self, "Comfy Kicker", "Check the ComfyUI folder (needs main.py) and the venv folder (needs bin/python).")
            return
        self.k.save_config()
        self.s.launch()

    def stop(self):
        self.s.stop()
        self._sync_buttons()

    def restart(self):
        self.s.restart()
        self._sync_buttons()

    def _health_reply(self, reply):
        online = reply.error() == QNetworkReply.NetworkError.NoError
        if online:
            try:
                data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                online = isinstance(data, dict) and "system" in data
            except (ValueError, UnicodeError):
                online = False
        reply.deleteLater()
        self._server_online = online
        self._sync_buttons()

    def _sync_buttons(self):
        if not hasattr(self, "btn_launch"):
            return
        run, online = self.s.running(), self._server_online
        self.btn_launch.setEnabled(not run and not online)
        self.btn_stop.setEnabled(run)
        self.btn_restart.setEnabled(run or not online)
        if online:
            dot, label = "#2ecc71", "Running" if run else "Running (external process)"
        elif run:
            dot, label = "#f1c40f", "Starting / restarting"
        else:
            dot, label = "#e74c3c", "Stopped / unavailable"
        pid = f" (pid {self.s.proc.processId()})" if run else ""
        self.status.setText(f'<span style="color:{dot}; font-size:15px;">●</span> {label}{pid}')
        self.k._refresh_tray()

    # ---------- log ----------
    def _log(self, text):
        """Append to this session's log (see LogPane.log)."""
        if hasattr(self, "logpane"):
            self.logpane.log(text)

    def set_log_auto_scroll(self, enabled):
        """Pin the embedded log to the newest output while auto-scroll is enabled."""
        self.btn_log_end.setText("↓ Auto-scroll ON" if enabled else "↓ Auto-scroll OFF")
        self.btn_log_end.setToolTip(
            "Auto-scroll ON: keep the embedded log pinned to the newest output.\n"
            "Click to turn OFF and freely scroll older output."
            if enabled else
            "Auto-scroll OFF: new log lines will not move the view.\n"
            "Scroll freely, then click to turn auto-scroll ON and jump to the newest output."
        )
        self.logpane.auto_scroll = enabled
        if enabled:
            self.scroll_log_to_end()

    def scroll_log_to_end(self):
        if hasattr(self, "logpane"):
            self.logpane.scroll_to_end()

    def open_log(self):
        log = Path(self.k.comfy_edit.text().strip()) / "user" / "comfyui.log"
        if log.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(log)))
        else:
            QMessageBox.information(self, "Comfy Kicker", f"Log file not found:\n{log}")

    def open_browser(self):
        self.k._open_url(self, self.endpoint())

    def open_timer_widget(self):
        data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        desktop = data_home / "applications" / "workflow-eta-panel.desktop"
        script = data_home / "workflow-eta-panel" / "workflow_eta_panel.py"
        # Desktop launching preserves the interpreter chosen by the panel installer.
        gio = shutil.which("gio")
        kio = shutil.which("kioclient6") or shutil.which("kioclient")
        if desktop.is_file() and gio:
            command = [gio, "launch", str(desktop)]
        elif desktop.is_file() and kio:
            command = [kio, "exec", str(desktop)]
        elif script.is_file():
            command = [sys.executable, str(script)]
        else:
            QMessageBox.information(self, "Open Timer Widget",
                "Workflow ETA Panel is not installed.\n\n"
                "Extract the Workflow ETA Panel package and run:\npython3 install.py\n\n"
                f"Expected panel location:\n{script}")
            return
        try:
            subprocess.Popen(command, start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            self._log("[kicker] Requested Workflow ETA Panel; an existing panel will be activated.\n")
        except OSError as exc:
            self._log(f"[kicker] Timer widget launch failed: {exc}\n")
            QMessageBox.warning(self, "Open Timer Widget", f"Could not open Workflow ETA Panel:\n{exc}")

    def _toggle_all_filters(self, checked):
        for _, checkbox in self.filter_boxes:
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)
        self._apply_filter()

    def _apply_filter(self):
        self.filter_all.blockSignals(True)
        self.filter_all.setChecked(all(cb.isChecked() for _, cb in self.filter_boxes))
        self.filter_all.blockSignals(False)
        selected = [bit for bit, cb in self.filter_boxes if cb.isChecked()]
        # No selection means no filter. Selecting every category is a distinct
        # classified-only mode; a partial selection matches the selected bits.
        all_selected = bool(self.filter_boxes) and len(selected) == len(self.filter_boxes)
        self.filter_classified_only = all_selected
        self.filter_mask = sum(selected) if selected and not all_selected else 0
        self.logpane.set_filter(self.filter_mask, self.filter_classified_only)

    # ---------- persistence ----------
    def push_cfg(self):
        """Copy the current UI state into this session's config sub-dict."""
        self.cfg.update(state=self.collect_state(), prefix=self.prefix_edit.text(), extra=self.extra.text(), env=self.env_edit.text(),
                        favorite_flags=sorted(getattr(self, "_favorite_flags", set(self.cfg.get("favorite_flags", [])))),
                        ttc_visible=self.btn_ttc.isChecked(), workflow_monitor=self.ttc.settings(),
                        flags_expanded=self.flags_section.toggle.isChecked(), log_expanded=self.log_section.toggle.isChecked(),
                        gpu_device=(self.s.gpu_index if self.s.gpu_index is not None else self.cfg.get("gpu_device")),
                        sound={"enabled": self.sound_enabled.isChecked(), "file": self.sound_path,
                               "volume": self.sound_volume.value()})


__all__ = [name for name in globals() if not name.startswith("__")]
