# nemo-assistant 阶段 1：定向手术执行计划

> **目标**：10-12 天实际工作量，让每个被问到的模块都有数字支撑，不被一问就穿
> **非目标**：做完整、追求完美覆盖、提升测试覆盖率到 80%
> **核心原则**：每个工单有明确的停手线。达到停手线立即停，不追求"再完善一点"

---

## 第一刀：止损（3 天）

### W1.1 清理敏感信息【P0 / 半天】

**目标**：防止泄密导致面试直接终止

**工单清单**：

1. nemo 本地仓库
   - [ ] `git log --format='%an %ae' | sort -u` 确认那 2 个 `mazilai@sinotrans.com` commit（`03a90aa`、`c28fd5b`）
   - [ ] 决定是否 `git filter-repo --mailmap` 重写（会改变所有后续 commit hash，如果已经有人 fork 过就别动）
   - [ ] 如果不重写，至少知道它在那儿，面试时有人问能解释

2. 材料文件（这些不能给任何人看）
   - [ ] `慢sql优化/03_配置与集成.txt` **隔离到非同步目录**，重命名为 `03_配置与集成-原始版-禁止外传.txt`
   - [ ] 新建 `03_配置与集成-脱敏版.txt`，把所有密码/IP/域名替换为 `<REDACTED>`
   - [ ] `autoOps/test/test_fsi.py:57` 删除 `password = "Sinotransbms@2022latter"` 和内网 IP，改成 `password = os.getenv("FSI_TEST_PASSWORD", "test_password_placeholder")`
   - [ ] `autoOps/` 根目录 `t` 文件**直接删除**（含客户银行账号）
   - [ ] `autoOps/iam_operations.py:88` 把 `fill("司冬波")` 改成 `fill(os.getenv("IAM_TEST_USER", "测试用户"))`
   - [ ] `autoOps/config.py` 等 4 处 `postgres:122817` 改成 `postgres:${DB_PASSWORD}`
   - [ ] `autoOps/.gitignore:30` 取消 `.env` 的注释（改成 `.env`）
   - [ ] `autoOps/config.py:77` 等处域名改成 `${FSI_URL}` / `${BMS_URL}`
   - [ ] `autoExcel/settings.py:4-6`、`data_format.py:176` 的 5 处本机路径改成 `Path.home()` 或配置项
   - [ ] 全量 grep 确认：`rg -i "sinotrans|sino@|122817|@2022latter|@2023|3602015019200888350|司冬波" 原始资料/` 应该只剩脱敏版文件有命中

**验收标准**：上述文件能放心发给任何面试官

**停手线**：敏感信息清理完就停，不做"顺便重构"

---

### W1.2 修 4 个会当场崩的 bug【P0 / 1 天】

**目标**：演示时不出丑

#### Bug 1：笔记查找 NameError【10 分钟】

```bash
cd /d/claudecode-projects/assistant
```

**文件**：`app/ui/components/markdown_editor.py`

**修改**：第 10 行导入块加一行
```python
from PySide6.QtGui import (
    QColor,
    QKeySequence,
    QPalette,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
    QImage,
    QTextDocument,  # 加这一行
)
```

**验收**：
```bash
# 启动 app，打开笔记编辑器，右键菜单 → 查找/替换，输入任意文本点"查找下一个"
# 预期：正常查找，不抛异常
```

#### Bug 2：工具生成死循环【10 分钟】

**文件**：`app/ui/tool_generate_dialog.py`

**修改**：删除 521-527 行的整个 if 块
```python
# 删除这 7 行（大约在 :521-527）
        if declared != frozenset():
            logger.warning(
                f"tool_generate: permission mismatch: declared={declared}, approved={frozenset()}"
            )
            self._show_needs_review()
            return
```

**原因**：这个 if 在对着恒为空集的桩做比较，导致声明任何权限的工具永远装不上

**验收**：
```bash
# 让 LLM 生成一个声明 {"network"} 权限的工具
# 预期：能安装成功，不会翻回"需重新审核"
```

#### Bug 3：快捷键保存不生效【10 分钟】

**文件**：`app/ui/settings_window.py`

**修改**：找到 `SettingsWindow.__init__` 里 stacked_widget 切换的信号连接（大约 :145-157），加一行
```python
self._settings_list.currentRowChanged.connect(self._stacked_widget.setCurrentIndex)
self._settings_list.currentRowChanged.connect(self._on_page_changed)  # 加这一行

# 然后在类的末尾加这个方法
def _on_page_changed(self, index: int):
    """页面切换时保存当前页设置"""
    current_widget = self._stacked_widget.widget(self._stacked_widget.currentIndex())
    if hasattr(current_widget, 'save'):
        current_widget.save()
```

**验收**：改快捷键 → 关闭设置窗 → 重开，快捷键还在

#### Bug 4：日志全部丢弃【半天】

**文件**：`main.py`

**修改**：在 `if __name__ == "__main__":` 块的最开始加
```python
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

if __name__ == "__main__":
    # 配置日志（在 QApplication 之前）
    log_dir = Path.home() / ".nemo" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            RotatingFileHandler(
                log_dir / "nemo.log",
                maxBytes=10*1024*1024,  # 10MB
                backupCount=3,
                encoding='utf-8'
            ),
            logging.StreamHandler()  # 同时输出到控制台
        ]
    )
    
    # 原有的 multiprocessing.freeze_support() 等代码...
```

**验收**：启动 app → 做任意操作 → 检查 `~/.nemo/logs/nemo.log` 有内容

**停手线**：四个 bug 修完就停，不做"顺便把其他 8 个未接线的也修了"

---

### W1.3 修正事实性表述【P0 / 半天】

**文件清单**：

1. **nemo README.md**
   - [ ] `:82` 删掉 "update notes"（代码里只有 list/create）
   - [ ] 搜索 "full-text search"，改成"关键词搜索"（实为 LIKE）

2. **nemo 文档目录调整**
   - [ ] `mv docs/design/llm-evaluation.md docs/blog-drafts/`（这是技术博客不是设计文档）
   - [ ] `docs/design/edge-snap-width-implementation.md` 删掉 :131-133 那个打勾但文件不存在的任务

3. **慢SQL 材料**
   - [ ] `慢SQL重构_01_概述与时间线.txt` 的成果表（:363-375）删掉这四行：
     - "复用 RestTemplate，资源泄漏风险 -90%"
     - "动态线程池"
     - "代理逐层剥离"
     - "11 个类 Lombok 化"
   - 原因：这四条代码里不存在，写进简历就是自设陷阱

4. **autoExcel 分类**
   - [ ] `mv 原始资料/AI项目/autoExcel 原始资料/自动化工具/autoExcel`
   - [ ] 或至少在你的项目清单里把它从"AI 项目"移到"业务自动化"

**验收标准**：README 和材料文档里没有不存在的功能声称

**停手线**：事实性错误改完就停，不做"顺便重写文档让它更清晰"

---

## 第二刀：补三个致命空洞（4-5 天）

### W2.1 eval 跑通一轮【P0 / 2-3 天】

**目标**：从"完全没有"变成"有 30 条用例、有 baseline 数字"

**不做**：达到 80% 覆盖、测 RAG 指标、做回归门禁

#### 子任务 1：扩充 golden set【1 天】

**路径**：`app/eval/cases.py`

**操作步骤**：

1. 用真实对话生成用例（这条路已经通了）
   ```bash
   # 启动 app，打开 trace 页面
   # 找一条成功的对话，点"保存为评测用例"
   # 填写 expected_tool_calls 和 tags
   # 重复 30 次（可以造一些变体：同样意图不同措辞、边界情况、容易混淆的工具）
   ```

2. 验证用例质量
   ```python
   # 在 Python REPL 里
   from app.eval.cases import list_eval_samples
   samples = list_eval_samples()
   print(f"共 {len(samples)} 条")
   
   # 检查覆盖面
   tools_covered = set()
   for s in samples:
       for tc in s.expected_tool_calls or []:
           tools_covered.add(tc['tool'])
   print(f"覆盖工具：{tools_covered}")
   ```

**停手线**：
- 30 条用例（不追求 50、100）
- 覆盖 6+ 个常用工具
- 每个用例有 `expected_tool_calls`

#### 子任务 2：接上 LLM-as-Judge【半天】

**文件**：`app/ui/settings_pages/eval_page.py`

**修改**：`:78` 左右找到 `_run_eval` 方法，把 judge_fn 参数从 `None` 改成真实调用

```python
# 原代码大约是这样
runner = EvalRunner(
    agent_loop_factory=...,
    judge_fn=None,  # 这一行
    ...
)

# 改成
from app.eval.judge import make_judge_fn

runner = EvalRunner(
    agent_loop_factory=...,
    judge_fn=make_judge_fn(provider="anthropic", model="claude-sonnet-4"),  # 用 sonnet，opus 太贵
    ...
)
```

#### 子任务 3：跑一轮产出报告【半天】

**操作**：
```bash
# 启动 app → Eval 页面 → 选全部 30 条 → Run
# 等跑完（可能要 5-10 分钟）
# 导出报告（CSV 或 JSON）
```

**整理成面试能说的数字**：
- 工具命中率：X%（expected_tool_calls 里列的工具是否被调用）
- 参数准确性：X%（judge 给的分数）
- 平均耗时：X 秒/turn
- 总 token：X，总成本：$X（这一项要等 W2.2 做完）

**验收标准**：
- `eval_runs` 表里有 ≥1 条 run，`judge_scores` 不再全 NULL
- 能回答"我用 30 条 golden set 测了，工具命中率 X%，参数准确性（judge 平均分）Y"

**停手线**：
- 跑通一轮、有数字就停
- **不做**：持续回归、多模型对比、按难度分层、做 CI 门禁

---

### W2.2 加成本核算【P0 / 半天】

**目标**：能回答"这个对话花了多少钱"

#### 步骤 1：数据库加列【10 分钟】

**文件**：`app/observability/trace_store.py`

1. 在 `_ensure_tables` 方法里，`llm_calls` 表定义加一列（大约 :150）
```python
cost_usd REAL,  # 加这一行，放在 cached_tokens 后面
```

2. 加一个 migration
```python
# 在 _ensure_tables 方法的最后，migrations 列表里加
{
    "version": 11,  # 假设现在最高是 10，你改成实际的下一个版本号
    "description": "add cost tracking",
    "sql": "ALTER TABLE llm_calls ADD COLUMN cost_usd REAL"
}
```

#### 步骤 2：调用 completion_cost【20 分钟】

**文件**：`app/llm/llm_gateway.py`

找到记录 usage 的地方（大约在 `_log_completion` 或类似方法里，搜 `INSERT INTO llm_calls`），加两行：

```python
from litellm import completion_cost

# 在已有的 usage 记录逻辑后面加
cost = 0.0
try:
    cost = completion_cost(
        model=model_id,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
    )
except Exception:
    pass  # 价格表缺失时不影响主流程

# INSERT 语句里加 cost 列
cursor.execute("""
    INSERT INTO llm_calls (..., cost_usd) VALUES (..., ?)
""", (..., cost))
```

#### 步骤 3：UI 显示【10 分钟】

**文件**：`app/ui/settings_pages/trace_page.py`

在已有的 turn 详情显示里加一行（搜 `total_tokens` 或 `latency_ms`）：

```python
# 查询时加 SUM
cursor.execute("""
    SELECT 
        COUNT(*) as call_count,
        SUM(prompt_tokens + completion_tokens) as total_tokens,
        SUM(cost_usd) as total_cost  -- 加这一行
    FROM llm_calls WHERE trace_id = ?
""", (trace_id,))
row = cursor.fetchone()

# 显示时加一行
detail_text += f"\n总成本: ${row[2]:.4f}" if row[2] else ""
```

**验收标准**：
- 新对话的 `llm_calls` 表有 `cost_usd` 非空
- trace 页面能看到"总成本: $0.0234"
- 能回答"平均每轮对话 $X"

**停手线**：
- 数字出来就停
- **不做**：成本预警、预算控制、按时间聚合、导出报表

---

### W2.3 接 tokenizer，修口径矛盾【P0 / 1 天】

**目标**：不再用字符估算，且修掉"估算时计入 tool_calls、送摘要时丢掉"的矛盾

#### 步骤 1：装 tiktoken【5 分钟】

```bash
cd /d/claudecode-projects/assistant
uv add tiktoken
```

#### 步骤 2：替换字符估算【1 小时】

**文件**：`app/conversation/consolidator.py`

```python
# 文件开头加导入
import tiktoken

# 在类初始化或模块级加一个缓存
_tokenizers = {}

def _get_tokenizer(model: str):
    """按模型获取 tokenizer，有缓存"""
    if model not in _tokenizers:
        # 简化：用 cl100k_base（GPT-4/Claude 通用）
        # 如果要更精确，可以按 model 前缀判断
        try:
            _tokenizers[model] = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _tokenizers[model] = None  # 回退到字符估算
    return _tokenizers[model]

# 替换 :40-44 的 estimate_tokens 函数
def estimate_tokens(text: str, model: str = "gpt-4") -> int:
    """估算 token 数量，优先用 tokenizer"""
    enc = _get_tokenizer(model)
    if enc:
        return len(enc.encode(text, disallowed_special=()))
    
    # 回退到字符估算
    chinese = sum(1 for c in text if '一' <= c <= '鿿')
    other = len(text) - chinese
    return int(chinese / 1.5 + other / 4)
```

#### 步骤 3：修口径矛盾【2 小时】

**问题定位**：
- `consolidator.py:48-52` 说"tool_calls 体量大，必须计入"
- 但 `:69-76` 的 `_messages_to_text` 只取 `content`，丢掉了 `tool_calls`

**修法**：让 `_messages_to_text` 也把 tool_calls 转成文本

```python
def _messages_to_text(messages: list, model: str) -> str:
    """把消息列表转成文本，包含 tool_calls"""
    parts = []
    for m in messages:
        role = m.get("role", "")
        
        # 1. content 部分
        content = m.get("content", "")
        if content:
            parts.append(f"{role}: {content[:500]}")  # 保持原有的 500 字符截断
        
        # 2. tool_calls 部分（新增）
        tool_calls = m.get("tool_calls", [])
        if tool_calls:
            for tc in tool_calls:
                func = tc.get("function", {})
                parts.append(f"[tool_call: {func.get('name')}({func.get('arguments', '')[:100]})]")
        
        # 3. tool 角色的结果（新增）
        if role == "tool":
            name = m.get("name", "")
            parts.append(f"tool({name}): {content[:200]}")
    
    return "\n".join(parts)
```

**注意**：这里不用完整序列化，保持摘要够用的长度就行（你原来是 500 字符，tool 部分给 100-200）

#### 步骤 4：max_context_tokens 按模型查表【1 小时】

**文件**：`app/conversation/consolidator.py` 和 `app/core/agent_loop.py`

```python
# consolidator.py 加一个模型上下文映射
MODEL_CONTEXT_LIMITS = {
    "claude-opus-4": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-haiku-4": 200_000,
    "gpt-4": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-3.5-turbo": 16_384,
    "deepseek-chat": 64_000,
    "deepseek-v4": 64_000,
}

def get_context_limit(model: str) -> int:
    """根据模型 ID 返回上下文限制"""
    for prefix, limit in MODEL_CONTEXT_LIMITS.items():
        if model.startswith(prefix):
            return limit
    return 60_000  # 保守默认值

# 在 should_consolidate 里用
def should_consolidate(self, messages: list, model: str) -> bool:
    limit = int(get_context_limit(model) * 0.7)  # 用 70% 作为阈值
    current = sum(estimate_tokens(self._messages_to_text([m], model), model) for m in messages)
    return current > limit
```

**验收标准**：
- 用 Claude 模型时阈值变成 140k（200k × 0.7），不再是硬编码 60k
- 能回答"我接了 tiktoken，按模型查表设上下文限制，摘要时 tool_calls 也计入了"

**停手线**：
- tokenizer 接上、口径对齐、按模型查表就停
- **不做**：AgentLoop 内的 token 预算控制（那是另一个 3 天的坑，需要在每次调用前裁剪 messages）

---

## 第三刀：顺手捡（1-2 天）

### W3.1 最小 onboarding【P1 / 半天】

**目标**：首次启动不再是空白窗口

**文件**：`app/ui/main_window.py`

在 `__init__` 或 `show` 方法里加：

```python
def _check_first_run(self):
    """首次启动检查"""
    from app.config.config import config_manager
    
    # 检查是否配置了任何 provider
    if not config_manager.get_litellm_models():  # 假设有这个方法返回配置的模型列表
        from PySide6.QtWidgets import QMessageBox
        
        reply = QMessageBox.information(
            self,
            "欢迎使用 Nemo",
            "检测到这是首次启动。\n\n"
            "Nemo 需要配置至少一个 AI 模型才能使用。\n"
            "是否现在打开设置页面配置？",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self._settings_window.show()
            # 自动切到 API 设置页
            # self._settings_window._switch_to_api_page()  # 如果有这个方法
```

**验收**：全新安装（删 `config/app_config.json`）→ 启动 → 弹窗引导 → 能直达设置

**停手线**：有引导弹窗就停，不做完整的 wizard/tour

---

### W3.2 修路径逃逸漏洞【P1 / 10 分钟】

**文件**：`app/tools/_path_utils.py`

```python
# :42 改成
def resolve_safe(target: Path, ws: Path) -> Path:
    resolved = target.resolve()
    # 用 is_relative_to 替代 startswith
    if not resolved.is_relative_to(ws):
        raise ValueError(f"Path escapes workspace: {target}")
    return resolved
```

**验收**：
```python
from pathlib import Path
from app.tools._path_utils import resolve_safe

ws = Path("/tmp/wsdemo/work")
try:
    resolve_safe(Path("../work_secrets/leak.txt"), ws)
    print("FAIL: 应该抛异常")
except ValueError as e:
    print(f"PASS: {e}")
```

---

### W3.3 加 ruff 到依赖和 CI【P1 / 1 小时】

```bash
cd /d/claudecode-projects/assistant
uv add --dev ruff
```

**文件**：`.github/workflows/tests.yml`

在 pytest 步骤前加：

```yaml
- name: Lint with ruff
  run: |
    uv run ruff check app tests --select E,F  # 只检查错误和未定义名称，不检查风格
```

**可选**：加 `pyproject.toml` 配置
```toml
[tool.ruff]
select = ["E", "F"]  # 只检查错误级
ignore = ["E501"]    # 忽略行长
```

**验收**：`uv run ruff check app tests --select E,F` 退出码为 0

**停手线**：能拦住下一个 `QTextDocument` 类问题就停，不追求零违规

---

### W3.4 外键约束 + 清孤儿数据【P1 / 1 小时】

**文件**：`app/storage/db_manager.py`

```python
# 在连接打开后立即执行（找 connect() 或 _get_connection()）
connection.execute("PRAGMA foreign_keys = ON")
```

**清理脚本**（一次性运行，不入库）：

```python
# cleanup_orphans.py
import sqlite3
from pathlib import Path

db_path = Path.home() / ".nemo" / "data" / "notes.db"
conn = sqlite3.connect(db_path)

# 清理孤儿标签关联
conn.execute("""
DELETE FROM note_tags 
WHERE note_id NOT IN (SELECT id FROM notes)
""")

# 清理孤儿标签（没有任何笔记引用的）
conn.execute("""
DELETE FROM tags 
WHERE id NOT IN (SELECT DISTINCT tag_id FROM note_tags)
""")

conn.commit()
print(f"Cleaned orphan rows: {conn.total_changes}")
conn.close()
```

**验收**：跑完脚本，`note_tags` 表没有指向不存在 note_id 的行

---

## 验收与停手

### 阶段 1 整体验收清单

在所有工单完成后，跑这个检查清单：

- [ ] **敏感信息**：`rg -i "sinotrans|122817|@2022latter|@2023|3602015019200888350" 原始资料/` 只在脱敏版文件有命中
- [ ] **崩溃修复**：笔记 Ctrl+F 不抛异常、工具生成能装带权限的工具、快捷键保存生效、日志文件存在
- [ ] **eval 数字**：能回答"我有 30 条 golden set，工具命中率 X%，参数准确性 Y"
- [ ] **成本数字**：能回答"平均每轮对话 $X"，trace 页面能看到总成本
- [ ] **tokenizer**：能回答"我接了 tiktoken，按模型查表设上下文限制"
- [ ] **onboarding**：删 config 重启有引导弹窗
- [ ] **CI 通过**：`uv run ruff check app tests --select E,F` + `uv run pytest tests -x` 都绿

### 明确的停手信号

当你发现自己在做以下事情时，**立即停止**：

- ❌ "eval 用例已经 30 条了，但我再加 20 条覆盖边界情况"
- ❌ "成本核算能显示了，但我再做个预算预警功能"
- ❌ "tokenizer 接上了，但我把 AgentLoop 内的预算控制也做了吧"
- ❌ "四个 bug 修完了，但笔记的那几个未接线功能我也修一下"
- ❌ "onboarding 弹窗有了，但我做个完整的 wizard 引导流程"
- ❌ "ruff 能跑了，但我把全部 499 个违规都修一遍"

**记住**：阶段 1 的目标是"每个被问到的模块都有数字支撑，不被一问就穿"，不是"项目完美无缺"。

10 月 1 日前，你需要的是：
- 70% 时间做阶段 1（代码）
- 30% 时间做阶段 2（简历+讲稿+试投）

如果阶段 1 做到第 14 天还停不下来，那就**强制停止，进入阶段 2**。因为有完美代码、没准备好怎么讲，面试一样会挂。

---

## 下一步

阶段 1 完成后，告诉我你实际花了多少天、遇到了什么卡点、哪些数字出来了。

我会基于实际情况，给你生成：
- **阶段 2 执行计划**（重写简历叙事 + 四组问题讲稿 + 试投策略）
- 或者如果时间不够，直接给你**压缩版的最小可行面试准备方案**

现在开始执行阶段 1。记住停手线。
