from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QComboBox, QLabel, QFrame, QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSlot, QTimer

from network import ApiClient
from ui.background_widget import BackgroundWidget
from ui.channel_panel      import ChannelPanel
from ui.search_panel       import SearchPanel
from ui.player_panel       import PlayerPanel
from ui.queue_panel        import QueuePanel


class MainWindow(QMainWindow):
    def __init__(self, client: ApiClient) -> None:
        super().__init__()
        self.client = client

        self._guild_id: int | None = None
        self._guilds:   list[dict] = []
        self._state:    dict       = {}

        self.setWindowTitle("Medral")
        self.setMinimumSize(960, 620)
        self.resize(1140, 720)

        self._build_ui()
        self._connect_signals()

    # ── build UI ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        # Animated background — sits below everything
        self._bg = BackgroundWidget(central)
        self._bg.lower()

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # left sidebar
        self.ch_panel = ChannelPanel()
        root.addWidget(self.ch_panel)

        # right column
        right = QWidget()
        right.setStyleSheet("background: transparent;")
        r_lay = QVBoxLayout(right)
        r_lay.setContentsMargins(0, 0, 0, 0)
        r_lay.setSpacing(0)

        r_lay.addWidget(self._make_top_bar())

        vsplit = QSplitter(Qt.Orientation.Vertical)
        vsplit.setChildrenCollapsible(False)
        vsplit.setStyleSheet("background: transparent;")

        upper = QWidget()
        upper.setStyleSheet("background: transparent;")
        u_lay = QVBoxLayout(upper)
        u_lay.setContentsMargins(20, 16, 20, 12)
        u_lay.setSpacing(14)

        self.search_panel = SearchPanel()
        u_lay.addWidget(self.search_panel)

        self.player_panel = PlayerPanel()
        u_lay.addWidget(self.player_panel, 1)

        vsplit.addWidget(upper)

        lower = QWidget()
        lower.setStyleSheet("background: transparent;")
        l_lay = QVBoxLayout(lower)
        l_lay.setContentsMargins(20, 8, 20, 12)
        l_lay.setSpacing(0)

        self.queue_panel = QueuePanel()
        l_lay.addWidget(self.queue_panel, 1)

        vsplit.addWidget(lower)
        vsplit.setSizes([440, 200])

        r_lay.addWidget(vsplit, 1)
        root.addWidget(right, 1)

        self.statusBar().showMessage("Connecting…")

    def _make_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(52)

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(12)

        logo = QLabel("♪  MEDRAL")
        logo.setObjectName("logo")
        lay.addWidget(logo)

        lay.addStretch()

        srv = QLabel("Server:")
        srv.setStyleSheet("color:#6b6b8a; background:transparent;")
        lay.addWidget(srv)

        self._guild_combo = QComboBox()
        self._guild_combo.setPlaceholderText("No server")
        self._guild_combo.setMinimumWidth(160)
        self._guild_combo.currentIndexChanged.connect(self._on_guild_changed)
        lay.addWidget(self._guild_combo)

        self._dot = QLabel("●")
        self._dot.setStyleSheet("color:#f87171; font-size:14px; background:transparent;")
        self._dot.setToolTip("WebSocket disconnected")
        lay.addWidget(self._dot)

        change_btn = QPushButton("⚙")
        change_btn.setToolTip("Change server")
        change_btn.setFixedSize(32, 32)
        change_btn.setStyleSheet(
            "QPushButton { background:#16162a; border:1px solid #2a2a40;"
            " border-radius:8px; color:#e8e8f5; font-size:15px; }"
            "QPushButton:hover { background:#1e1e32; border-color:#6C63FF; }"
        )
        change_btn.clicked.connect(self._on_change_server)
        lay.addWidget(change_btn)

        return bar

    # ── connect signals ───────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self.client.state_updated.connect(self._on_state)
        self.client.guilds_updated.connect(self._on_guilds)
        self.client.search_results_ready.connect(self.search_panel.show_results)
        self.client.ws_connected.connect(self._on_ws_up)
        self.client.ws_disconnected.connect(self._on_ws_down)
        self.client.request_error.connect(self._on_error)

        self.ch_panel.join_requested.connect(
            lambda g, c: self.client.join(g, c)
        )
        self.ch_panel.leave_requested.connect(
            lambda g: self.client.leave(g)
        )

        self.search_panel.search_submitted.connect(self._on_search)
        self.search_panel.play_requested.connect(self._on_play_url)

        self.player_panel.play_pause_clicked.connect(self._on_play_pause)
        self.player_panel.skip_clicked.connect(
            lambda: self._guild_id and self.client.skip(self._guild_id)
        )
        self.player_panel.previous_clicked.connect(
            lambda: self._guild_id and self.client.previous(self._guild_id)
        )
        self.player_panel.volume_changed.connect(
            lambda v: self._guild_id and self.client.set_volume(self._guild_id, v)
        )
        self.player_panel.seek_requested.connect(
            lambda pos: self._guild_id and self.client.seek(self._guild_id, pos)
        )

        self.queue_panel.remove_requested.connect(
            lambda i: self._guild_id and self.client.remove_from_queue(self._guild_id, i)
        )
        self.queue_panel.move_requested.connect(
            lambda f, t: self._guild_id and self.client.move_in_queue(self._guild_id, f, t)
        )

    # ── state handler ─────────────────────────────────────────────────────

    @pyqtSlot(dict)
    def _on_state(self, state: dict) -> None:
        gid = state.get("guild_id")
        if gid and self._guild_id is not None and str(self._guild_id) != str(gid):
            return
        self._state = state
        self.ch_panel.update_state(state)
        self.player_panel.update_state(state)
        self.queue_panel.update_state(state)

    # ── guild list ────────────────────────────────────────────────────────

    @pyqtSlot(list)
    def _on_guilds(self, guilds: list) -> None:
        self._guilds = guilds
        self._guild_combo.blockSignals(True)
        self._guild_combo.clear()
        for g in guilds:
            self._guild_combo.addItem(g["name"], g["id"])
        self._guild_combo.blockSignals(False)

        if not guilds:
            return

        if self._guild_id is None:
            self._guild_combo.setCurrentIndex(0)
            self._on_guild_changed(0)
        else:
            restore_idx = next(
                (i for i, g in enumerate(guilds) if int(g["id"]) == self._guild_id),
                0,
            )
            self._guild_combo.setCurrentIndex(restore_idx)
            self.client.fetch_state(self._guild_id)

    @pyqtSlot(int)
    def _on_guild_changed(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._guilds):
            return
        g = self._guilds[idx]
        self._guild_id = int(g["id"])
        self.ch_panel.set_guild(
            self._guild_id,
            g["name"],
            g.get("voice_channels", []),
        )
        self.client.fetch_state(self._guild_id)

    # ── WS status ─────────────────────────────────────────────────────────

    @pyqtSlot()
    def _on_ws_up(self) -> None:
        self._dot.setStyleSheet("color:#34d399; font-size:14px; background:transparent;")
        self._dot.setToolTip("Connected")
        self.statusBar().showMessage("Connected", 3000)
        self.client.fetch_guilds()

    @pyqtSlot()
    def _on_ws_down(self) -> None:
        self._dot.setStyleSheet("color:#f87171; font-size:14px; background:transparent;")
        self._dot.setToolTip("Disconnected — retrying…")
        self.statusBar().showMessage("Disconnected — reconnecting…")

    @pyqtSlot(str)
    def _on_error(self, msg: str) -> None:
        self.statusBar().showMessage(f"Error: {msg}", 6000)

    # ── playback controls ─────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_search(self, query: str) -> None:
        self.client.search(query)

    @pyqtSlot(str)
    def _on_play_url(self, url: str) -> None:
        if self._guild_id:
            self.client.play(self._guild_id, url)

    @pyqtSlot()
    def _on_play_pause(self) -> None:
        if not self._guild_id:
            return
        if self._state.get("is_paused"):
            self.client.resume(self._guild_id)
        elif self._state.get("is_playing"):
            self.client.pause(self._guild_id)

    def _on_change_server(self) -> None:
        import json
        from pathlib import Path
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit
        from PyQt6.QtWidgets import QPushButton as _Btn

        cfg_file = Path.home() / ".medral" / "config.json"
        try:
            cfg = json.loads(cfg_file.read_text())
        except Exception:
            cfg = {"host": "89.124.90.59", "port": 8000}

        dlg = QDialog(self)
        dlg.setWindowTitle("Change server")
        dlg.setFixedSize(340, 160)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Host"))
        host_edit = QLineEdit(cfg.get("host", "89.124.90.59"))
        row1.addWidget(host_edit)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Port"))
        port_edit = QLineEdit(str(cfg.get("port", 8000)))
        row2.addWidget(port_edit)
        lay.addLayout(row2)

        btns = QHBoxLayout()
        cancel = _Btn("Cancel")
        cancel.clicked.connect(dlg.reject)
        ok = _Btn("Connect")
        ok.setObjectName("primaryBtn")
        ok.clicked.connect(dlg.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        host = host_edit.text().strip() or cfg["host"]
        try:
            port = int(port_edit.text().strip())
        except ValueError:
            port = cfg.get("port", 8000)

        cfg["host"] = host
        cfg["port"] = port
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        cfg_file.write_text(json.dumps(cfg, indent=2))

        self._guild_id = None
        self._guilds   = []
        self._state    = {}
        self.client.set_server(host, port)
        self.statusBar().showMessage(f"Connecting to {host}:{port}…")

    # ── resize ────────────────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_bg"):
            self._bg.resize(self.centralWidget().size())
