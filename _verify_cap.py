import sys
from PyQt6.QtWidgets import QApplication
from PyQt6 import sip

app = QApplication(sys.argv)
from app.ui.hotkey_settings_widget import _Capture

# 1. 存活对象正常 emit
cap = _Capture()
received = []
cap.finished.connect(lambda s: received.append(s))
cap._safe_emit("ctrl+alt+x")
app.processEvents()
print("alive emit received:", received)

# 2. 已删除对象 safe_emit 不崩
cap2 = _Capture()
sip.delete(cap2)
print("cap2 deleted:", sip.isdeleted(cap2))
cap2._safe_emit("should-not-crash")  # 不应抛异常
print("deleted emit handled OK")
