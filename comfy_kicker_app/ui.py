"""Comfy Kicker widgets and main application window."""
from .common import *
from .launcher import *
from .monitor import FLAG_GUIDANCE, TtcPanel, WorkflowPanel
from .session import ComfySession

def detailed_flag_tooltip(spec):
    flag = spec.get("flag", "")
    help_text = " ".join(str(spec.get("help", "No help text supplied by this ComfyUI build.")).replace("%%", "%").split())
    detail = FLAG_GUIDANCE.get(flag)
    if not detail:
        # Safe general guidance for flags added by future ComfyUI releases.
        kind = "boolean switch" if spec.get("kind") == "bool" else "value-taking option"
        detail = (f"This option is discovered from the installed ComfyUI command-line parser ({kind}). "
                  "Its exact behavior is defined by the ComfyUI version and any custom patches in use. "
                  "Before enabling it for a production workflow, check the upstream help/source for this release, "
                  "change one option at a time, and compare startup logs, output correctness, speed, VRAM and RAM. "
                  "If it names a backend, precision mode, device, or memory policy, compatibility can depend on "
                  "the GPU architecture, driver, PyTorch/CUDA build, installed extensions, and model family. "
                  "Do not assume it is compatible with another option in the same category unless ComfyUI documents that.")
    return f"{flag}\n\nWhat it does / when to use it:\n{detail}\n\nComfyUI help for this installed version:\n{help_text or 'No help text supplied.'}\n\nVersion note: flags and their implementation can change after ComfyUI updates. If behavior differs from this description, the installed version's parser/help and startup log take precedence."

class FlagRow(QWidget):
    """One flag: checkbox, optional value widget, and a help line."""
    changed = Signal(object)
    favoriteRequested = Signal(str, bool)

    def __init__(self, s, is_favorite=False):
        super().__init__()
        self.spec, self.flag, self.group = s, s["flag"], s["group"]
        self.val = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(0)
        top = QHBoxLayout()
        self.cb = QCheckBox(self.flag)
        self.cb.setMinimumWidth(260)
        self.cb.setToolTip(detailed_flag_tooltip(s))
        top.addWidget(self.cb)
        self.favorite_btn = QToolButton()
        self.favorite_btn.setText("★" if is_favorite else "☆")
        self.favorite_btn.setToolTip("Remove from Favorites" if is_favorite else "Add to Favorites")
        self.favorite_btn.setAccessibleName(self.favorite_btn.toolTip())
        self.favorite_btn.setFixedWidth(30)
        self.favorite_btn.clicked.connect(lambda: self.favoriteRequested.emit(self.flag, self.favorite_btn.text() != "★"))
        top.addWidget(self.favorite_btn)
        if s["kind"] == "value":
            if s["choices"]:
                self.val = QComboBox()
                self.val.addItems(s["choices"])
                if str(s["default"]) in s["choices"]:
                    self.val.setCurrentText(str(s["default"]))
                self.val.currentTextChanged.connect(lambda _: self.changed.emit(self))
            else:
                self.val = QLineEdit()
                self.val.setPlaceholderText(self._placeholder())
                self.val.textChanged.connect(lambda _: self.changed.emit(self))
            self.val.setToolTip(detailed_flag_tooltip(s))
            self.val.setEnabled(False)
            top.addWidget(self.val, 1)
        else:
            top.addStretch(1)
        lay.addLayout(top)
        desc = QLabel(" ".join(s["help"].replace("%%", "%").split()))
        desc.setWordWrap(True)
        desc.setContentsMargins(24, 0, 0, 0)
        desc.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
        lay.addWidget(desc)
        self.cb.toggled.connect(self._toggled)

    def _placeholder(self):
        s = self.spec
        if s["nargs"] == "?":
            return f"blank = {s['const']}" if s["const"] is not None else "(optional value)"
        if s["nargs"] == "*":
            return "(optional values)"
        if s["append"]:
            return "entry; entry; ..."
        if s["default"] is not None:
            return f"default: {s['default']}"
        return s["metavar"] or "value"

    @property
    def enabled(self):
        return self.cb.isChecked()

    def set_enabled(self, on):
        self.cb.blockSignals(True)
        self.cb.setChecked(on)
        self.cb.blockSignals(False)
        if self.val is not None:
            self.val.setEnabled(on)

    def _toggled(self, on):
        if self.val is not None:
            self.val.setEnabled(on)
            if on and isinstance(self.val, QLineEdit) and self.spec["nargs"] in (None, "+"):
                self.val.setFocus()
        self.changed.emit(self)

    def _text(self):
        if self.val is None:
            return ""
        return self.val.currentText() if isinstance(self.val, QComboBox) else self.val.text().strip()

    def args(self):
        if not self.enabled:
            return []
        s, n = self.spec, self.spec["nargs"]
        if s["kind"] == "bool":
            return [self.flag]
        t = self._text()
        entries = [e.strip() for e in t.split(";")] if s["append"] and t else [t]
        out = []
        for e in entries:
            if n in ("?", "*"):
                out += [self.flag] + (_split(e) if e else [])
            elif not e:
                continue
            elif n == "+":
                out += [self.flag] + _split(e)
            else:
                out += [self.flag, e]
        self.cb.setStyleSheet("" if out else "color: #e67e22;")  # orange = value still needed
        return out

    def to_state(self):
        return {"on": self.enabled, "val": self._text()}

    def from_state(self, st):
        v = st.get("val", "")
        if isinstance(self.val, QLineEdit):
            self.val.setText(v)
        elif isinstance(self.val, QComboBox) and v:
            self.val.setCurrentText(v)
        self.set_enabled(bool(st.get("on")))


class FastRow(FlagRow):
    """--fast with per-feature sub-options (all or none ticked = bare --fast)."""

    def __init__(self, s, options):
        super().__init__(dict(s, kind="bool", nargs=None))
        box = QHBoxLayout()
        box.setContentsMargins(24, 0, 0, 0)
        self.subs = {}
        for o in options:
            c = QCheckBox(o)
            c.setChecked(True)
            c.setEnabled(False)
            c.toggled.connect(lambda _: self.changed.emit(self))
            box.addWidget(c)
            self.subs[o] = c
        box.addStretch(1)
        self.layout().addLayout(box)

    def _picked(self):
        return [o for o, c in self.subs.items() if c.isChecked()]

    def _sync(self, on):
        for c in self.subs.values():
            c.setEnabled(on)

    def set_enabled(self, on):
        super().set_enabled(on)
        self._sync(on)

    def _toggled(self, on):
        self._sync(on)
        super()._toggled(on)

    def args(self):
        if not self.enabled:
            return []
        p = self._picked()
        return [self.flag] if not p or len(p) == len(self.subs) else [self.flag] + p

    def to_state(self):
        return {"on": self.enabled, "val": " ".join(self._picked())}

    def from_state(self, st):
        want = set(st.get("val", "").split()) or set(self.subs)
        for o, c in self.subs.items():
            c.setChecked(o in want)
        self.set_enabled(bool(st.get("on")))



class CollapsibleSection(QFrame):
    """A compact arrow at the top-left beside the section body."""
    def __init__(self, title, body, expanded=True):
        super().__init__()
        self.body = body
        self.title = title
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setAutoRaise(True)
        self.toggle.setCheckable(True)
        self.toggle.setAccessibleName(f"Toggle {title}")
        self.toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(body, 1)
        self.toggle.toggled.connect(self._expand)
        self.toggle.setChecked(expanded)
        self._expand(expanded)

    def _expand(self, expanded):
        self.body.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow if expanded else Qt.ArrowType.DownArrow)
        self.toggle.setToolTip(f"{'Collapse' if expanded else 'Expand'} {self.title.lower()}")
        header_height = max(24, self.toggle.sizeHint().height()) + 8
        self.setMinimumHeight(header_height)
        self.setMaximumHeight(16777215 if expanded else header_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                          QSizePolicy.Policy.Expanding if expanded else QSizePolicy.Policy.Fixed)
        self.updateGeometry()


class LogPane(QWidget):
    """One session's log view: ANSI-stripped colouring, per-line filter bits, auto-scroll."""

    def __init__(self):
        super().__init__()
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)
        self.view.setStyleSheet("font-family: monospace; font-size: 11px;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
        self._fmts = self._make_formats()
        self._cat, self._line, self._bol, self._in_tb = None, "", True, False  # log colouring state
        self._cr, self._esc = False, ""  # carriage-return overwrite flag, partial ANSI escape code
        self._gen_times = []  # generation run times for the summary line
        self.filter_mask, self.filter_classified_only = 0, False  # active bits; all boxes means classified-only mode
        self.auto_scroll = True

    def log(self, text):
        """Append to the log; a bare \\r (tqdm progress) overwrites the current line."""
        text = self._esc + text  # an escape code may arrive split across two reads
        m = re.search(r"\x1b(\[[0-9;?]*[ -/]*)?$", text)
        self._esc, text = (text[m.start():], text[:m.start()]) if m else ("", text)
        text = ANSI_RE.sub("", text)
        extra = []  # summary lines to add once this chunk is fully written
        sb = self.view.verticalScrollBar()
        follow = self.auto_scroll  # explicit toggle controls whether new output moves the view
        cur = QTextCursor(self.view.document())  # private cursor: leaves the user's selection alone
        cur.movePosition(QTextCursor.MoveOperation.End)
        for tok in re.split(r"(\r\n|\r|\n)", text):
            if tok == "\r":
                self._cr = True
            elif tok in ("\n", "\r\n"):
                done = GEN_TIME_RE.search(self._line)
                cur.insertText("\n")
                self._cr, self._bol, self._cat, self._line = False, True, None, ""
                self._place(cur.block(), 0)  # fresh empty line: hidden while a filter is active
                if done:
                    extra.append(self._gen_summary(float(done.group(1))))
            elif tok:
                if self._cr:
                    cur.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
                    cur.removeSelectedText()
                    self._cr, self._bol, self._cat, self._line = False, True, None, ""
                earlier = bool(self._line)
                self._line += tok
                cat = self._classify(tok)
                changed = bool(cat) and (self._cat is None or LOG_RANK[cat] < LOG_RANK[self._cat])
                if changed:
                    self._cat = cat
                # A new/unknown colour category must never interrupt log ingestion.
                cur.insertText(tok, self._fmts.get(self._cat, self._fmts[None]))
                if changed and earlier:  # category only became clear mid-line: recolour the whole line
                    cur.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
                    cur.setCharFormat(self._fmts[self._cat])
                    cur.movePosition(QTextCursor.MoveOperation.End)
                self._bol = False
                self._place(cur.block(), sum(bit for bit, _, rx in FILTER_RULES if rx.search(self._line) or (bit == 8 and self._cat in ("error", "tb"))))
        if follow:
            sb.setValue(sb.maximum())
        for line in extra:
            self.log(line)

    def _make_formats(self):
        """Per-category text formats; pastel colours on dark themes, deeper ones on light."""
        dark = self.view.palette().base().color().lightness() < 128
        spec = {  # category: (dark-theme colour, light-theme colour, bold)
            "error": ("#ff6b6b", "#c0392b", True), "tb": ("#d98a8a", "#a5524a", False),
            "warn": ("#f5c04a", "#b9770e", False), "success": ("#6bcf7f", "#1e8449", False),
            "info": ("#6cb6ff", "#1f6fb2", False), "progress": ("#5fb3b3", "#148f8f", False),
            "rate": ("#5fb3b3", "#148f8f", False),
            "workflow_eta": ("#c792ea", "#8e44ad", True),
            "debug": ("#8a8f98", "#7f8c8d", False), "kicker": ("#c792ea", "#8e44ad", True),
        }
        fmts = {None: QTextCharFormat()}
        for cat, (d, l, bold) in spec.items():
            f = QTextCharFormat()
            f.setForeground(QColor(d if dark else l))
            if bold:
                f.setFontWeight(QFont.Weight.Bold)
            fmts[cat] = f
        return fmts

    def _classify(self, frag):
        """Colour category for a log fragment (None = default text)."""
        if self._bol:
            if frag.startswith("Traceback"):
                self._in_tb = True
            elif self._in_tb:
                if frag[:1] in (" ", "\t"):
                    return "tb"
                self._in_tb = False
                return "error"  # the closing 'SomeError: message' line
        for cat, rx in LOG_RULES:
            if rx.search(self._line):
                return cat
        return None

    def _place(self, blk, mask):
        """Tag a log line with its filter bits and show/hide it per the active filter."""
        blk.setUserState(mask)
        vis = (mask != 0) if self.filter_classified_only else (not self.filter_mask or bool(mask & self.filter_mask))
        if blk.isVisible() != vis:
            blk.setVisible(vis)
            self.view.document().markContentsDirty(blk.position(), blk.length())

    def set_filter(self, mask, classified_only):
        """Apply the shared filter selection to every line of this log."""
        self.filter_mask, self.filter_classified_only = mask, classified_only
        doc = self.view.document()
        blk = doc.begin()
        while blk.isValid():
            m = max(blk.userState(), 0)
            vis = (m != 0) if classified_only else (not mask or bool(m & mask))
            if blk.isVisible() != vis:
                blk.setVisible(vis)
            blk = blk.next()
        doc.markContentsDirty(0, doc.characterCount())
        if self.auto_scroll:
            sb = self.view.verticalScrollBar()
            QTimer.singleShot(0, lambda: sb.setValue(sb.maximum()))  # after relayout, respect auto-scroll

    def scroll_to_end(self):
        self.view.moveCursor(QTextCursor.MoveOperation.End)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def _gen_summary(self, secs):
        self._gen_times.append(secs)
        n, avg = len(self._gen_times), sum(self._gen_times) / len(self._gen_times)
        return f"[kicker] Generation time: {_fmt_secs(secs)}  (run {n} · avg {_fmt_secs(avg)})\n"


class Kicker(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Comfy Kicker")
        self.resize(1400, 1010)  # ~1010 for the launcher + ~380 for the Magik TtC column
        self.cfg = load_config()
        self.rows, self.groups, self.other = {}, {}, []
        self._loading = self._restart = False
        self.filter_mask, self.filter_classified_only = 0, False  # active bits; all boxes means classified-only mode
        self._server_online = self._server_online2 = False
        self._health_busy = False
        self.gpus = []
        self.selected_gpu_token = None
        self.selected_gpu_index = None
        self._ready, self._tail = False, ""  # server-up flag and a short output tail to spot the ready marker
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(lambda e: self._log(f"[kicker] process error: {e}\n"))
        self.proc.errorOccurred.connect(lambda _e: self._sync_buttons())  # FailedToStart emits no finished()
        self._kill_timer = QTimer(self)  # escalates a stuck Stop to SIGKILL; cancelled when the process exits
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._force_kill)
        self.s2 = ComfySession(self)  # second ComfyUI session: own port, GPU, process and log tab
        self.s2.output.connect(self._log2)
        self.s2.stateChanged.connect(self._sync_buttons2)
        self._build_ui()
        self.reload_flags()
        self._health_nam = QNetworkAccessManager(self)
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(1000)
        self._health_timer.timeout.connect(self._probe_server)
        self._health_timer.start()
        self._probe_server()

    # ---------- UI ----------
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        comfy = self.cfg.get("comfy_dir") or (str(Path.home() / "ComfyUI") if (Path.home() / "ComfyUI").is_dir() else "")
        venv = self.cfg.get("venv_dir") or next((str(Path(comfy) / d) for d in ("venv", ".venv") if comfy and (Path(comfy) / d).is_dir()), "")
        self.comfy_edit, self.venv_edit = QLineEdit(comfy), QLineEdit(venv)
        folder_row = QHBoxLayout()
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
        self.gpu_refresh.clicked.connect(self.refresh_gpus)
        gpu_row.addWidget(self.gpu_refresh)
        v.addLayout(gpu_row)

        pr = QHBoxLayout()
        pr.addWidget(QLabel("Preset"))
        self.presets = QComboBox()
        self.presets.setMinimumWidth(200)
        pr.addWidget(self.presets)
        for text, fn in (("Load", self.load_preset), ("Save as…", self.save_preset), ("Delete", self.delete_preset),
                         ("Reload flags", self.reload_flags)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            pr.addWidget(b)
        pr.addStretch(1)
        v.addLayout(pr)
        sound_row = QHBoxLayout()
        self._build_sound_area(sound_row)
        sound_row.addStretch(1)
        v.addLayout(sound_row)
        self._fill_presets()

        # Middle section = left pane (tabs, log, extra args, env, command) | right pane (Magik TtC panel).
        # `v` points at the left pane's layout until the splitter is assembled below; `main` is the outer layout.
        main = v
        main.removeItem(pr)
        main.removeItem(sound_row)
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
        self.log_tabs = QTabWidget()
        self.log1, self.log2 = LogPane(), LogPane()
        self.log_tabs.addTab(self.log1, "Session 1")
        self.log_tabs.addTab(self.log2, "Session 2")
        self.log = self.log1.view  # alias: the session-1 log view
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
        lv.addWidget(self.log_tabs, 1)
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
        self.env_edit.editingFinished.connect(self.refresh_gpus)
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
        v.insertLayout(2, command_row)
        self.s2_section = self._build_session2_section()
        v.insertWidget(3, self.s2_section)
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
        self.ttc = WorkflowPanel(self.monitor_endpoint, self.cfg.get("workflow_monitor"))  # native Magik TtC panel: no browser engine involved
        self.ttc.setTitle("")
        self.ttc2 = WorkflowPanel(lambda override=None: self.monitor_endpoint(self.s2.port if override is None else override),
                                   self.cfg.get("workflow_monitor2"))
        self.ttc2.setTitle("")
        self.monitor_tabs = QTabWidget()
        self.monitor_tabs.addTab(self.ttc, "Session 1")
        self.monitor_tabs.addTab(self.ttc2, "Session 2")
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
        main.addLayout(timing_header)
        timing_layout.addWidget(self.monitor_tabs, 1)
        hsplit.addWidget(self.timing_shell)
        hsplit.setChildrenCollapsible(False)
        hsplit.setStretchFactor(0, 1)
        hsplit.setStretchFactor(1, 0)
        self.main_splitter = hsplit
        self._timing_sizes = [890, 500]
        hsplit.setSizes(self._timing_sizes)
        main.addWidget(hsplit, 1)
        for panel in (self.ttc, self.ttc2):
            panel.batchFinished.connect(self._play_batch_sound)
            panel.set_background_poll(self.sound_enabled.isChecked())
        self.monitor_tabs.setVisible(self.btn_ttc.isChecked())
        self.timing_shell.setVisible(self.btn_ttc.isChecked())
        # Keep the action bar in the left column; timing spans the full remaining height.

        bar = QHBoxLayout()
        self.btn_launch, self.btn_stop = QPushButton("Launch"), QPushButton("Stop")
        self.btn_restart = QPushButton("Restart")
        self.btn_launch.setText("▶  Launch")
        self.btn_stop.setText("■  Stop")
        self.btn_restart.setText("↻  Restart")
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
        self.btn_open = QToolButton()  # split button: click = open, arrow = choose browser
        self.btn_open.setText("Open in browser")
        self.btn_open.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_open.setIconSize(QSize(24, 24))
        self.btn_open.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.btn_open.setMinimumHeight(self.btn_launch.sizeHint().height())
        self.btn_open.setMenu(self._browser_menu())
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
        self.monitor_status2 = QLabel("S2 monitor: waiting")
        self.ttc2.monitorStatus.connect(self.monitor_status2.setText)
        bar.addWidget(self.monitor_status2)
        v.addLayout(bar)
        self._sync_buttons()

    def _toggle_timing(self, expanded):
        if not expanded:
            sizes = self.main_splitter.sizes()
            if len(sizes) == 2 and sizes[1] > 0:
                self._timing_sizes = sizes
        self.monitor_tabs.setVisible(expanded)
        self.timing_shell.setVisible(expanded)
        if expanded:
            self.main_splitter.setSizes(self._timing_sizes)

    # ---------- second session ----------
    def _build_session2_section(self):
        """Collapsible section for the second ComfyUI session: own port, GPU, buttons."""
        s2cfg = self.cfg.get("session2", {}) if isinstance(self.cfg.get("session2"), dict) else {}
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port"))
        self.s2_port = QSpinBox()
        self.s2_port.setRange(1025, 65534)
        self.s2_port.setValue(_clamp(s2cfg.get("port"), 1025, 65534, 8288))
        self.s2_port.setToolTip("Listen port for the second ComfyUI session.\n"
                                "Session 1 uses the --port flag above; keep the two ports different.")
        self.s2_port.valueChanged.connect(self._s2_port_changed)
        port_row.addWidget(self.s2_port)
        hint = QLabel("session 1 uses the --port flag above")
        hint.setStyleSheet("color: palette(placeholder-text);")
        port_row.addWidget(hint)
        port_row.addStretch(1)
        bl.addLayout(port_row)
        gpu_row = QHBoxLayout()
        gpu_row.addWidget(QLabel("GPU:"))
        self.s2_gpu_status = QLabel("Detecting CUDA GPUs…")
        gpu_row.addWidget(self.s2_gpu_status)
        self.s2_gpu_container = QWidget()
        self.s2_gpu_layout = QHBoxLayout(self.s2_gpu_container)
        self.s2_gpu_layout.setContentsMargins(0, 0, 0, 0)
        self.s2_gpu_layout.setSpacing(12)
        self.s2_gpu_group = QButtonGroup(self)
        self.s2_gpu_group.setExclusive(True)
        gpu_row.addWidget(self.s2_gpu_container, 1)
        bl.addLayout(gpu_row)
        btn_row = QHBoxLayout()
        self.btn_launch2, self.btn_stop2, self.btn_restart2 = QPushButton("▶  Launch 2"), QPushButton("■  Stop 2"), QPushButton("⇻  Restart 2")
        self.btn_open2 = QPushButton("Open in browser")
        self.btn_open2.setToolTip("Open this session's ComfyUI (its own port) with the selected browser,\n"
                                  "in a new window / app window like session 1")
        designs = (
            (self.btn_launch2, "#16845b", "#20a472", "#116747", "#16845b", "#ffffff"),
            (self.btn_stop2, "#202632", "#382931", "#492c35", "#e87979", "#f29a9a"),
            (self.btn_restart2, "#202632", "#25364d", "#294361", "#71a5ed", "#93bcf3"),
        )
        for button, bg, hover, pressed, border, fg in designs:
            button.setMinimumHeight(28)
            button.setMinimumWidth(96)
            button.setStyleSheet(f"""
                QPushButton {{ background-color: {bg}; color: {fg};
                    border: 1px solid {border}; border-radius: 6px;
                    padding: 4px 10px; font-weight: 600; }}
                QPushButton:hover {{ background-color: {hover}; }}
                QPushButton:pressed {{ background-color: {pressed}; }}
                QPushButton:focus {{ border: 2px solid {fg}; padding: 3px 9px; }}
                QPushButton:disabled {{ background-color: #252934; color: #727887;
                    border: 1px solid #424856; }}
            """)
        self.btn_open2.setMinimumHeight(28)
        self.btn_launch2.clicked.connect(self.launch2)
        self.btn_stop2.clicked.connect(self.stop2)
        self.btn_restart2.clicked.connect(self.restart2)
        self.btn_open2.clicked.connect(self.open_browser2)
        for b in (self.btn_launch2, self.btn_stop2, self.btn_restart2, self.btn_open2):
            btn_row.addWidget(b)
        self.s2_status = QLabel("Stopped")
        self.s2_status.setTextFormat(Qt.TextFormat.RichText)
        btn_row.addWidget(self.s2_status, 1)
        bl.addLayout(btn_row)
        self.preview2 = QLineEdit()
        self.preview2.setReadOnly(True)
        self.preview2.setStyleSheet("QLineEdit { font-family: monospace; color: #800080; background-color: #000000; }")
        bl.addWidget(self.preview2)
        self._s2_port_changed(self.s2_port.value())
        return CollapsibleSection("Second session (other GPU)", body, bool(s2cfg.get("expanded", False)))

    def _s2_port_changed(self, value):
        self.s2.port = int(value)
        self.update_preview()

    def launch2(self):
        self.save_config()
        self.s2.launch()
        self._sync_buttons2()

    def stop2(self):
        self.s2.stop()
        self._sync_buttons2()

    def restart2(self):
        self.s2.restart()
        self._sync_buttons2()

    def _sync_buttons2(self):
        if not hasattr(self, "btn_launch2"):
            return
        run, online = self.s2.running(), self._server_online2
        self.btn_launch2.setEnabled(not run and not online)
        self.btn_stop2.setEnabled(run)
        self.btn_restart2.setEnabled(run or not online)
        if online:
            dot, label = "#2ecc71", "Running" if run else "Running (external process)"
        elif run:
            dot, label = "#f1c40f", "Starting / restarting"
        else:
            dot, label = "#e74c3c", "Stopped / unavailable"
        pid = f" (pid {self.s2.proc.processId()})" if run else ""
        self.s2_status.setText(f'<span style="color:{dot}; font-size:15px;">●</span> {label}{pid}')

    def flag_port(self):
        """The --port value from the shared flag rows (session 1's port)."""
        args = self.flag_args()
        for i, arg in enumerate(args):
            if arg == "--port" and i + 1 < len(args):
                return args[i + 1]
            if arg.startswith("--port="):
                return arg.split("=", 1)[1]
        return "8188"

    def _gpu2_selected(self, index, checked):
        if not checked:
            return
        device = next((item for item in self.gpus if int(item["index"]) == index), None)
        if device is None:
            return
        self.s2.gpu_index = index
        self.s2.gpu_token = device["visibility_token"]
        self.update_preview()

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
            self.save_config()

    def _sound_toggled(self, enabled):
        if not enabled:
            self.sound_player.stop()
        if hasattr(self, "ttc"):
            self.ttc.set_background_poll(enabled)
            self.ttc2.set_background_poll(enabled)

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

    def _browse(self, edit):
        d = QFileDialog.getExistingDirectory(self, "Select folder", edit.text() or str(Path.home()))
        if d:
            edit.setText(d)
            self.reload_flags()

    # ---------- flags ----------
    def reload_flags(self):
        comfy, venv = self.comfy_edit.text().strip(), self.venv_edit.text().strip()
        py = Path(venv) / "bin" / "python"
        if comfy and venv and py.exists() and (Path(comfy) / "comfy" / "cli_args.py").exists():
            data, note = discover(str(py), comfy)
        else:
            data, note = fallback_data(), "set valid ComfyUI + venv folders to load flags from your install; using built-in list"
        self._log(f"[kicker] {note}\n")
        self._rebuild(data)
        if hasattr(self, "gpu_group"):
            self.refresh_gpus()

    def _rebuild(self, data):
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

    def _set_favorite(self, flag, make_favorite):
        favorites = set(getattr(self, "_favorite_flags", set()))
        if make_favorite:
            favorites.add(flag)
        else:
            favorites.discard(flag)
        self.cfg["favorite_flags"] = sorted(favorites)
        state = self.collect_state()
        self._rebuild_current_state = state
        self._rebuild(self._last_flag_data)
        self.save_config()

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
            self.save_config()
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
            self.save_config()
            self._fill_presets()

    # ---------- GPU selection ----------
    def refresh_gpus(self):
        """Re-detect CUDA devices in ComfyUI's own Python environment."""
        if not hasattr(self, "gpu_group"):
            return
        py = self.python_path()
        comfy = self.comfy_edit.text().strip()
        if not Path(py).is_file():
            devices, note = [], "Set a valid ComfyUI venv to detect CUDA GPUs"
        else:
            devices, note = detect_gpus(py, comfy, dict(self.env_pairs()) if hasattr(self, "env_edit") else None)

        # Keep the previous choice if still present. On first migration, honor an
        # old --cuda-device value when it maps to a currently visible index.
        previous = self.cfg.get("gpu_device")
        try:
            previous = int(previous) if previous is not None else None
        except (TypeError, ValueError):
            previous = None
        if previous is None:
            old = self.cfg.get("state", {}).get("--cuda-device", {})
            if old.get("on"):
                try:
                    previous = int(str(old.get("val", "")).strip())
                except (TypeError, ValueError):
                    previous = None
        available = {int(device["index"]) for device in devices}
        selected = previous if previous in available else (int(devices[0]["index"]) if devices else None)

        self.gpus = devices
        self.selected_gpu_index = selected
        self.selected_gpu_token = None
        self.gpu_status.setText(note if not devices else note + ":")
        self.gpu_status.setStyleSheet("" if devices else "color: palette(placeholder-text);")
        self._fill_gpu_picker(self.gpu_layout, self.gpu_group, devices, selected, self._gpu_selected)

        if hasattr(self, "s2_gpu_group"):
            s2cfg = self.cfg.get("session2", {})
            previous2 = s2cfg.get("gpu_device") if isinstance(s2cfg, dict) else None
            try:
                previous2 = int(previous2) if previous2 is not None else None
            except (TypeError, ValueError):
                previous2 = None
            available = {int(device["index"]) for device in devices}
            selected2 = previous2 if previous2 in available else None
            if selected2 is None and devices:
                # Default to a GPU different from session 1's when possible.
                others = [int(device["index"]) for device in devices if int(device["index"]) != selected]
                selected2 = others[0] if others else int(devices[0]["index"])
            self.s2.gpu_index, self.s2.gpu_token = selected2, None
            self.s2_gpu_status.setText(note if not devices else note + ":")
            self.s2_gpu_status.setStyleSheet("" if devices else "color: palette(placeholder-text);")
            self._fill_gpu_picker(self.s2_gpu_layout, self.s2_gpu_group, devices, selected2, self._gpu2_selected)

        if selected is not None:
            self.cfg["gpu_device"] = selected
        self.update_preview()
        self._log(f"[kicker] {note}\n")

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
        device = next((item for item in self.gpus if int(item["index"]) == index), None)
        if device is None:
            return
        self.selected_gpu_index = index
        self.selected_gpu_token = device["visibility_token"]
        self.cfg["gpu_device"] = index
        self.update_preview()

    # ---------- command ----------
    def python_path(self):
        return str(Path(self.venv_edit.text().strip()) / "bin" / "python")

    def flag_args(self):
        out = []
        for r in self.rows.values():
            out += r.args()
        return out + _split(self.extra.text())

    def env_pairs(self):
        return [tuple(t.split("=", 1)) for t in _split(self.env_edit.text()) if "=" in t]

    def effective_env_pairs(self):
        pairs = self.env_pairs()
        if self.selected_gpu_token is not None:
            pairs = [(key, value) for key, value in pairs if key != "CUDA_VISIBLE_DEVICES"]
            pairs.append(("CUDA_VISIBLE_DEVICES", str(self.selected_gpu_token)))
        return pairs

    def launch_command(self):
        prefix = _split(self.prefix_edit.text())
        command = [self.python_path(), str(Path(self.comfy_edit.text().strip()) / "main.py"), *self.flag_args()]
        if prefix:
            # env is a real executable here, so assignments follow the wrapper.
            pairs = [f"{k}={value}" for k, value in self.effective_env_pairs()]
            return [*prefix, "env", *pairs, *command]
        return command

    def command_str(self):
        prefix = _split(self.prefix_edit.text())
        if prefix:
            return shlex.join(self.launch_command())
        env = "".join(f"{k}={shlex.quote(val)} " for k, val in self.effective_env_pairs())
        return f"{env}{shlex.join(self.launch_command())}"

    def update_preview(self):
        if self._loading:
            return
        if hasattr(self, "preview"):
            self.preview.setText(self.command_str())
            self.preview.setCursorPosition(0)
        if hasattr(self, "preview2") and hasattr(self, "s2"):
            self.preview2.setText(self.s2.command_str())
            self.preview2.setCursorPosition(0)

    # ---------- process ----------
    def _running(self):
        return self.proc.state() != QProcess.ProcessState.NotRunning

    def _probe_server(self):
        if getattr(self, "s2", None) is not None:
            req2 = QNetworkRequest(QUrl(self.s2.endpoint() + "/system_stats"))
            req2.setTransferTimeout(1500)
            rep2 = self._health_nam.get(req2)
            rep2.finished.connect(lambda: self._health_reply2(rep2))
        if self._health_busy:
            return
        self._health_busy = True
        base = getattr(self, "_monitor_base", None) or self.monitor_endpoint()
        request = QNetworkRequest(QUrl(base + "/system_stats"))
        request.setTransferTimeout(1500)
        reply = self._health_nam.get(request)
        reply.finished.connect(lambda: self._health_reply(reply, base))

    def _health_reply(self, reply, base):
        online = reply.error() == QNetworkReply.NetworkError.NoError
        if online:
            try:
                data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                online = isinstance(data, dict) and "system" in data
            except (ValueError, UnicodeError):
                online = False
        reply.deleteLater()
        self._health_busy = False
        current_base = getattr(self, "_monitor_base", None) or self.monitor_endpoint()
        if base != current_base:
            return
        self._server_online = self._ready = online
        self._sync_buttons()

    def _health_reply2(self, reply):
        online = reply.error() == QNetworkReply.NetworkError.NoError
        if online:
            try:
                data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                online = isinstance(data, dict) and "system" in data
            except (ValueError, UnicodeError):
                online = False
        reply.deleteLater()
        self._server_online2 = online
        self._sync_buttons2()

    def _sync_buttons(self):
        run, online = self._running(), self._server_online
        self.btn_launch.setEnabled(not run and not online)
        self.btn_stop.setEnabled(run)
        self.btn_restart.setEnabled(run or not online)
        if online:
            dot, label = "#2ecc71", "Running" if run else "Running (external process)"
        elif run:
            dot, label = "#f1c40f", "Starting / restarting"
        else:
            dot, label = "#e74c3c", "Stopped / unavailable"
        pid = f" (pid {self.proc.processId()})" if run else ""
        self.status.setText(f'<span style="color:{dot}; font-size:15px;">●</span> {label}{pid}')
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

    def launch(self):
        if self._running():
            return
        comfy, venv = self.comfy_edit.text().strip(), self.venv_edit.text().strip()
        if not (Path(comfy) / "main.py").exists() or not Path(self.python_path()).exists():
            QMessageBox.warning(self, "Comfy Kicker", "Check the ComfyUI folder (needs main.py) and the venv folder (needs bin/python).")
            return
        self.save_config()
        env = QProcessEnvironment.systemEnvironment()
        env.insert("VIRTUAL_ENV", venv)
        env.insert("PATH", f"{venv}/bin:" + env.value("PATH"))
        env.insert("PYTHONUNBUFFERED", "1")
        env.remove("PYTHONHOME")
        if not _split(self.prefix_edit.text()):
            for k, val in self.env_pairs():
                env.insert(k, val)
        if self.selected_gpu_token is not None:
            env.insert("CUDA_VISIBLE_DEVICES", str(self.selected_gpu_token))
        self.proc.setProcessEnvironment(env)
        self.proc.setWorkingDirectory(comfy)
        self.log1._gen_times.clear()
        self._ready, self._tail = False, ""
        self._log(f"[kicker] {self.command_str()}\n")
        self._monitor_base = self.monitor_endpoint()
        command = self.launch_command()
        self.proc.start(command[0], command[1:])
        self._sync_buttons()

    KILL_AFTER_MS = 8000

    def stop(self):
        if self._running():
            self.proc.terminate()
            self._kill_timer.start(self.KILL_AFTER_MS)

    def _force_kill(self):
        if self._running():
            self._log(f"[kicker] ComfyUI did not stop within {self.KILL_AFTER_MS // 1000}s; killing it\n")
            self.proc.kill()

    def restart(self):
        if self._running():
            self._restart = True
            self.stop()
        else:
            self.launch()

    def _finished(self, code, _status):
        self._kill_timer.stop()  # a late kill must never hit a freshly relaunched process
        self._log(bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace"))  # flush trailing output
        self._log(f"\n[kicker] ComfyUI exited (code {code})\n")
        self._sync_buttons()
        if self._restart:
            self._restart = False
            self.launch()

    def _browser_menu(self):
        self.browsers = find_browsers()
        saved = self.cfg.get("browser", "")
        self.browser = saved if saved in self.browsers else ""  # uninstalled -> system default
        menu = QMenu(self)
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
        self.app_mode_action = menu.addAction("Open as app")
        self.app_mode_action.setCheckable(True)
        self.app_mode_action.toggled.connect(self._set_app_mode)
        menu.addAction("Choose installed web-app shortcut…", self._choose_app_shortcut)
        menu.addAction("Forget web-app shortcut", self._forget_app_shortcut)
        menu.aboutToShow.connect(self._update_open_tip)
        self._update_open_tip()
        return menu

    def _set_browser(self, bid):
        self.browser = bid
        self.cfg["browser"] = bid
        self._update_open_tip()
        self.save_config()

    def _set_app_mode(self, enabled):
        self.cfg.setdefault("browser_app_modes", {})[self.browser] = enabled
        self._update_open_tip()
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
        self._update_open_tip()
        self.save_config()

    def _update_open_tip(self):
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
        self.app_mode_action.blockSignals(True)
        self.app_mode_action.setChecked(enabled)
        self.app_mode_action.blockSignals(False)
        self.btn_open.setText("Open as app" if enabled else "Open in browser")
        name = entry.get("Name", "system default")
        mode = f"system default ({name})" if not self.browser and entry else name
        self.btn_open.setIcon(browser_icon(entry))
        shortcut = self.cfg.get("browser_app_shortcuts", {}).get(self.browser)
        behavior = "Normal browser mode"
        if enabled:
            behavior = ("Installed web-app shortcut (uses its saved address)" if shortcut else
                        "Dedicated app window" if browser_family(entry) == "chromium" else
                        "App mode unavailable: opens a normal browser window")
        self.btn_open.setToolTip(f"Opens with: {mode}\n{behavior}\nUse the arrow to choose browser and app mode.")

    def monitor_endpoint(self, override=None):
        if self._running() and hasattr(self, "_monitor_base"):
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

    def open_browser(self):
        self._open_url(self.monitor_endpoint())

    def open_browser2(self):
        self._open_url(self.s2.endpoint())

    def _open_url(self, url):
        self._update_open_tip()
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
                    self._log("[kicker] App mode unavailable for this browser; opening a normal browser window.\n")
                launch_entry(entry["Exec"], url, app=app_mode, family=family)
                return
        except (OSError, ValueError) as exc:
            self._log(f"[kicker] Browser/app launch failed ({exc}); opening system default.\n")
        QDesktopServices.openUrl(QUrl(url))

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
        for pane in (self.log1, self.log2):
            pane.auto_scroll = enabled
        if enabled:
            self.scroll_log_to_end()

    def scroll_log_to_end(self):
        pane = self.log_tabs.currentWidget() if hasattr(self, "log_tabs") else None
        if pane is not None:
            pane.scroll_to_end()

    def open_log(self):
        log = Path(self.comfy_edit.text().strip()) / "user" / "comfyui.log"
        if log.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(log)))
        else:
            QMessageBox.information(self, "Comfy Kicker", f"Log file not found:\n{log}")

    def _read(self):
        text = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        if not self._ready:
            self._tail = (self._tail + text)[-200:]
            self._ready = bool(READY_RE.search(self._tail))
        self._log(text)
        self._sync_buttons()

    def _log(self, text):
        """Append to session 1's log (see LogPane.log)."""
        self.log1.log(text)

    def _log2(self, text):
        """Append to session 2's log."""
        if hasattr(self, "log2"):
            self.log2.log(text)

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
        for pane in (self.log1, self.log2):
            pane.set_filter(self.filter_mask, self.filter_classified_only)

    # ---------- persistence ----------
    def save_config(self):
        self.cfg.update(comfy_dir=self.comfy_edit.text().strip(), venv_dir=self.venv_edit.text().strip(),
                        state=self.collect_state(), prefix=self.prefix_edit.text(), extra=self.extra.text(), env=self.env_edit.text(),
                        favorite_flags=sorted(getattr(self, "_favorite_flags", set(self.cfg.get("favorite_flags", [])))),
                        ttc_visible=self.btn_ttc.isChecked(), workflow_monitor=self.ttc.settings(),
                        flags_expanded=self.flags_section.toggle.isChecked(), log_expanded=self.log_section.toggle.isChecked(),
                        gpu_device=(self.selected_gpu_index if self.selected_gpu_index is not None
                                    else self.cfg.get("gpu_device")),
                        sound={"enabled": self.sound_enabled.isChecked(), "file": self.sound_path,
                               "volume": self.sound_volume.value()},
                        session2={"port": self.s2_port.value(), "gpu_device": self.s2.gpu_index,
                                  "expanded": self.s2_section.toggle.isChecked()},
                        workflow_monitor2=self.ttc2.settings())
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(self.cfg, indent=2))

    def closeEvent(self, e):
        if self._running() or self.s2.running():
            if QMessageBox.question(self, "Comfy Kicker", "ComfyUI is still running. Stop it and quit?") != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self._restart = False
            self.s2._restart = False
            if self._running():
                self.proc.terminate()
                if not self.proc.waitForFinished(8000):
                    self.proc.kill()
                    self.proc.waitForFinished(2000)
            if self.s2.running():
                self.s2.proc.terminate()
                if not self.s2.proc.waitForFinished(8000):
                    self.s2.proc.kill()
                    self.s2.proc.waitForFinished(2000)
        self.save_config()
        if hasattr(self, "_status_tray"):
            self._status_tray.hide()
        e.accept()



