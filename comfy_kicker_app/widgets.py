"""Reusable widgets: flag rows, collapsible sections, per-session log panes."""
from .common import *
from .launcher import *
from .monitor import FLAG_GUIDANCE

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
