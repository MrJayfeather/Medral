import os
import sys
import json
import socket
import subprocess
import tempfile
import threading
from pathlib import Path


# ── server mode ───────────────────────────────────────────────────────────────
# When the exe is launched with --server it runs the FastAPI/Discord server
# instead of the GUI.  The GUI client starts it this way for local mode.

def _run_server() -> None:
    frozen = getattr(sys, "frozen", False)

    if frozen:
        root = Path(sys.executable).parent
    else:
        root = Path(__file__).parent.parent          # client/ → project root
        bot_dir = root / "bot"
        if str(bot_dir) not in sys.path:
            sys.path.insert(0, str(bot_dir))

    os.chdir(str(root))                              # load_dotenv() in api.py finds .env here

    import uvicorn
    import api as _api                               # bot/api.py (on sys.path)
    uvicorn.run(_api.app, host=_api.API_HOST, port=_api.API_PORT, reload=False)


if "--server" in sys.argv:
    _run_server()
    sys.exit(0)


# ── normal GUI mode ───────────────────────────────────────────────────────────

from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar, QWidget,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont

sys.path.insert(0, str(Path(__file__).parent))

from styles          import STYLESHEET
from network         import ApiClient
from ui.main_window  import MainWindow


# ── version ───────────────────────────────────────────────────────────────────

def _read_version() -> str:
    for candidate in (
        Path(__file__).parent / "version.txt",
        Path(__file__).parent.parent / "version.txt",
        Path(sys.executable).parent / "version.txt",
    ):
        if candidate.exists():
            return candidate.read_text().strip()
    return "0.0.0"


CLIENT_VERSION = _read_version()
CONFIG_FILE = Path.home() / ".medral" / "config.json"


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {"host": "127.0.0.1", "port": 8000}


def _save_config(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


# ── server auto-start ─────────────────────────────────────────────────────────

def _is_server_running(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _start_local_server() -> bool:
    """Launch this same exe with --server in a hidden window."""
    exe = Path(sys.executable)
    subprocess.Popen(
        [str(exe), "--server"],
        creationflags=subprocess.CREATE_NO_WINDOW,
        cwd=str(exe.parent),
    )
    return True


# ── auto-update ───────────────────────────────────────────────────────────────

class _Downloader(QObject):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    def run(self) -> None:
        import urllib.request
        try:
            tmp = tempfile.mktemp(suffix=".exe")
            with urllib.request.urlopen(self._url, timeout=60) as resp:
                total = int(resp.headers.get("content-length", 0))
                done  = 0
                with open(tmp, "wb") as f:
                    while chunk := resp.read(65536):
                        f.write(chunk)
                        done += len(chunk)
                        if total:
                            self.progress.emit(int(done / total * 100))
            self.finished.emit(tmp)
        except Exception as e:
            self.error.emit(str(e))


class UpdateDialog(QDialog):
    def __init__(self, current: str, latest: str, url: str) -> None:
        super().__init__()
        self._url = url
        self.setWindowTitle("Обновление")
        self.setFixedSize(380, 200)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(12)

        lay.addWidget(QLabel(
            f"Доступна новая версия: <b>{latest}</b><br>Текущая: {current}"
        ))

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setVisible(False)
        lay.addWidget(self._bar)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#7d8590; font-size:11px;")
        lay.addWidget(self._status)

        btn_row = QHBoxLayout()
        self._skip = QPushButton("Пропустить")
        self._skip.clicked.connect(self.reject)
        btn_row.addWidget(self._skip)

        self._update_btn = QPushButton("Обновить сейчас")
        self._update_btn.setObjectName("primaryBtn")
        self._update_btn.clicked.connect(self._start_download)
        btn_row.addWidget(self._update_btn)
        lay.addLayout(btn_row)

    def _start_download(self) -> None:
        self._update_btn.setEnabled(False)
        self._skip.setEnabled(False)
        self._bar.setVisible(True)
        self._status.setText("Загрузка…")

        self._dl = _Downloader(self._url)
        self._dl.progress.connect(self._bar.setValue)
        self._dl.finished.connect(self._on_done)
        self._dl.error.connect(self._on_error)

        t = threading.Thread(target=self._dl.run, daemon=True)
        t.start()

    def _on_done(self, tmp_path: str) -> None:
        self._status.setText("Установка…")
        exe = Path(sys.executable)
        bat = tempfile.mktemp(suffix=".bat")
        Path(bat).write_text(
            f"@echo off\n"
            f"ping 127.0.0.1 -n 3 >nul\n"
            f'move /y "{tmp_path}" "{exe}"\n'
            f'start "" "{exe}"\n'
            f"del \"%~f0\"\n",
            encoding="utf-8",
        )
        subprocess.Popen(["cmd", "/c", bat], creationflags=subprocess.CREATE_NO_WINDOW)
        QApplication.quit()

    def _on_error(self, msg: str) -> None:
        self._status.setText(f"Ошибка: {msg}")
        self._update_btn.setEnabled(True)
        self._skip.setEnabled(True)


def _ver_tuple(v: str):
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,)


def _check_update(host: str, port: int, current_version: str) -> None:
    import urllib.request, json as _json
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/version", timeout=5) as r:
            data = _json.loads(r.read())
        latest    = data.get("client", "0.0.0")
        available = data.get("client_available", False)
        if available and _ver_tuple(latest) > _ver_tuple(current_version):
            UpdateDialog._pending = (current_version, latest,
                                     f"http://{host}:{port}/update/client")
    except Exception:
        pass


# ── connection dialog ─────────────────────────────────────────────────────────

class ConnectDialog(QDialog):
    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.result_host = ""
        self.result_port = 8000
        self.setWindowTitle("Medral")
        self.setFixedSize(420, 280)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self._build(cfg)

    def _build(self, cfg: dict) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 36, 36, 36)
        root.setSpacing(0)

        title = QLabel("Connect to server")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        root.addSpacing(6)

        sub = QLabel(f"Client v{CLIENT_VERSION} — Enter the address of your Medral server.")
        sub.setStyleSheet("color:#7d8590; font-size:12px;")
        root.addWidget(sub)
        root.addSpacing(20)

        h_row = QHBoxLayout()
        h_lbl = QLabel("Host")
        h_lbl.setFixedWidth(40)
        h_lbl.setStyleSheet("color:#7d8590;")
        self._host = QLineEdit(cfg.get("host", "127.0.0.1"))
        self._host.setPlaceholderText("127.0.0.1  или  IP сервера")
        h_row.addWidget(h_lbl)
        h_row.addWidget(self._host)
        root.addLayout(h_row)
        root.addSpacing(10)

        p_row = QHBoxLayout()
        p_lbl = QLabel("Port")
        p_lbl.setFixedWidth(40)
        p_lbl.setStyleSheet("color:#7d8590;")
        self._port = QLineEdit(str(cfg.get("port", 8000)))
        self._port.setPlaceholderText("8000")
        p_row.addWidget(p_lbl)
        p_row.addWidget(self._port)
        root.addLayout(p_row)
        root.addSpacing(8)

        self._hint = QLabel("")
        self._hint.setStyleSheet("color:#3fb950; font-size:11px;")
        root.addWidget(self._hint)
        root.addSpacing(16)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        local_btn = QPushButton("Запустить локально")
        local_btn.setToolTip("Запустить встроенный сервер на этом ПК")
        local_btn.clicked.connect(self._on_local)
        btn_row.addWidget(local_btn)

        connect = QPushButton("Подключиться")
        connect.setObjectName("primaryBtn")
        connect.setDefault(True)
        connect.clicked.connect(self._on_connect)
        btn_row.addWidget(connect)
        root.addLayout(btn_row)

    def _on_local(self) -> None:
        host, port = "127.0.0.1", 8000
        if not _is_server_running(host, port):
            self._hint.setText("Запускаю сервер…")
            QApplication.processEvents()
            if not _start_local_server():
                self._hint.setText("Не удалось запустить сервер.")
                return
            for _ in range(20):
                QApplication.processEvents()
                import time
                time.sleep(0.5)
                if _is_server_running(host, port):
                    break
            else:
                self._hint.setText("Сервер не ответил за 10 сек.")
                return
        self._hint.setText("Сервер запущен!")
        self.result_host = host
        self.result_port = port
        self.accept()

    def _on_connect(self) -> None:
        h = self._host.text().strip()
        if not h:
            self._host.setFocus()
            return
        try:
            p = int(self._port.text().strip())
        except ValueError:
            p = 8000
        self.result_host = h
        self.result_port = p
        self.accept()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = ev.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, ev) -> None:
        if ev.buttons() == Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(ev.globalPosition().toPoint() - self._drag_pos)


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Medral")
    app.setStyleSheet(STYLESHEET)
    app.setFont(QFont("Segoe UI", 10))

    cfg    = _load_config()
    dialog = ConnectDialog(cfg)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)

    cfg["host"] = dialog.result_host
    cfg["port"] = dialog.result_port
    _save_config(cfg)

    client = ApiClient(dialog.result_host, dialog.result_port)
    client.start()

    window = MainWindow(client)
    window.show()

    QTimer.singleShot(800, client.fetch_guilds)

    def _do_update_check():
        _check_update(dialog.result_host, dialog.result_port, CLIENT_VERSION)
        pending = getattr(UpdateDialog, "_pending", None)
        if pending:
            del UpdateDialog._pending
            UpdateDialog(*pending).exec()

    QTimer.singleShot(3000, _do_update_check)

    ret = app.exec()
    client.stop()
    sys.exit(ret)


if __name__ == "__main__":
    main()
