import sys
import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QWidget, QFrame,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

# resolve imports when running from client/ directory
sys.path.insert(0, str(Path(__file__).parent))

from styles       import STYLESHEET
from network      import ApiClient
from ui.main_window import MainWindow

CONFIG_FILE = Path.home() / ".medral" / "config.json"


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {"host": "127.0.0.1", "port": 8000}


def _save_config(host: str, port: int) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({"host": host, "port": port}, indent=2))


# ── connection dialog ─────────────────────────────────────────────────────

class ConnectDialog(QDialog):
    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.host = ""
        self.port = 8000
        self.setWindowTitle("Medral")
        self.setFixedSize(400, 260)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self._build(cfg)

    def _build(self, cfg: dict) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 36, 36, 36)
        root.setSpacing(0)

        # title
        title = QLabel("Connect to server")
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        root.addSpacing(6)

        sub = QLabel("Enter the address of your Medral server.")
        sub.setStyleSheet("color:#7d8590; font-size:12px;")
        root.addWidget(sub)

        root.addSpacing(20)

        # host row
        h_row = QHBoxLayout()
        h_lbl = QLabel("Host")
        h_lbl.setFixedWidth(40)
        h_lbl.setStyleSheet("color:#7d8590;")
        self._host = QLineEdit(cfg.get("host", "127.0.0.1"))
        self._host.setPlaceholderText("127.0.0.1")
        h_row.addWidget(h_lbl)
        h_row.addWidget(self._host)
        root.addLayout(h_row)

        root.addSpacing(10)

        # port row
        p_row = QHBoxLayout()
        p_lbl = QLabel("Port")
        p_lbl.setFixedWidth(40)
        p_lbl.setStyleSheet("color:#7d8590;")
        self._port = QLineEdit(str(cfg.get("port", 8000)))
        self._port.setPlaceholderText("8000")
        p_row.addWidget(p_lbl)
        p_row.addWidget(self._port)
        root.addLayout(p_row)

        root.addSpacing(24)

        # buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)

        connect = QPushButton("Connect")
        connect.setObjectName("primaryBtn")
        connect.setDefault(True)
        connect.clicked.connect(self._on_connect)
        btn_row.addWidget(connect)
        root.addLayout(btn_row)

    def _on_connect(self) -> None:
        h = self._host.text().strip()
        if not h:
            self._host.setFocus()
            return
        try:
            p = int(self._port.text().strip())
        except ValueError:
            p = 8000
        self.host = h
        self.port = p
        self.accept()

    # allow dragging the frameless dialog
    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = ev.globalPosition().toPoint() - self.pos()
            ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        if ev.buttons() == Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(ev.globalPosition().toPoint() - self._drag_pos)
            ev.accept()


# ── entry point ───────────────────────────────────────────────────────────

def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Medral")
    app.setStyleSheet(STYLESHEET)

    # apply a clean font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    cfg    = _load_config()
    dialog = ConnectDialog(cfg)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)

    _save_config(dialog.host, dialog.port)

    client = ApiClient(dialog.host, dialog.port)
    client.start()

    window = MainWindow(client)
    window.show()

    # small delay before fetching guilds — gives WS time to connect first
    QTimer.singleShot(800, client.fetch_guilds)

    ret = app.exec()
    client.stop()
    sys.exit(ret)


if __name__ == "__main__":
    main()
