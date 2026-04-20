from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QWidget,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont


class ChannelPanel(QFrame):
    # object instead of int — Qt truncates 64-bit Discord snowflakes to 32-bit with pyqtSignal(int)
    join_requested  = pyqtSignal(object, object)  # guild_id, channel_id
    leave_requested = pyqtSignal(object)           # guild_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("leftPanel")
        self.setFixedWidth(220)

        self._guild_id:           int | None  = None
        self._channels:           list[dict]  = []
        self._connected_ch_id:    int | None  = None

        self._build_ui()

    # ── layout ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # header
        header = QWidget()
        header.setFixedHeight(52)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(16, 0, 16, 0)
        self._server_label = QLabel("NO SERVER")
        self._server_label.setObjectName("sectionTitle")
        h_lay.addWidget(self._server_label)
        root.addWidget(header)

        root.addWidget(_Divider())

        # section title
        sec = QWidget()
        sec.setFixedHeight(32)
        s_lay = QHBoxLayout(sec)
        s_lay.setContentsMargins(16, 0, 16, 0)
        lbl = QLabel("VOICE CHANNELS")
        lbl.setObjectName("sectionTitle")
        s_lay.addWidget(lbl)
        root.addWidget(sec)

        # channel list
        self._list = QListWidget()
        self._list.setSpacing(1)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        root.addWidget(self._list, 1)

        root.addWidget(_Divider())

        # connect / disconnect button
        btn_wrap = QWidget()
        btn_wrap.setFixedHeight(60)
        b_lay = QVBoxLayout(btn_wrap)
        b_lay.setContentsMargins(12, 10, 12, 10)
        self._action_btn = QPushButton("Connect Bot")
        self._action_btn.setObjectName("connectBtn")
        self._action_btn.setEnabled(False)
        self._action_btn.clicked.connect(self._on_action)
        b_lay.addWidget(self._action_btn)
        root.addWidget(btn_wrap)

    # ── public ────────────────────────────────────────────────────────────

    def set_guild(self, guild_id: int, name: str, channels: list[dict]) -> None:
        self._guild_id = guild_id
        self._channels = channels
        self._server_label.setText(name.upper()[:22])
        self._rebuild_list()
        self._action_btn.setEnabled(True)

    def update_state(self, state: dict) -> None:
        raw = state.get("voice_channel_id")
        self._connected_ch_id = int(raw) if raw else None
        self._rebuild_list()
        self._refresh_btn()

    # ── private ───────────────────────────────────────────────────────────

    def _rebuild_list(self) -> None:
        self._list.clear()
        for ch in self._channels:
            active = (self._connected_ch_id is not None
                      and int(ch["id"]) == self._connected_ch_id)
            text = f"  🔊  {ch['name']}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, str(ch["id"]))  # store as str, Qt truncates large ints
            if active:
                item.setForeground(
                    __import__("PyQt6.QtGui", fromlist=["QColor"]).QColor("#58a6ff")
                )
                item.setFont(_bold_font())
            self._list.addItem(item)


    def _refresh_btn(self) -> None:
        if self._connected_ch_id is not None:
            self._action_btn.setText("Disconnect Bot")
            self._action_btn.setObjectName("disconnectBtn")
        else:
            self._action_btn.setText("Connect Bot")
            self._action_btn.setObjectName("connectBtn")
        # force stylesheet re-polish
        self._action_btn.style().unpolish(self._action_btn)
        self._action_btn.style().polish(self._action_btn)

    def _on_action(self) -> None:
        if self._guild_id is None:
            return
        if self._connected_ch_id is not None:
            self.leave_requested.emit(self._guild_id)
            return
        item = self._list.currentItem()
        if item:
            self.join_requested.emit(
                self._guild_id,
                int(item.data(Qt.ItemDataRole.UserRole)),  # data is str, safe to int()
            )

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        pass

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        if self._guild_id is None:
            return
        self.join_requested.emit(
            self._guild_id,
            int(item.data(Qt.ItemDataRole.UserRole)),  # data is str, safe to int()
        )


# ── helpers ───────────────────────────────────────────────────────────────

class _Divider(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("divider")
        self.setFixedHeight(1)


def _bold_font() -> QFont:
    f = QFont()
    f.setBold(True)
    return f
