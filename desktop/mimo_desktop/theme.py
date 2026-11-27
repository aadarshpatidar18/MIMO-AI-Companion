"""One stylesheet, applied at startup. Dark by default: this is a companion that sits next to the
IDE at night, and Qt's default grey is not a design."""
QSS = """
QMainWindow, QDialog { background: #14161a; }
QWidget { color: #e6e8eb; font-size: 13px; }
QTabWidget::pane { border: 1px solid #24272e; border-radius: 8px; }
QTabBar::tab {
    background: #1a1d23; padding: 8px 16px; margin-right: 4px;
    border-top-left-radius: 8px; border-top-right-radius: 8px; color: #9aa3ad;
}
QTabBar::tab:selected { background: #23272f; color: #ffffff; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background: #1a1d23; border: 1px solid #2e3239; border-radius: 6px; padding: 7px;
    selection-background-color: #2f6ef0;
}
QPushButton {
    background: #23272f; border: 1px solid #2e3239; border-radius: 6px;
    padding: 7px 14px;
}
QPushButton:hover { background: #2b3038; }
QPushButton:disabled { color: #6b7480; }
QPushButton#primary { background: #2f6ef0; border-color: #2f6ef0; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #3d79f5; }
QPushButton#danger { background: #b3261e; border-color: #b3261e; color: white; font-weight: 600; }
QPushButton#danger:hover { background: #c9312a; }
QListWidget { background: #1a1d23; border: 1px solid #24272e; border-radius: 8px; }
QListWidget::item { padding: 6px; }
QListWidget::item:selected { background: #23272f; }
QHeaderView::section { background: #1a1d23; border: none; padding: 6px; color: #9aa3ad; }
QTableWidget { background: #1a1d23; border: 1px solid #24272e; border-radius: 8px;
               gridline-color: #24272e; }
QLabel#muted { color: #9aa3ad; }
QLabel#status { padding: 4px 10px; border-radius: 10px; background: #23272f; }
QLabel#statusOnline { padding: 4px 10px; border-radius: 10px; background: #16351f; color: #58d27d; }
QLabel#statusOffline { padding: 4px 10px; border-radius: 10px; background: #3a1a1a; color: #ff8a80; }
"""
