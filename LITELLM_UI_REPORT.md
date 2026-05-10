# LiteLLM UI 改造完成报告

## 修改的文件

### 1. `app/ui/settings_dialog.py`

**新增导入**：
- `QGroupBox`：用于多模型调用配置分组
- `QScrollArea`：API Tab 内容过多时支持滚动

**新增 UI 元素**：

#### LiteLLM 配置区域（可折叠）
位置：API Tab 中，商道配置下方

1. **启用开关**（`_ll_enabled`）
   - QCheckBox："启用 LiteLLM"
   - 勾选后禁用 OpenAI 和商道配置

2. **展开/收起按钮**（`_ll_toggle_btn`）
   - 默认折叠，点击展开详细配置

3. **服务地址**（`_ll_base_url`）
   - QLineEdit，默认 "http://localhost:4000"

4. **API Key**（`_ll_api_key`）
   - QLineEdit，密码模式，可选
   - 存储在系统 keyring 中

5. **默认模型**（`_ll_default_model`）
   - QComboBox，从 `litellm.models` 动态填充
   - 显示格式："{model.name} ({model.provider})"

6. **多模型调用配置**（`_ll_model_checkboxes`）
   - QGroupBox 标题："多模型调用"
   - 内部动态生成 QCheckBox 列表
   - 每个模型一个 QCheckBox
   - 勾选状态对应 `model.enabled`

**新增方法**：

1. `_on_ll_expand()`
   - 展开/收起 LiteLLM 配置区域

2. `_on_ll_toggled(enabled: bool)`
   - LiteLLM 启用时，禁用 OpenAI 和商道配置
   - 确保三种 API 类型互斥

**修改的方法**：

1. `_on_sd_toggled(enabled: bool)`
   - 新增：商道启用时，禁用 LiteLLM 配置

2. `_load()`
   - 新增：加载 LiteLLM 配置
   - 动态填充默认模型下拉框
   - 动态生成多模型调用的 QCheckBox 列表

3. `_save()`
   - 新增：保存 LiteLLM 配置
   - 根据启用状态设置 `api_type`（"openai" | "shangdao" | "litellm"）
   - 更新模型的 `enabled` 状态

## 界面布局

```
API Tab
├── OpenAI 配置
│   ├── API 地址
│   ├── API Key
│   ├── 模型
│   ├── 最大 Token
│   └── Temperature
├── ─────────────────────
├── 商道 API
│   ├── [✓] 启用商道 API  [▶ 展开配置]
│   └── （折叠内容）
│       ├── API 地址
│       ├── API Key
│       ├── 模型
│       ├── 最大 Token
│       └── Temperature
├── ─────────────────────
└── LiteLLM
    ├── [✓] 启用 LiteLLM  [▶ 展开配置]
    └── （折叠内容）
        ├── 服务地址
        ├── API Key
        ├── 默认模型
        └── 多模型调用
            ├── [✓] GPT-4o (openai)
            ├── [✓] Claude 3.5 Sonnet (anthropic)
            ├── [ ] Gemini 2.0 Flash (google)
            └── [ ] DeepSeek Chat (deepseek)
```

## 交互逻辑

1. **互斥启用**：
   - OpenAI、商道、LiteLLM 三种 API 类型互斥
   - 启用一个时，其他两个的配置区域自动禁用

2. **折叠展开**：
   - 默认折叠，节省空间
   - 点击"展开配置"按钮显示详细配置
   - 按钮文字动态切换："▶ 展开配置" / "▼ 收起配置"

3. **动态模型列表**：
   - 默认模型下拉框从配置文件动态填充
   - 多模型调用的 QCheckBox 列表也动态生成
   - 支持未来添加更多模型

4. **保存逻辑**：
   - API Key 存入系统 keyring（安全）
   - 模型的 `enabled` 状态批量更新
   - `api_type` 根据启用状态自动设置

## 测试方法

### 1. 运行测试脚本

```bash
cd D:\claudecode-projects\assistant
python test_litellm_ui.py
```

测试脚本会：
1. 打印当前 LiteLLM 配置
2. 打开设置对话框
3. 保存后打印新配置

### 2. 手动测试步骤

1. **启动应用**
   ```bash
   python main.py
   ```

2. **打开设置对话框**
   - 点击托盘图标 → 设置
   - 或主窗口菜单 → 设置

3. **测试 LiteLLM 配置**
   - 切换到"API"标签
   - 勾选"启用 LiteLLM"
   - 验证 OpenAI 和商道配置被禁用
   - 点击"展开配置"
   - 填写服务地址（如 http://localhost:4000）
   - 选择默认模型
   - 勾选需要启用的模型
   - 点击"确定"保存

4. **验证配置生效**
   - 重新打开设置对话框
   - 验证配置已保存
   - 检查 `config/app_config.json` 文件
   - 验证 `api_type` 为 "litellm"

5. **测试互斥逻辑**
   - 启用 LiteLLM 后，尝试启用商道
   - 验证 LiteLLM 配置被禁用
   - 取消商道，验证 OpenAI 配置恢复

## 配置文件示例

保存后的 `config/app_config.json`：

```json
{
  "api": {
    "api_type": "litellm"
  },
  "litellm": {
    "enabled": true,
    "base_url": "http://localhost:4000",
    "default_model": "gpt-4o",
    "models": [
      {
        "id": "gpt-4o",
        "name": "GPT-4o",
        "provider": "openai",
        "enabled": true
      },
      {
        "id": "claude-3-5-sonnet-20241022",
        "name": "Claude 3.5 Sonnet",
        "provider": "anthropic",
        "enabled": true
      },
      {
        "id": "gemini-2.0-flash-exp",
        "name": "Gemini 2.0 Flash",
        "provider": "google",
        "enabled": false
      }
    ]
  }
}
```

## 注意事项

1. **商道 UI 完全未动**：
   - 只新增了 LiteLLM 相关代码
   - 商道配置逻辑保持不变

2. **向后兼容**：
   - 如果配置文件中没有 `litellm` 字段，使用默认值
   - 不影响现有的 OpenAI 和商道配置

3. **安全性**：
   - LiteLLM API Key 存储在系统 keyring 中
   - 不会明文保存在配置文件

4. **扩展性**：
   - 模型列表动态生成，易于添加新模型
   - 只需修改 `config.py` 中的默认配置

## 后续工作

1. **测试 LiteLLM 集成**：
   - 启动 LiteLLM 服务
   - 配置 UI 后发送聊天消息
   - 验证 AIClient 正确路由到 LiteLLM

2. **多模型调用测试**：
   - 使用 `multi_model_consult` 工具
   - 验证只调用启用的模型

3. **错误处理**：
   - 测试 LiteLLM 服务不可用时的错误提示
   - 验证 API Key 错误时的提示

4. **UI 优化**（可选）：
   - 添加"测试连接"按钮
   - 显示模型列表加载状态
   - 添加模型描述/说明
