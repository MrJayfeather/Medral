from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QComboBox, QLabel, QFrame, QPushButton,
    QGraphicsOpacityEffect,
)
from PyQt6.QtCore import (
    Qt, pyqtSlot, QTimer, QPoint, QAbstractAnimation, QEasingCurve,
    QParallelAnimationGroup, QPropertyAnimation,
)

from network import ApiClient
from ui import anim
from ui.background_widget import BackgroundWidget
from ui.channel_panel      import ChannelPanel
from ui.search_panel       import SearchPanel
from ui.player_panel       import PlayerPanel
from ui.queue_panel        import QueuePanel


def _is_playlist_url(url: str) -> bool:
    """Mirrors the server-side playlist detection in POST /play."""
    return url.startswith("http") and (
        "list=" in url or "/playlist" in url or "/album" in url
    )


class MainWindow(QMainWindow):
    def __init__(self, client: ApiClient) -> None:
        super().__init__()
        self.client = client

        self._guild_id: int | None = None
        self._guilds:   list[dict] = []
        self._state:    dict       = {}

        # вход через Discord: main() задаёт коллбек, guard не даёт
        # открыть несколько LoginDialog при серии 401/4401
        self._login_handler = None
        self._login_active  = False

        self._intro_played = False   # one-shot cascade on first show

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
        self._top_bar = bar

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
        self._dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)

        self._user_lbl = QLabel("")
        self._user_lbl.setStyleSheet("color:#6b6b8a; background:transparent;")
        self._user_lbl.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        lay.addWidget(self._user_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        change_btn = QPushButton("⚙")
        change_btn.setToolTip("Change server")
        change_btn.setFixedSize(32, 32)
        change_btn.setStyleSheet(
            "QPushButton { background:#16162a; border:1px solid #2a2a40;"
            " border-radius:8px; color:#e8e8f5; font-size:15px; padding:0; }"
            "QPushButton:hover { background:#1e1e32; border-color:#6C63FF; }"
        )
        change_btn.clicked.connect(self._on_change_server)
        lay.addWidget(change_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        return bar

    # ── connect signals ───────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self.client.state_updated.connect(self._on_state)
        self.client.guilds_updated.connect(self._on_guilds)
        self.client.search_results_ready.connect(self.search_panel.show_results)
        self.client.ws_connected.connect(self._on_ws_up)
        self.client.ws_disconnected.connect(self._on_ws_down)
        self.client.request_error.connect(self._on_error)
        self.client.auth_required.connect(self._on_auth_required)
        self.client.auth_ok.connect(self._on_auth_ok)

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
        self.player_panel.shuffle_clicked.connect(
            lambda: self._guild_id and self.client.shuffle(self._guild_id)
        )
        self.player_panel.loop_clicked.connect(
            lambda mode: self._guild_id and self.client.set_loop(self._guild_id, mode)
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
        anim.pulse(self._dot, ms=2000, low=0.35)   # soft breathing while live
        self.statusBar().showMessage("Connected", 3000)
        self.client.fetch_guilds()

    @pyqtSlot()
    def _on_ws_down(self) -> None:
        anim.stop_pulse(self._dot)
        self._dot.setStyleSheet("color:#f87171; font-size:14px; background:transparent;")
        self._dot.setToolTip("Disconnected — retrying…")
        self.statusBar().showMessage("Disconnected — reconnecting…")

    @pyqtSlot(str)
    def _on_error(self, msg: str) -> None:
        self.statusBar().showMessage(f"Error: {msg}", 6000)
        # a failed /search never emits search_results_ready — unfreeze the panel
        self.search_panel.reset_loading()

    # ── auth ──────────────────────────────────────────────────────────────

    def set_login_handler(self, fn) -> None:
        """fn() -> bool: показывает LoginDialog, True = вход выполнен."""
        self._login_handler = fn

    def set_username(self, name: str) -> None:
        self._user_lbl.setText(name or "")

    def request_login(self) -> bool:
        if self._login_active or self._login_handler is None:
            return False
        self._login_active = True
        try:
            return bool(self._login_handler())
        finally:
            self._login_active = False

    @pyqtSlot()
    def _on_auth_required(self) -> None:
        self.request_login()

    @pyqtSlot(dict)
    def _on_auth_ok(self, data: dict) -> None:
        self.set_username(data.get("username", ""))

    def _do_logout(self) -> None:
        import json
        from pathlib import Path

        self.client.logout()          # токен снапшотится внутри logout()

        cfg_file = Path.home() / ".medral" / "config.json"
        try:
            cfg = json.loads(cfg_file.read_text())
        except Exception:
            cfg = {}
        cfg.pop("token", None)
        cfg.pop("username", None)
        try:
            cfg_file.parent.mkdir(parents=True, exist_ok=True)
            cfg_file.write_text(json.dumps(cfg, indent=2))
        except Exception:
            pass

        self.client.set_token(None)
        self.set_username("")
        self.request_login()

    # ── playback controls ─────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_search(self, query: str) -> None:
        self.search_panel.set_loading()
        self.client.search(query)

    @pyqtSlot(str)
    def _on_play_url(self, url: str) -> None:
        if not self._guild_id:
            return
        if _is_playlist_url(url):
            self.client.play_playlist(self._guild_id, url)
            self.statusBar().showMessage("Загружаю плейлист…", 8000)
        else:
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

        from defaults import DEFAULT_HOST, DEFAULT_PORT

        cfg_file = Path.home() / ".medral" / "config.json"
        try:
            cfg = json.loads(cfg_file.read_text())
        except Exception:
            cfg = {"host": DEFAULT_HOST, "port": DEFAULT_PORT}

        LOGOUT = 2   # кастомный код результата диалога

        dlg = QDialog(self)
        dlg.setWindowTitle("Change server")
        dlg.setFixedSize(340, 210)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Host"))
        host_edit = QLineEdit(cfg.get("host", DEFAULT_HOST))
        row1.addWidget(host_edit)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Port"))
        port_edit = QLineEdit(str(cfg.get("port", 8000)))
        row2.addWidget(port_edit)
        lay.addLayout(row2)

        logout_btn = _Btn("Выйти из аккаунта")
        logout_btn.setObjectName("disconnectBtn")
        logout_btn.clicked.connect(lambda: dlg.done(LOGOUT))
        lay.addWidget(logout_btn)

        btns = QHBoxLayout()
        cancel = _Btn("Cancel")
        cancel.clicked.connect(dlg.reject)
        ok = _Btn("Connect")
        ok.setObjectName("primaryBtn")
        ok.clicked.connect(dlg.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

        res = dlg.exec()
        if res == LOGOUT:
            self._do_logout()
            return
        if res != QDialog.DialogCode.Accepted:
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

    # ── intro cascade ─────────────────────────────────────────────────────

    def _intro_plan(self):
        # widget, dx, dy, delay_ms — sidebar slides from the left, top bar
        # from above, content panels fade upward; ~500 ms total cascade
        return [
            (self.ch_panel,     -16,   0,   0),
            (self._top_bar,       0, -12,  60),
            (self.search_panel,   0,  14, 130),
            (self.player_panel,   0,  14, 200),
            (self.queue_panel,    0,  14, 270),
        ]

    def _intro_fade(self, widget, dx: int = 0, dy: int = 0, ms: int = 380) -> None:
        """anim.fade_in twin with horizontal offset support (fade_in is dy-only)."""
        try:
            if dx == 0:
                anim.fade_in(widget, ms, dy)
                return

            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.0)
            widget.setGraphicsEffect(effect)

            group = QParallelAnimationGroup(widget)

            fade = QPropertyAnimation(effect, b"opacity", group)
            fade.setDuration(ms)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.setEasingCurve(QEasingCurve.Type.OutQuint)
            group.addAnimation(fade)

            end = widget.pos()
            slide = QPropertyAnimation(widget, b"pos", group)
            slide.setDuration(ms)
            slide.setStartValue(end + QPoint(dx, dy))
            slide.setEndValue(end)
            slide.setEasingCurve(QEasingCurve.Type.OutQuint)
            group.addAnimation(slide)

            def _cleanup() -> None:
                try:
                    if widget.graphicsEffect() is effect:
                        widget.setGraphicsEffect(None)
                except RuntimeError:
                    pass

            group.finished.connect(_cleanup)
            group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
        except RuntimeError:
            pass   # widget destroyed before its turn

    def _play_intro(self) -> None:
        for w, dx, dy, delay in self._intro_plan():
            if delay == 0:
                self._intro_fade(w, dx, dy)
            else:
                QTimer.singleShot(
                    delay,
                    lambda w=w, dx=dx, dy=dy: self._intro_fade(w, dx, dy),
                )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._intro_played:
            return
        self._intro_played = True
        # hide intro targets before the first paint so nothing flashes
        for w, *_ in self._intro_plan():
            eff = QGraphicsOpacityEffect(w)
            eff.setOpacity(0.0)
            w.setGraphicsEffect(eff)
        # defer one event-loop turn so the layout has final geometry
        QTimer.singleShot(0, self._play_intro)

    # ── resize ────────────────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_bg"):
            self._bg.resize(self.centralWidget().size())
