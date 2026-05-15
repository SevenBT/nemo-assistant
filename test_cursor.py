"""Diagnostic: test what controls QTextEdit cursor color."""
import sys
from PyQt6.QtWidgets import QApplication, QTextEdit, QVBoxLayout, QWidget
from PyQt6.QtGui import QPalette, QColor, QTextCharFormat
from PyQt6.QtCore import QTimer

app = QApplication(sys.argv)

# Apply theme like the real app
from app.ui.style import apply_theme
qss = apply_theme("morning")

win = QWidget()
win.setStyleSheet(qss)
layout = QVBoxLayout(win)

# Test 1: plain QTextEdit with no special styling
edit1 = QTextEdit()
edit1.setPlaceholderText("Test 1: no styling")
layout.addWidget(edit1)

# Test 2: widget's own stylesheet
edit2 = QTextEdit()
edit2.setPlaceholderText("Test 2: self.setStyleSheet color black")
edit2.setStyleSheet("color: black;")
layout.addWidget(edit2)

# Test 3: palette on viewport
edit3 = QTextEdit()
edit3.setPlaceholderText("Test 3: viewport palette black")
pal = edit3.viewport().palette()
pal.setColor(QPalette.ColorRole.Text, QColor("black"))
edit3.viewport().setPalette(pal)
layout.addWidget(edit3)

# Test 4: char format
edit4 = QTextEdit()
edit4.setPlaceholderText("Test 4: currentCharFormat black")
fmt = QTextCharFormat()
fmt.setForeground(QColor("black"))
edit4.setCurrentCharFormat(fmt)
layout.addWidget(edit4)

# Test 5: setTextColor
edit5 = QTextEdit()
edit5.setPlaceholderText("Test 5: setTextColor black")
edit5.setTextColor(QColor("black"))
layout.addWidget(edit5)

win.setWindowTitle("Cursor Color Test")
win.resize(400, 500)
win.show()

# Auto-close after 30 seconds
QTimer.singleShot(30000, app.quit)
app.exec()
