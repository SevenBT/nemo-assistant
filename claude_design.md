# 工具迁移方案（最终版）

## 一、背景与原则

从 nanobot 项目迁移工具能力到当前 PyQt6 桌面助手。

核心原则：
- 借鉴能力和实现思路，不搬框架
- 保留当前 BuiltinTool / ToolRegistry / ToolContext 架构
- 用户画像：开发者/技术用户
- 安全边界：workspace 目录限制

不做的事：
- 不做 MCP（现阶段 ScriptToolAdapter 够用，中期再评估）
- 不做 generate_image（独立功能，不在本次范围）
- 不扩展 ScriptToolAdapter 支持其他语言（打包体积考量）
- 不增加 web_search provider（当前够用）

---

## 二、迁移清单与优先级

### Phase 1：补齐本地检索能力（3 天）

| 工具 | 类型 | 工作量 |
|------|------|--------|
| list_dir | 新增 | ~60 行 |
| find_files | 新增 | ~80 行 |
| grep | 新增 | ~150 行 |

### Phase 2：exec 命令执行（2 天）

| 工具 | 类型 | 工作量 |
|------|------|--------|
| exec | 新增 | ~200 行（含安全策略） |

### Phase 3：现有工具安全增强（1 天）

| 工具 | 类型 | 工作量 |
|------|------|--------|
| fetch_url | 增强 | ~50 行（SSRF 防护） |

---

## 三、Phase 1 详细设计

### 3.1 list_dir

**文件**：`app/tools/list_dir.py`

**参数**：

```python
parameters = tool_params(
    "path",
    path=Str("目录路径，相对于 workspace"),
    recursive=Bool("是否递归列出子目录，默认 false"),
    max_entries=Int("最大返回条目数", maximum=500),
    include_hidden=Bool("是否包含隐藏文件，默认 false"),
)
```

**属性**：
- `read_only = True`
- 需要 ToolContext 获取 workspace 路径

**实现要点**：
- `pathlib.Path.iterdir()` 遍历，递归时用 `rglob("*")`
- 路径必须 resolve 后在 workspace 内（防止 `../` 逃逸）
- 返回 name、type（file/dir）、size（文件才有）
- 超过 max_entries 时截断并标记 `truncated: true`
- 排序：目录在前，文件在后，各自按名称排序

**返回格式**：

```json
{
  "status": "success",
  "data": {
    "path": "src/",
    "entries": [
      {"name": "utils", "type": "dir"},
      {"name": "main.py", "type": "file", "size": 2048}
    ],
    "total": 15,
    "truncated": false
  }
}
```

---

### 3.2 find_files

**文件**：`app/tools/find_files.py`

**参数**：

```python
parameters = tool_params(
    "query",
    query=Str("文件名关键词或 glob 模式，如 '*.py' 或 'config'"),
    root=Str("搜索起始目录，相对于 workspace，默认根目录"),
    max_results=Int("最大返回数量", maximum=200),
)
```

**属性**：
- `read_only = True`

**实现要点**：
- 判断 query 是否含 glob 字符（`*?[]`）
  - 是 → `Path.rglob(query)`
  - 否 → 遍历所有文件，`query.lower() in name.lower()` 模糊匹配
- 路径限制在 workspace 内
- 返回相对路径列表 + 文件大小
- 自动跳过 `.git`、`__pycache__`、`node_modules` 等常见忽略目录

**返回格式**：

```json
{
  "status": "success",
  "data": {
    "matches": [
      {"path": "src/config.py", "size": 1024},
      {"path": "tests/test_config.py", "size": 512}
    ],
    "total": 2,
    "truncated": false
  }
}
```

---

### 3.3 grep

**文件**：`app/tools/grep.py`

**参数**：

```python
parameters = tool_params(
    "pattern",
    pattern=Str("搜索模式（正则表达式或纯文本）"),
    root=Str("搜索起始目录，相对于 workspace，默认根目录"),
    glob=Str("文件过滤 glob，如 '*.py'"),
    case_sensitive=Bool("是否区分大小写，默认 false"),
    fixed_string=Bool("是否按纯文本匹配（非正则），默认 false"),
    context_lines=Int("匹配行前后显示的上下文行数", maximum=10),
    max_results=Int("最大匹配数量", maximum=200),
    output_mode=Str("输出模式", enum=["content", "files", "count"]),
)
```

**属性**：
- `read_only = True`

**实现要点**：
- 纯 Python 实现：`os.walk` + `re` + `fnmatch`
- 自动跳过二进制文件（读取前 512 字节检测 `\x00`）
- 自动跳过大文件（>2MB）
- 三种输出模式：
  - `files`：只返回匹配的文件路径列表
  - `content`：返回匹配行 + 行号 + 上下文
  - `count`：返回每个文件的匹配数
- 总输出字符数上限 64K，超出截断
- 路径限制在 workspace 内
- 跳过 `.git`、`__pycache__`、`node_modules`

**返回格式（content 模式）**：

```json
{
  "status": "success",
  "data": {
    "matches": [
      {
        "file": "src/main.py",
        "line": 42,
        "content": "    def execute(self, params):",
        "context_before": ["    # 执行工具逻辑"],
        "context_after": ["        result = self._run(params)"]
      }
    ],
    "total_matches": 5,
    "files_searched": 23,
    "truncated": false
  }
}
```

---

## 四、Phase 2 详细设计

### 4.1 exec — Shell 命令执行

**文件**：
- `app/tools/exec_tool.py` — 工具类
- `app/tools/exec_security.py` — 安全策略（deny patterns）

**参数**：

```python
parameters = tool_params(
    "command",
    command=Str("要执行的 shell 命令"),
    working_dir=Str("工作目录，相对于 workspace，默认 workspace 根目录"),
    timeout=Int("超时秒数，默认 60，最大 300", maximum=300),
)
```

**属性**：
- `read_only = False`
- `retry_safe = False`

#### 安全模型

**deny_patterns（硬编码，不可配置）**：

```python
DENY_PATTERNS = [
    # 递归删除
    r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*|--recursive)",
    r"rmdir\s+/s",
    r"del\s+/[fqs]",
    # 磁盘格式化
    r"\bformat\b",
    r"\bmkfs\b",
    r"\bdiskpart\b",
    # 系统关机
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bpoweroff\b",
    # 注册表危险操作
    r"reg\s+delete",
    # fork bomb
    r":\(\)\s*\{",
    # 覆盖系统文件
    r">\s*/dev/sd",
    r"dd\s+if=",
]
```

**执行流程**：

```
1. 路径校验：working_dir resolve 后必须在 workspace 内
2. 安全检查：command 匹配 deny_patterns → 弹确认框
3. 用户确认：通过 ToolContext 的回调触发 UI 确认对话框
4. 执行：subprocess.run(command, shell=True, timeout=timeout, cwd=working_dir)
5. 返回：stdout + stderr + return_code
```

**用户确认机制**：

ToolContext 新增字段：

```python
# context.py
confirm_action: Callable[[str, str], bool] | None = None
# (title, message) -> bool，None 表示默认拒绝
```

工具中调用：

```python
if self._matches_deny(command):
    if not ctx.confirm_action:
        return error("无确认回调，拒绝执行危险命令")
    if not ctx.confirm_action("命令确认", f"即将执行:\n{command}\n\n是否允许？"):
        return error("用户取消执行")
```

UI 层实现：在 MainWindow 中将 `confirm_action` 绑定到 `QMessageBox.question`。

**返回格式**：

```json
{
  "status": "success",
  "data": {
    "stdout": "...",
    "stderr": "...",
    "return_code": 0,
    "timed_out": false
  }
}
```

**输出截断**：stdout/stderr 各最大 32K 字符，超出截断并标注。

---

## 五、Phase 3 详细设计

### 5.1 fetch_url SSRF 防护

**文件**：修改现有 `app/tools/fetch_url.py`

**新增函数**：

```python
import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

def _is_safe_url(url: str) -> tuple[bool, str]:
    """检查 URL 是否安全（非内网地址）。"""
    parsed = urlparse(url)

    # 只允许 http/https
    if parsed.scheme not in ("http", "https"):
        return False, f"不支持的协议: {parsed.scheme}"

    hostname = parsed.hostname
    if not hostname:
        return False, "无效的 URL"

    # 解析域名为 IP
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False, f"无法解析域名: {hostname}"

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        for network in _BLOCKED_NETWORKS:
            if ip in network:
                return False, f"禁止访问内网地址: {hostname}"

    return True, ""
```

**集成点**：
- 在 `execute()` 开头调用 `_is_safe_url(url)`
- 如果使用 requests 且 `allow_redirects=True`，需要用 Session + 自定义 `response` hook 在每次重定向时再次校验目标 URL

---

## 六、ToolContext 变更汇总

```python
@dataclass
class ToolContext:
    # 现有字段不变...

    # Phase 1 + 2 新增
    workspace: Path = field(default_factory=lambda: Path("."))  # 已有，确认使用
    confirm_action: Callable[[str, str], bool] | None = None   # exec 确认回调
```

workspace 字段已存在，只需确保在 MainWindow 初始化时正确设置为用户配置的工作目录。

---

## 七、通用设计规范

### 路径安全

所有文件系统工具共用一个路径校验函数：

```python
# app/tools/_path_utils.py（内部模块，下划线开头不会被 loader 扫描）

def resolve_safe(path_str: str, workspace: Path) -> tuple[Path | None, str]:
    """
    将用户输入路径解析为绝对路径，确保在 workspace 内。

    Returns:
        (resolved_path, error_message)
        成功时 error_message 为空字符串
    """
    try:
        target = (workspace / path_str).resolve()
    except (OSError, ValueError) as e:
        return None, f"路径无效: {e}"

    if not str(target).startswith(str(workspace.resolve())):
        return None, "路径超出 workspace 范围"

    return target, ""
```

### 忽略目录

文件遍历工具共用忽略列表：

```python
IGNORE_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".venv",
    "venv", ".idea", ".vs", ".vscode", "dist", "build",
})
```

### 二进制文件检测

```python
def _is_binary(path: Path) -> bool:
    """读取前 512 字节，含 \x00 则视为二进制。"""
    try:
        chunk = path.read_bytes()[:512]
        return b"\x00" in chunk
    except OSError:
        return True
```

---

## 八、测试计划

每个工具对应一个测试文件：

```
tests/
├── test_list_dir.py
├── test_find_files.py
├── test_grep.py
├── test_exec_tool.py
└── test_fetch_url_ssrf.py
```

关键测试场景：

| 工具 | 必测场景 |
|------|----------|
| list_dir | 正常列目录、递归、路径逃逸拦截、max_entries 截断、隐藏文件过滤 |
| find_files | glob 模式、模糊匹配、忽略目录、路径逃逸 |
| grep | 正则/纯文本、大小写、context_lines、二进制跳过、大文件跳过、输出截断 |
| exec | 正常执行、deny_pattern 拦截、超时、路径逃逸、输出截断 |
| fetch_url | 内网 IP 拦截、localhost 拦截、重定向后再校验、正常 URL 放行 |

---

## 九、实施顺序

```
Phase 1（第 1-3 天）：
  Day 1: _path_utils.py + list_dir + 测试
  Day 2: find_files + 测试
  Day 3: grep + 测试

Phase 2（第 4-5 天）：
  Day 4: exec_security.py + exec_tool.py
  Day 5: ToolContext.confirm_action 接入 UI + 测试

Phase 3（第 6 天）：
  Day 6: fetch_url SSRF 防护 + 测试
```

---

## 十、验收标准

- [ ] 所有新工具通过 `loader.py` 自动发现并注册
- [ ] 所有新工具在 LLM 工具列表中正确显示
- [ ] list_dir / find_files / grep 标记为 `read_only=True`，可并发执行
- [ ] 路径逃逸测试全部通过（`../`、绝对路径、符号链接）
- [ ] exec deny_pattern 匹配时弹出确认框
- [ ] fetch_url 无法访问 127.0.0.1 / 10.x / 192.168.x
- [ ] 测试覆盖率 >= 80%
