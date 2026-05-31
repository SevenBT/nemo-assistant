# 模型设置与 System Prompt

当前项目保留两层 System Prompt 配置：

1. 全局 System Prompt：作为默认提示词。
2. 会话级 System Prompt：为空时使用全局提示词，非空时覆盖全局提示词。

预设角色功能已移除，不再包含角色模板、角色管理、角色导入导出、新建会话选角色、`preset_id` 会话字段或 `config/presets.json` 存储。

## 当前优先级

构建 API 消息时的 System Prompt 优先级：

1. `Session.system_prompt`
2. `cfg.systemPrompt`
3. `DEFAULT_USER_PROMPT`
4. 自动追加当前时间信息和内置工具说明

## 相关文件

| 文件 | 说明 |
| --- | --- |
| `app/models/session.py` | 会话模型，仅保留 `system_prompt` |
| `app/core/session_manager.py` | 创建会话和更新会话级 System Prompt |
| `app/ui/session_settings_dialog.py` | 编辑会话级 System Prompt |
| `app/ui/main_window.py` | 构建发送给模型的 system 消息 |
