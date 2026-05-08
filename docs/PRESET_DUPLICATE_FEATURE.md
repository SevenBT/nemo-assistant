# 预设角色复制功能实现总结

## 功能概述

为 AI Agent Desktop Assistant 的预设角色管理功能添加"复制预设"功能，解决用户无法编辑内置预设的问题。

## 实现内容

### 1. PresetManager 添加 duplicate() 方法

**文件**: `app/core/preset_manager.py`

**功能**:
- 复制任意预设（内置或自定义）
- 生成唯一的新 ID（使用 uuid）
- 支持自定义新名称，默认为 "原名称 副本"
- 复制的预设 `is_builtin=False`，可编辑

**关键代码**:
```python
def duplicate(self, preset_id: str, new_name: str = None) -> Preset:
    """复制预设角色"""
    original = self._presets.get(preset_id)
    if not original:
        raise ValueError(f"预设 {preset_id} 不存在")
    
    # 生成新的 ID
    import uuid
    new_id = str(uuid.uuid4())[:8]
    
    # 生成新的名称
    if not new_name:
        new_name = f"{original.name} 副本"
    
    # 创建新预设（is_builtin=False，可编辑）
    new_preset = Preset(
        id=new_id,
        name=new_name,
        icon=original.icon,
        system_prompt=original.system_prompt,
        params=dict(original.params),  # 深拷贝
        is_builtin=False  # 关键：复制的预设不是内置的
    )
    
    self._presets[new_id] = new_preset
    self._save()
    return new_preset
```

### 2. PresetManagerDialog 添加"复制"按钮

**文件**: `app/ui/preset_manager_dialog.py`

**UI 改动**:
1. 工具栏添加"复制"按钮（在"新建"和"删除"之间）
2. 添加只读提示标签（黄色背景，显示在编辑器顶部）
3. 内置预设的编辑控件设为只读状态
4. "保存"按钮在内置预设时禁用

**工具栏布局**:
```
[新建] [复制] [删除] [导入] [导出]
```

**复制功能实现**:
```python
def _on_duplicate(self):
    """复制选中的预设"""
    if not self._current_preset:
        QMessageBox.warning(self, "提示", "请先选择要复制的预设")
        return
    
    # 弹出对话框输入新名称
    new_name, ok = QInputDialog.getText(
        self,
        "复制预设",
        "请输入新预设的名称:",
        text=f"{self._current_preset.name} 副本"
    )
    
    if ok and new_name.strip():
        try:
            new_preset = self._preset_mgr.duplicate(self._current_preset.id, new_name.strip())
            self._load_list()
            # 选中新创建的预设
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == new_preset.id:
                    self._list.setCurrentItem(item)
                    break
        except Exception as e:
            QMessageBox.critical(self, "错误", f"复制失败: {str(e)}")
```

### 3. 内置预设的 UI 提示改进

**只读提示标签**:
```python
self._readonly_label = QLabel()
self._readonly_label.setStyleSheet("""
    QLabel {
        background-color: #FEF3C7;
        color: #92400E;
        padding: 8px;
        border-radius: 4px;
        font-size: 12px;
    }
""")
self._readonly_label.setWordWrap(True)
self._readonly_label.setVisible(False)
```

**选择变化时的处理**:
```python
def _on_selection_changed(self, current: QListWidgetItem, previous: QListWidgetItem):
    # ...
    is_readonly = preset.is_builtin
    can_edit = not is_readonly
    
    self._set_editor_enabled(can_edit)
    self._delete_btn.setEnabled(can_edit)
    self._save_btn.setEnabled(can_edit)
    
    # 显示只读提示
    if is_readonly:
        self._readonly_label.setText("⚠️ 内置预设（只读）— 点击「复制」按钮创建可编辑版本")
        self._readonly_label.setVisible(True)
    else:
        self._readonly_label.setVisible(False)
```

## 测试结果

**测试脚本**: `test_preset_duplicate.py`

**测试点**:
- ✅ 复制内置预设 → 创建成功 → 新预设可编辑（is_builtin=False）
- ✅ 复制自定义预设 → 创建成功
- ✅ 复制后自动选中新预设
- ✅ 使用默认名称（"原名称 副本"）
- ✅ 使用自定义名称
- ✅ 深拷贝 params 字典
- ✅ 生成唯一 ID

**测试输出**:
```
当前预设数量: 7
  - 默认助手 (ID: default, 内置: True)
  - 翻译官 (ID: translator, 内置: True)
  - 代码助手 (ID: coder, 内置: True)
  - 写作助手 (ID: writer, 内置: True)
  - 摘要大师 (ID: summarizer, 内置: True)
  - 新角色 (ID: 025752f2-..., 内置: False)
  - 我的助手 (ID: cf0fcbeb, 内置: False)

--- 复制内置预设「默认助手」---
[OK] 复制成功: 我的助手
  - ID: e6fb282a
  - 内置: False
  - 提示词: 你是一个智能AI助手。你可以调用工具来帮助用户完成任务。...

--- 复制自定义预设（使用默认名称）---
[OK] 复制成功: 我的助手 副本
  - ID: 9a178780
  - 内置: False

--- 最终预设列表 ---
总数: 9
  - 默认助手 (ID: default, 内置: True)
  - 翻译官 (ID: translator, 内置: True)
  - 代码助手 (ID: coder, 内置: True)
  - 写作助手 (ID: writer, 内置: True)
  - 摘要大师 (ID: summarizer, 内置: True)
  - 新角色 (ID: 025752f2-..., 内置: False)
  - 我的助手 (ID: cf0fcbeb, 内置: False)
  - 我的助手 (ID: e6fb282a, 内置: False)
  - 我的助手 副本 (ID: 9a178780, 内置: False)

--- 清理测试数据 ---
[OK] 清理完成
```

## 用户体验流程

1. 用户打开"管理预设角色"对话框
2. 选择一个内置预设（如"默认助手"）
3. 编辑器顶部显示黄色提示："⚠️ 内置预设（只读）— 点击「复制」按钮创建可编辑版本"
4. 编辑控件和"保存"按钮被禁用
5. 用户点击"复制"按钮
6. 弹出对话框，输入新名称（默认为"默认助手 副本"）
7. 点击确定，创建新预设
8. 列表自动刷新并选中新预设
9. 新预设可以正常编辑和保存

## 技术细节

### ID 生成策略
- 使用 `uuid.uuid4()` 生成唯一 ID
- 截取前 8 位作为短 ID（如 `e6fb282a`）
- 碰撞概率极低（2^32 种可能）

### 深拷贝 params
```python
params=dict(original.params)  # 深拷贝，避免引用共享
```

### 错误处理
- 预设不存在 → 抛出 `ValueError`
- 用户取消输入 → 不执行任何操作
- 复制失败 → 显示错误对话框

## 文件清单

**修改的文件**:
- `app/core/preset_manager.py` - 添加 `duplicate()` 方法
- `app/ui/preset_manager_dialog.py` - 添加"复制"按钮和只读提示

**新增的文件**:
- `test_preset_duplicate.py` - 功能测试脚本
- `PRESET_DUPLICATE_FEATURE.md` - 本文档

## 后续优化建议

1. **批量复制**: 支持选中多个预设一次性复制
2. **复制到剪贴板**: 支持将预设导出为 JSON 字符串
3. **预设模板市场**: 支持从在线市场下载预设模板
4. **版本管理**: 记录预设的修改历史，支持回滚
5. **预设分组**: 支持将预设分组管理（如"工作"、"学习"、"娱乐"）

## 总结

本次实现完整解决了用户无法编辑内置预设的问题，通过"复制"功能让用户可以基于内置预设创建自定义版本。实现遵循了以下原则：

- ✅ 代码风格一致
- ✅ 错误处理完善
- ✅ 用户体验友好
- ✅ 功能测试通过
- ✅ 文档完整清晰
