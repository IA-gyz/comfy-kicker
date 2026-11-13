"""ComfyUI queue and workflow monitoring panels."""
from .common import *
from .launcher import *

class TtcPanel(QGroupBox):
    """Native Magik TtC panel. Polls the Magik TtC external API (127.0.0.1:8189-8198) and shows generation timing:
    a live timer, min/max, mean + ETA for the last N and for all generations, and a newest-first list of cards."""
    PORTS = range(8189, 8199)
    MAX_ENTRIES = 9999

    def __init__(self, saved=None):
        super().__init__("Magik TtC")
        s = saved or {}
        self.port = _clamp(s.get("port"), 1025, 65534, None)  # only a manually chosen (locked) port is saved
        self.port_locked = self.port is not None
        self.poll_s, self.cap = _clamp(s.get("poll"), 1, 60, 3), _clamp(s.get("cap"), 1, 999, 10)
        self.discard = bool(s.get("discard", False))
        self.entries, self.deleted, self.queue = [], set(), 0
        self.gen_start, self.last_queue, self.last_cards = None, 0, 0
        self._busy = self._scanning = False
        self._epoch, self._sig, self._error = 0, None, None
        dark = QApplication.palette().base().color().lightness() < 128
        self.col = {"time": "#6bcf7f" if dark else "#1e8449", "file": "#6cb6ff" if dark else "#1f6fb2",
                    "dur": "#f5c04a" if dark else "#b9770e", "mean": "#5fb3b3" if dark else "#148f8f",
                    "bad": "#ff6b6b" if dark else "#c0392b", "manual": "#a5b4fc" if dark else "#5b6bc0"}
        self.col["ok"], self.col["warn"] = self.col["time"], self.col["dur"]
        self.nam = QNetworkAccessManager(self)
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll)
        self.gen_timer = QTimer(self)
        self.gen_timer.setInterval(100)
        self.gen_timer.timeout.connect(self._tick)
        self.setMinimumWidth(300)
        self._build()
        self._render()

    # ---------- UI ----------
    def _build(self):
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.timer_lbl = QLabel()
        f = self.timer_lbl.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 3)
        self.timer_lbl.setFont(f)
        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setToolTip("Clear the generation entries (also asks the Magik TtC API to clear it)")
        self.btn_clear.clicked.connect(self.clear)
        top.addWidget(self.timer_lbl)
        top.addStretch(1)
        top.addWidget(self.btn_clear)
        v.addLayout(top)
        self._show_timer(None)

        row = QHBoxLayout()
        self.minmax, self.counts = QLabel(), QLabel()
        row.addWidget(self.minmax)
        row.addStretch(1)
        row.addWidget(self.counts)
        v.addLayout(row)

        grid = QGridLayout()
        self.stat = {}
        for r, key in enumerate(("recent", "all")):
            self.stat[key] = labels = (QLabel(), QLabel(), QLabel())
            labels[0].setMinimumWidth(70)
            labels[0].setStyleSheet("font-weight: bold; color: palette(placeholder-text);")
            for c, lb in enumerate(labels):
                grid.addWidget(lb, r, c)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        v.addLayout(grid)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Time", "File", "Duration", ""])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        hd = self.tree.header()
        hd.setStretchLastSection(False)
        for col, mode in enumerate((QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Stretch,
                                    QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.ResizeToContents)):
            hd.setSectionResizeMode(col, mode)
        self.tree.itemClicked.connect(self._clicked)
        self.msg = QLabel()
        self.msg.setWordWrap(True)
        self.msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg.setStyleSheet("color: palette(placeholder-text);")
        self.stack = QStackedWidget()
        self.stack.addWidget(self.tree)
        self.stack.addWidget(self.msg)
        v.addWidget(self.stack, 1)

        self.btn_discard = QPushButton("Discard 1st gen")
        self.btn_discard.setCheckable(True)
        self.btn_discard.setChecked(self.discard)
        self.btn_discard.setToolTip("Ignore the oldest generation in the stats (it usually includes model loading)")
        self.btn_discard.toggled.connect(self._set_discard)
        v.addWidget(self.btn_discard)

        srow = QHBoxLayout()
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.btn_scan = QPushButton("Rescan")
        self.btn_scan.setToolTip("Auto-detect the Magik TtC API port")
        self.btn_scan.clicked.connect(self._rescan_clicked)
        self.btn_cfg = QToolButton()
        self.btn_cfg.setText("⚙")
        self.btn_cfg.setCheckable(True)
        self.btn_cfg.setToolTip("Port, poll interval and 'last N' size")
        srow.addWidget(self.status, 1)
        srow.addWidget(self.btn_scan)
        srow.addWidget(self.btn_cfg)
        v.addLayout(srow)

        self.cfg_row = QWidget()
        cr = QHBoxLayout(self.cfg_row)
        cr.setContentsMargins(0, 0, 0, 0)
        self.port_spin, self.poll_spin, self.cap_spin = QSpinBox(), QSpinBox(), QSpinBox()
        for text, tip, sp, lo, hi, val in (
                ("API port", "Magik TtC API port; editing it locks the port (no auto-detect)", self.port_spin, 1025, 65534,
                 self.port or self.PORTS[0]),
                ("Poll (s)", "Seconds between updates", self.poll_spin, 1, 60, self.poll_s),
                ("Last N", "How many of the most recent generations the LAST N stats use", self.cap_spin, 1, 999, self.cap)):
            sp.setRange(lo, hi)
            sp.setValue(val)
            sp.setToolTip(tip)
            sp.setKeyboardTracking(False)
            cr.addWidget(QLabel(text))
            cr.addWidget(sp)
        self.cfg_row.hide()
        self.btn_cfg.toggled.connect(self.cfg_row.setVisible)
        self.port_spin.valueChanged.connect(self._manual_port)
        self.poll_spin.valueChanged.connect(self._set_poll)
        self.cap_spin.valueChanged.connect(self._set_cap)
        v.addWidget(self.cfg_row)
        self._set_status(f"Manual: {self.port}" if self.port_locked else "Detecting port…",
                         "manual" if self.port_locked else "warn")

    def _set_status(self, text, kind=None):
        self.status.setText(f'<span style="color:{self.col[kind]}">●</span> {text}' if kind else text)

    # ---------- settings ----------
    def settings(self):
        return {"port": self.port if self.port_locked else None, "poll": self.poll_s, "cap": self.cap,
                "discard": self.discard}

    def _set_discard(self, on):
        self.discard = on
        self._render()

    def _set_poll(self, secs):
        self.poll_s = secs
        if self.poll_timer.isActive():
            self.poll_timer.start(secs * 1000)

    def _set_cap(self, n):
        self.cap = n
        self._render()

    def _manual_port(self, port):
        self.port, self.port_locked = port, True
        self._epoch, self._busy = self._epoch + 1, False
        self._set_status(f"Manual: {port}", "manual")
        self.poll()

    def _rescan_clicked(self):
        self.port_locked = False
        self.rescan()

    # ---------- network ----------
    def _get(self, path, cb, port=None, timeout=1500):
        req = QNetworkRequest(QUrl(f"http://127.0.0.1:{port or self.port}{path}"))
        req.setTransferTimeout(timeout)
        reply = self.nam.get(req)
        reply.finished.connect(lambda: self._reply(reply, cb))

    @staticmethod
    def _reply(reply, cb):
        ok, data = reply.error() == QNetworkReply.NetworkError.NoError, None
        if ok:
            try:
                data = json.loads(bytes(reply.readAll()).decode("utf-8", "replace"))
            except ValueError:
                pass
        reply.deleteLater()
        cb(ok, data)

    def rescan(self):
        """Probe the API port range in parallel; the first port that answers /queue_count wins."""
        if self._scanning:
            return
        self._scanning = True
        left, hit = [len(self.PORTS)], []
        self._set_status("Detecting port…", "warn")

        def probe(p):
            def cb(_ok, data):
                left[0] -= 1
                if not hit and isinstance(data, dict) and isinstance(data.get("count"), int):
                    hit.append(p)
                    self._found(p)
                if left[0] == 0:
                    self._scanning = False
                    if not hit:
                        self._missing()
            return cb

        for p in self.PORTS:
            self._get("/queue_count", probe(p), port=p)

    def _found(self, port):
        if self.port_locked:
            return
        if port != self.port:
            self.port, self._epoch, self._busy = port, self._epoch + 1, False
        self._error = None
        self.port_spin.blockSignals(True)
        self.port_spin.setValue(port)
        self.port_spin.blockSignals(False)
        self._set_status(f"Auto-detected on {port}", "ok")
        self.poll()

    def _missing(self):
        if self.port_locked:
            return
        self.port = None
        self._error = "Magik TtC API not found.\nStart ComfyUI with the Magik TtC node, or set the port under ⚙."
        self._set_status("No API found — check port manually", "bad")
        self._render()

    def poll(self):
        if self.port is None:
            self.rescan()
            return
        if self._busy:
            return
        self._busy, got, epoch = True, {}, self._epoch

        def cb(key):
            def f(ok, data):
                got[key] = data if ok else None
                if len(got) == 2 and epoch == self._epoch:  # replies from before a port change or Clear are stale: drop
                    self._busy = False
                    self._apply(got["entries"], got["queue"])
            return f

        self._get(f"/entries?max={self.MAX_ENTRIES}", cb("entries"))
        self._get("/queue_count", cb("queue"))

    def _apply(self, ent, q):
        if not (isinstance(ent, dict) and isinstance(ent.get("entries"), list)
                and isinstance(q, dict) and isinstance(q.get("count"), int)):
            self._error = f"Magik TtC API not reachable on port {self.port}."
            if not self.port_locked:
                self._set_status("Port unresponsive, rescanning…", "warn")
                self.rescan()
            self._render()
            return
        self._error = None
        self.entries = [e for e in ent["entries"] if isinstance(e, dict) and _fp(e) not in self.deleted]
        self.queue = q["count"]
        self._update_gen(self.queue, len(self.entries))
        self._render()

    def clear(self):
        if self.port is not None:
            self._get("/clear", lambda ok, _d: ok and self._reset())

    def _reset(self):
        self.entries, self.deleted = [], set()
        self.last_queue = self.last_cards = 0
        self._epoch, self._busy = self._epoch + 1, False  # a poll already in flight carries pre-clear data
        self._stop_gen()
        self._sig = None
        self._render()

    # ---------- generation timer ----------
    def _show_timer(self, secs):
        self.timer_lbl.setText(f"⏱ {secs or 0:.1f}s")
        self.timer_lbl.setStyleSheet(f"color: {self.col['dur']};" if secs is not None
                                     else "color: palette(placeholder-text);")

    def _tick(self):
        self._show_timer(time.monotonic() - self.gen_start)

    def _start_gen(self):
        if not self.gen_timer.isActive():
            self.gen_start = time.monotonic()
            self.gen_timer.start()
            self._tick()

    def _stop_gen(self):
        self.gen_timer.stop()
        self.gen_start = None
        self._show_timer(None)

    def _update_gen(self, queue, cards):
        if self.last_queue == 0 and queue > 0:
            self._start_gen()
        elif cards > self.last_cards and queue > 0:
            self.gen_start = time.monotonic()  # a card finished and more are queued: time the next one
        elif queue == 0:
            self._stop_gen()
        self.last_queue, self.last_cards = queue, cards

    # ---------- rendering ----------
    def _render(self):
        ents, q = self.entries, self.queue
        calc = ents[1:] if self.discard else ents
        recent = calc[-self.cap:]
        n = min(len(calc), self.cap)
        durs = [_dur(e) for e in calc]
        self.minmax.setText(f"Min <b>{_fmt_dur(min(durs) if durs else 0)}</b> | Max <b>{_fmt_dur(max(durs) if durs else 0)}</b>")
        self.counts.setText(f"Queue <b>{q}</b> · Entries <b>{len(ents)}</b>")
        for key, group, label in (("recent", recent, f"LAST {n}"), ("all", calc, "ALL")):
            mean = sum(_dur(e) for e in group) / len(group) if group else 0
            grp, mlbl, elbl = self.stat[key]
            grp.setText(label)
            mlbl.setText(f'<span style="color:{self.col["mean"]}">Ø</span> <b>{_fmt_dur(mean)}</b>')
            eta = _fmt_dur(mean * q) if q > 0 and mean > 0 else "—"
            elbl.setText(f'<span style="color:{self.col["warn"]}">≈</span> <b>{eta}</b>')
        sig = (tuple(map(_fp, ents)), self.discard, n, self._error)
        if sig == self._sig:
            return  # nothing visible changed: don't rebuild the list
        self._sig = sig
        if self._error or not ents:
            if not self._error:
                self.tree.clear()  # genuinely empty: don't keep stale rows around
            self.msg.setText(f"⚠ {self._error}" if self._error else "No generations yet.\nRun a workflow that saves text files.")
            self.stack.setCurrentWidget(self.msg)
            return
        self.stack.setCurrentWidget(self.tree)
        self._fill(ents, n)

    def _fill(self, ents, n):
        sb = self.tree.verticalScrollBar()
        keep = sb.value()
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        dim, bad = QBrush(self.palette().color(QPalette.ColorRole.PlaceholderText)), QBrush(QColor(self.col["bad"]))
        accent = [QBrush(QColor(self.col[k])) for k in ("time", "file", "dur")]
        total = len(ents)
        for i, e in enumerate(reversed(ents)):  # newest first
            files = ", ".join(map(str, e.get("files") or [])) or "—"
            it = QTreeWidgetItem([str(e.get("end_time", "")), files, f"⏱ {_dur(e):.1f}s", "✕"])
            it.setData(0, Qt.ItemDataRole.UserRole, _fp(e))
            it.setToolTip(1, files)
            it.setToolTip(3, "Delete this entry")
            it.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            it.setTextAlignment(3, Qt.AlignmentFlag.AlignCenter)
            discarded = self.discard and i == total - 1
            for col in range(3):
                it.setForeground(col, dim if discarded or i >= n else accent[col])  # outside the LAST-N window: dimmed
                if discarded:
                    f = it.font(col)
                    f.setStrikeOut(True)
                    it.setFont(col, f)
            if i < n:
                f = it.font(2)
                f.setBold(True)
                it.setFont(2, f)
            it.setForeground(3, bad)
            self.tree.addTopLevelItem(it)
        self.tree.setUpdatesEnabled(True)
        sb.setValue(keep)

    def _clicked(self, item, col):
        if col == 3:  # the ✕ column
            fp = item.data(0, Qt.ItemDataRole.UserRole)
            self.deleted.add(fp)
            self.entries = [e for e in self.entries if _fp(e) != fp]
            self._render()

    # ---------- lifecycle: poll only while visible ----------
    def showEvent(self, e):
        super().showEvent(e)
        self.poll_timer.start(self.poll_s * 1000)
        if self.gen_start is not None:
            self.gen_timer.start()
        self.poll()

    def hideEvent(self, e):
        super().hideEvent(e)
        if not e.spontaneous():  # a real hide (toggle), not just the window being minimized
            self.poll_timer.stop()
            self.gen_timer.stop()


# Detailed, practical guidance for common ComfyUI CLI flags. The live parser help is
# always appended, so this remains useful across ComfyUI versions.
FLAG_GUIDANCE = {
    "--listen": "Network exposure: controls which interface(s) the HTTP server binds to. Keep it on 127.0.0.1 for same-machine access. Binding to 0.0.0.0 or :: can expose the UI to your LAN (and potentially beyond, depending on firewall/router). ComfyUI is not an authentication boundary; do not expose it to untrusted networks. Some versions accept comma-separated addresses.",
    "--port": "HTTP port used by the ComfyUI server (normally 8188). Change it when another service already uses the port or when running multiple instances. The browser URL, extensions, API clients, and Kicker's monitor must use the matching port. A port change does not by itself make the server safer or expose it externally.",
    "--disable-auto-launch": "Prevents ComfyUI from automatically opening a browser after startup. Useful when Kicker manages browser opening, when running headless, or when you want to avoid duplicate browser windows. It does not disable the web UI or the HTTP server.",
    "--enable-manager": "Enables the ComfyUI-Manager integration when supported by this installation. Useful for installing/updating custom nodes and managing dependencies. Availability and exact behavior depend on the Manager version and ComfyUI packaging; it does not guarantee every node is compatible, and installing code from third parties carries supply-chain risk.",
    "--preview-method": "Selects how intermediate latent previews are produced (choices vary by ComfyUI version, commonly auto, latent2rgb, taesd, none). Previews can improve feedback but add processing and memory overhead; TAESD requires suitable preview decoder assets, and latent2rgb is approximate rather than a final-quality decode. 'none' minimizes preview work but removes intermediate visual feedback. This affects previews, not final output quality.",
    "--use-pytorch-cross-attention": "Selects PyTorch's native scaled-dot-product/cross-attention implementation where supported. Can be a robust baseline and may use efficient CUDA kernels depending on PyTorch, GPU, dtype, and tensor shape. Speed and memory use vary; it is not universally faster than SageAttention, FlashAttention, or xFormers. Usually mutually exclusive with other explicit attention backend selectors.",
    "--use-sage-attention": "Requests SageAttention kernels for supported attention operations. It can improve throughput and/or memory use on compatible GPUs and model paths, but benefits depend on architecture, dtype, tensor dimensions, and the installed SageAttention build. Custom CUDA/Triton extensions must match the Python/PyTorch/CUDA environment. Unsupported operations may error or fall back depending on the integration. Treat it as a workload-specific optimization and compare output/performance against a known-good baseline.",
    "--use-flash-attention": "Requests FlashAttention where the installed package and model path support it. Potentially faster and more memory-efficient for compatible attention shapes, dtypes, GPU architectures, and package builds. Installation/build compatibility is important, especially across PyTorch, CUDA, and Python versions. Not all ComfyUI models or attention calls can use it; conflicts with selecting another attention backend are possible.",
    "--disable-xformers": "Prevents ComfyUI from using xFormers attention. Useful for troubleshooting xFormers-specific errors, comparing backends, or when xFormers is incompatible with the installed PyTorch/CUDA stack. It may increase memory use or reduce speed if the fallback is less efficient. It does not install or enable an alternative backend by itself.",
    "--highvram": "Keeps models resident in GPU memory more aggressively instead of offloading them after use. Can reduce model-transfer overhead and help repeated inference when VRAM is plentiful. On a GPU shared with a display, another process, or another workload, it can leave too little VRAM and trigger allocation failures or offloading pressure elsewhere. Generally a poor fit for a memory-constrained/shared GPU; avoid combining with contradictory low/normal-VRAM modes.",
    "--lowvram": "Uses more aggressive model/component offloading to reduce peak VRAM requirements. Useful when a model otherwise cannot fit on the selected GPU. Expect more CPU-RAM use and potentially slower generation due to transfers; performance depends heavily on PCIe bandwidth and model architecture. It is not a free speed optimization and may interact with dynamic-VRAM/offload systems. Do not combine with other mutually exclusive VRAM mode flags.",
    "--novram": "An even more memory-constrained mode for cases where low-VRAM handling is insufficient. Typically increases offloading and can make inference substantially slower; it may still fail if system RAM or other resources are insufficient. Use as a last resort to fit workloads, not as a general performance setting. Mutually exclusive with other VRAM-mode selectors.",
    "--gpu-only": "Requests keeping model execution/data on the GPU rather than using normal CPU offloading. Can reduce transfer overhead when the model and working set fit comfortably in VRAM. If they do not fit, allocations can fail or the run can become unstable; it is usually unsuitable when sharing a GPU with games or desktop workloads. Do not combine with low/novram-style modes unless the installed version explicitly defines their interaction.",
    "--reserve-vram": "Reserves a specified amount of VRAM (in GB) for other uses by making ComfyUI behave as though less VRAM is available. Useful when the same GPU also drives a desktop or runs another application. Set a realistic amount: too little can still allow contention; too much reduces the memory available to ComfyUI and may force offloading or prevent models from fitting. It is a planning hint, not a hard isolation boundary, and does not reserve VRAM for a particular process.",
    "--disable-smart-memory": "Disables ComfyUI's smart memory management and tends to favor more aggressive unloading/offloading behavior (exact details vary by version). May help avoid VRAM pressure in some setups, but can increase transfers and generation latency. Test with your model and watch both VRAM and system RAM; it is not equivalent to disabling CUDA allocation or guaranteeing a fixed memory ceiling.",
    "--disable-dynamic-vram": "Disables the dynamic VRAM management path when that feature is available in this ComfyUI version. This can be useful for isolating memory-management regressions or comparing behavior, but may remove optimizations that keep memory usage responsive to workload. Effects depend on the ComfyUI release and related offload components; if you see no benefit, leave it off. Avoid stacking several memory-management switches without measuring each change.",
    "--fast-disk": "Enables a disk-backed/fast-disk loading path in versions that provide it, trading storage I/O and caching behavior against RAM/VRAM pressure. Potentially useful when memory is the bottleneck and fast SSD storage is available, but may be slower than RAM/VRAM-resident execution and is sensitive to storage throughput and free space. Exact behavior is version-dependent; monitor disk activity and latency.",
    "--cache-none": "Disables node-result caching so nodes are executed again rather than reusing cached outputs. Can lower memory use for large workflows or make repeated runs reflect upstream changes, but may substantially increase runtime because unchanged parts of the graph are recomputed. This affects workflow execution/caching, not the model's numerical precision. Use when cache memory is the problem, not as a default speed setting.",
    "--fast": "Enables a collection of performance-oriented options; some versions allow selecting individual features, while a bare --fast may enable a broader set. The exact list changes between releases and may include experimental kernels or precision/performance trade-offs. Faster does not mean identical behavior in every workflow: validate image/video quality, determinism, and compatibility for your models. Prefer explicit sub-options when you need reproducibility or want to isolate a regression.",
    "--disable-cuda-malloc": "Disables ComfyUI's CUDA memory allocator path when supported, changing how CUDA allocations are handled. Primarily useful for troubleshooting allocator-related crashes, fragmentation, or compatibility issues; it may reduce performance or change memory behavior. It is not the same as setting PyTorch's PYTORCH_CUDA_ALLOC_CONF and is not automatically beneficial. Compare with your current allocator configuration before keeping it enabled.",
    "--async-offload": "Enables asynchronous model/component offloading where supported, potentially overlapping transfers with computation to reduce stalls. Benefits depend on the model, storage/PCIe bandwidth, memory pressure, and ComfyUI's offload implementation. Can increase concurrency and resource pressure; if you see instability, freezes, or no speedup, compare against the default. It does not mean all model transfers become free or instantaneous.",
}


class WorkflowPanel(TtcPanel):
    """Poll server-recorded lifecycle times; never infer starts from queue size."""
    batchFinished = Signal()
    monitorStatus = Signal(str)

    def __init__(self, endpoint, saved=None):
        self._history_revision = 0
        self._entries_dirty = False
        self._stats_key = self._view_key = None
        self._stats_cache = {}
        self.output_folders = list((saved or {}).get("output_folders", []))
        self._folder_config_session = None
        self.background_poll = False
        self._batch_counter = None
        self.endpoint = endpoint
        self.server_session = None
        self.cursor = 0
        self.records = {}
        self.hidden_ids = set()
        self.active_id = None
        self._base_elapsed = 0
        self._elapsed_received = None
        super().__init__(saved)
        self.setTitle("Workflow timing")
        self.setObjectName("workflowTimingArea")
        dark = self.palette().window().color().lightness() < 128
        background = self.palette().window().color().darker(140).name()
        self.setStyleSheet(f"QGroupBox#workflowTimingArea {{ background-color: {background}; }}")
        self.tree.setStyleSheet(f"QTreeWidget {{ background-color: {background}; }}")
        self.tree.setHeaderLabels(["Finished", "Saved files", "Duration", ""])
        self.btn_scan.setText("Reconnect")
        self.btn_scan.setToolTip("Reconnect to the selected ComfyUI server")
        self.btn_clear.setText("Clear history")
        self.btn_clear.setToolTip("Hide completed runs locally; server records are retained")
        self.btn_clear_queue = QPushButton("Clear queue")
        self.btn_clear_queue.setStyleSheet(
            "QPushButton { background-color: #b32632; color: white; "
            "border: 1px solid #e0525f; border-radius: 5px; padding: 4px 10px; }"
            "QPushButton:hover { background-color: #cf3341; }"
            "QPushButton:pressed { background-color: #8e1e28; }"
            "QPushButton:disabled { background-color: #643238; color: #bba5a7; "
            "border-color: #785057; }"
        )
        self.btn_clear_queue.setToolTip("Remove pending jobs; the current workflow continues")
        self.btn_clear_queue.clicked.connect(self.clear_queue)
        top_row = self.layout().itemAt(0).layout()
        top_row.addWidget(self.btn_clear_queue)
        self.folder_button = QPushButton("Output folders…")
        self.folder_button.setToolTip("Optional filesystem-event tracking; requires watchdog in ComfyUI")
        self.folder_button.clicked.connect(self._folder_menu)
        top_row.addWidget(self.folder_button)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._file_menu)
        self.port_spin.setToolTip("Override the ComfyUI server port; Reconnect restores automatic selection")

    def settings(self):
        return super().settings() | {"output_folders": self.output_folders}

    def _folder_menu(self):
        menu = QMenu(self)
        add = menu.addAction("Add output folder…")
        removals = {}
        for folder in self.output_folders:
            removals[menu.addAction("Remove " + folder)] = folder
        clear = menu.addAction("Stop tracking all folders")
        action = menu.exec(self.folder_button.mapToGlobal(self.folder_button.rect().bottomLeft()))
        if action == add:
            folder = QFileDialog.getExistingDirectory(self, "Track output folder")
            if not folder:
                return
            if folder not in self.output_folders:
                self.output_folders.append(folder)
        elif action in removals:
            self.output_folders.remove(removals[action])
        elif action == clear:
            self.output_folders.clear()
        else:
            return
        self._configure_folders()

    def _configure_folders(self):
        self._folder_config_session = self.server_session
        base = self.endpoint(self.port if self.port_locked else None)
        request = QNetworkRequest(QUrl(base + "/comfy-kicker/output-folders"))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setTransferTimeout(5000)
        reply = self.nam.post(request, json.dumps({"directories": self.output_folders}).encode())
        def received(ok, data):
            error = data.get("error") if isinstance(data, dict) else "Folder tracking unavailable"
            if not ok or error:
                QMessageBox.warning(self, "Output folder tracking", str(error or "Request failed"))
        reply.finished.connect(lambda: self._reply(reply, received))

    def _file_menu(self, position):
        item = self.tree.itemAt(position)
        if item is None:
            return
        pid = item.data(3, Qt.ItemDataRole.UserRole)
        record = self.records.get(pid, {})
        menu = QMenu(self)
        for name in record.get("files", []):
            submenu = menu.addMenu(name)
            action = submenu.addAction("Copy filename")
            action.triggered.connect(lambda checked=False, text=name: QApplication.clipboard().setText(text))
            paths = record.get("file_paths", {}).get(name, [])
            if not paths:
                action = submenu.addAction("Full path unavailable")
                action.setEnabled(False)
            for path in paths:
                target = submenu.addMenu(path) if len(paths) > 1 else submenu
                action = target.addAction("Copy path")
                action.triggered.connect(lambda checked=False, text=path: QApplication.clipboard().setText(text))
                action = target.addAction("Open containing folder")
                action.triggered.connect(lambda checked=False, text=path:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(text).parent))))
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def clear_queue(self):
        self.btn_clear_queue.setEnabled(False)
        base = self.endpoint(self.port if self.port_locked else None)
        request = QNetworkRequest(QUrl(base + "/comfy-kicker/clear-queue"))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setTransferTimeout(5000)
        reply = self.nam.post(request, b'{}')
        def finished(ok, data):
            self.btn_clear_queue.setEnabled(True)
            if not ok or not isinstance(data, dict) or not isinstance(data.get("removed"), int):
                QMessageBox.warning(self, "Clear queue", "No clear result received. The queue may already have been cleared. Check its refreshed count before retrying; check the ComfyUI log for details.")
                self.poll()
            else:
                removed = data["removed"]
                self._queue_feedback = f"Cleared {removed} pending job{'s' if removed != 1 else ''}"
                self._queue_feedback_until = time.monotonic() + 4
                self._set_status(self._queue_feedback, "ok")
                if data.get("warning"):
                    self._set_status(self._queue_feedback + " — status notification delayed", "warn")
                self.poll()
        reply.finished.connect(lambda: self._reply(reply, finished))

    def rescan(self):
        self._epoch += 1
        self._busy = False
        self.poll()

    def poll(self):
        if self._busy:
            return
        self._busy = True
        epoch = self._epoch
        base = self.endpoint(self.port if self.port_locked else None)
        url = QUrl(base + "/comfy-kicker/monitor")
        query = QUrlQuery()
        if not self.isVisible():
            query.addQueryItem("summary", "1")
        else:
            query.addQueryItem("since", str(self.cursor))
            query.addQueryItem("session", self.server_session or "")
        url.setQuery(query)
        req = QNetworkRequest(url)
        req.setTransferTimeout(2500)
        reply = self.nam.get(req)
        reply.finished.connect(lambda: self._reply(reply, lambda ok, data: self._receive(epoch, ok, data)))

    def _receive(self, epoch, ok, data):
        if epoch != self._epoch:
            return
        self._busy = False
        if not ok or not isinstance(data, dict) or data.get("protocol") != 1:
            self.monitorStatus.emit("Monitor: disconnected")
            self._error = "Monitor unavailable. Install comfy_kicker_monitor and restart ComfyUI."
            self._set_status("Disconnected — timing paused", "bad")
            self.gen_timer.stop()
            self._elapsed_received = None
            self._show_timer(None)
            self._render()
            return
        if self.server_session != data.get("session"):
            self._batch_counter = None
            self.server_session = data.get("session")
            self.records.clear()
            self.entries = []
            self._history_revision = getattr(self, "_history_revision", 0) + 1
            self._entries_dirty = True
            self.hidden_ids.clear()
            self._sig = None
        self._error = None
        self.monitorStatus.emit("Monitor: connected")
        if self._folder_config_session != self.server_session and self.output_folders:
            self._configure_folders()
        pending = data.get("pending", max(0, int(data.get("queue", 0)) - len(data.get("active") or [])))
        self.btn_clear_queue.setToolTip(f"About {pending} pending jobs. Current execution continues.")
        tracking = data.get("folder_tracking") or {}
        self.folder_button.setToolTip(tracking.get("error") or
            ("Tracking: " + ", ".join(tracking.get("directories") or []) if tracking.get("directories") else
             "Folder tracking disabled; add folders to track native/subprocess writes"))
        counter = data.get("batches_finished")
        if isinstance(counter, int):
            if self._batch_counter is not None and counter > self._batch_counter and not data.get("queue", 0):
                self.batchFinished.emit()
            self._batch_counter = counter
        self.queue = max(0, int(data.get("queue", 0)))
        if data.get("summary"):
            # Leave the history cursor unchanged so reopening catches up.
            return
        self.cursor = data.get("sequence", 0)
        for r in data.get("entries", []):
            if isinstance(r, dict) and r.get("prompt_id"):
                pid = r["prompt_id"]
                if self.records.get(pid) != r:
                    self.records[pid] = r
                    self._entries_dirty = True
        retained = set(data.get("retained", [r.get("prompt_id") for r in data.get("entries", []) if isinstance(r, dict)]))
        evicted = self.records.keys() - retained
        if evicted:
            for pid in evicted:
                del self.records[pid]
            self.hidden_ids.difference_update(evicted)
            self._entries_dirty = True
        if self._entries_dirty:
            self.entries = []
            for pid, r in sorted(self.records.items(), key=lambda kv: kv[1].get("sequence", 0)):
                if pid in self.hidden_ids:
                    continue
                stamp = r.get("end_time")
                self.entries.append(dict(prompt_id=pid, end_time=time.strftime("%H:%M:%S", time.localtime(stamp)) if stamp else "—",
                                         duration=r.get("duration"), outcome=r.get("outcome"),
                                         files=list(r.get("files") or [])))
            self._history_revision = getattr(self, "_history_revision", 0) + 1
            self._entries_dirty = False
        self.queue = max(0, int(data.get("queue", 0)))
        active = data.get("active") or []
        if active:
            r = active[0]
            self.active_id = r.get("prompt_id")
            self._base_elapsed = max(0, float(r.get("elapsed", 0)))
            self._elapsed_received = time.monotonic()
            self.gen_timer.start()
            self._tick()
        else:
            self.active_id = None
            self._elapsed_received = None
            self._stop_gen()
        self._set_status(self._queue_feedback if time.monotonic() < getattr(self, "_queue_feedback_until", 0)
                         else "Monitor connected", "ok")
        self._render()

    def set_background_poll(self, enabled):
        self.background_poll = enabled
        if not enabled and not self.isVisible():
            self.monitorStatus.emit("Monitor: paused")
        # Start with a fresh baseline when enabling notifications.
        self._batch_counter = None
        if enabled or self.isVisible():
            self.poll_timer.start(self.poll_s * 1000)
            self.poll()
        else:
            self.poll_timer.stop()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self.background_poll:
            self.poll_timer.start(self.poll_s * 1000)
        else:
            self.monitorStatus.emit("Monitor: paused")

    def _fill(self, ents, n):
        tree = self.tree
        keep = tree.verticalScrollBar().value()
        tree.setUpdatesEnabled(False)
        try:
            rows = {tree.topLevelItem(i).data(3, Qt.ItemDataRole.UserRole): tree.topLevelItem(i)
                    for i in range(tree.topLevelItemCount())}
            wanted = {e["prompt_id"] for e in ents}
            for pid, item in list(rows.items()):
                if pid not in wanted:
                    tree.takeTopLevelItem(tree.indexOfTopLevelItem(item))
                    del rows[pid]
            dim = QBrush(self.palette().color(QPalette.ColorRole.PlaceholderText))
            accent = [QBrush(QColor(self.col[k])) for k in ("time", "file", "dur")]
            for i, e in enumerate(reversed(ents)):
                pid = e["prompt_id"]
                item = rows.get(pid)
                if item is None:
                    item = QTreeWidgetItem()
                    item.setData(3, Qt.ItemDataRole.UserRole, pid)
                    tree.insertTopLevelItem(i, item)
                    item.setText(3, "✕")
                    item.setToolTip(3, "Delete this entry")
                    item.setForeground(3, QBrush(QColor(self.col["bad"])))
                    item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    item.setTextAlignment(3, Qt.AlignmentFlag.AlignCenter)
                fingerprint = _fp(e)
                if item.data(0, Qt.ItemDataRole.UserRole) != fingerprint:
                    files = ", ".join(map(str, e.get("files") or [])) or "—"
                    item.setText(0, str(e.get("end_time", "")))
                    item.setText(1, files)
                    item.setToolTip(1, "\n".join(e.get("files") or []))
                    item.setText(2, "unknown" if e.get("duration") is None else f"⏱ {_dur(e):.1f}s")
                    item.setData(0, Qt.ItemDataRole.UserRole, fingerprint)
                discarded = self.discard and i == len(ents) - 1
                for col in range(3):
                    item.setForeground(col, dim if discarded or i >= n else accent[col])
                    font = item.font(col)
                    font.setStrikeOut(discarded)
                    font.setBold(col == 2 and i < n)
                    item.setFont(col, font)
        finally:
            tree.setUpdatesEnabled(True)
            tree.verticalScrollBar().setValue(keep)

    def _tick(self):
        if self._elapsed_received is not None:
            self._show_timer(self._base_elapsed + time.monotonic() - self._elapsed_received)

    def _empty_tree(self):
        """Swap out populated views; never destroy thousands of rows in a click."""
        old = self.tree
        if old.topLevelItemCount() == 0:
            return
        tree = QTreeWidget()
        tree.setHeaderLabels([old.headerItem().text(i) for i in range(old.columnCount())])
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        tree.setAlternatingRowColors(True)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        tree.setStyleSheet(old.styleSheet())
        tree.header().setStretchLastSection(False)
        for col in range(old.columnCount()):
            tree.header().setSectionResizeMode(col, old.header().sectionResizeMode(col))
        tree.itemClicked.connect(self._clicked)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._file_menu)
        self.stack.removeWidget(old)
        self.stack.addWidget(tree)
        self.tree = tree
        old.hide()
        old.setUpdatesEnabled(False)
        old.blockSignals(True)
        for col in range(old.columnCount()):
            old.header().setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        # Retire from the end to avoid shifting remaining row positions.
        QTimer.singleShot(10, lambda: self._retire_tree(old))

    def _retire_tree(self, tree):
        if not isValid(tree):
            return  # the window may have closed during deferred cleanup
        deadline = time.monotonic() + 0.008
        for _ in range(32):
            if tree.topLevelItemCount() == 0:
                tree.deleteLater()
                return
            item = tree.takeTopLevelItem(tree.topLevelItemCount() - 1)
            del item
            if time.monotonic() >= deadline:
                break
        QTimer.singleShot(10, lambda: self._retire_tree(tree))

    def clear(self):
        self.hidden_ids.update(self.records)
        self.entries = []
        self._history_revision += 1
        self._render()

    def _clicked(self, item, col):
        if col == 3:
            pid = item.data(3, Qt.ItemDataRole.UserRole)
            self.hidden_ids.add(pid)
            self.entries = [e for e in self.entries if e["prompt_id"] != pid]
            self._history_revision += 1
            self._render()

    def _compute_stats(self):
        calc = self.entries[1:] if self.discard else self.entries
        valid = [r for r in calc if r.get("outcome") == "success"
                 and isinstance(r.get("duration"), (int, float))]
        durations = [_dur(r) for r in valid]
        result = {"min": min(durations) if durations else 0,
                  "max": max(durations) if durations else 0,
                  "n": min(len(calc), self.cap)}
        for key, group in (("recent", valid[-self.cap:]), ("all", valid)):
            result[key] = (len(group), sum(_dur(r) for r in group) / len(group) if group else 0)
        return result

    def _render(self):
        stats_key = (self._history_revision, self.discard, self.cap)
        if self._stats_key != stats_key:
            self._stats_cache = self._compute_stats()
            self._stats_key = stats_key
        stats = self._stats_cache
        self.minmax.setText(f"Min <b>{_fmt_dur(stats['min'])}</b> | Max <b>{_fmt_dur(stats['max'])}</b>")
        self.counts.setText(f"Queue <b>{self.queue}</b> · Entries <b>{len(self.entries)}</b>")
        for key in ("recent", "all"):
            count, mean = stats[key]
            label, mlbl, elbl = self.stat[key]
            label.setText(f"LAST {count}" if key == "recent" else "ALL")
            mlbl.setText(f"Ø <b>{_fmt_dur(mean)}</b>")
            elapsed = self._base_elapsed if self.active_id else 0
            eta = max(0, mean * self.queue - elapsed)
            elbl.setText(f"≈ <b>{_fmt_dur(eta) if mean and self.queue else '—'}</b>")
        view_key = (stats_key, self._error)
        if self._view_key == view_key:
            return
        self._view_key = view_key
        if self._error or not self.entries:
            if not self.entries:
                self._empty_tree()
            self.msg.setText(f"⚠ {self._error}" if self._error else "No completed workflows yet. Run any workflow.")
            self.stack.setCurrentWidget(self.msg)
        else:
            self.stack.setCurrentWidget(self.tree)
            self._fill(self.entries, stats['n'])



