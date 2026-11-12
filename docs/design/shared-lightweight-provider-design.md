# 共用轻量模型传输与供应商差异配置

日期：2026-11-12。状态：已实施统一替代；LiteLLM 和 OpenAI SDK 已从依赖、锁文件及本地开发环境移除。

## 决策

完成替代后彻底移除，不长期维护两套调用体系。没有 transport=litellm 开关、自动协议降级或 SDK 兜底。普通用户保留运行记录、token 和服务商账单入口，不需要维护价格表。

## 实际分层

桌面配置或 headless GatewayConfig → LLMGateway → HTTPProviderAdapter → 协议 codec → HttpTransport。

- gateway 保留限流、重试、取消、脱敏、attempt 记录和 TraceStore 接口。
- providers/contracts.py 定义请求与适配协议，不依赖 Qt、设置或 keyring。
- providers/registry.py 定义带 revision 的端点/协议默认值及地址校验。
- providers/transport.py 使用一个后台 asyncio 事件循环和可复用 httpx.AsyncClient，向现有同步迭代接口提供有界队列。每个 gateway 拥有自己的池，支持同时调用；close 后释放连接和线程。
- chat.py、responses.py、anthropic.py、cohere.py 分别处理协议数据，不通过猜 URL 或请求失败来切换协议。底层不反向依赖 gateway。
- providers/errors.py 复用脱敏、错误分类与 token 归一化。

## 厂商与接口

| 配置身份 | 默认协议 | 端点策略 |
| --- | --- | --- |
| openai | openai_chat | 官方 /v1/chat/completions；可显式选择 responses |
| deepseek | openai_chat | 官方根地址；图片保留已有 /beta；thinking 保持禁用 |
| anthropic | anthropic_messages | 原生 /v1/messages、x-api-key 和版本头 |
| gemini | openai_chat | 官方 /v1beta/openai 兼容接口；保留工具 thought_signature |
| dashscope | openai_chat | 默认中国区 compatible-mode/v1；其他区域可覆盖基址 |
| zai | openai_chat | /api/paas/v4 |
| meta_llama | openai_chat | /compat/v1 |
| cohere | cohere_chat | 原生 /v2/chat |
| azure | openai_chat | 用户资源主机 /openai/v1，模型填写部署名；旧 deployment 路径显式提示迁移 |
| 自定义身份 | openai_chat 或显式协议 | 必须填写 API 地址；不冒充已经实网验证的厂商 |

表中表示实现的协议映射，不表示每个模型或账户已进行付费实网认证。保留用户已有模型 ID，不擅自更换模型。模型能力、区域限制及供应商接口变化仍需按实际服务验证。

API 地址保留自定义路径，追加一次对应接口；已填完整路径不重复追加。拒绝嵌入账号、query、fragment、协议路径冲突和重定向；不在共享 client 默认 headers 中保存密钥。Azure 使用 v1 资源接口，不再依赖旧 api-version 参数。

## 请求、流式和工具安全

- 支持 UTF-8/CRLF 跨网络分片、SSE 注释保活和多行 data；限制单行/事件 2 Mi 字符、错误响应 64 KiB、待消费队列 32 项。工具参数限制 2 Mi 字符，单次最多 128 个调用。
- 阶段超时用于连接、读、写和池等待；可选 stream_timeout 限制整个调用，即使服务器只返回保活也会超时。等待响应头时取消能终止底层任务，不等待服务器回复。
- Chat 要求 finish_reason 和 DONE；Claude 要求块完成和 message_stop；Responses 要求 response.completed 和成功状态；Cohere 要求 message-end。EOF 不算成功。
- 执行前验证所有工具的 ID、名称、JSON 对象参数、冲突片段和重复 ID。截断、异常终止、错误参数或部分调用均不能提交执行。
- 只有尚未收到文本、推理或工具片段时才允许瞬态重试；不支持协议、参数配置错误、鉴权和余额不足不重试。不自动切换接口重发。
- 已收到的服务商 usage 即使随后流中断、工具校验失败或响应未完成也会记录到该次 attempt；未知字段保持未知，不补成零。内部 usage 事件不传递给界面。
- OpenAI 推理系列使用保守参数策略，避免发送不支持的采样控制；其他参数映射按 codec 处理，不把 Responses 或原生 Claude 当作 Chat Completions。

## 多轮与持久化

Message 添加可选 reasoning_content 和 provider_state，ToolCall 添加 extra_content，缺省值兼容旧会话。

Agent 在 done 时发出 validated message metadata；Qt 只桥接该回调。控制器在工具 start 之前保存当前 assistant 元数据，工具签名通过 ID 关联。Agent 的下一轮、消息保存/恢复、ConsolidatorHook 转换和独立评估场景均保留这些字段。

Claude 保存原始签名内容块，Responses 保存完整 output/reasoning items，Gemini 保存工具 extra_content。切换协议时不会向不兼容厂商发送其他协议的私有字段。图像和工具结果分别翻译，不支持的内容报错。

注意：持久化协议历史可能包含供应商的加密推理项/签名；它们属于本地会话数据，不写入运行汇总日志。当前内容 token 预算仍沿用应用既有 tiktoken 估计方式，不能视为所有厂商的精确账单计数。

## 配置兼容与依赖移除

模型编辑页增加可选 api_protocol（默认 auto）。桌面、工具生成模型覆盖、咨询、headless eval target/judge 都转成同一 GatewayConfig。编辑条目保留未知字段。

旧 LiteLLM 命名的配置键、翻译键、对话框类及 keyring 槽位仅为数据/内部接口兼容保留；不导入同名包，不形成第二调用路径。旧 API.ApiType 是废弃存储标识，运行时不使用它路由。无需重新输入密钥。

删除 LiteLLMAdapter、litellm_loader、DeepSeek 专用第二套 transport、SDK 后台预热和启动依赖安装检查。根项目与 evals 锁文件不含 litellm/openai/anthropic；PyInstaller 不再 collect_all 它们，并显式 exclude。CI 去掉价格表环境变量。SDK 不会从已运行进程自动卸载，需正常退出并重启应用；本次未操作用户的运行中窗口。

## 验证和限制

- 纯离线协议响应覆盖文本、图片、工具、签名、多轮、usage、错误、截断、未知结束、协议配置和端点。
- 本机真实 HTTP 服务验证响应头等待取消、仅保活总时限、并发取消隔离、连接池和线程关闭。
- 干净子进程禁止模型 SDK/Qt/keyring 导入并运行聊天、咨询；安装/锁文件断言防止 SDK 依赖回流。
- 独立评估测试和 core 三个离线场景验证无工具回答、多轮文件和错误恢复。
- 没有读取密钥、调用付费模型或启动真实桌面钩子。离线测试不能代替每个供应商的实网验证；尚未做新一轮全供应商真实内存测量。
- 完整桌面 offscreen 回归中原有贴图辉光像素测试失败与本次网络实现无关，单列报告，不以隐藏或跳过代替修复。
- 最终验证：迁移相关测试 124 项通过，独立评估测试 35 项通过，core 离线场景 3/3 通过；仓库检查、独立依赖边界及 diff 检查通过。

历史受控内存数据见 [DeepSeek 第一阶段测量](lightweight-model-transport.md)，不能把卸载磁盘依赖直接等同于新增内存收益。
