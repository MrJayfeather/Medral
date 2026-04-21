BG         = "#06060c"
SURFACE    = "#0e0e1a"
SURFACE2   = "#16162a"
BORDER     = "#2a2a40"
ACCENT     = "#6C63FF"
ACCENT2    = "#A78BFA"
ACCENT_H   = "#8b85ff"
ACCENT_P   = "#5b53e6"
TEXT       = "#e8e8f5"
TEXT_MUTED = "#6b6b8a"
SUCCESS    = "#34d399"
DANGER     = "#f87171"

STYLESHEET = f"""
/* ─────────────────── base ─────────────────── */
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: "DM Sans", "Segoe UI", "SF Pro Display", Ubuntu, sans-serif;
    font-size: 13px;
    border: none;
    outline: none;
}}
QMainWindow, QDialog {{
    background-color: {BG};
}}

/* ─────────────────── labels ─────────────────── */
QLabel {{
    background: transparent;
    color: {TEXT};
}}
QLabel#trackTitle {{
    font-size: 17px;
    font-weight: 700;
}}
QLabel#trackArtist {{
    font-size: 13px;
    color: {TEXT_MUTED};
}}
QLabel#sectionTitle {{
    font-size: 10px;
    font-weight: 700;
    color: {TEXT_MUTED};
    letter-spacing: 1.5px;
}}
QLabel#logo {{
    font-size: 17px;
    font-weight: 700;
    color: {ACCENT};
    background: transparent;
    letter-spacing: 2px;
}}
QLabel#timeLabel {{
    font-size: 11px;
    color: {TEXT_MUTED};
    background: transparent;
}}

/* ─────────────────── buttons ─────────────────── */
QPushButton {{
    background-color: {SURFACE2};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 16px;
}}
QPushButton:hover  {{ background-color: #1e1e32; border-color: {ACCENT}; }}
QPushButton:pressed {{ background-color: #12121f; }}
QPushButton:disabled {{ color: {TEXT_MUTED}; border-color: {BORDER}; }}

QPushButton#primaryBtn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}, stop:1 {ACCENT2});
    color: #ffffff;
    border: none;
    font-weight: 700;
    padding: 9px 22px;
    border-radius: 8px;
}}
QPushButton#primaryBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT_H}, stop:1 {ACCENT2});
}}
QPushButton#primaryBtn:pressed {{ background: {ACCENT_P}; }}

QPushButton#connectBtn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {SUCCESS}, stop:1 #6ee7b7);
    color: #062613;
    border: none;
    font-weight: 700;
    border-radius: 8px;
    padding: 8px;
}}
QPushButton#connectBtn:hover {{ background: #6ee7b7; }}

QPushButton#disconnectBtn {{
    background-color: transparent;
    color: {DANGER};
    border: 1px solid {DANGER};
    border-radius: 8px;
    padding: 8px;
}}
QPushButton#disconnectBtn:hover {{ background-color: rgba(248,113,113,0.12); }}

QPushButton#transportBtn {{
    background-color: transparent;
    border: none;
    border-radius: 20px;
    padding: 8px;
    font-size: 18px;
    min-width: 40px;
    min-height: 40px;
}}
QPushButton#transportBtn:hover   {{ background-color: rgba(108,99,255,0.15); }}
QPushButton#transportBtn:pressed {{ background-color: rgba(108,99,255,0.28); }}

QPushButton#playBtn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {ACCENT}, stop:1 {ACCENT2});
    color: #ffffff;
    border: none;
    border-radius: 24px;
    font-size: 18px;
    font-weight: 700;
    min-width: 48px;
    min-height: 48px;
}}
QPushButton#playBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {ACCENT_H}, stop:1 {ACCENT2});
}}
QPushButton#playBtn:pressed {{ background: {ACCENT_P}; }}

QPushButton#searchBtn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}, stop:1 {ACCENT2});
    color: #ffffff;
    border: none;
    font-weight: 600;
    border-radius: 8px;
    padding: 8px 18px;
}}
QPushButton#searchBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT_H}, stop:1 {ACCENT2});
}}

QPushButton#resultPlayBtn {{
    background-color: transparent;
    border: 1px solid {BORDER};
    border-radius: 16px;
    min-width: 32px;
    min-height: 32px;
    color: {ACCENT};
    font-size: 12px;
}}
QPushButton#resultPlayBtn:hover {{
    background-color: rgba(108,99,255,0.15);
    border-color: {ACCENT};
}}

/* ─────────────────── line edit ─────────────────── */
QLineEdit {{
    background-color: {SURFACE2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    color: {TEXT};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{ border-color: {ACCENT}; background-color: #1a1a2e; }}
QLineEdit:hover {{ border-color: #3a3a5c; }}

/* ─────────────────── sliders ─────────────────── */
QSlider::groove:horizontal {{
    height: 4px;
    background-color: {SURFACE2};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}, stop:1 {ACCENT2});
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px;
    height: 14px;
    background-color: {TEXT};
    border-radius: 7px;
    margin: -5px 0;
}}
QSlider::handle:horizontal:hover  {{ background-color: {ACCENT2}; }}
QSlider::handle:horizontal:pressed {{ background-color: {ACCENT}; }}

/* ─────────────────── scrollbar ─────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
}}
QScrollBar::handle:vertical {{
    background-color: {BORDER};
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background-color: rgba(108,99,255,0.5); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
}}
QScrollBar::handle:horizontal {{
    background-color: {BORDER};
    border-radius: 3px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ─────────────────── list widget ─────────────────── */
QListWidget {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget::item {{
    padding: 0;
    border-radius: 8px;
    margin: 1px 4px;
    color: {TEXT};
}}
QListWidget::item:hover    {{ background-color: rgba(108,99,255,0.08); }}
QListWidget::item:selected {{ background-color: rgba(108,99,255,0.16); }}

/* ─────────────────── combo box ─────────────────── */
QComboBox {{
    background-color: {SURFACE2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px 10px;
    color: {TEXT};
    min-width: 140px;
}}
QComboBox:hover {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid {TEXT_MUTED};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE2};
    border: 1px solid {BORDER};
    selection-background-color: rgba(108,99,255,0.2);
    color: {TEXT};
    outline: none;
    border-radius: 4px;
}}

/* ─────────────────── frames ─────────────────── */
QFrame#leftPanel {{
    background-color: {SURFACE};
    border-right: 1px solid {BORDER};
}}
QFrame#topBar {{
    background-color: rgba(14,14,26,0.97);
    border-bottom: 1px solid {BORDER};
}}
QFrame#playerCard {{
    background-color: rgba(14,14,26,0.85);
    border-radius: 16px;
    border: 1px solid {BORDER};
}}
QFrame#searchResultRow {{
    background-color: {SURFACE2};
    border-radius: 10px;
    border: 1px solid transparent;
}}
QFrame#searchResultRow:hover {{
    border-color: {ACCENT};
    background-color: rgba(108,99,255,0.07);
}}
QFrame#divider {{
    background-color: {BORDER};
}}

/* ─────────────────── tooltip ─────────────────── */
QToolTip {{
    background-color: {SURFACE2};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
}}

/* ─────────────────── status bar ─────────────────── */
QStatusBar {{
    background-color: rgba(14,14,26,0.97);
    color: {TEXT_MUTED};
    border-top: 1px solid {BORDER};
    font-size: 11px;
}}

/* ─────────────────── dialog ─────────────────── */
QDialog {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 16px;
}}

/* ─────────────────── splitter ─────────────────── */
QSplitter::handle:vertical {{
    background-color: {BORDER};
    height: 1px;
}}
QSplitter::handle:horizontal {{
    background-color: {BORDER};
    width: 1px;
}}

/* ─────────────────── menu ─────────────────── */
QMenu {{
    background-color: {SURFACE2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 16px;
    border-radius: 4px;
    color: {TEXT};
}}
QMenu::item:selected {{ background-color: rgba(108,99,255,0.2); }}
QMenu::separator {{
    height: 1px;
    background-color: {BORDER};
    margin: 4px 8px;
}}

/* ─────────────────── progress bar (update dialog) ─────────────────── */
QProgressBar {{
    background-color: {SURFACE2};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}, stop:1 {ACCENT2});
    border-radius: 4px;
}}
"""
