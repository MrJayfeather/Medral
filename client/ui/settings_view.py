"""Embedded settings page (design system v2).

Replaces the old "Change server" QDialog: host/port editing, account row
with logout and the client version now live on a stacked page inside the
main window, with the aurora background visible behind a centered card.
"""

import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal


def _read_version() -> str:
    """Same lookup order as main._read_version (importing main is circular)."""
    for candidate in (
        Path(__file__).parent.parent / "version.txt",           # client/version.txt
        Path(__file__).parent.parent.parent / "version.txt",    # project root
        Path(sys.executable).parent / "version.txt",            # next to frozen exe
    ):
        try:
            if candidate.exists():
                return candidate.read_text().strip()
        except OSError:
            pass
    return "0.0.0"


class SettingsView(QWidget):
    """Settings page: server address, account and client version.

    The page itself is transparent (aurora shows through); content sits on
    a centered surface card.  All persistence/apply logic stays in
    MainWindow — this view only collects input and emits signals.
    """

    back_requested    = pyqtSignal()
    connect_requested = pyqtSignal(str, int)   # host, port
    logout_requested  = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsView")

        # used when the edits are blank / unparsable on "Connect"
        self._fallback_host = ""
        self._fallback_port = 8000

        self.setStyleSheet("""
            QWidget#settingsView { background: transparent; }
            QFrame#settingsCard {
                background-color: #0e0e1a;
                border: 1px solid #2a2a40;
                border-radius: 16px;
            }
            QLabel#settingsTitle {
                font-family: "Syne", "DM Sans", "Segoe UI", sans-serif;
                font-size: 24px;
                font-weight: 700;
                letter-spacing: 1px;
                color: #e8e8f5;
                background: transparent;
            }
            QPushButton#backBtn {
                background: transparent;
                border: none;
                border-radius: 8px;
                color: #6b6b8a;
                font-size: 13px;
                padding: 6px 12px;
            }
            QPushButton#backBtn:hover {
                color: #e8e8f5;
                background: rgba(108,99,255,0.10);
            }
        """)

        self._build_ui()

    # ── layout ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 12, 20, 16)
        root.setSpacing(0)

        # back button — top left
        top = QHBoxLayout()
        back = QPushButton("←  Назад")
        back.setObjectName("backBtn")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self.back_requested)
        top.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        top.addStretch()
        root.addLayout(top)

        root.addStretch(1)

        title = QLabel("Настройки")
        title.setObjectName("settingsTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(title)
        root.addSpacing(20)

        # centered surface card
        card = QFrame()
        card.setObjectName("settingsCard")
        card.setFixedWidth(460)
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(28, 24, 28, 24)
        c_lay.setSpacing(12)

        srv_sec = QLabel("СЕРВЕР")
        srv_sec.setObjectName("sectionTitle")
        c_lay.addWidget(srv_sec)

        host_row = QHBoxLayout()
        host_lbl = QLabel("Host")
        host_lbl.setFixedWidth(40)
        host_lbl.setStyleSheet("color:#6b6b8a; background:transparent;")
        self._host_edit = QLineEdit()
        self._host_edit.setPlaceholderText("127.0.0.1  или  IP сервера")
        host_row.addWidget(host_lbl)
        host_row.addWidget(self._host_edit)
        c_lay.addLayout(host_row)

        port_row = QHBoxLayout()
        port_lbl = QLabel("Port")
        port_lbl.setFixedWidth(40)
        port_lbl.setStyleSheet("color:#6b6b8a; background:transparent;")
        self._port_edit = QLineEdit()
        self._port_edit.setPlaceholderText("8000")
        port_row.addWidget(port_lbl)
        port_row.addWidget(self._port_edit)
        c_lay.addLayout(port_row)

        c_lay.addSpacing(4)

        connect_btn = QPushButton("Подключиться")
        connect_btn.setObjectName("primaryBtn")
        connect_btn.clicked.connect(self._on_connect_clicked)
        c_lay.addWidget(connect_btn)

        c_lay.addSpacing(8)
        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        c_lay.addWidget(divider)
        c_lay.addSpacing(8)

        acc_sec = QLabel("АККАУНТ")
        acc_sec.setObjectName("sectionTitle")
        c_lay.addWidget(acc_sec)

        acc_row = QHBoxLayout()
        self._user_lbl = QLabel("—")
        self._user_lbl.setStyleSheet("color:#e8e8f5; background:transparent;")
        acc_row.addWidget(self._user_lbl, 1)
        logout_btn = QPushButton("Выйти из аккаунта")
        logout_btn.setObjectName("disconnectBtn")
        logout_btn.clicked.connect(self.logout_requested)
        acc_row.addWidget(logout_btn, 0)
        c_lay.addLayout(acc_row)

        center = QHBoxLayout()
        center.addStretch()
        center.addWidget(card)
        center.addStretch()
        root.addLayout(center)

        root.addStretch(2)

        ver = QLabel(f"Medral Client v{_read_version()}")
        ver.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        ver.setStyleSheet("color:#6b6b8a; font-size:11px; background:transparent;")
        root.addWidget(ver)

    # ── public ────────────────────────────────────────────────────────────

    def set_values(self, host: str, port: int) -> None:
        self._fallback_host = host
        self._fallback_port = port
        self._host_edit.setText(host)
        self._port_edit.setText(str(port))

    def set_username(self, name: str) -> None:
        self._user_lbl.setText(name or "—")

    # ── private ───────────────────────────────────────────────────────────

    def _on_connect_clicked(self) -> None:
        host = self._host_edit.text().strip() or self._fallback_host
        try:
            port = int(self._port_edit.text().strip())
        except ValueError:
            port = self._fallback_port
        self.connect_requested.emit(host, port)
