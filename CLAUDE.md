# AI Agent Desktop Assistant

PyQt6 无边框透明浮窗桌面应用。

---

## 自动学习规则

**每当在本项目中遇到新的开发问题并找到解决方案后，必须立即将其追加到本文件末尾。**

追加格式：
```
### [问题简题]
**根本原因**：一句话说明为什么会出错。
**✗ 错误做法**：（可选代码片段）
**✓ 正确做法**：（必须有代码片段或操作步骤）
```

触发条件（满足任意一条即追加）：
- 同一类错误出现超过一次
- 调试时走了弯路，最终找到了非显而易见的正确方案
- PyQt6 / Python / 项目特定的 API 与直觉不符

不追加的内容：可从代码或文档直接查到的常规用法、一次性临时问题。

---

## PyQt6 无边框窗口开发规范

> 本节总结了开发本项目时反复出现的错误模式，每节给出根本原因 + 正确做法。

### 1. 窗口拖动：使用 startSystemMove()

**根本原因**：Python 层计算鼠标偏移再调用 `self.move()` 每帧都走 Python 事件循环，有明显延迟。

```python
# ✗ 错误：Python 计算偏移，有卡顿
def mousePressEvent(self, event):
    self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
def mouseMoveEvent(self, event):
    self.move(event.globalPosition().toPoint() - self._drag_pos)

# ✓ 正确：交给 OS，零延迟
def mousePressEvent(self, event):
    if event.button() == Qt.MouseButton.LeftButton:
        self.windowHandle().startSystemMove()
```

---

### 2. 窗口边框调整大小：QApplication 事件过滤器 + 手动 setGeometry

**根本原因**：
- `MainWindow.mousePressEvent` — 鼠标在子控件上时父窗口收不到事件
- `nativeEvent` + `ctypes.wintypes.MSG.from_address(int(message))` — PyQt6 的 `message` 是 `sip.voidptr`，`from_address` 地址错误，在 `window.show()` 时段错误崩溃
- `windowHandle().startSystemResize()` — 与 `WA_TranslucentBackground` 叠加会产生约 0.5 秒半透明幽灵边框

```python
# ✓ 正确：QApplication 级别过滤器 + 手动 setGeometry
def eventFilter(self, obj, event):
    etype = event.type()
    if etype == QEvent.Type.MouseMove:
        gpos = event.globalPosition().toPoint()
        if self._resize_active:
            if event.buttons() & Qt.MouseButton.LeftButton:
                self._do_manual_resize(gpos)
            else:
                self._resize_active = False
            return True
        # 更新光标...
    elif etype == QEvent.Type.MouseButtonPress:
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._resize_edges(self.mapFromGlobal(gpos))
            if edges is not None:
                self._resize_active = True
                self._resize_start_geo = self.geometry()
                self._resize_start_pos = gpos
                return True
    elif etype == QEvent.Type.MouseButtonRelease:
        if self._resize_active:
            self._resize_active = False
            return True
    return super().eventFilter(obj, event)

# 必须装在 QApplication 上
QApplication.instance().installEventFilter(self)
```

---

### 3. 光标管理：QApplication.setOverrideCursor

**根本原因**：`widget.setCursor()` 只影响该控件自身，子控件会覆盖父控件设置，离开后也不自动复位。

```python
# ✗ 错误：子控件光标不受影响，离开不复位
self.setCursor(Qt.CursorShape.SizeHorCursor)

# ✓ 正确：全局栈，任何控件上都生效
QApplication.setOverrideCursor(shape)      # 压栈
QApplication.changeOverrideCursor(shape)   # 替换当前（不弹栈）
QApplication.restoreOverrideCursor()       # 弹栈（每次 set 必须对应一次 restore）
```

---

### 4. 透明背景：外层 WA_TranslucentBackground + 内层 QFrame

**根本原因**：`QWidget { background: transparent }` 是通配符，会让所有控件背景透明，视觉错乱。

```python
# ✓ 正确结构：
# MainWindow(QWidget) — 设 WA_TranslucentBackground，不写任何 CSS 背景
#   └── QFrame #mainWindow — 写主题背景色和圆角
#       └── 所有业务控件

self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
# CSS 用 ID 选择器精确匹配容器：
# #mainWindow { background: #1e1e2e; border-radius: 10px; }
```

---

### 5. PyQt6 API：空 Edges 标志值用 Qt.Edge(0)

```python
# ✗ 错误：PyQt6 中不存在
edges = Qt.Edges()

# ✓ 正确
edges = Qt.Edge(0)
edges |= Qt.Edge.LeftEdge
```

---

### 6. QSizeGrip 在无边框+充满布局下无效

`QSizeGrip` 依赖系统窗口管理器，设置了 `FramelessWindowHint` 且子控件充满客户区后完全不起作用。改用第 2 条方案。

---

### 7. 事件过滤器必须装在 QApplication 上

```python
# ✗ 错误：只拦截该控件事件，其他子控件漏掉
child_widget.installEventFilter(handler)

# ✓ 正确：捕获应用内所有控件事件
QApplication.instance().installEventFilter(handler)
```

---

## 快速检查清单

- [ ] 拖动用 `windowHandle().startSystemMove()`
- [ ] 调整大小用 `QApplication.installEventFilter` + `setGeometry`
- [ ] 光标用 `QApplication.setOverrideCursor` / `restoreOverrideCursor`
- [ ] 外层 `MainWindow` 只设 `WA_TranslucentBackground`，不写 CSS 背景
- [ ] 内层用具名 `QFrame` + ID 选择器承载主题色
- [ ] 空 Edges 用 `Qt.Edge(0)`
- [ ] 不用 `QSizeGrip`
- [ ] 事件过滤器装在 `QApplication` 上
