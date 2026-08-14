from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QAbstractItemView,
    QPushButton, QMenu, QSizePolicy, QGraphicsOpacityEffect,
)
from PyQt6.QtCore import (
    pyqtSignal, Qt, QSize, QPoint,
    QEasingCurve, QPropertyAnimation, QVariantAnimation,
)
from PyQt6.QtGui import QAction

from i18n import tr, tr_n
from ui.anim import stagger
from ui.elide import ElideLabel


class QueuePanel(QWidget):
    remove_requested = pyqtSignal(int)
    move_requested   = pyqtSignal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._tracks:   list[dict] = []
        self._no_signal = False
        self._build_ui()

    # ── layout ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        hdr = QHBoxLayout()
        title = QLabel(tr("queue_header"))
        title.setObjectName("sectionTitle")
        self._count = QLabel("")
        self._count.setStyleSheet("color:#6b6b8a; font-size:11px; background:transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(self._count)
        root.addLayout(hdr)

        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)
        self._list.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._list.setSpacing(1)
        self._list.model().rowsMoved.connect(self._on_rows_moved)

        root.addWidget(self._list, 1)

    # ── public ────────────────────────────────────────────────────────────

    def update_state(self, state: dict) -> None:
        new = list(state.get("queue", []))
        old = self._tracks
        # cascade only when tracks were appended — not on move/remove/replace
        appended = len(new) > len(old) and new[:len(old)] == old
        self._tracks = new
        self._rebuild()
        if appended:
            rows = [self._list.itemWidget(self._list.item(i))
                    for i in range(len(old), len(new))]
            rows = [w for w in rows if w is not None]
            if rows:
                stagger(rows, step_ms=45, ms=300, dy=0)
        n = len(self._tracks)
        self._count.setText(f"{n} {tr_n('track', n)}" if n else "")

    # ── private ───────────────────────────────────────────────────────────

    def _rebuild(self) -> None:
        self._no_signal = True
        sel = self._list.currentRow()
        self._list.clear()

        for i, track in enumerate(self._tracks):
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 54))
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._list.addItem(item)

            row = _QueueRow(i, track)
            row.remove_clicked.connect(self._on_remove)
            self._list.setItemWidget(item, row)

        if 0 <= sel < self._list.count():
            self._list.setCurrentRow(sel)

        self._no_signal = False

    def _on_rows_moved(
        self,
        _src_parent, src_start: int, src_end: int,
        _dst_parent, dst_row: int,
    ) -> None:
        if self._no_signal:
            return
        from_idx = src_start
        to_idx = (dst_row - 1) if dst_row > src_start else dst_row
        if from_idx == to_idx:
            return
        track = self._tracks.pop(from_idx)
        self._tracks.insert(to_idx, track)
        self._rebuild()
        self.move_requested.emit(from_idx, to_idx)

    def _on_remove(self, index: int) -> None:
        self.remove_requested.emit(index)

    def _context_menu(self, pos: QPoint) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        row = self._list.row(item)
        menu = QMenu(self)
        act_remove = menu.addAction(tr("remove_from_queue"))
        act_up     = menu.addAction(tr("move_up"))
        act_down   = menu.addAction(tr("move_down"))

        act_up.setEnabled(row > 0)
        act_down.setEnabled(row < self._list.count() - 1)

        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen == act_remove:
            self.remove_requested.emit(row)
        elif chosen == act_up and row > 0:
            self.move_requested.emit(row, row - 1)
        elif chosen == act_down and row < self._list.count() - 1:
            self.move_requested.emit(row, row + 1)


# ── individual row widget ──────────────────────────────────────────────────

class _QueueRow(QWidget):
    remove_clicked = pyqtSignal(int)

    _MARGIN      = 12   # resting left margin
    _MARGIN_HOV  = 16   # hovered: content nudged 4px right

    def __init__(self, index: int, track: dict, parent=None) -> None:
        super().__init__(parent)
        self._idx = index

        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(self._MARGIN, 0, 8, 0)
        self._lay.setSpacing(10)

        num = QLabel(str(index + 1))
        num.setFixedWidth(22)
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        num.setStyleSheet("color:#6b6b8a; font-size:11px; background:transparent;")
        self._lay.addWidget(num)

        info = QVBoxLayout()
        info.setSpacing(2)

        title  = str(track.get("title") or tr("unknown"))
        artist = str(track.get("artist") or "")
        dur    = int(track.get("duration") or 0)
        m, s   = divmod(dur, 60)

        # labels shrink with the row (elided dynamically) instead of
        # pushing the remove button past the panel edge in narrow windows
        t_lbl = ElideLabel(title)
        t_lbl.setStyleSheet("font-size:13px; font-weight:500; color:#e8e8f5; background:transparent;")
        info.addWidget(t_lbl)

        sub_text = f"{artist}  •  {m}:{s:02d}"
        # Non-YouTube tracks are labelled with their source
        source = track.get("source")
        if source == "soundcloud":
            sub_text += "  •  SoundCloud"
        elif source == "spotify":
            sub_text += "  •  Spotify"
        sub = ElideLabel(sub_text)
        sub.setStyleSheet("font-size:11px; color:#6b6b8a; background:transparent;")
        info.addWidget(sub)

        self._lay.addLayout(info, 1)

        rm = QPushButton("✕")
        rm.setFixedSize(22, 22)
        rm.setStyleSheet(
            "QPushButton { background:transparent; color:#6b6b8a; border:none;"
            "              font-size:11px; border-radius:11px; }"
            "QPushButton:hover { color:#f87171; background:rgba(248,113,113,0.12); }"
        )
        rm.clicked.connect(lambda: self.remove_clicked.emit(self._idx))
        # stretch 0 — the button keeps its fixed 22x22 and is never squeezed
        self._lay.addWidget(rm, 0)

        # remove button hidden until row hover (opacity fade)
        self._rm_fx = QGraphicsOpacityEffect(rm)
        self._rm_fx.setOpacity(0.0)
        rm.setGraphicsEffect(self._rm_fx)

        # hover animations — parented to the row, freed with it
        self._shift = QVariantAnimation(self)
        self._shift.setDuration(150)
        self._shift.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._shift.valueChanged.connect(self._apply_shift)

        self._rm_anim = QPropertyAnimation(self._rm_fx, b"opacity", self)
        self._rm_anim.setDuration(150)
        self._rm_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _apply_shift(self, v) -> None:
        self._lay.setContentsMargins(int(v), 0, 8, 0)

    def _animate_hover(self, entered: bool) -> None:
        self._shift.stop()
        self._shift.setStartValue(self._lay.contentsMargins().left())
        self._shift.setEndValue(self._MARGIN_HOV if entered else self._MARGIN)
        self._shift.start()

        self._rm_anim.stop()
        self._rm_anim.setStartValue(self._rm_fx.opacity())
        self._rm_anim.setEndValue(1.0 if entered else 0.0)
        self._rm_anim.start()

    def enterEvent(self, ev) -> None:
        self._animate_hover(True)
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:
        self._animate_hover(False)
        super().leaveEvent(ev)
