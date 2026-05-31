# nanobot 工具迁移设计方案

本文面向当前 PyQt 桌面助手项目，整理 nanobot 内置工具的迁移价值、适配成本、实施优先级和设计建议。

## 一、目标

当前项目已经有自己的工具系统：

```text
app/tools/base.py
app/tools/schema.py
app/tools/loader.py
app/tools/registry.py
app/tools/script_adapter.py
app/core/agent_loop.py
```

因此迁移 nanobot 工具时，不建议直接整套搬运，而应遵循：

```text
借鉴能力和实现思路
保留当前项目的 BuiltinTool / ToolRegistry / ToolContext 架构
按当前桌面助手的产品边界重新封装
```

最终目标：

```text
增强当前助手的文件理解、内容检索、网页阅读和可控自动化能力。
```

## 二、nanobot 内置工具清单

nanobot 的主要内置工具如下。

### 1. 文件系统类

```text
read_file
write_file
edit_file
list_dir
apply_patch
find_files
grep
```

能力说明：

```text
read_file     读取文件，支持分页、文档、图片等
write_file    写入/覆盖文件
edit_file     小范围文本替换
list_dir      列目录，支持递归
apply_patch   多文件补丁式代码修改
find_files    按文件名、glob、类型搜索文件
grep          正则搜索文件内容
```

### 2. 命令执行类

```text
exec
write_stdin
list_exec_sessions
```

能力说明：

```text
exec                执行 shell 命令
write_stdin         向长运行命令会话写入 stdin
list_exec_sessions  查看活跃长运行命令会话
```

### 3. 网页类

```text
web_search
web_fetch
```

能力说明：

```text
web_search  多 provider 搜索网页
web_fetch   抓取网页并提取可读正文
```

### 4. 任务和自动化类

```text
cron
long_task
complete_goal
spawn
message
```

能力说明：

```text
cron           定时任务
long_task      标记长目标任务
complete_goal  结束长目标任务
spawn          创建子代理
message        主动给用户/频道发送消息
```

### 5. 扩展和集成类

```text
MCPToolWrapper
MCPResourceWrapper
MCPPromptWrapper
run_cli_app
generate_image
my
```

能力说明：

```text
MCP wrappers   接入 MCP server 的工具、资源和 prompt
run_cli_app    调用 nanobot CLI app service
generate_image 图像生成
my             nanobot 自身状态/配置/自修改工具
```

## 三、迁移原则

### 1. 不直接复制 Tool 基类

nanobot 使用：

```text
nanobot.agent.tools.base.Tool
async def execute(**kwargs)
```

当前项目使用：

```text
app.tools.base.BuiltinTool
def execute(params: dict)
```

两者接口不同：

```text
nanobot:
    execute(**kwargs)
    async 工具
    返回字符串或 content blocks

assistant:
    execute(params)
    同步工具
    返回 {"status": "...", "data": {...}}
```

因此不能直接复制工具类，需要重新封装为当前项目的 `BuiltinTool`。

### 2. 优先迁移只读工具

只读工具风险低，适合当前阶段。

优先级最高：

```text
list_dir
find_files
grep
read_file 增强
web_fetch 增强
```

这些工具默认可以：

```text
read_only=True
retry_safe=True
```

### 3. 写入和执行类工具必须单独评估

这些工具有副作用或安全风险：

```text
write_file
edit_file
apply_patch
exec
write_stdin
cron
message
```

迁移前必须设计：

```text
权限边界
用户确认机制
工作目录限制
执行超时
执行日志
UI 展示方式
失败恢复策略
```

### 4. 与当前已有功能避免重复

当前项目已有：

```text
read_file
save_file
fetch_url
web_search
scheduler
reminder
notes
run_python
clipboard
multi_model_consult
```

迁移时应优先增强已有工具，而不是新增同名重复工具。

例如：

```text
nanobot web_fetch  -> 增强当前 fetch_url
nanobot web_search -> 增强当前 web_search
nanobot cron       -> 参考当前 scheduler/reminder，不直接搬
nanobot read_file  -> 增强当前 read_file
```

## 四、推荐迁移优先级

## P0：最值得优先迁移

### 1. list_dir

价值：

```text
让模型能理解目录结构。
配合 read_file / grep / find_files 使用效果很好。
```

建议实现为：

```text
app/tools/list_dir.py
```

参数建议：

```text
path: str
recursive: bool = false
max_entries: int = 200
include_hidden: bool = false
```

返回建议：

```json
{
  "status": "success",
  "data": {
    "path": "...",
    "entries": [
      {"name": "...", "type": "file", "size": 123},
      {"name": "...", "type": "dir"}
    ],
    "truncated": false
  }
}
```

注意：

```text
限制最大条目数量，避免一次返回过大。
未来可接入 workspace 限制。
```

### 2. find_files

价值：

```text
让模型先找文件，再读文件。
比让模型猜路径可靠。
```

建议实现为：

```text
app/tools/find_files.py
```

参数建议：

```text
query: str
root: str = "."
glob: str | None
file_type: str | None
max_results: int = 100
```

适用场景：

```text
查找某个文件名
查找所有 .py / .md 文件
查找包含关键词的路径
```

### 3. grep

价值：

```text
让模型按内容搜索文件。
是代码阅读、笔记搜索、配置查找的基础能力。
```

建议实现为：

```text
app/tools/grep.py
```

参数建议：

```text
pattern: str
root: str = "."
glob: str | None
case_sensitive: bool = false
max_results: int = 100
context_lines: int = 0
```

实现建议：

```text
优先使用 Python pathlib + re 实现，保持跨平台。
不要依赖系统 rg，避免 Windows 用户环境不一致。
```

可选优化：

```text
如果检测到 rg 可用，可走 rg 快速路径。
```

### 4. read_file 增强

当前已有 `app/tools/read_file.py`，建议吸收 nanobot 的增强点：

```text
offset / limit 分页
行号输出
最大字符限制
PDF 支持
Office 文档支持
图片文件识别
设备文件阻断
重复读取去重
```

优先实现：

```text
offset / limit
行号输出
最大字符限制
二进制文件友好错误
```

后续再考虑：

```text
PDF / Office
图片内容作为附件或视觉输入
```

## P1：适合增强现有联网工具

### 1. fetch_url 增强

当前已有：

```text
app/tools/fetch_url.py
```

建议借鉴 nanobot `web_fetch`：

```text
SSRF 防护
私有 IP 阻断
重定向安全检查
HTML -> markdown/text
max_chars 参数
JS-heavy / login-walled 页面友好错误
```

高优先级安全项：

```text
阻止访问 127.0.0.1
阻止访问 localhost
阻止访问 10.0.0.0/8
阻止访问 172.16.0.0/12
阻止访问 192.168.0.0/16
阻止 file:// 等非 http(s) scheme
重定向后再次校验 URL
```

### 2. web_search 增强

当前已有：

```text
app/tools/web_search.py
```

可借鉴 nanobot：

```text
provider 动态选择
无 API Key 自动 fallback
Brave 429 后内部重试一次
搜索结果格式稳定化
```

建议保持当前已有 provider：

```text
ddg
bing
tavily
brave
bocha
```

只吸收：

```text
更稳的错误分类
429 / rate limit 提示
单 provider 内部小范围重试
```

## P2：可做但需要安全设计

### 1. apply_patch

价值：

```text
适合代码编辑场景。
比 write_file 更安全，因为是补丁式修改。
```

风险：

```text
当前产品不是纯 coding agent。
用户可能不希望聊天助手自动改项目文件。
```

建议：

```text
如果做，必须增加 UI 确认。
先展示 patch，再让用户确认应用。
限制在 workspace 内。
```

### 2. exec

价值：

```text
可以运行测试、构建、命令行工具。
```

风险很高：

```text
任意命令执行
删除文件
访问用户隐私
网络请求
阻塞进程
```

迁移前必须具备：

```text
命令确认弹窗
危险命令拦截
工作目录限制
超时
输出截断
日志记录
可取消
```

建议：

```text
不要作为近期工具迁移目标。
```

### 3. generate_image

价值：

```text
图片生成对桌面助手有产品价值。
```

需要适配：

```text
当前 AIClient/provider 配置
图片保存目录
UI 预览
历史记录/附件管理
错误提示
```

建议：

```text
作为独立功能规划，不和基础工具迁移混在一起。
```

## P3：不建议直接迁移

这些工具与 nanobot 架构强耦合：

```text
spawn
long_task
complete_goal
message
my
MCP wrappers
run_cli_app
```

原因：

```text
spawn 依赖子代理系统。
long_task / complete_goal 依赖 sustained goal 机制。
message 依赖多 channel 消息系统。
my 依赖 nanobot 自身运行时状态和自修改能力。
MCP 是独立大功能，需要单独产品设计。
run_cli_app 依赖 nanobot CLI app service。
```

建议：

```text
暂不迁移。
后续如果要做 MCP，应作为单独模块设计，而不是从 nanobot 直接复制 wrapper。
```

## 五、迁移实施路线

### 第一阶段：补齐只读本地检索工具

目标：

```text
让模型可以可靠浏览本地文件结构和搜索内容。
```

建议顺序：

```text
1. list_dir
2. find_files
3. grep
4. read_file offset/limit 增强
```

验收标准：

```text
模型可以先 list_dir / find_files / grep，再 read_file。
工具输出不会爆上下文。
路径错误有清晰提示。
只读工具可并发执行。
```

### 第二阶段：增强网页读取安全性

目标：

```text
提升 fetch_url / web_search 的可靠性和安全边界。
```

建议顺序：

```text
1. fetch_url 增加 SSRF 防护
2. fetch_url 增加重定向后安全校验
3. fetch_url 增加 markdown/text 提取模式
4. web_search 优化 429 / 网络错误处理
```

验收标准：

```text
不能访问内网和本机地址。
重定向不能绕过安全校验。
联网失败返回明确 error_type。
网络瞬态错误可在 retry_safe 场景下重试。
```

### 第三阶段：评估写入类工具

目标：

```text
在可控安全边界下增强文件修改能力。
```

候选：

```text
apply_patch
edit_file
write_file
```

建议：

```text
优先 apply_patch，而不是 write_file。
必须有 UI 确认。
必须有 diff 预览。
必须限制 workspace。
```

### 第四阶段：评估高风险自动化

候选：

```text
exec
generate_image
MCP
```

建议：

```text
分别作为独立功能设计。
不要和基础工具迁移混合开发。
```

## 六、迁移到当前工具架构的模板

nanobot 工具通常是：

```python
class SomeTool(Tool):
    name = "some_tool"
    description = "..."

    async def execute(self, **kwargs):
        ...
```

当前项目应改写为：

```python
class SomeTool(BuiltinTool):
    @property
    def name(self) -> str:
        return "some_tool"

    @property
    def description(self) -> str:
        return "..."

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(...)

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        ...
        return {"status": "success", "data": {...}}
```

如果需要项目依赖：

```python
@classmethod
def create(cls, ctx: ToolContext):
    return cls(workspace=ctx.workspace, config=ctx.config)
```

## 七、路径和安全边界建议

迁移文件类工具时，建议引入统一路径解析策略。

未来可在 `ToolContext` 中使用：

```text
workspace
```

作为默认安全根目录。

建议策略：

```text
默认允许读取用户选择的 workspace。
写入类工具必须限制在 workspace。
联网工具禁止访问本机和内网地址。
命令执行类工具必须要求用户确认。
```

路径错误提示要明确：

```text
路径不存在
路径不是文件
路径不是目录
路径超出允许范围
二进制文件不支持文本读取
```

## 八、重试策略和工具迁移的关系

迁移工具时应遵循：

```text
只读工具：
    read_only=True
    retry_safe 默认 True

写入/执行/发送类工具：
    read_only=False
    retry_safe 默认 False
```

用户脚本工具：

```text
默认 retry_safe=False。
只有 manifest 显式声明 retry_safe=true 才允许自动重试。
```

局部重试建议：

```text
如果工具非常清楚某个错误是瞬态错误，可以在工具内部做一次小范围重试。
例如：
    web_search 某 provider 429
    MCP 连接瞬断
```

不要全局无差别重试：

```text
写文件失败不能盲目重试。
创建笔记失败不能盲目重试。
发送消息失败不能盲目重试。
外置脚本输出协议错误不能盲目重试。
```

## 九、最终建议

近期最值得做的是：

```text
1. list_dir
2. find_files
3. grep
4. read_file 分页和行号增强
5. fetch_url SSRF 防护和 markdown 提取
```

不建议近期做：

```text
exec
spawn
MCP
long_task
message
my
```

总体路线：

```text
先补只读理解能力。
再补联网阅读安全性。
最后再考虑写入、命令执行、MCP 等高风险能力。
```

最重要的设计原则：

```text
当前项目不是 nanobot 的运行时环境。
迁移工具时不要搬框架，只搬能力。
```

