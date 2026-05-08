# System Prompt 功能实施总结

## 实施时间
2026-05-08

## 功能概述
为 AI Agent Desktop Assistant 添加全局 System Prompt 设置功能，允许用户在设置界面自定义 AI 行为风格。

---

## 实施范围（P0）

✅ **已完成**：
- 全局 System Prompt 设置
- 设置 UI（新增「模型」Tab）
- 配置存储与读取
- 内置工具说明自动追加
- 恢复默认功能
- 向后兼容处理

❌ **未包含**（后续版本）：
- 预设角色（P1）
- 会话级覆盖（P1）
- 多模型配置（P2）
- 高级参数（已砍掉）

---

## 代码变更

### 新增文件
1. **`app/core/constants.py`** - 常量定义文件
   - `DEFAULT_USER_PROMPT` - 默认用户可编辑部分
   - `BUILTIN_TOOLS_INSTRUCTION` - 内置工具说明
   - **目的**：避免循环导入，集中管理常量

### 修改文件

#### 1. `app/core/config.py`
**变更**：
- 在 `DEFAULT_APP_CONFIG` 中新增 `system_prompt` 字段（默认空字符串）
- 新增 `system_prompt` 属性方法

**代码**：
```python
# 第 36 行
"system_prompt": "",  # 空字符串表示使用 DEFAULT_USER_PROMPT

# 第 126 行
@property
def system_prompt(self) -> str:
    """返回用户自定义的 System Prompt，如果为空则返回空字符串（由调用方处理默认值）"""
    return self._app["api"].get("system_prompt", "")
```

#### 2. `app/ui/main_window.py`
**变更**：
- 移除硬编码的 `SYSTEM_PROMPT`
- 从 `constants.py` 导入常量
- 修改 `_build_api_messages()` 方法，从 config 读取并拼接工具说明

**代码**：
```python
# 第 53 行 - 导入
from app.core.constants import DEFAULT_USER_PROMPT, BUILTIN_TOOLS_INSTRUCTION

# 第 463-470 行 - 消息构建逻辑
def _build_api_messages(self, messages: list[Message]) -> list[dict]:
    # 读取用户自定义的 System Prompt，如果为空则使用默认值
    user_prompt = self._config.system_prompt.strip()
    if not user_prompt:
        user_prompt = DEFAULT_USER_PROMPT

    # 拼接：用户自定义部分 + 内置工具说明
    full_system_prompt = user_prompt + "\n" + BUILTIN_TOOLS_INSTRUCTION

    result = [{"role": "system", "content": full_system_prompt}]
    # ...
```

#### 3. `app/ui/settings_dialog.py`
**变更**：
- 导入 `QPlainTextEdit` 和 `QLabel`
- 从 `constants.py` 导入 `DEFAULT_USER_PROMPT`
- 新增「模型」Tab（在 API 和窗口之间）
- 实现 `_reset_system_prompt()` 方法
- 在 `_load()` 和 `_save()` 中处理 System Prompt

**代码**：
```python
# 第 3-19 行 - 导入
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    # ...
    QLabel,
    QPlainTextEdit,
    # ...
)
from app.core.constants import DEFAULT_USER_PROMPT

# 第 84-108 行 - 新增「模型」Tab
model_w = QWidget()
model_layout = QVBoxLayout(model_w)

prompt_label = QLabel("System Prompt:")
model_layout.addWidget(prompt_label)

self._system_prompt_edit = QPlainTextEdit()
self._system_prompt_edit.setMinimumHeight(200)
self._system_prompt_edit.setPlaceholderText("自定义 AI 行为风格和回复方式…")
model_layout.addWidget(self._system_prompt_edit)

reset_btn = QPushButton("恢复默认")
reset_btn.setFixedWidth(100)
reset_btn.clicked.connect(self._reset_system_prompt)
model_layout.addWidget(reset_btn, alignment=Qt.AlignmentFlag.AlignLeft)

model_layout.addStretch()
tabs.addTab(model_w, "模型")

# 第 193-195 行 - 恢复默认方法
def _reset_system_prompt(self):
    """恢复默认 System Prompt"""
    self._system_prompt_edit.setPlainText(DEFAULT_USER_PROMPT)

# 第 177 行 - 加载逻辑
self._system_prompt_edit.setPlainText(self._config.system_prompt)

# 第 236 行 - 保存逻辑
system_prompt=self._system_prompt_edit.toPlainText().strip(),
```

---

## 数据结构变更

### config/app_config.json
```jsonc
{
  "api": {
    "base_url": "https://api.openai.com/v1",
    "api_key": "",
    "model": "gpt-4o",
    "max_tokens": 4096,
    "temperature": 0.7,
    "system_prompt": ""  // 新增字段
  },
  // ...
}
```

**向后兼容**：
- 旧配置文件无此字段时，`get("system_prompt", "")` 返回空字符串
- 空字符串触发使用 `DEFAULT_USER_PROMPT`

---

## 代码审查结果

### CRITICAL 问题 - 已修复 ✅
**问题**：循环导入风险（`settings_dialog.py` 运行时导入 `main_window.py`）

**解决方案**：
- 创建独立的 `app/core/constants.py` 文件
- 将 `DEFAULT_USER_PROMPT` 和 `BUILTIN_TOOLS_INSTRUCTION` 移到常量文件
- 两个文件都从 `constants.py` 导入

### MEDIUM 问题 - 已知但未修复
1. **缺少输入验证**：无长度限制，超长输入可能导致 API 错误
   - 优先级：P1（第二期优化）
   - 影响：中等，用户可能输入超长内容

2. **System Prompt 拼接格式**：可能产生多余空行
   - 优先级：P2
   - 影响：低，仅浪费少量 token

### LOW 问题 - 已知但未修复
1. **缺少字符计数**：用户无法直观了解当前长度
   - 优先级：P2（用户体验优化）

2. **恢复默认无确认**：可能误操作
   - 优先级：P2（用户体验优化）

---

## 测试计划

详见 `docs/TEST_SYSTEM_PROMPT.md`

### 测试清单
- [ ] 测试 1: 新用户场景（默认行为）
- [ ] 测试 2: 自定义 Prompt 场景
- [ ] 测试 3: 工具调用保护
- [ ] 测试 4: 恢复默认场景
- [ ] 测试 5: 向后兼容场景
- [ ] 测试 6: 边界情况 - 空字符串
- [ ] 测试 7: 边界情况 - 超长输入
- [ ] 测试 8: UI 交互体验

---

## 技术亮点

1. **向后兼容设计**：
   - 使用 `get("system_prompt", "")` 提供默认值
   - 空字符串触发默认 Prompt，无需迁移脚本

2. **工具说明保护**：
   - 用户只能编辑行为风格部分
   - 工具说明自动追加，确保工具调用正常

3. **循环导入规避**：
   - 独立常量文件，避免模块间循环依赖
   - 符合 Python 最佳实践

4. **UI 设计**：
   - 编辑器高度 200px，支持多行编辑
   - 占位符文本清晰
   - 恢复默认按钮位置合理

---

## 用户价值

### 直接价值 ⭐⭐⭐⭐⭐
- 用户可自定义 AI 行为风格（专业/幽默/简洁）
- 体感明显，比调参数直观 100 倍
- 降低使用门槛，无需理解技术参数

### 使用场景
1. **专业场景**：设置为"你是一个专业的技术顾问，回复要严谨准确"
2. **创意场景**：设置为"你是一个富有创意的助手，回复要生动有趣"
3. **简洁场景**：设置为"你是一个简洁的助手，回复要言简意赅"
4. **多语言场景**：设置为"请用英文回复"或其他语言

---

## 下一步计划

### P1 功能（第二期）
1. **预设角色（Prompt 模板）**
   - 内置模板：翻译官、代码助手、写作助手、摘要大师
   - 自定义模板：用户可创建和管理
   - 新建会话时选择预设角色

2. **会话级 System Prompt 覆盖**
   - 每个会话可独立设置 Prompt
   - 优先级：会话级 > 全局级

### P2 功能（第三期）
1. **多模型配置与切换**
   - 支持配置多个模型端点
   - 会话中快速切换模型

### 优化项（可选）
1. 添加 System Prompt 长度验证和警告
2. 添加实时字符计数显示
3. 添加恢复默认确认对话框
4. 规范化 Prompt 拼接逻辑

---

## 相关文档

- **需求文档**：`docs/PRD_MODEL_SETTINGS.md`
- **测试文档**：`docs/TEST_SYSTEM_PROMPT.md`
- **项目概要**：`PROJECT_OVERVIEW.md`
- **开发规范**：`CLAUDE.md`

---

## 提交信息

```bash
git add app/core/constants.py app/core/config.py app/ui/main_window.py app/ui/settings_dialog.py
git commit -m "feat: 添加全局 System Prompt 设置功能

- 新增「模型」Tab，支持自定义 System Prompt
- 内置工具说明自动追加，确保工具调用正常
- 支持恢复默认功能
- 向后兼容旧配置文件
- 创建独立常量文件，避免循环导入

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## 总结

本次实施完成了 P0 功能的全部需求，代码质量经过审查，CRITICAL 问题已修复。功能设计简洁实用，用户价值明显。测试计划完备，待手动测试验证后即可提交。

**实施状态**：✅ 代码完成，⏳ 待测试验证
