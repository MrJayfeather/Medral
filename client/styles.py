# Medral design system v2.
# Palette / spacing (4px grid) / radii: 8 small, 12 mini-cards, 16 main cards.
# Headings: Syne. Body: DM Sans (loaded in main._load_fonts, bundled fallback).

BG         = "#06060c"
SURFACE    = "#0e0e1a"
SURFACE2   = "#16162a"
SURFACE_H  = "#1e1e32"   # hover surface
BORDER     = "#2a2a40"
ACCENT     = "#6C63FF"
ACCENT2    = "#A78BFA"
ACCENT_H   = "#8b85ff"
ACCENT_P   = "#5b53e6"
TEXT       = "#e8e8f5"
TEXT_MUTED = "#6b6b8a"
SUCCESS    = "#34d399"
DANGER     = "#f87171"

HEADING_FONT = '"Syne", "DM Sans", "Segoe UI", sans-serif'
BODY_FONT    = '"DM Sans", "Segoe UI", "SF Pro Display", Ubuntu, sans-serif'

STYLESHEET = f"""
/* ─────────────────── base ─────────────────── */
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: {BODY_FONT};
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
    letter-spacing: 0.2px;
}}
QLabel#trackArtist {{
    font-size: 13px;
    color: {TEXT_MUTED};
}}
QLabel#sectionTitle {{
    font-family: {HEADING_FONT};
    font-size: 10px;
    font-weight: 700;
    color: {TEXT_MUTED};
    letter-spacing: 2px;
}}
QLabel#logo {{
    font-family: {HEADING_FONT};
    font-size: 17px;
    font-weight: 700;
    color: {ACCENT};
    background: transparent;
    letter-spacing: 2px;
}}
QLabel#dialogTitle {{
    font-family: {HEADING_FONT};
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 1px;
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
    padding: 7px 16px;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {SURFACE_H}, stop:1 rgba(108,99,255,0.18));
    border-color: {ACCENT};
}}
QPushButton:pressed  {{ background-color: #12121f; border-color: {ACCENT_P}; }}
QPushButton:disabled {{
    color: {TEXT_MUTED};
    background-color: {SURFACE};
    border-color: #1c1c2e;
}}

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
        stop:0 {ACCENT_H}, stop:1 #b9a8ff);
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
QPushButton#connectBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #45deaa, stop:1 #86efc7);
}}

QPushButton#disconnectBtn {{
    background-color: transparent;
    color: {DANGER};
    border: 1px solid rgba(248,113,113,0.55);
    border-radius: 8px;
    padding: 8px;
}}
QPushButton#disconnectBtn:hover {{
    background-color: rgba(248,113,113,0.12);
    border-color: {DANGER};
}}

QPushButton#transportBtn {{
    background-color: transparent;
    border: none;
    border-radius: 20px;
    padding: 8px;
    font-size: 18px;
    min-width: 40px;
    min-height: 40px;
}}
QPushButton#transportBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(108,99,255,0.10), stop:1 rgba(167,139,250,0.22));
}}
QPushButton#transportBtn:pressed {{ background-color: rgba(108,99,255,0.30); }}

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
        stop:0 {ACCENT_H}, stop:1 #b9a8ff);
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
        stop:0 {ACCENT_H}, stop:1 #b9a8ff);
}}

QPushButton#resultPlayBtn {{
    background-color: transparent;
    border: 1px solid {BORDER};
    border-radius: 16px;
    /* no min sizes and zero padding: the inherited QPushButton padding
       (6px 16px) inflated the 32x32 fixed-size button into a wide pill
       and pushed the glyph off-center */
    padding: 0px;
    color: {ACCENT2};
    font-size: 12px;
}}
QPushButton#resultPlayBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(108,99,255,0.12), stop:1 rgba(167,139,250,0.24));
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
QLineEdit:hover {{ border-color: #3a3a5c; }}
QLineEdit:focus {{ border-color: {ACCENT}; background-color: #1a1a2e; }}

/* ─────────────────── sliders ─────────────────── */
QSlider::groove:horizontal {{
    height: 6px;
    background-color: {SURFACE2};
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}, stop:1 {ACCENT2});
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    width: 16px;
    height: 16px;
    background-color: {TEXT};
    border-radius: 8px;
    margin: -5px 0;
}}
QSlider::handle:horizontal:hover   {{ background-color: {ACCENT2}; }}
QSlider::handle:horizontal:pressed {{ background-color: {ACCENT}; }}

/* ─────────────────── scrollbar ─────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 4px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background-color: {BORDER};
    border-radius: 2px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background-color: rgba(108,99,255,0.55); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical  {{ background: transparent; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 4px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background-color: {BORDER};
    border-radius: 2px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background-color: rgba(108,99,255,0.55); }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

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
    padding: 6px 12px;
    color: {TEXT};
    min-width: 140px;
}}
QComboBox:hover {{ border-color: {ACCENT}; background-color: {SURFACE_H}; }}
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
    border-radius: 8px;
    padding: 4px;
    selection-background-color: rgba(108,99,255,0.2);
    color: {TEXT};
    outline: none;
}}

/* ─────────────────── frames ─────────────────── */
QFrame#leftPanel {{
    background-color: {SURFACE};
    border-right: 1px solid #1c1c2e;
}}
QFrame#topBar {{
    background-color: rgba(10,10,18,0.97);
    border-bottom: 1px solid #1c1c2e;
}}
QFrame#playerCard {{
    background-color: rgba(14,14,26,0.88);
    border-radius: 16px;
    border: 1px solid {BORDER};
}}
QFrame#searchDropdown {{
    background-color: rgba(10, 10, 20, 0.97);
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame#searchResultRow {{
    background-color: {SURFACE2};
    border-radius: 12px;
    border: 1px solid transparent;
}}
QFrame#searchResultRow:hover {{
    border-color: {ACCENT};
    background-color: rgba(108,99,255,0.07);
}}
QFrame#divider {{
    background-color: #1c1c2e;
}}

/* ─────────────────── tooltip ─────────────────── */
QToolTip {{
    background-color: {SURFACE_H};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px 10px;
    font-size: 11px;
}}

/* ─────────────────── status bar ─────────────────── */
QStatusBar {{
    background-color: rgba(10,10,18,0.97);
    color: {TEXT_MUTED};
    border-top: 1px solid #1c1c2e;
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
    background-color: #1c1c2e;
    height: 1px;
}}
QSplitter::handle:horizontal {{
    background-color: #1c1c2e;
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
    border-radius: 6px;
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
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}, stop:1 {ACCENT2});
    border-radius: 3px;
}}
"""
