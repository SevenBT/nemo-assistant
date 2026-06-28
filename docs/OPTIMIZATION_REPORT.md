# 系统现有功能优化与深化报告

> 生成日期：2026/06/28
> 范围：`app/core`（核心业务）、`app/ui`（界面层）、`app/tools`（工具系统）、`app/eval` + `tests`（测试与评测）
> 方法：实际阅读源码，按文件:行号定位。本报告仅为分析，**未改动任何代码**。

---

## 一、总览与建议处理顺序

按"风险 × 收益"排序，建议分三批推进：

| 批次 | 主题 | 为什么先做 |
|------|------|-----------|
| **第 1 批（安全）** | 工具沙箱与网络防护漏洞 | 涉及任意代码执行 / 凭证泄露 / SSRF，风险最高 |
| **第 2 批（健壮性）** | 并发写竞态、Agent 循环死路、记忆白名单、trace 无限增长 | 都是会"静默损坏数据"或"埋雷"的问题 |
| **第 3 批（可维护性 & 体验）** | 超大文件拆分、UI 响应性、测试与 CI 补全 | 长期收益，不阻塞功能 |

下面按模块展开，每条标注 **优先级（高/中/低）**。

---

## 二、安全：工具系统（第 1 批，最高优先）

工具系统是 LLM 能触达真实系统的唯一出口，当前沙箱以"黑名单 + 字符串匹配"为主，对抗性不足。

### 高优先

- **[高] `script_adapter.py:164` 用户脚本继承全部环境变量**
  `env = os.environ.copy()` 把主进程所有 env（含 API Key、DB 连接串）透传给用户脚本子进程。与 `run_python.py` 的最小 env 策略相反，是明显的安全倒退。
  → 改为白名单 env，工具所需 config 通过 `stdin_payload["context"]` 显式注入。

- **[高] `fetch_url.py:136` 重定向可绕过 SSRF 校验**
  `follow_redirects=True` 无限制。外网 URL 可 302 重定向到 `http://192.168.1.1` 直达内网，而 SSRF 检查只在首跳做。
  → 对每一跳重定向目标都跑 `_check_url_safety`，或限制重定向次数 + 禁止跳转到私有地址。

- **[高] `exec_tool.py:94` Linux/macOS 用 `shell=True` 执行原始命令串**
  结合 LLM 生成命令存在注入风险（`; rm -rf /`）。
  → 改为 `["bash", "-c", command]` + `shell=False`，功能等价更明确。

- **[高] `exec_tool.py:69`、`run_python.py:102` 沙箱可越界**
  `cwd` 仅是初始目录，子 shell 可 `cd /`；`run_python` 的 `-I` 屏蔽了 PYTHONPATH，但 site-packages 全量可用，可任意读写文件系统、发网络请求。
  → 短期在文档/错误提示中明确局限；中期引入容器 / chroot 级隔离。

- **[高] `loader.py:144`、`tool_generator.py:195` manifest `script` 字段路径穿越**
  `tool_dir / manifest.get("script", "tool.py")` 若 script 为 `../../app/core/evil.py` 可执行任意文件。
  → parse / load 阶段校验 script 为合法文件名（无路径分隔符）。

- **[高] `exec_security.py:14` deny list 对抗性不足**
  仅约 12 条字符串规则，`r\m -rf`、base64 编码、`python -c "shutil.rmtree(...)"`、PowerShell `Remove-Item -Recurse` 均可绕过。
  → 转向 allow list 或"能力开关"模型（用户授权类别，而非逐条过滤）。

### 中优先

- **[中] `run_python.py:37` Windows env 白名单含 APPDATA/LOCALAPPDATA/ProgramData** —— 子进程可枚举凭证文件，建议收敛到 PATH/SYSTEMROOT/TEMP 最小集。
- **[中] `run_python.py:93` 超时后未显式 kill 子进程** —— Windows 上可能留孤儿进程，`except TimeoutExpired` 后补 `proc.kill()`。
- **[中] `fetch_url.py:64` DNS rebinding** —— 解析时校验通过、实际连接时切内网。需在 TCP 连接层验证实际 IP。
- **[中] `multi_model_consult.py:135` `execute` 内 `asyncio.run()`** —— 若已有运行中事件循环会抛 `RuntimeError`，建议改 ThreadPoolExecutor。
- **[中] `registry.py:252` `format_result` 整体截断破坏 JSON** —— 截断点可能落在 JSON 串中间产生非法 JSON，应先截断 data 内长字段再序列化。
- **[中] `script_adapter.py:271` 工具 name 无校验** —— 应限定 `^[a-z][a-z0-9_]{0,63}$`，防止污染 registry。
- **[中] `script_adapter.py:215` stdout 仅取最后一行且无大小上限** —— 大量输出可能撑爆内存。

### 低优先

- `web_search.py:204` DuckDuckGo HTML 解析依赖 DOM 结构，易静默失败 → 加空结果提示与 fallback。
- `web_search.py:88`、`schema.py:147/171`、`registry.py:143/216`、`loader.py:60`、`multi_model_consult.py:56`（名实不符："多模型"实为多角色单模型）等可维护性/扩展性改进。

---

## 三、健壮性：核心业务层（第 2 批）

### 高优先

- **[高] `agent_loop.py:127` 取消分支是逻辑死路**
  ```
  if self._cancelled: ctx.state = TurnState.FINALIZE
  if ctx.state is TurnState.DONE: break   # 永远 False
  ```
  `break` 永不执行。当前靠后续 handler 兜底，意图误导且状态机异常时有死循环风险。

- **[高] `agent_loop.py:416` 并发批结果可能含 None**
  `results = [None]*len(batch)`，若线程池 submit 失败某槽留 None，调用方 `for tc, result in batch_results` 会 `TypeError` 解包失败。

- **[高] `consolidator.py:83` token 估算漏算 tool_calls / tool 结果**
  仅拼 `m.content`，assistant 的 tool_calls JSON、tool 角色结果都没算进去，估算严重偏低，压缩可能晚触发一倍。

- **[高] `dream.py:165` UPDATE/DELETE 未校验 id 归属**
  直接用 LLM 输出的 id 调 update/delete，幻觉 id 静默失败，更严重的是可能误删 session 级记忆。
  → 执行前用 `{m.id for m in existing}` 做白名单校验。

- **[高] `scheduler.py:113` `_run_job` 不捕获工具异常**
  工具抛异常时 `_on_result` 不被调用，调用方无法感知失败。→ 捕获并通过 callback 上报 + `logger.exception`。

- **[高] `session_manager.py:38` 会话文件并发写竞态**
  `add_message`（AgentLoop QThread）与 `save_session`（UI 线程）可能同时写同一 JSON，产生损坏文件。→ 写锁 + 原子替换（临时文件 rename）。

- **[高] `trace_store.py:686` `prune()` 无自动触发**
  方法存在但无人调用，`traces.db` 会无限增长直到磁盘耗尽。→ 在 SchedulerManager 注册定期 prune，或启动时概率触发。

### 中优先

- **[中] `llm_gateway.py:558` 限流器 `_sleep` 阻塞整个 QThread**（含 Qt 事件循环），多线程唤醒后还可能空转。
- **[中] `llm_gateway.py:389` 单次 completion 无超时上限** —— 慢响应永久占 Semaphore 槽，饿死其他请求。
- **[中] `agent_loop.py:404` `_session_id` 就地注入 `ai_args` 污染引用** —— hook 拿到的 arguments 含内部键，与"LLM 不可见"设计不符。
- **[中] `agent_loop.py:155` done 信号正常/异常两条路径不对称** —— 易在维护时重复发信号。
- **[中] `memory_manager.py:149` 记忆全量加载** —— `SELECT *` 无 LIMIT，大记忆库不可扩展，缺向量相似度检索。
- **[中] `consolidator.py:47` 摘要前固定截断 500 字符** —— 漏掉消息后半（代码块/长文件）。
- **[中] `consolidator.py:95` keep_count 计算意图不清** —— 单条超大消息时可能算出 0/负数（有 max(...,4) 兜底但脆弱）。
- **[中] `dream.py:106` LLM 失败无退避** —— 持续不可用时每次 scheduler 触发都重复读同批 archives 失败。
- **[中] `scheduler.py:128`、`session_manager.py:38` jobs.json / 会话非原子写** —— 写一半崩溃即损坏。
- **[中] `note_manager.py:567` 迁移每次启动全表扫描** —— 应加迁移版本标记（`PRAGMA user_version`）。
- **[中] `note_manager.py:620` 搜索用 LIKE 全表扫描** —— 无 FTS5 全文索引，笔记多时退化。
- **[中] `note_manager.py:58` 标签 N+1 查询** —— 100 条笔记 = 101 次查询，应 JOIN 或批量 IN。
- **[中] `trace_store.py:759` 每次写都新建 SQLite 连接** —— 高频路径开销大，可用长连接（Lock 已覆盖竞争）。
- **[中] `conversation_prompt_builder.py:51` 时间提示 system 消息追加在末尾** —— 部分 provider 不规范，转发处理可能不一致。
- **[中] `conversation_prompt_builder.py:97` tool result 全量 `json.dumps` 无截断** —— 大结果占满上下文窗口、触发 Consolidator。

### 低优先

- `llm_gateway.py:615`（日志每次开关文件）、`memory_manager.py:197`（max_chars 硬编码未联动模型窗口）、`scheduler.py:27`（时区硬编码 Asia/Shanghai）、多处 `print` 替代 `logging`（`scheduler.py`、`session_manager.py`）、`dream.py:207`（查重 O(n²)）、`turn_context.py:71`（reset_turn 不清 error_message）等。

---

## 四、可维护性 & 体验：UI 层（第 3 批）

### 高优先（超大文件，违反 <800 行规范）

- **[高] `notes_dialog.py` 1325 行** —— 三个类 + OCR/拖拽/菜单/导出/文件夹/钉屏全混在一起。
  → 拆为 `note_item_delegate.py` / `notes_panel.py` / `note_actions.py` / `folder_manager.py`。
- **[高] `style.py` 1146 行** —— 15+ 主题色字典 + 超长 QSS 模板 + 逻辑混放。
  → 拆为 `themes.py`（纯数据）/ `qss_template.py` / `style.py`（逻辑精简到 100–150 行）。
- **[中] `screenshot_overlay.py` 949 行** —— OCR 布局重建算法与 UI 无关，抽出为 `ocr_layout.py` 即可降到 800 行内。

### 中优先（性能 / 内存 / 信号）

- **[中] `chat_widget.py:73` 流式每个 token 都全量 markdown 重渲染** —— 长回复在低端机卡顿。建议双阶段：流式用 `setPlainText` 追加，结束后再 markdown 渲染一次。
- **[中] `main_window.py:158` 字号变化每次全量重应用 1000+ 行 QSS** —— 拖滑块高频触发，建议 200ms debounce。
- **[中] `result_bubble.py:68` 划词快查每次新建 `LLMGateway`** —— 与主窗依赖注入复用不一致，且绕开 trace_sink（快查不被记录）。
- **[中] `chat_session_controller.py:436` lambda 连接 5 个信号无法显式 disconnect** —— 取消滞留的 worker 延迟完成时仍可能更新 UI。建议 `functools.partial` / 命名方法。
- **[中] `notes_dialog.py:462` `_apply_editor_font_size` 触发 textChanged 误启自动保存** —— 应 `blockSignals` 包裹。
- **[中] `notes_dialog.py:669` 切换笔记无 dirty 标记，每次都读写 DB + 全量重渲染** —— 快速上下键切换卡顿。加 dirty flag。
- **[中] `screenshot_overlay.py:95` RapidOCR 懒加载异常被后台线程吞掉** —— 用户看到永久转圈而非错误提示。捕获并发信号回主线程 toast。
- **[中] `notes_dialog.py:289` 钉屏窗口列表清理依赖 lambda，建议 weakref。**

### 低优先

- 重复代码：右键菜单逻辑（`sticky_note_window.py:366` vs `notes_dialog.py:1085`）、唤起主窗逻辑（`selection_controller.py:222` vs `main_window.py:404`）可抽公共工厂 / 公共方法。
- `main_window.py:80` 暴力清除 FluentWindow 默认 TitleBarButton 是黑盒操作，跨版本脆弱。
- `sticky_note_window.py:63` `_color_index` 全局可变状态，恢复已保存便签时会覆盖 DB 里的 `pin_color`。
- 右键菜单缺键盘可访问性（`Qt.Key_Menu`）。

---

## 五、测试与评测（第 3 批，工程基建）

### 现状

- `tests/` 下 **23 个测试文件，约 120–140 个有效用例**，集中在 eval 纯函数、selection、attachment、file_parser。
- **eval 系统已相当完整**：`cases`（trace→用例）、`runner`（重跑+打分+落库）、`rule_checks`（5 个零成本确定性指标）、`scorer`（离线补打分）、`metrics`（基线对比+方向感知）、`judge`（可选 LLM-as-Judge）。

### 核心模块零测试覆盖（缺口）

| 模块 | 优先级 |
|------|--------|
| `app/core/agent_loop.py`（系统核心循环） | 高 |
| `app/core/session_manager.py`（持久化） | 高 |
| `app/eval/runner.py`（评测主干） | 高 |
| `app/tools/exec_security.py` / `exec_tool.py` / `run_python.py`（高危执行路径） | 高 |
| `app/eval/cases.py` | 中 |
| `memory_manager.py` / `consolidator.py` / `trace_store.py` / `agent_hooks.py` | 中 |

### 工程基建缺口

- **[高] 无 `pytest.ini` / `[tool.pytest.ini_options]`** —— 无 `testpaths`，易扫到 `.venv` 第三方测试。
- **[高] 无 `.coveragerc`** —— coverage 把 `.venv`/`app/ui` 计入，数字失真。建议 `source=["app"]`、`omit=[".venv/*","tests/*"]`。
- **[中] 无 CI（`.github/workflows/`）** —— 测试只能手动跑，无 PR 门禁。建议 `pytest -q` + 用 marker 跳过需 QApplication 的 UI 测试。
- **[低] `test_imports.py` 无 assert** —— 永远通过（导入失败也只 print），应改为真 smoke test 或删除。

### 评测系统可深化

- 为 `cases.py` / `runner.py` 补测试（Fake AgentLoop + 真实 TraceStore，不发真实 LLM）。
- judge 一致率集成测试（Fake gateway 注入预设 JSON）。
- 评测维度扩展：目前 5 个确定性指标偏"过程正确性"，可增加"任务完成质量"维度（结合 judge）。

---

## 六、最小起步清单（如果只想先做几件）

1. **`script_adapter.py:164` env 白名单** —— 一处改动堵住凭证泄露。
2. **`fetch_url.py:136` 重定向 SSRF 校验** —— 补全已有防护的明显漏洞。
3. **`session_manager.py` 原子写 + 写锁** —— 防会话文件损坏。
4. **`trace_store.py` 注册定期 prune** —— 防数据库无限膨胀。
5. **`agent_loop.py:127` 修取消死路 + `:416` None 解包兜底** —— 核心循环稳定性。
6. **加 `pytest.ini` + `.coveragerc`** —— 几行配置，为后续测试铺路。

---

*以上均为分析结论，等待指令后再动手改代码。需要我对某个模块出详细修复方案或直接动手时告诉我。*
