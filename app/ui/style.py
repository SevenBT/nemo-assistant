STYLESHEET = """
/* ── Base ─────────────────────────────────────────────────────────── */
QWidget {
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
    color: #cdd6f4;
}

/* ── Transparent containers (explicit opt-in only) ────────────────── */
QStackedWidget, QScrollArea > QWidget > QWidget {
    background: transparent;
}

/* ── Main container (QFrame inside transparent top window) ────────── */
#mainWindow {
    background: #1e1e2e;
    border: 1px solid #45475a;
    border-radius: 10px;
}
/* chat area filler */
#chatArea {
    background: #1e1e2e;
}

/* ── Title bar ────────────────────────────────────────────────────── */
#titleBar {
    background: #181825;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    border-bottom: 1px solid #313244;
}
#titleLabel {
    font-size: 13px;
    font-weight: 600;
    color: #cdd6f4;
}

/* ── Session panel ────────────────────────────────────────────────── */
#sessionPanel {
    background: #181825;
    border-right: 1px solid #313244;
}
#panelTitle {
    font-size: 12px;
    font-weight: 600;
    color: #6c7086;
    text-transform: uppercase;
    letter-spacing: 1px;
}
#sessionList {
    background: transparent;
    border: none;
    outline: none;
}
#sessionList::item {
    padding: 7px 8px;
    border-radius: 6px;
    color: #bac2de;
    font-size: 12px;
}
#sessionList::item:selected {
    background: #313244;
    color: #cdd6f4;
}
#sessionList::item:hover:!selected {
    background: #27273a;
}

/* ── Chat scroll area ─────────────────────────────────────────────── */
#chatScroll {
    border: none;
    background: #1e1e2e;
}
#chatScroll QScrollBar:vertical {
    width: 4px;
    background: transparent;
}
#chatScroll QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 2px;
    min-height: 20px;
}

/* ── Message bubbles ──────────────────────────────────────────────── */
#userMessage {
    background: #313244;
    border-radius: 10px;
    margin-left: 40px;
}
#aiMessage {
    background: #252538;
    border-radius: 10px;
    margin-right: 40px;
}
#userLabel {
    font-size: 11px;
    font-weight: 600;
    color: #89b4fa;
}
#aiLabel {
    font-size: 11px;
    font-weight: 600;
    color: #a6e3a1;
}
#userBubble, #aiBubble {
    color: #cdd6f4;
    font-size: 13px;
    line-height: 1.5;
    background: transparent;
    border: none;
}

/* ── Tool card ────────────────────────────────────────────────────── */
#toolCard {
    background: #1e1e2e;
    border: 1px solid #45475a;
    border-radius: 8px;
    margin-top: 4px;
}
#detailLabel {
    font-size: 11px;
    color: #6c7086;
    font-weight: 600;
}
#detailText {
    background: #11111b;
    color: #a6adc8;
    border: 1px solid #313244;
    border-radius: 4px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 11px;
}

/* ── Input area ───────────────────────────────────────────────────── */
#inputWidget {
    background: #181825;
    border-top: 1px solid #313244;
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
}
#inputEdit {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 13px;
}
#inputEdit:focus {
    border-color: #89b4fa;
}

/* ── Buttons ──────────────────────────────────────────────────────── */
#sendBtn {
    background: #89b4fa;
    color: #1e1e2e;
    border: none;
    border-radius: 8px;
    font-weight: 600;
    font-size: 13px;
    padding: 6px 12px;
}
#sendBtn:hover  { background: #b4befe; }
#sendBtn:pressed{ background: #74c7ec; }
#sendBtn:disabled { background: #45475a; color: #6c7086; }

#iconBtn {
    background: transparent;
    color: #cdd6f4;
    border: none;
    border-radius: 5px;
    font-size: 12px;
    font-weight: 500;
    padding: 0 4px;
}
#iconBtn:hover  { background: #313244; color: #ffffff; }
#iconBtn:pressed{ background: #45475a; }

#closeBtn {
    background: transparent;
    color: #bac2de;
    border: none;
    border-radius: 5px;
    font-size: 14px;
    font-weight: 600;
    padding: 0 4px;
}
#closeBtn:hover  { background: #f38ba8; color: #1e1e2e; }

/* ── New session button ───────────────────────────────────────────── */
#newSessionBtn {
    background: #313244;
    color: #89b4fa;
    border: none;
    border-radius: 5px;
    font-size: 11px;
    font-weight: 600;
    padding: 0 6px;
}
#newSessionBtn:hover  { background: #45475a; color: #cdd6f4; }
#newSessionBtn:pressed{ background: #585b70; }

/* ── Resize grip ──────────────────────────────────────────────────── */
#sizeGrip {
    background: transparent;
    width: 14px;
    height: 14px;
}

#toggleBtn {
    background: #313244;
    color: #89b4fa;
    border: none;
    border-radius: 4px;
    font-size: 11px;
    padding: 2px 6px;
}
#toggleBtn:hover { background: #45475a; }

/* ── Dialogs ──────────────────────────────────────────────────────── */
QDialog {
    background: #1e1e2e;
}
QLabel { background: transparent; }
QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QComboBox {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 4px 8px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #89b4fa;
}
QTabWidget::pane {
    border: 1px solid #313244;
    border-radius: 6px;
    background: #1e1e2e;
}
QTabBar::tab {
    background: #181825;
    color: #6c7086;
    padding: 6px 16px;
    border-radius: 6px 6px 0 0;
}
QTabBar::tab:selected { background: #313244; color: #cdd6f4; }
QPushButton {
    background: #313244;
    color: #cdd6f4;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
}
QPushButton:hover  { background: #45475a; }
QPushButton:pressed{ background: #585b70; }
QDialogButtonBox QPushButton { min-width: 70px; }
QCheckBox { spacing: 6px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #45475a;
    border-radius: 4px;
    background: #313244;
}
QCheckBox::indicator:checked { background: #89b4fa; border-color: #89b4fa; }
QTableWidget {
    background: #181825;
    border: 1px solid #313244;
    border-radius: 6px;
    gridline-color: #313244;
}
QTableWidget::item { padding: 4px 8px; }
QTableWidget::item:selected { background: #313244; }
QHeaderView::section {
    background: #11111b;
    color: #6c7086;
    padding: 6px 8px;
    border: none;
    font-size: 12px;
    font-weight: 600;
}
QScrollBar:vertical {
    width: 6px;
    background: transparent;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

/* ── Typing indicator ─────────────────────────────────────────────── */
#typingLabel {
    color: #6c7086;
    font-size: 12px;
    font-style: italic;
}

/* ── Tray / context menu (dark theme) ────────────────────────────── */
QMenu {
    background: #1e1e2e;
    border: 1px solid #45475a;
    border-radius: 8px;
    padding: 4px 2px;
    color: #cdd6f4;
}
QMenu::item {
    padding: 7px 28px 7px 14px;
    border-radius: 5px;
    color: #cdd6f4;
    background: transparent;
}
QMenu::item:selected {
    background: #313244;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #585b70;
}
QMenu::separator {
    height: 1px;
    background: #45475a;
    margin: 4px 10px;
}

/* ── Notes dialog ─────────────────────────────────────────────────────── */
#noteListPanel {
    background: #181825;
    border-radius: 6px 0 0 6px;
}
#noteList {
    background: transparent;
    border: none;
    outline: none;
}
#noteList::item {
    padding: 8px 10px;
    border-radius: 6px;
    color: #bac2de;
    font-size: 12px;
    line-height: 1.4;
}
#noteList::item:selected {
    background: #313244;
    color: #cdd6f4;
}
#noteList::item:hover:!selected {
    background: #27273a;
}
#noteTitleEdit {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 14px;
    font-weight: 600;
}
#noteTitleEdit:focus {
    border-color: #89b4fa;
}
#noteContentEdit {
    background: #252538;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 13px;
}
#noteContentEdit:focus {
    border-color: #89b4fa;
}
#noteToolBtn {
    background: #313244;
    color: #cdd6f4;
    border: none;
    border-radius: 6px;
    padding: 5px 14px;
    font-size: 12px;
}
#noteToolBtn:hover  { background: #45475a; color: #ffffff; }
#noteToolBtn:pressed { background: #585b70; }
/* ── View-switcher buttons in title bar ─────────────────────────────── */
#viewBtn {
    background: transparent;
    color: #cdd6f4;
    border: none;
    border-radius: 5px;
}
#viewBtn:hover   { background: #313244; color: #ffffff; }
#viewBtn:checked { background: #313244; color: #89b4fa; }
#viewBtn:checked:hover { background: #45475a; color: #89b4fa; }
#noteStatusLabel {
    color: #a6e3a1;
    font-size: 11px;
    padding: 0 6px;
}
"""
