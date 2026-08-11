from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QWidget,
    QGraphicsOpacityEffect, QStyle, QStyledItemDelegate,
)
from PyQt6.QtCore import (
    pyqtSignal, Qt, QAbstractAnimation, QEasingCurve, QEvent,
    QPropertyAnimation, QRectF, QVariantAnimation,
)
from PyQt6.QtGui import QFont, QColor, QLinearGradient, QPainter

_ACTIVE_ROLE = Qt.ItemDataRole.UserRole + 1   # bot connected to this channel


class ChannelPanel(QFrame):
    # object instead of int — Qt truncates 64-bit Discord snowflakes to 32-bit with pyqtSignal(int)
    join_requested  = pyqtSignal(object, object)  # guild_id, channel_id
    leave_requested = pyqtSignal(object)           # guild_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("leftPanel")
        self.setFixedWidth(220)

        self._guild_id:        int | None = None
        self._channels:        list[dict] = []
        self._connected_ch_id: int | None = None
        self._rendered:        tuple | None = None  # what _rebuild_list last drew

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

        # channel list — delegate paints animated hover + active accent bar,
        # so mute the QSS item backgrounds for this list only
        self._list = QListWidget()
        self._list.setSpacing(1)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list.setStyleSheet(
            "QListWidget::item { background: transparent; }"
            "QListWidget::item:hover { background: transparent; }"
            "QListWidget::item:selected { background: transparent; }"
        )
        self._delegate = _ChannelDelegate(self._list)
        self._list.setItemDelegate(self._delegate)
        self._list.viewport().setMouseTracking(True)
        self._list.viewport().installEventFilter(self)
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
        # keepalive pushes state_update every 10 s — don't wipe the list
        # (and the user's selection) unless something actually changed
        if self._snapshot() != self._rendered:
            self._rebuild_list()
        self._refresh_btn()

    # ── hover tracking for the delegate ───────────────────────────────────

    def eventFilter(self, obj, ev) -> bool:
        if obj is self._list.viewport():
            et = ev.type()
            if et in (QEvent.Type.MouseMove, QEvent.Type.HoverMove):
                idx = self._list.indexAt(ev.position().toPoint())
                self._delegate.set_hovered(idx.row() if idx.isValid() else -1)
            elif et in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
                self._delegate.set_hovered(-1)
        return super().eventFilter(obj, ev)

    # ── private ───────────────────────────────────────────────────────────

    def _snapshot(self) -> tuple:
        return (
            tuple((str(ch["id"]), ch["name"]) for ch in self._channels),
            self._connected_ch_id,
        )

    def _rebuild_list(self) -> None:
        current = self._list.currentItem()
        selected_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        self._delegate.reset()
        self._list.clear()
        for ch in self._channels:
            active = (self._connected_ch_id is not None
                      and int(ch["id"]) == self._connected_ch_id)
            text = f"  🔊  {ch['name']}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, str(ch["id"]))
            if active:
                item.setData(_ACTIVE_ROLE, True)
                item.setForeground(QColor("#6C63FF"))
                item.setFont(_bold_font())
            self._list.addItem(item)
            if selected_id is not None and str(ch["id"]) == selected_id:
                self._list.setCurrentItem(item)
        self._rendered = self._snapshot()

    def _refresh_btn(self) -> None:
        connected = self._connected_ch_id is not None
        name = "disconnectBtn" if connected else "connectBtn"
        if self._action_btn.objectName() == name:
            return   # state unchanged — no repolish, no animation
        self._action_btn.setText("Disconnect Bot" if connected else "Connect Bot")
        self._action_btn.setObjectName(name)
        self._action_btn.style().unpolish(self._action_btn)
        self._action_btn.style().polish(self._action_btn)
        self._fade_btn()

    def _fade_btn(self) -> None:
        # soften the style swap with a short opacity ramp
        btn = self._action_btn
        fx = QGraphicsOpacityEffect(btn)
        fx.setOpacity(0.35)
        btn.setGraphicsEffect(fx)
        anim = QPropertyAnimation(fx, b"opacity", btn)
        anim.setDuration(250)
        anim.setStartValue(0.35)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _done() -> None:
            try:
                if btn.graphicsEffect() is fx:
                    btn.setGraphicsEffect(None)
            except RuntimeError:
                pass

        anim.finished.connect(_done)
        anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

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
                int(item.data(Qt.ItemDataRole.UserRole)),
            )

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        pass

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        if self._guild_id is None:
            return
        self.join_requested.emit(
            self._guild_id,
            int(item.data(Qt.ItemDataRole.UserRole)),
        )


# ── delegate ──────────────────────────────────────────────────────────────

class _ChannelDelegate(QStyledItemDelegate):
    """Rounded row backgrounds with animated hover and an accent bar
    on the active (connected) channel."""

    def __init__(self, view) -> None:
        super().__init__(view)
        self._view = view
        self._progress: dict[int, float] = {}   # row → hover 0..1
        self._anims:    dict[int, QVariantAnimation] = {}
        self._hovered = -1

    def set_hovered(self, row: int) -> None:
        if row == self._hovered:
            return
        old, self._hovered = self._hovered, row
        if old >= 0:
            self._animate(old, 0.0)
        if row >= 0:
            self._animate(row, 1.0)

    def reset(self) -> None:
        for anim in self._anims.values():
            anim.stop()
            anim.deleteLater()
        self._anims.clear()
        self._progress.clear()
        self._hovered = -1

    def _animate(self, row: int, end: float) -> None:
        anim = self._anims.get(row)
        if anim is None:
            anim = QVariantAnimation(self)
            anim.setDuration(150)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.valueChanged.connect(lambda v, r=row: self._tick(r, float(v)))
            self._anims[row] = anim
        anim.stop()
        anim.setStartValue(self._progress.get(row, 0.0))
        anim.setEndValue(end)
        anim.start()

    def _tick(self, row: int, value: float) -> None:
        self._progress[row] = value
        try:
            self._view.viewport().update()
        except RuntimeError:
            pass   # view already destroyed

    def paint(self, painter, option, index) -> None:
        r = QRectF(option.rect.adjusted(4, 1, -4, -1))
        t = self._progress.get(index.row(), 0.0)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        active   = bool(index.data(_ACTIVE_ROLE))

        alpha = 0.08 * t
        if selected:
            alpha += 0.16
        elif active:
            alpha += 0.10

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if alpha > 0.0:
            bg = QColor(0x6C, 0x63, 0xFF)
            bg.setAlphaF(min(alpha, 0.28))
            painter.setBrush(bg)
            painter.drawRoundedRect(r, 8.0, 8.0)
        if active:
            bar = QRectF(r.left() + 2, r.top() + 8, 3.0, r.height() - 16)
            grad = QLinearGradient(bar.topLeft(), bar.bottomLeft())
            grad.setColorAt(0.0, QColor("#6C63FF"))
            grad.setColorAt(1.0, QColor("#A78BFA"))
            painter.setBrush(grad)
            painter.drawRoundedRect(bar, 1.5, 1.5)
        painter.restore()

        super().paint(painter, option, index)


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
