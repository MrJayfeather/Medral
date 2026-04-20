BG          = "#0d1117"
SURFACE     = "#161b22"
SURFACE2    = "#21262d"
BORDER      = "#30363d"
ACCENT      = "#58a6ff"
ACCENT_HOV  = "#79b8ff"
ACCENT_PRE  = "#388bfd"
TEXT        = "#e6edf3"
TEXT_MUTED  = "#7d8590"
SUCCESS     = "#3fb950"
DANGER      = "#f85149"

STYLESHEET = f"""
/* ───────────────── base ───────────────── */
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: "Segoe UI", "SF Pro Display", Ubuntu, sans-serif;
    font-size: 13px;
    border: none;
    outline: none;
}}
QMainWindow, QDialog {{
    background-color: {BG};
}}

/* ───────────────── labels ───────────────── */
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
    letter-spacing: 1px;
}}
QLabel#dialogTitle {{
    font-size: 20px;
    font-weight: 700;
}}
QLabel#logo {{
    font-size: 16px;
    font-weight: 700;
    color: {ACCENT};
    background: transparent;
}}
QLabel#timeLabel {{
    font-size: 11px;
    color: {TEXT_MUTED};
    background: transparent;
}}

/* ───────────────── buttons ───────────────── */
QPushButton {{
    background-color: {SURFACE2};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 16px;
}}
QPushButton:hover  {{ background-color: #2d333b; border-color: {ACCENT}; }}
QPushButton:pressed {{ background-color: #1c2128; }}
QPushButton:disabled {{ color: {TEXT_MUTED}; border-color: {BORDER}; }}

QPushButton#primaryBtn {{
    background-color: {ACCENT};
    color: {BG};
    border: none;
    font-weight: 700;
    padding: 9px 22px;
    border-radius: 6px;
}}
QPushButton#primaryBtn:hover   {{ background-color: {ACCENT_HOV}; }}
QPushButton#primaryBtn:pressed {{ background-color: {ACCENT_PRE}; }}

QPushButton#connectBtn {{
    background-color: {SUCCESS};
    color: {BG};
    border: none;
    font-weight: 700;
    border-radius: 6px;
    padding: 8px;
}}
QPushButton#connectBtn:hover {{ background-color: #56d364; }}

QPushButton#disconnectBtn {{
    background-color: transparent;
    color: {DANGER};
    border: 1px solid {DANGER};
    border-radius: 6px;
    padding: 8px;
}}
QPushButton#disconnectBtn:hover {{ background-color: rgba(248,81,73,0.12); }}

QPushButton#transportBtn {{
    background-color: transparent;
    border: none;
    border-radius: 20px;
    padding: 8px;
    font-size: 18px;
    min-width: 40px;
    min-height: 40px;
}}
QPushButton#transportBtn:hover   {{ background-color: {SURFACE2}; }}
QPushButton#transportBtn:pressed {{ background-color: {SURFACE}; }}

QPushButton#playBtn {{
    background-color: {ACCENT};
    color: {BG};
    border: none;
    border-radius: 24px;
    font-size: 18px;
    font-weight: 700;
    min-width: 48px;
    min-height: 48px;
}}
QPushButton#playBtn:hover   {{ background-color: {ACCENT_HOV}; }}
QPushButton#playBtn:pressed {{ background-color: {ACCENT_PRE}; }}

QPushButton#searchBtn {{
    background-color: {ACCENT};
    color: {BG};
    border: none;
    font-weight: 600;
    border-radius: 6px;
    padding: 8px 18px;
}}
QPushButton#searchBtn:hover {{ background-color: {ACCENT_HOV}; }}

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
    background-color: rgba(88,166,255,0.12);
    border-color: {ACCENT};
}}

/* ───────────────── line edit ───────────────── */
QLineEdit {{
    background-color: {SURFACE2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 8px 12px;
    color: {TEXT};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:hover {{ border-color: #484f58; }}

/* ───────────────── sliders ───────────────── */
QSlider::groove:horizontal {{
    height: 4px;
    background-color: {SURFACE2};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background-color: {ACCENT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px;
    height: 14px;
    background-color: {TEXT};
    border-radius: 7px;
    margin: -5px 0;
}}
QSlider::handle:horizontal:hover  {{ background-color: {ACCENT}; }}
QSlider::handle:horizontal:pressed {{ background-color: {ACCENT_PRE}; }}

/* ───────────────── scrollbar ───────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
}}
QScrollBar::handle:vertical {{
    background-color: {BORDER};
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background-color: #484f58; }}
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

/* ───────────────── list widget ───────────────── */
QListWidget {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget::item {{
    padding: 0;
    border-radius: 6px;
    margin: 1px 4px;
    color: {TEXT};
}}
QListWidget::item:hover    {{ background-color: {SURFACE2}; }}
QListWidget::item:selected {{ background-color: rgba(88,166,255,0.14); }}

/* ───────────────── combo box ───────────────── */
QComboBox {{
    background-color: {SURFACE2};
    border: 1px solid {BORDER};
    border-radius: 6px;
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
    selection-background-color: rgba(88,166,255,0.2);
    color: {TEXT};
    outline: none;
    border-radius: 4px;
}}

/* ───────────────── frames ───────────────── */
QFrame#leftPanel {{
    background-color: {SURFACE};
    border-right: 1px solid {BORDER};
}}
QFrame#topBar {{
    background-color: {SURFACE};
    border-bottom: 1px solid {BORDER};
}}
QFrame#playerCard {{
    background-color: {SURFACE};
    border-radius: 12px;
    border: 1px solid {BORDER};
}}
QFrame#searchResultRow {{
    background-color: {SURFACE2};
    border-radius: 8px;
    border: 1px solid transparent;
}}
QFrame#searchResultRow:hover {{
    border-color: {ACCENT};
    background-color: rgba(88,166,255,0.05);
}}
QFrame#divider {{
    background-color: {BORDER};
}}

/* ───────────────── tooltip ───────────────── */
QToolTip {{
    background-color: {SURFACE2};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 8px;
}}

/* ───────────────── status bar ───────────────── */
QStatusBar {{
    background-color: {SURFACE};
    color: {TEXT_MUTED};
    border-top: 1px solid {BORDER};
    font-size: 11px;
}}

/* ───────────────── dialog ───────────────── */
QDialog {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

/* ───────────────── splitter ───────────────── */
QSplitter::handle:vertical {{
    background-color: {BORDER};
    height: 1px;
}}
QSplitter::handle:horizontal {{
    background-color: {BORDER};
    width: 1px;
}}

/* ───────────────── menu ───────────────── */
QMenu {{
    background-color: {SURFACE2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 16px;
    border-radius: 4px;
    color: {TEXT};
}}
QMenu::item:selected {{ background-color: rgba(88,166,255,0.15); }}
QMenu::separator {{
    height: 1px;
    background-color: {BORDER};
    margin: 4px 8px;
}}
"""
