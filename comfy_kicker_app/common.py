#!/usr/bin/env python3
"""Comfy Kicker - flag-driven ComfyUI launcher for Linux / KDE Plasma (PySide6).

Flags are discovered from your installed ComfyUI (comfy/cli_args.py) on every
load, so new flags appear after a ComfyUI update. A curated Favorites tab holds
the everyday ones; everything else is on the searchable "All other flags" tab.

    python comfy_kicker.py                     # run
    python comfy_kicker.py --install-desktop   # add an app-launcher entry
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from shiboken6 import isValid

from PySide6.QtCore import QLockFile, QStandardPaths, QProcess, QProcessEnvironment, Qt, QTimer, QUrl, QUrlQuery, QSize, Signal
from PySide6.QtGui import QActionGroup, QPainter, QPixmap, QIcon, QBrush, QColor, QDesktopServices, QFont, QPalette, QTextCharFormat, QTextCursor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtNetwork import QLocalServer, QLocalSocket, QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QInputDialog, QDoubleSpinBox, QFrame, QSizePolicy, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QSystemTrayIcon, QScrollArea, QSpinBox, QSplitter, QStackedWidget, QTabWidget, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "comfy-kicker" / "config.json"

# Curated tab. Flags missing from the installed ComfyUI are skipped silently.
FAVORITES = [
    ("Server", ["--listen", "--port", "--disable-auto-launch", "--enable-manager", "--preview-method"]),
    ("Attention", ["--use-pytorch-cross-attention", "--use-sage-attention", "--use-flash-attention", "--disable-xformers"]),
    ("VRAM / memory", ["--highvram", "--lowvram", "--novram", "--gpu-only", "--reserve-vram",
                       "--disable-smart-memory", "--disable-dynamic-vram", "--fast-disk", "--cache-none"]),
    ("Performance", ["--fast", "--disable-cuda-malloc", "--async-offload"]),
]
# Flags that make no sense from a launcher (they print and exit, or are build-specific).
HIDDEN = {"--quick-test-for-ci", "--windows-standalone-build", "--list-feature-flags", "--cuda-device"}

# Log colouring: first matching rule wins per fragment; the most severe category (lowest rank) wins per line.
LOG_RULES = [
    ("error", re.compile(r"error|critical|fatal|traceback|exception|failed|out of memory|exited \(code (?!0\))", re.I)),
    ("warn", re.compile(r"warn|deprecat", re.I)),
    ("success", re.compile(r"prompt executed in|to see the gui go to|starting server|loaded completely|exited \(code 0\)", re.I)),
    ("workflow_eta", re.compile(r"\[workflow-eta\]", re.I)),
    ("rate", re.compile(r"\b(?:\d+(?:\.\d+)?\s*)?(?:it/s|s/it)\b", re.I)),
    ("info", re.compile(r"got prompt|requested to load|loaded partially|loading \d+ new model|using .* attention|total vram", re.I)),
    ("progress", re.compile(r"\d+%\|")),
    ("debug", re.compile(r"\bDEBUG\b")),
    ("kicker", re.compile(r"^\[kicker\]")),
]
LOG_RANK = {"tb": -1, **{cat: i for i, (cat, _) in enumerate(LOG_RULES)}}

# Log filter checkboxes: (bit, label, pattern). A line can carry several bits; ticked boxes show the union.
FILTER_RULES = [
    (1, "Saved", re.compile(r"\bsaved\b", re.I)),
    (2, "Progress", re.compile(r"\d+%\||\bit/s\b|\bs/it\b")),
    (4, "Generation Time", re.compile(r"prompt executed in|generation time", re.I)),
    (8, "Errors", LOG_RULES[0][1]),
    (16, "got prompt", re.compile(r"got prompt", re.I)),
    (32, "Starting server", re.compile(r"starting server", re.I)),
]
GEN_TIME_RE = re.compile(r"prompt executed in ([\d.]+) seconds", re.I)
READY_RE = re.compile(r"to see the gui go to", re.I)  # ComfyUI prints this once the server is up
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")  # colour/cursor escape codes (e.g. Magik's [34m ... [0m)



# Export shared names, including private helpers/constants, to sibling modules.
__all__ = [name for name in globals() if not name.startswith("__")]
