import os
import sys
import json
import socket
import secrets
import subprocess
import tempfile
import threading
import time
import webbrowser
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
from defaults        import DEFAULT_HOST, DEFAULT_PORT
from network         import ApiClient
from ui.main_window   import MainWindow
from ui.splash_screen import SplashScreen


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
        return {"host": DEFAULT_HOST, "port": DEFAULT_PORT}


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


class _UpdateChecker(QObject):
    """Runs the blocking /version request off the UI thread (cf. _Downloader)."""

    update_available = pyqtSignal(str, str, str)   # current, latest, url

    def __init__(self, host: str, port: int, current_version: str) -> None:
        super().__init__()
        self._host    = host
        self._port    = port
        self._current = current_version
        # queued connection → the dialog is created in the UI thread
        self.update_available.connect(self._show_dialog)

    def check_in_background(self) -> None:
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self) -> None:
        import urllib.request, json as _json
        try:
            with urllib.request.urlopen(
                f"http://{self._host}:{self._port}/version", timeout=5
            ) as r:
                data = _json.loads(r.read())
            latest    = data.get("client", "0.0.0")
            available = data.get("client_available", False)
            if available and _ver_tuple(latest) > _ver_tuple(self._current):
                self.update_available.emit(
                    self._current, latest,
                    f"http://{self._host}:{self._port}/update/client",
                )
        except Exception:
            pass

    def _show_dialog(self, current: str, latest: str, url: str) -> None:
        UpdateDialog(current, latest, url).exec()


# ── Discord login ─────────────────────────────────────────────────────────────

class LoginDialog(QDialog):
    """OAuth-вход через Discord: открывает браузер и поллит /auth/poll.

    Поллинг — QTimer каждые 2 с + urllib в daemon-потоке (cf. _UpdateChecker),
    UI не блокируется. Таймаут 180 с. «Отмена» = reject → выход из приложения.
    """

    _poll_done = pyqtSignal(dict)   # daemon thread → UI thread (queued)

    def __init__(self, host: str, port: int, parent=None) -> None:
        super().__init__(parent)
        self._host     = host
        self._port     = port
        self._state    = ""
        self._deadline = 0.0
        self._polling  = False

        self.result_token    = ""
        self.result_user_id  = ""
        self.result_username = ""

        self.setWindowTitle("Medral — вход")
        self.setFixedSize(420, 300)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._poll_tick)
        self._poll_done.connect(self._on_poll_done)

        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 32, 36, 28)
        root.setSpacing(0)

        logo = QLabel("♪  MEDRAL")
        logo.setObjectName("logo")
        logo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(logo)
        root.addSpacing(16)

        sub = QLabel("Войди через Discord, чтобы управлять ботом")
        sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#7d8590; font-size:12px;")
        root.addWidget(sub)
        root.addSpacing(22)

        self._login_btn = QPushButton("Войти через Discord")
        self._login_btn.setObjectName("primaryBtn")
        self._login_btn.setDefault(True)
        self._login_btn.clicked.connect(self._start_login)
        root.addWidget(self._login_btn)
        root.addSpacing(8)

        # Для тех, у кого нужный Discord-аккаунт в другом браузере:
        # копирует ссылку входа вместо открытия браузера по умолчанию.
        self._copy_btn = QPushButton("Скопировать ссылку для другого браузера")
        self._copy_btn.setStyleSheet(
            "QPushButton { background:transparent; border:none; color:#6b6b8a;"
            " font-size:11px; text-decoration:underline; }"
            "QPushButton:hover { color:#A78BFA; }"
        )
        self._copy_btn.clicked.connect(self._copy_login_link)
        root.addWidget(self._copy_btn)
        root.addSpacing(10)

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#6b6b8a; font-size:11px;")
        root.addWidget(self._status)
        root.addStretch()

        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        root.addWidget(cancel)

    # ── login flow ────────────────────────────────────────────────────────

    def _begin(self, open_browser: bool) -> None:
        self._state    = secrets.token_urlsafe(24)
        self._deadline = time.monotonic() + 180
        self._login_btn.setEnabled(False)
        url = f"http://{self._host}:{self._port}/auth/login?state={self._state}"
        if open_browser:
            self._status.setText("Открыл браузер — подтверди вход и вернись сюда…")
            webbrowser.open(url)
        else:
            QApplication.clipboard().setText(url)
            self._status.setText(
                "Ссылка скопирована — вставь её в браузер с нужным "
                "аккаунтом Discord и подтверди вход"
            )
        self._timer.start()

    def _start_login(self) -> None:
        self._begin(open_browser=True)

    def _copy_login_link(self) -> None:
        self._begin(open_browser=False)

    def _fail(self, message: str) -> None:
        self._status.setText(message)
        self._login_btn.setEnabled(True)

    def _poll_tick(self) -> None:
        if time.monotonic() >= self._deadline:
            self._timer.stop()
            self._fail("Не дождался входа, попробуй ещё раз")
            return
        if self._polling:
            return
        self._polling = True
        threading.Thread(
            target=self._poll_once, args=(self._state,), daemon=True
        ).start()

    def _poll_once(self, state: str) -> None:
        import urllib.request, urllib.error, json as _json
        try:
            with urllib.request.urlopen(
                f"http://{self._host}:{self._port}/auth/poll?state={state}", timeout=5
            ) as r:
                data = _json.loads(r.read())
        except urllib.error.HTTPError as e:
            # 404 = state неизвестен/протух (например, сервер перезапустился)
            # — ждать дальше бессмысленно
            data = {"status": "expired"} if e.code == 404 else {}
        except Exception:
            data = {}   # сеть — просто ждём следующий тик
        self._poll_done.emit(data if isinstance(data, dict) else {})

    def _on_poll_done(self, data: dict) -> None:
        self._polling = False
        if not self._timer.isActive():
            return   # уже таймаут или отмена
        if data.get("status") == "expired":
            self._timer.stop()
            self._fail("Сессия входа устарела — нажми кнопку ещё раз")
            return
        if data.get("status") == "ok" and data.get("token"):
            self._timer.stop()
            self.result_token    = data["token"]
            self.result_user_id  = str(data.get("user_id", ""))
            self.result_username = data.get("username", "")
            self.accept()

    def reject(self) -> None:
        self._timer.stop()
        super().reject()

    # frameless drag (как у ConnectDialog)
    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = ev.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, ev) -> None:
        if ev.buttons() == Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(ev.globalPosition().toPoint() - self._drag_pos)


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

def _load_fonts() -> None:
    """Try to load Syne + DM Sans from ~/.medral/fonts/ if present."""
    from PyQt6.QtGui import QFontDatabase
    fonts_dir = Path.home() / ".medral" / "fonts"
    if fonts_dir.is_dir():
        for f in fonts_dir.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(f))


def _install_excepthook() -> None:
    """Log unhandled slot exceptions instead of letting PyQt6 abort the app.

    Without a custom excepthook PyQt6 calls qFatal() on any Python exception
    that escapes a slot — the process dies with 0xc0000409 and no trace.
    """
    import traceback
    from datetime import datetime
    log_file = Path.home() / ".medral" / "client.log"

    def hook(exc_type, exc_value, exc_tb):
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] Unhandled exception:\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except Exception:
            pass
        traceback.print_exception(exc_type, exc_value, exc_tb)

    sys.excepthook = hook


def main() -> None:
    _install_excepthook()
    app = QApplication(sys.argv)
    app.setApplicationName("Medral")
    app.setStyleSheet(STYLESHEET)

    _load_fonts()
    app.setFont(QFont("DM Sans", 10))

    cfg   = _load_config()
    host  = cfg.get("host", DEFAULT_HOST)
    port  = cfg.get("port", DEFAULT_PORT)
    token = cfg.get("token") or None

    client = ApiClient(host, port)
    client.set_token(token)
    client.start()

    window = MainWindow(client)

    def _show_login() -> bool:
        """Модальный вход через Discord. Отмена = выход из приложения."""
        c   = _load_config()   # host/port могли смениться через «Change server»
        dlg = LoginDialog(
            c.get("host", DEFAULT_HOST), c.get("port", DEFAULT_PORT),
            parent=window if window.isVisible() else None,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            c["token"]    = dlg.result_token
            c["username"] = dlg.result_username
            _save_config(c)
            client.set_token(dlg.result_token)
            window.set_username(dlg.result_username)
            client.fetch_guilds()
            return True
        QApplication.quit()
        return False

    window.set_login_handler(_show_login)

    if token is None:
        # входим ДО показа главного окна (request_login → guard от повторов)
        if not window.request_login():
            client.stop()
            sys.exit(0)
    else:
        window.set_username(cfg.get("username", ""))

    splash = SplashScreen()
    splash.show()

    def _on_splash_done() -> None:
        window.show()
        QTimer.singleShot(800, client.fetch_guilds)
        if token is not None:
            # валидация сохранённого токена в фоне; при 401 → auth_required
            QTimer.singleShot(1200, client.auth_me)

    splash.closed.connect(_on_splash_done)

    checker = _UpdateChecker(host, port, CLIENT_VERSION)   # keep a reference alive
    QTimer.singleShot(3500, checker.check_in_background)

    ret = app.exec()
    client.stop()
    sys.exit(ret)


if __name__ == "__main__":
    main()
