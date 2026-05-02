STYLESHEET = """
/* ── Base ─────────────────────────────────────────────────────────── */
QWidget {
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
    color: #1A1D23;
    background: transparent;
}

/* ── Transparent containers (explicit opt-in only) ────────────────── */
QStackedWidget, QScrollArea > QWidget > QWidget {
    background: transparent;
}

/* ── Main container (QFrame inside transparent top window) ────────── */
#mainWindow {
    background: #F0F2F5;
    border: 1px solid #D1D5DB;
    border-radius: 12px;
}
#chatArea {
    background: #F0F2F5;
}

/* ── Title bar ────────────────────────────────────────────────────── */
#titleBar {
    background: #FFFFFF;
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
    border-bottom: 1px solid #E5E7EB;
}
#titleLabel {
    font-size: 14px;
    font-weight: 600;
    color: #1A1D23;
}

/* ── Session panel ────────────────────────────────────────────────── */
#sessionPanel {
    background: #FFFFFF;
    border-right: 1px solid #E5E7EB;
}
#panelTitle {
    font-size: 12px;
    font-weight: 600;
    color: #9CA3AF;
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
    color: #4B5563;
    font-size: 12px;
}
#sessionList::item:selected {
    background: #E8F4FD;
    color: #1A1D23;
}
#sessionList::item:hover:!selected {
    background: #F3F4F6;
}

/* ── Chat scroll area ─────────────────────────────────────────────── */
#chatScroll {
    border: none;
    background: #F0F2F5;
}
#chatScroll QScrollBar:vertical {
    width: 4px;
    background: transparent;
}
#chatScroll QScrollBar::handle:vertical {
    background: #D1D5DB;
    border-radius: 2px;
    min-height: 20px;
}
#chatScroll QScrollBar::handle:vertical:hover {
    background: #9CA3AF;
}

/* ── Message bubbles ──────────────────────────────────────────────── */
#userMessage {
    background: #E8F4FD;
    border-radius: 14px;
    border-top-right-radius: 4px;
    margin-left: 40px;
}
#aiMessage {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 14px;
    border-top-left-radius: 4px;
    margin-right: 40px;
}
#userLabel {
    font-size: 11px;
    font-weight: 600;
    color: #5B9BD5;
}
#aiLabel {
    font-size: 11px;
    font-weight: 600;
    color: #34D399;
}
#userBubble, #aiBubble {
    color: #1A1D23;
    font-size: 13px;
    line-height: 1.6;
    background: transparent;
    border: none;
}

/* ── Tool card ────────────────────────────────────────────────────── */
#toolCard {
    background: #F9FAFB;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    margin-top: 4px;
}
#detailLabel {
    font-size: 11px;
    color: #9CA3AF;
    font-weight: 600;
}
#detailText {
    background: #F3F4F6;
    color: #4B5563;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 11px;
}

/* ── Input area ───────────────────────────────────────────────────── */
#inputWidget {
    background: #FFFFFF;
    border-top: 1px solid #E5E7EB;
    border-bottom-left-radius: 12px;
    border-bottom-right-radius: 12px;
}
#inputEdit {
    background: #F3F4F6;
    color: #1A1D23;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 13px;
}
#inputEdit:focus {
    border-color: #5B9BD5;
    background: #FFFFFF;
}

/* ── Buttons ──────────────────────────────────────────────────────── */
#sendBtn {
    background: #5B9BD5;
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    font-weight: 600;
    font-size: 13px;
    padding: 6px 12px;
}
#sendBtn:hover  { background: #7DB9DE; }
#sendBtn:pressed{ background: #4A8BC5; }
#sendBtn:disabled {
    background: #D1D5DB;
    color: #9CA3AF;
}

#iconBtn {
    background: transparent;
    color: #6B7280;
    border: none;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 500;
    padding: 0 4px;
}
#iconBtn:hover  { background: #F3F4F6; color: #1A1D23; }
#iconBtn:pressed{ background: #E5E7EB; }

#closeBtn {
    background: transparent;
    color: #9CA3AF;
    border: none;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 600;
    padding: 0 4px;
}
#closeBtn:hover  { background: #F87171; color: #FFFFFF; }

/* ── New session button ───────────────────────────────────────────── */
#newSessionBtn {
    background: #F3F4F6;
    color: #5B9BD5;
    border: none;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 600;
    padding: 0 8px;
}
#newSessionBtn:hover  { background: #E5E7EB; color: #4A8BC5; }
#newSessionBtn:pressed{ background: #D1D5DB; }

/* ── Toggle button (tool card expand/collapse) ─────────────────────── */
#toggleBtn {
    background: #F3F4F6;
    color: #5B9BD5;
    border: none;
    border-radius: 4px;
    font-size: 11px;
    padding: 2px 8px;
}
#toggleBtn:hover { background: #E5E7EB; }

/* ── Dialogs ──────────────────────────────────────────────────────── */
QDialog {
    background: #FFFFFF;
}
QLabel { background: transparent; }
QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QComboBox {
    background: #F9FAFB;
    color: #1A1D23;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 6px 10px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #5B9BD5;
    background: #FFFFFF;
}
QTabWidget::pane {
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    background: #FFFFFF;
}
QTabBar::tab {
    background: #F3F4F6;
    color: #9CA3AF;
    padding: 6px 16px;
    border-radius: 8px 8px 0 0;
}
QTabBar::tab:selected {
    background: #FFFFFF;
    color: #1A1D23;
}
QPushButton {
    background: #F3F4F6;
    color: #1A1D23;
    border: none;
    border-radius: 8px;
    padding: 6px 14px;
}
QPushButton:hover  { background: #E5E7EB; }
QPushButton:pressed{ background: #D1D5DB; }
QDialogButtonBox QPushButton {
    min-width: 70px;
    background: #5B9BD5;
    color: #FFFFFF;
}
QDialogButtonBox QPushButton:hover { background: #7DB9DE; }
QCheckBox { spacing: 6px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #D1D5DB;
    border-radius: 4px;
    background: #FFFFFF;
}
QCheckBox::indicator:checked {
    background: #5B9BD5;
    border-color: #5B9BD5;
}
QTableWidget {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    gridline-color: #F3F4F6;
    color: #1A1D23;
}
QTableWidget::item { padding: 6px 8px; }
QTableWidget::item:selected { background: #E8F4FD; color: #1A1D23; }
QHeaderView::section {
    background: #F9FAFB;
    color: #6B7280;
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid #E5E7EB;
    font-size: 12px;
    font-weight: 600;
}
QScrollBar:vertical {
    width: 6px;
    background: transparent;
}
QScrollBar::handle:vertical {
    background: #D1D5DB;
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #9CA3AF; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

/* ── Typing indicator ─────────────────────────────────────────────── */
#typingLabel {
    color: #9CA3AF;
    font-size: 12px;
    font-style: italic;
}

/* ── Tray / context menu ──────────────────────────────────────────── */
QMenu {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 6px 4px;
    color: #1A1D23;
}
QMenu::item {
    padding: 7px 28px 7px 14px;
    border-radius: 6px;
    color: #1A1D23;
    background: transparent;
}
QMenu::item:selected {
    background: #F3F4F6;
    color: #1A1D23;
}
QMenu::item:disabled {
    color: #D1D5DB;
}
QMenu::separator {
    height: 1px;
    background: #E5E7EB;
    margin: 4px 10px;
}

/* ── Notes dialog ─────────────────────────────────────────────────── */
#noteListPanel {
    background: #FFFFFF;
    border-radius: 8px 0 0 8px;
}
#noteList {
    background: transparent;
    border: none;
    outline: none;
}
#noteList::item {
    padding: 8px 10px;
    border-radius: 6px;
    color: #4B5563;
    font-size: 12px;
    line-height: 1.4;
}
#noteList::item:selected {
    background: #E8F4FD;
    color: #1A1D23;
}
#noteList::item:hover:!selected {
    background: #F3F4F6;
}
#noteTitleEdit {
    background: #F9FAFB;
    color: #1A1D23;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 14px;
    font-weight: 600;
}
#noteTitleEdit:focus {
    border-color: #5B9BD5;
    background: #FFFFFF;
}
#noteContentEdit {
    background: #F9FAFB;
    color: #1A1D23;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
}
#noteContentEdit:focus {
    border-color: #5B9BD5;
    background: #FFFFFF;
}
#noteToolBtn {
    background: #F3F4F6;
    color: #1A1D23;
    border: none;
    border-radius: 8px;
    padding: 5px 14px;
    font-size: 12px;
}
#noteToolBtn:hover  { background: #E5E7EB; color: #1A1D23; }
#noteToolBtn:pressed { background: #D1D5DB; }

/* ── View-switcher buttons in title bar ────────────────────────────── */
#viewBtn {
    background: transparent;
    color: #6B7280;
    border: none;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 500;
}
#viewBtn:hover   { background: #F3F4F6; color: #1A1D23; }
#viewBtn:checked { background: #E8F4FD; color: #5B9BD5; font-weight: 600; }
#viewBtn:checked:hover { background: #D9EDFB; color: #4A8BC5; }

#noteStatusLabel {
    color: #34D399;
    font-size: 11px;
    padding: 0 6px;
}

/* ── Size grip (unused but defined) ────────────────────────────────── */
#sizeGrip {
    background: transparent;
    width: 14px;
    height: 14px;
}
"""
