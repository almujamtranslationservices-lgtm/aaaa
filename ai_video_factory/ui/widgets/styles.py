"""Application-wide dark theme (Qt stylesheet) — modern, flat, accent-driven."""

DARK_STYLESHEET = """
* { outline: none; }

QWidget {
    background-color: #12141a;
    color: #e8eaf2;
    font-size: 14px;
}

QMainWindow, QDialog { background-color: #12141a; }

/* ---------- Sidebar ---------- */
#Sidebar {
    background-color: #0d0f14;
    border-right: 1px solid #23262f;
}
#AppTitle {
    font-size: 19px;
    font-weight: 700;
    color: #ffffff;
    padding: 2px 0 0 0;
}
#AppSubtitle { color: #7d8698; font-size: 12px; }
#SidebarHint { color: #5a6272; font-size: 11px; }

QPushButton#NavButton {
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 10px 14px;
    text-align: left;
    color: #aab3c5;
    font-size: 14px;
}
QPushButton#NavButton:hover { background-color: #191d27; color: #e8eaf2; }
QPushButton#NavButton:checked {
    background-color: #23283a;
    color: #ffffff;
    font-weight: 600;
}

/* ---------- Cards & panels ---------- */
#Card, #ProgressPanel {
    background-color: #1b1e27;
    border: 1px solid #262b38;
    border-radius: 10px;
}
#CardTitle { font-size: 15px; font-weight: 600; color: #f2f4fa; }
#SectionTitle { font-size: 16px; font-weight: 700; color: #ffffff; }
#MutedLabel { color: #8a93a5; font-size: 12px; }
#StatValue { font-size: 22px; font-weight: 700; color: #7cc4ff; }
#HeroTitle { font-size: 26px; font-weight: 800; color: #ffffff; }
#Chip {
    background-color: #1f2b22; color: #7dd87d;
    border: 1px solid #2c4a2f; border-radius: 9px; padding: 3px 10px;
    font-size: 12px; font-weight: 600;
}
#ChipWarn { background-color: #2b2416; color: #ffcf6b; border: 1px solid #4a3d20; }

/* ---------- Inputs ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #161923;
    border: 1px solid #2a2f3d;
    border-radius: 7px;
    padding: 6px 9px;
    selection-background-color: #7c5cff;
    selection-color: #ffffff;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid #7c5cff; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background-color: #1b1e27; border: 1px solid #2a2f3d;
    selection-background-color: #7c5cff; selection-color: #ffffff;
}
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QCheckBox { spacing: 8px; }

/* ---------- Buttons ---------- */
QPushButton {
    background-color: #262b38;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    color: #e8eaf2;
    font-weight: 500;
}
QPushButton:hover { background-color: #323950; }
QPushButton:pressed { background-color: #2a3044; }
QPushButton:disabled { color: #5a6272; background-color: #1c202b; }

QPushButton#PrimaryButton {
    background-color: #7c5cff; color: #ffffff; font-weight: 700;
}
QPushButton#PrimaryButton:hover { background-color: #8f74ff; }
QPushButton#PrimaryButton:pressed { background-color: #6b4de6; }
QPushButton#PrimaryButton:disabled { background-color: #37325a; color: #8681ad; }

QPushButton#DangerButton:hover { background-color: #57303a; color: #ff9d9d; }

/* ---------- Tables & lists ---------- */
QTableWidget, QListView, QListWidget, QTreeView {
    background-color: #161923;
    border: 1px solid #262b38;
    border-radius: 8px;
    gridline-color: #232837;
    alternate-background-color: #191d28;
}
QHeaderView::section {
    background-color: #1b1e27;
    color: #aab3c5;
    border: none;
    border-bottom: 1px solid #2a3140;
    padding: 7px 9px;
    font-weight: 600;
}
QTableWidget::item, QListWidget::item { padding: 5px; }
QTableWidget::item:selected, QListWidget::item:selected, QListView::item:selected {
    background-color: #2f3752; color: #ffffff;
}

/* ---------- Progress ---------- */
QProgressBar {
    background-color: #161923;
    border: 1px solid #2a2f3d;
    border-radius: 7px;
    text-align: center;
    color: #e8eaf2;
    min-height: 18px;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #7c5cff, stop:1 #4cc2ff);
    border-radius: 6px;
}

/* ---------- Group boxes & tabs ---------- */
QGroupBox {
    background-color: #1b1e27;
    border: 1px solid #262b38;
    border-radius: 10px;
    margin-top: 12px;
    padding: 10px 10px 10px 10px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px; top: 0px;
    padding: 0 6px;
    color: #c7cede;
}

/* ---------- Scrollbars ---------- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #2c3242; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #3a4157; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #2c3242; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* ---------- Status bar & messages ---------- */
QStatusBar { background-color: #0d0f14; color: #8a93a5; border-top: 1px solid #23262f; }
QStatusBar::item { border: none; }
QToolTip {
    background-color: #23283a; color: #e8eaf2;
    border: 1px solid #3a4157; padding: 5px 8px; border-radius: 5px;
}
"""
