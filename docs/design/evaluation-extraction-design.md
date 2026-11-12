# 评估模块独立化设计

> 日期：2026-11-09。
> 状态：核心拆分已实现；本文保留完整目标设计，实际支持范围与验证见第 15 节及 evals/README.md。
> 依据：当前工作区源码静态检查，包含尚未提交的 Agent / 上下文管理改动；不把旧设计文档当作现状。
> 本轮交付：独立评估包、无界面执行与 CI、运行记录界面迁移、旧库兼容和回归测试。

## 1. 已确认的产品决定

1. 普通用户界面移除评估页面和打分入口；保留运行记录、Token、估算成本与脱敏导出。
2. 评估工具位于同一仓库，具有独立 Python 包、配置和命令行入口；支持无界面 CI。
3. 确定性离线测试为 CI 必跑项；真实模型回归和独立 Judge 仅按需运行，首期不作为必跑发布门禁。

评估的主要使用者是应用维护者。首期不引入开发者模式评估页、用户模型排行榜、用户配置 A/B 页面或独立仓库。普通用户不需要维护回归集，也不因正常聊天被自动调用 Judge。

## 2. 目标和可验收的边界

- 应用负责真实执行、运行观测和诊断导出；评估工具负责用例、验收、Judge、比较与报告。
- 应用安装和正常启动不依赖评估包；评估内核不依赖应用、Qt、用户配置或用户数据库。
- 评估应用本身时，通过适配器调用同一份生产 Agent、工具注册和可复用的提示词构建逻辑，不另写一套 Agent 循环。
- 最小 CI 环境不安装 Qt / Fluent Widgets / Windows 桌面自动化依赖，也能执行真实 Agent 加脚本化模型及受控工具的回归。仅不创建 QApplication 不算解耦完成。
- 输入、环境、证据、验收标准均版本化；缺失证据或执行异常不能被平均分掩盖。
- 不承诺真实模型输出逐字可复现。确定性模式保证可重复；真实模型模式保证条件可追溯、结果可审计。

## 3. 现状及具体缺口

| 位置 | 静态确认的行为 | 设计要求 |
| --- | --- | --- |
| `app/eval/runner.py` | 导入 AgentThread，同步调用 run，并读取私有 `_trace_id` | 适配器调用 Agent 的公开同步入口和公开运行结果 |
| `app/core/agent_context.py` | CancellationToken 来自 llm_gateway；gateway 导入 config，config 基于 QConfig | 清理传递性 Qt 依赖，不能只替换 AgentThread |
| `app/core/checkpoint.py`、`trace_store.py` | 模块级导入 config 中的路径常量 | 路径与存储由组合入口注入，导入不读取桌面配置 |
| `app/core/llm_gateway.py` | config_proxy 只覆盖部分配置；采样参数、密钥及模型查找仍依赖全局 cfg | 显式、完整、不可变的网关配置；桌面配置转换放到桌面组合层 |
| `app/core/conversation_prompt_builder.py` | 模块级导入 cfg，视觉支持也回查桌面 config | scenario 使用同一构建器，但配置、视觉能力、记忆与会话读取显式注入 |
| `app/eval/cases.py` | 丢弃多轮上下文；成功工具调用集合被自动作为 expected_tools | Trace 只能生成草稿；预期由维护者明确编写和审核 |
| `app/eval/runner.py::_build_messages` | 有 prompt_builder 时只用单条 user 输入重建，优先于保存的 api_messages | 明确回放模式，不能静默重建或降级 |
| `app/eval/judge.py`、`scripts/eval/run_eval_with_judge.py` | Judge 看问答，脚本复用被测网关；标准答案和工具证据未进入评判 | 独立 Judge 配置、结构化证据与任务验收条件 |
| `app/eval/runner.py`、`app/eval/metrics.py` | 用例异常被记录后跳过，只对已有数值求均值，仍完成 run | 每个计划用例必须有终态；区分失败、错误、不适用与未评判 |
| `app/eval/rule_checks.py` | completed 等同 Trace status=ok；重复调用被命名为不必要调用；JSON 校验针对落库后的字符串 | 将运行观测与任务达标分开；指标准确命名并注明局限 |
| `app/core/trace_store.py` | 观测和评估共库；写入吞异常；字段通常截断到 2000 字符 | 用户观测可 best-effort，评估证据和结果必须严格持久化；不能依赖截断 Trace 作为完整证据 |
| `app/ui/settings_window.py`、`app/ui/settings_pages/trace_page.py` | 用户可见评估页、打分、保存回归用例、评估详情 | 移除评估操作和评分展示，保留诊断能力 |
| `pyproject.toml`、`.github/workflows/tests.yml` | Qt 属于根运行依赖，现有 CI 为 Windows 全依赖测试 | 增加独立无 Qt 离线作业；保留现有桌面测试 |

以上为实施前的静态检查结论；实施验证记录见第 15 节。

## 4. 目录与依赖方向

建议目录如下，均为待实现结构：

```text
app/
  core/
    agent.py                    # 共用生产执行核心
    agent_context.py
    agent_interface.py
    cancellation.py             # 无 Qt 的取消令牌
    runtime_config.py           # 网关配置值对象和运行路径
    llm_gateway.py              # 配置显式注入
    trace_store.py              # 用户运行观测，无评分职责
    diagnostics.py              # 诊断包导出与脱敏
  ui/                           # 桌面配置到运行对象的组合入口
evals/
  pyproject.toml                 # 独立工具包 nemo-eval
  uv.lock                       # 评估环境依赖锁定
  src/nemo_eval/
    contracts.py                # 用例、执行结果、检查结果
    runner.py                   # 编排，不导入 app
    checks.py                   # 确定性检查
    judge.py                    # 证据驱动 Judge
    artifacts.py                # 严格写入结果与证据
    comparison.py               # 显式基线比较
    cli.py
    adapters/
      nemo.py                   # 此包唯一允许导入应用执行模块的位置
      legacy.py                 # 旧 DB 只读导入与格式转换
  cases/                        # 版本化 JSON 用例
  fixtures/                     # 文件、记忆、工具和模型脚本
  configs/                      # offline / live / judge 示例配置
  tests/
scripts/eval/                   # 迁移期间只保留兼容入口和说明
artifacts/eval/                 # gitignore，默认本地运行产物
```

依赖图：

```text
桌面组合层 ──> 生产 Agent / 网关 / 工具 / TraceStore
                                    ↑
nemo_eval.runner ──> Executor 协议 <── nemo_eval.adapters.nemo
        │
        ├──> 确定性检查与报告
        └──> Judge 协议 <── 独立 Judge client
```

应用任何模块都不导入 nemo_eval；nemo_eval 内核不导入 app。适配器是组合根，可以同时依赖两侧。契约属于评估包，生产 Agent 提供自己的中性运行结果，由适配器转换；不让生产代码实现一个来自评估包的类型。

### 4.1 安装与无界面执行

根包继续使用现有名称 nemo-assistant。将运行依赖整理为：

- 默认依赖：执行核心和无界面网关实际需要的库。
- `desktop` extra：Qt、Fluent Widgets、OCR、键鼠和 Windows 桌面集成等 UI 启动依赖。现有桌面安装、打包与 CI 显式选择该 extra。
- 根 `dev` extra 保留桌面开发测试依赖；评估项目自己的 `dev` extra 不依赖 pytest-qt。

评估项目通过 uv 本地 path source 引用仓库根包，不启用 desktop extra；两边更新锁文件。现有应用发布仍安装完整桌面依赖，用户下载的可执行文件不受影响。需要同步更新 README 中的源码启动命令、Windows 打包流程和开发脚本，不能只改 pyproject。

首期不把整个运行核心搬到新仓库，也不复制 app 源码到评估包。Qt、系统密钥库、个人配置与系统路径的适配留在桌面组合层。CancellationToken、运行路径和 CheckpointStore 先解除全局配置依赖；AgentContext 依赖网关协议，具体 Gateway 通过参数传入。

工具采用显式清单注册，复用生产工具实现和 ToolRegistry，不在评估中自动发现所有桌面工具。涉及平台能力的工具标注能力要求，由专门 Windows 集成测试覆盖；缺少能力的已选用例报配置错误，不静默跳过。最小离线套件只选择跨平台可运行的能力。

## 5. 普通用户侧保留什么

### 5.1 运行记录

保留会话关联、运行状态、模型、耗时、输入/输出/缓存 Token、工具调用及错误详情。界面使用“运行结束”“工具成功”“工具失败”等事实性名称，不给出缺少任务标准支持的“质量分”或“任务已达标”。

费用沿用现有成本计算与 llm_calls 记录，补齐界面展示和聚合语义：

- 展示“估算费用”和货币单位；不要冒充供应商账单。
- 缺 usage 或无模型价格时显示未知；明确已知部分、未知调用数与计价来源，不能将未知当零。
- 按 attempt 唯一标识去重；只累计已返回的实际 usage。重试耗费计入，不能把最后一次 usage 当成所有尝试的总量。
- Trace 费用只覆盖已关联的调用。后台整理、工具内部模型调用等未关联支出不得被呈现为已包含；首期至少展示统计范围与完整性。
- 历史费用保存计算结果及定价来源/版本；不因当前价格变化静默改写历史记录。

### 5.2 移除的入口

- 设置导航中的 EvalPage 和后台评估 worker。
- TracePage 的打分按钮、保存回归用例按钮、评估分数与评估专用标签页。
- 普通应用对 app.eval 的调用及相关依赖注入参数；清理双语文案、用户文档和打包引用。
- settingsPage 原以序号保存，删除页面后需校验索引范围并回退到有效页面。

若迭代答复和计数仍用于诊断，将 EvalHook 改为中性的 IterationTraceHook；数据归入迭代记录，不含 scores，也不导入评估逻辑。旧 eval_samples 兼容方案见第 11 节。

### 5.3 脱敏诊断导出

用户选中一次运行后本地导出诊断 JSON 包；不自动上传、不自动变成有效回归用例。包中包含 schema_version、应用版本、运行摘要、已脱敏事件、脱敏项清单和完整性标记。密钥、用户目录等敏感标识递归替换，文件/笔记正文和附件原文默认不导出。导出前给出内容预览和删减能力。

诊断包与可执行评估用例是两种对象：前者帮助定位，后者需要完整初始条件和人工确认的验收标准。缺上下文时允许导出诊断，但必须标记不可重放；不能静默用最近一条用户消息补成“可复现用例”。

常态不为评估额外保存所有完整 Prompt、记忆和文件正文。需要精确捕获时，维护者提前使用显式 replay capture 模式，在隔离环境保存执行前快照；首期不新增普通用户常开捕获功能。

## 6. 用例契约与多轮场景

### 6.1 用例最小字段

| 字段 | 含义 |
| --- | --- |
| schema_version、id、revision | 稳定标识及格式/内容版本，标题不作为唯一键 |
| status | draft / reviewed；仅 reviewed 可加入默认门禁套件 |
| tags、capabilities | 场景分类、平台及所需能力 |
| input.mode | snapshot 或 scenario，必须显式指定 |
| input.messages / steps | 固定消息快照，或多轮交互步骤 |
| fixtures | 文件、附件、记忆、数据库、工具响应、固定时钟等初始条件 |
| expectations | 必须满足的任务结果、允许变化范围及工具行为 |
| reference | 可选参考答案和来源；开放任务可只提供明确 rubric，不强求唯一标准答案 |
| limits | deadline、最大 Agent 迭代数、工具调用数、模型预算等 |
| provenance | 人工编写 / 诊断导入 / 旧 DB 导入、来源及审核说明 |

### 6.2 两种输入模式

**snapshot：固定模型输入。** 保存该次目标执行开始前的完整 API messages，包含 system、历史 assistant/tool 消息、当前 user 和对应附件引用；保留 role、tool_call_id 及关联关系。直接传入，不再调用 prompt_builder 重建。这种模式验证固定输入下的执行行为，不能用于证明新提示词构建逻辑正确。

**scenario：重建当前应用行为。** 从版本化会话与环境初态开始，依次提交用户消息、必要的人工输入和中途注入事件；使用当前生产提示词构建和上下文管理逻辑，承接前一步实际输出，按步骤和最终产物验收。记忆、时间、工具清单和审批响应全部显式注入，不读取个人会话或记忆。

每步可包含预期的中间检查。缺参数询问由脚本在触发对应事件后提供响应；用例未声明响应时返回 input_required 并终止该例，不能无限等待 UI 或自动授权。Agent 的 iteration 与用户对话 step 分开编号。

scenario 未实现前只能运行 snapshot 套件；不能把单轮快照标成已覆盖多轮会话。回归新 Prompt 的核心套件必须在 scenario 支持后编写，不把旧 system 快照结果误当作新 Prompt 验证。

### 6.3 用例示例（设计格式）

```json
{
  "schema_version": 1,
  "id": "file-update-followup",
  "revision": 1,
  "status": "reviewed",
  "tags": ["multi_turn", "file_write"],
  "capabilities": ["workspace_files"],
  "input": {
    "mode": "scenario",
    "steps": [
      {"id": "read", "user": "读取 workspace 中的 plan.txt"},
      {"id": "update", "user": "把刚才那个文件的日期改为 2026-11-10，保留其他内容。"}
    ]
  },
  "fixtures": {
    "workspace_files": {"plan.txt": "日期：2026-11-09\n负责人：甲\n"},
    "memory": [],
    "clock": "2026-11-09T09:00:00+08:00",
    "tool_profile": "workspace-files",
    "model_script": "file-update-followup"
  },
  "expectations": {
    "tools": {
      "required": [{"name": "read_file", "step": "read", "outcome": "success", "min_calls": 1}],
      "forbidden": []
    },
    "artifacts": [{
      "path": "plan.txt",
      "check": "text_equals",
      "expected": "日期：2026-11-10\n负责人：甲\n"
    }]
  },
  "limits": {"deadline_seconds": 30, "max_iterations_per_step": 6},
  "provenance": {"source": "maintainer_authored"}
}
```

示例只说明结构，实际套件先校验工具 profile 与当前注册名，不直接照搬旧脚本中的工具名称。文件修改用最终文件内容验收；只有任务确实要求特定工具时才约束工具名，允许实现通过等价的合法路径完成任务。

### 6.4 不再把历史行为当成标准

- imported Trace 的实际调用只进入 observed_tools，不自动填 required。
- required / forbidden / no_tools 必须可表达；空 required 只表示未要求工具，不表示禁止所有工具。
- required 默认要求指定调用成功；“发生过尝试”“被策略拒绝”“因不存在而失败”均可单独声明。包含工具名不等于执行成功。
- 工具匹配支持必要的参数子集、次数和局部先后约束；并发只读调用使用 call_id、父子关系或偏序关系，不强制一个不稳定的总顺序。
- 允许声明替代工具组；工具名命中率只作诊断，任务产物仍是主要验收依据。
- 参考答案不是让被测模型照抄的输入；独立保存在评估端。拒绝、追问等任务可以用行为 rubric 和禁止副作用验收。

## 7. 执行接口与证据

评估内核只要求 Executor 提供两个概念接口：

```text
validate(case, run_config) -> ValidationReport
execute(case, isolated_environment) -> ExecutionResult
```

ExecutionResult 至少包含：case_id/revision、attempt_id、输入/环境摘要、每步执行状态、最终回答、工具事件与结果、审批/拒绝事件、产物清单和内容摘要、模型调用及 usage、耗时、错误和 evidence_completeness。跨步保留完整关联。应用提供公开 trace_id 和必要的中性运行输出，适配器不读取 `_trace_id` 等私有属性。

证据直接由运行事件、返回结果及受控产物收集，不通过 TraceStore 截断字符串反推。评估运行可另写独立的诊断 Trace，但 TraceStore 是否启用不影响能否执行和打分。

保存策略：完整证据写本地受控产物，manifest 记录内容 hash、大小、媒体类型和清理策略；Judge 只接收经脱敏和裁剪的相关子集。不得将 2000 字符截断后的 JSON 当作完整工具结果或结构合法性证据。缺少必要证据时产生明确 error/abstain，不能自动判 pass。

输入校验同时检查 role/tool_call_id 完整性、附件引用存在性、fixture 路径边界、必需能力和验收字段。schema 不接受任意 shell/代码形式的检查表达式；首期仅用受控检查类型。

### 7.1 隔离与生命周期

- 每个 case/attempt 建独立临时目录、会话、记忆和数据库，禁止默认回落到用户 data、config、sessions、logs 及 keyring。
- 离线模式使用脚本化网关：返回确定的标准化流事件，必要时匹配请求角色、工具 schema 和调用参数；脚本不匹配或用尽即报错。实际执行同一生产 Agent 和受控工具。
- 首期串行运行用例；工具内部已有的并发机制继续覆盖。每次重试重建环境，不承接失败尝试产生的文件或记忆。
- 每例在独立 worker 进程中执行，软取消后超时终止；等待人工输入、模型流、工具、子进程均受统一 deadline 约束。清理进程树和临时资源，不只终止一个 Python 线程。
- 不自动注册任意用户脚本工具或打开个人数据库。文件工具限定在 fixture workspace；外部网络、桌面自动化、任意 shell 等由专门 profile 显式启用。
- 临时目录和超时机制不等于 OS 安全沙箱。具有逃逸能力的真实 shell/桌面工具仅在专用受限 runner 或 VM 运行；首期默认套件使用受控替身。
- 需要审批的任务复用生产执行策略，审批结果作为明确 fixture 记录，不通过全局 allow-all 绕过。

## 8. 验收、状态与指标语义

将执行和评判分成独立字段，避免一个 completed 混用两种含义：

| 层级 | 状态示例 | 解释 |
| --- | --- | --- |
| execution_status | completed / error / timeout / input_required / cancelled | 被测执行过程是否结束，以及如何结束 |
| check.status | pass / fail / error / not_applicable | 某项确定性验收的结果 |
| judge.status | scored / abstain / error / disabled | Judge 是否完成了有证据的评判 |
| verdict | pass / fail / inconclusive / error / skipped | 根据必需检查、执行完整性和套件策略生成的最终结论 |

执行层 completed 只说明流程正常结束。任务结果由 expectations 检查；正常返回但没写目标文件，必须 fail。特定错误恢复或拒绝场景可显式允许预期终止类型；未声明的异常、取消和超时为 error。

汇总优先级：未预期的执行异常或必需检查自身出错 -> error；存在已确定的必需检查不满足 -> fail；缺必要证据或必需 Judge abstain -> inconclusive；全部必需检查通过 -> pass。可选 Judge 出错保留独立 warning，不改写已通过的确定性结论。skipped 只用于预先明确的排除原因，不用于隐藏失败；已选择的必跑用例缺能力、缺结果或被跳过会使门禁不通过。

### 8.1 首期检查类型

- 文本/结构化结果：必要内容、明确禁止内容、受控正则、JSON schema。自然语言质量交给 rubric，避免大量依赖易碎的精确字符串。
- 工具行为：required / forbidden / no_tools、参数子集、成功/尝试/拒绝、次数及局部顺序。
- 最终产物：文件存在与内容、结构化文档、临时 DB 指定记录、未授权副作用为零。
- 多轮上下文：第二轮实际接收到第一轮信息，原工具消息和 call_id 未丢失；最终任务检查覆盖用户的指代和修订。
- 生命周期：输入等待、超时、取消、错误恢复和证据完整性。

### 8.2 观测指标不作为质量捷径

- completed 改名 execution_completed；保留工具成功率，但不将其等价为任务成功率。
- redundant_call_rate 改为 duplicate_call_rate。重复调用可能是必要轮询、恢复或复核，不自动认定“无用”。
- error_recovery_rate 不再只看 Trace status=ok；在明确标注恢复场景的用例中，以最终验收是否通过判断恢复。否则只能称为发生工具错误后执行正常结束的观测比例。
- JSON 参数格式检查使用模型原始参数或规范化前后的独立字段，不用存储序列化是否成功冒充模型输出是否合法。
- 用例级硬约束优先于平均分；不把质量、成本、安全和延迟混成无解释的总分。

### 8.3 分母与完整性

每轮报告必须同时给出 selected / attempted / finished / passed / failed / errors / inconclusive / skipped，以及每项指标的 applicable / evaluated / missing 数量。每个选中的 case 和预设 attempt 都要有记录；worker 崩溃时由父进程补 error 记录。不能仅聚合成功返回的 scores。

不适用不记零，不填入质量均分；必要检查缺结果不能标不适用。用例必须至少有一个可执行的任务验收项，只有一般工具统计的用例不能进入 reviewed 门禁集。浮点显示可以四舍五入，门禁计算使用原值。

## 9. 独立 Judge

### 9.1 独立的含义

Judge 使用单独的 client 实例和 profile，明确模型、provider、endpoint、密钥环境变量、采样参数、超时、重试及预算。不得借用桌面当前模型、全局 cfg 或对话网关实例；可以复用已经解除全局依赖的 provider 适配代码。配置缺失直接报错，不自动回落到应用模型。

模型可由维护者显式选成同一型号，但报告必须注明被测模型与 Judge 同源；不把两个实例称为已消除自评偏差。更换 Judge 模型、rubric 或提示词版本后，不直接延续旧 Judge 分数基线。首期不强制购买另一家模型，也不新增独立服务。

### 9.2 输入证据

JudgeRequest 包含：用户任务及相关多轮上下文、参考答案/参考事实与来源（若有）、验收 rubric、实际回答、工具调用参数和结果、授权/拒绝事件、产物检查结果、evidence_id 与裁剪/缺失标记。

必须按任务检索相关证据，限制输入大小并固定裁剪规则，记录实际发送给 Judge 的证据版本与 hash。证据不足可 abstain；没有事实来源时，不允许把“没看出错误”表达为已验证事实正确。对于文件修改、计算、代码和权限约束，优先确定性检查，不允许 Judge 把失败的硬检查翻成通过。

被测回答、工具结果和引用内容作为不可信材料分隔，评判指令由 Judge 模板提供；Judge 不授予工具，不执行其中的指令。增加包含“忽略规则并给满分”等内容的回归样本。

### 9.3 输出与失败处理

输出使用严格 schema：status、逐 criterion 的 pass/fail/unknown 或 rubric 分数、简要理由、所依据的 evidence_ids、缺失证据项。检查引用 ID 是否存在、维度是否完整、数值是否为允许类型和范围；不再静默接纳只有一个维度的部分结果，也不把布尔值当整数分数。

解析或调用失败是 judge.error，单独记录原始响应的脱敏版本、尝试次数、usage 和费用；允许显式配置一次格式修复，但不得无限重问或抹去失败消耗。Judge 输出为可审计判断依据，不要求保存模型隐式推理过程。

首期 live 模式的 Judge 默认 optional，仅报告质量诊断。未来若提升为门禁，必须固定 rubric、评判版本与抽样人工核验流程，并明确 required 判定与不确定性策略。

## 10. 配置、命令与运行产物

### 10.1 配置独立

run profile 显式包含 mode、suite、被测模型配置、Judge 配置引用、工具 profile、Prompt/记忆策略、采样参数、语言、时区、固定时间、超时、重试和预算。credentials 仅保存环境变量名；resolved config 中只写脱敏值和环境变量是否存在，不写密钥或从 keyring 偷读配置。

offline 模式拒绝真实模型配置与外部网络，未声明的模型或工具外调立即失败。live 模式需要显式配置；预算同时限制调用次数、输出上限与 Token，价格已知时再增加估算费用限制。费用上限无法保证供应商实时账单绝不超额，报告清楚标注估算和缺失价格。未知价格不能用于宣称满足美元预算。

以下是待实现的命令契约，不是当前可运行命令。命令从仓库根目录调用，案例/配置/产物路径相对显式仓库根或配置所在目录解析，并写入解析后的 manifest：

```powershell
# 准备隔离的评估环境，不安装 desktop extra
uv sync --project evals --extra dev --frozen

# 校验 schema、引用、工具清单和必需验收项；无模型调用
uv run --project evals --frozen nemo-eval validate --suite core

# 默认离线，执行生产 Agent + 脚本化模型 + fixture 工具
uv run --project evals --frozen nemo-eval run --suite core --mode offline --out artifacts/eval/local-core

# 按需真实模型回归；该命令明确允许付费调用
uv run --project evals --frozen nemo-eval run --suite live-core --mode live --config evals/configs/live.toml --out artifacts/eval/local-live

# 复用既有执行证据，只增加独立 Judge 评判，不重新执行工具
uv run --project evals --frozen nemo-eval judge --run artifacts/eval/local-live --config evals/configs/judge.toml

# 只读比较；基线由调用者明确指定
uv run --project evals --frozen nemo-eval compare --current artifacts/eval/candidate --baseline artifacts/eval/baseline

# 旧数据库只读导出为草稿，不能直接进入必跑套件
uv run --project evals --frozen nemo-eval import-legacy --db data/traces.db --out artifacts/eval/import-drafts
```

--out 不允许覆写已有运行目录；重复尝试创建独立 run_id。judge 子命令创建新的 assessment 目录，保留原执行数据和旧 Judge 结果；report/compare 不触发模型调用。validate 不导入真实 provider、不读取密钥、不创建业务数据库。

命令退出码：0=所选策略通过；1=验收失败；2=用例/配置/基线不兼容或结果写入错误；3=执行/必需评判不完整或基础设施错误；130=用户取消。混合失败时报告保留全部原因，进程优先返回 2、3、1；不把打印了报告等同于通过。

### 10.2 产物布局

```text
<run-dir>/
  manifest.json           # schema、代码/数据/配置/环境指纹、计划运行清单
  cases/<id>/<attempt>/
    input.json            # 实际执行前输入快照，按捕获策略保存
    events.jsonl          # step/iteration/call 关联事件
    execution.json        # 执行状态、usage 和完整性
    checks.json           # 硬检查与证据引用
    artifacts/            # 受控产物与完整性 hash
  assessments/<id>/      # Judge 请求/响应、版本和独立用量
  summary.json
  junit.xml
  report.md
```

manifest 记录应用 Git commit、dirty 状态和受跟踪改动指纹、case/suite/fixtures hash、有效 Prompt hash、工具 schema 版本、依赖锁文件 hash、Python/OS/语言/时区、模型及请求参数和 Judge 模板版本。未跟踪但参与执行的资源也必须纳入内容指纹。密钥不参与持久化；供应商不支持固定模型版本时记录模型别名及调用时间，不宣称固定模型权重。

写入使用临时文件加原子替换，schema 校验后才标记运行完成。events 可以流式追加，最终 manifest 列出数量/hash；重启发现未完成运行时显示 incomplete，不将半份 summary 作为成功。结果写入失败要传出错误，不能沿用用户 TraceStore 的吞错策略。

成本按 target / judge / 其它辅助模型及 attempt 分账；显示已知费用小计、未知部分和 usage 来源。辅助模型包括 scenario 中被实际触发的上下文整理，不可漏记也不可与父调用重复计费。

本地产物建议默认保留最近 20 次完整运行，显式 pin 的基线除外；清理仅作用于工具管理且验证身份的目录，不删除外部路径。CI 产物建议保留 14 天，发布基线由维护者单独保留。完整输入和工具证据可能含测试数据，本地和 CI 上传分别使用策略；CI 只上传合成/已审核 fixture 数据与脱敏报告，不上传个人诊断包或密钥。

### 10.3 基线和重复运行

不再自动取“上一次运行”作为可信基线。先检查 suite/case 集合和版本、fixture、mode、评判版本及关键运行条件的兼容性，再比较同一 case_id + revision + attempt 计划的配对结果。用例增删必须列清，不能因少跑困难用例而让均分改善。

比较默认拒绝不兼容结果。比较模型或 Prompt 时允许显式声明变化维度；其余条件保持一致并在报告列出。真实模型重复次数和随机种子（供应商支持时）写入计划，所有尝试参与报告；失败重跑不是覆盖原失败。首期展示通过率、样本数和逐例差异，不从少量随机样本声称显著提升，也不沿用当前固定 5% 均分变化作为发布门禁。

## 11. 旧数据与代码迁移

原则：用户运行历史保留；旧评分不当作可信质量基线；迁移可重复、可回退。

1. 首先建立旧 schema 的只读导入器，使用 SQLite mode=ro 打开副本或源库，不实例化会自动初始化/迁移的 TraceStore。旧表列名 V1/V2 均显式映射。数据库忙、WAL 一致性或字段截断导致无法读取时报告错误，不默默产生空用例。
2. eval_cases 导入为 draft；旧 expected_tools 放 observed_tools，并记录其来源为旧成功调用基线。completion_note 保留为说明，不自动转为验收断言。旧 eval_runs/eval_results 可归档展示，但不参与新门禁。
3. 旧 api_messages 只有单条输入时标记 context_incomplete，不补造历史。旧库 `_to_json` 可能截断长字符串，因此检查 JSON 完整性；损坏输入保留原始脱敏文本和警告，不自动启用。标题重复不合并；用旧 case_id 和库来源指纹实现重复导入去重。
4. 引入 runtime schema V3：迭代观测归入中性的 iteration_records；从旧 eval_samples 幂等复制必要运行字段，排除 scores，保留 trace_id、迭代序号和迁移来源键。事务、备份和回滚遵循现有迁移机制；验证行数后提交。若备份/复制失败，不删旧数据。
5. fresh runtime DB 不再创建 eval_cases/eval_runs/eval_results/eval_samples。旧 DB 的历史评估表保留为 legacy，不自动 DROP；runtime get_trace/prune 只处理运行观测及必要的 legacy 兼容读取/限容，不通过评估包读旧表。新事件只写 iteration_records，避免双写。
6. 评估运行改为文件产物，不写用户 traces.db。完成调用方切换后移除 TraceStore 的评分/用例/回归 CRUD，将旧格式转换集中到评估工具的 legacy 适配器。
7. scripts/eval 的旧命令保留一个过渡版本，给出新命令和数据库导入说明；禁止将旧付费命令静默重定向到新的真实模型批跑，也不再默认写 data/traces.db。
8. 最后删除 app/eval 和 EvalPage，迁移仍有价值的纯规则测试，更新文档和打包。PyInstaller 成品不得包含 nemo_eval 与评估集。

历史迁移测试使用临时构造的库，禁止直接对用户 data/traces.db 执行测试。没有可靠 source-message 关联的旧 Trace 保持诊断材料定位；不把 _first_user_input 或会话最新消息当作所选 Trace 的历史输入。

## 12. CI 与验收用例

### 12.1 三种验证各自证明什么

| 层级 | 触发与环境 | 结论范围 |
| --- | --- | --- |
| 评估内核测试 | 每次 PR，最小无 Qt 环境 | schema、编排、检查、Judge 协议、报告和异常语义正确 |
| 离线生产回归 | 每次 PR，无密钥/禁外网，实际生产 Agent + 脚本化模型 + fixture 工具 | 执行、上下文、工具契约、失败恢复和产物检查未退化 |
| 真实模型回归 + 可选 Judge | 本地或手动 CI，显式模型配置和预算 | 指定条件下真实模型的任务表现；首期仅报告，不作为必跑门禁 |

离线模型脚本预设了模型行为，不能证明真实模型会选择正确工具。验证“本应调用但未调用”要同时具备：能发现缺调用的验收器负例，以及真实模型套件中的相应任务；离线测试只证明评估器能够判错。

### 12.2 CI 作业

- 保留现有 Windows 桌面 pytest 作业，安装 desktop/dev extra 并沿用 UI 集成验证。
- 新增 eval-offline 作业，评估独立环境不安装 Qt、qfluentwidgets、pytest-qt、pywin32、uiautomation 等；执行 schema 校验、评估内核测试和 reviewed core 套件。
- 新作业建议在 Linux 运行，直接检验无桌面平台依赖；对 platform-neutral 路径与文件检查同时在现有 Windows 测试中做代表性验证。
- 运行阶段阻断外部网络并移除真实模型凭据；依赖安装阶段可联网。包含价格表等 import 时联网路径也必须禁用或使用固定 fixture。
- 加入动态导入守卫：在干净进程禁止 PyQt6/qfluentwidgets/app.core.config 导入，再实际运行 Agent 和 scenario；不只 grep 直接 import。
- 加入依赖方向检查：app 不得导入 nemo_eval；评估内核不导入 app；适配器是唯一例外。
- JUnit 对 fail/error/inconclusive 和必跑缺项映射为失败或错误；不映射为 ignored。无论执行是否通过，都上传已脱敏 summary/JUnit/report，不吞主命令退出码。
- 真实模型手动作业只在可信分支及显式触发下取凭据，不能对不可信 PR 代码提供密钥；首期不创建定时作业。

### 12.3 首期必须覆盖的代表场景

| 场景 | 必须验证的行为 |
| --- | --- |
| 多轮指代和修改文件 | 第二步承接第一步上下文；最终文件内容正确，未修改字段保留 |
| 应调用却从未调用 | 即使 Trace 正常结束、回答声称完成，required 工具或产物检查仍 fail |
| 工具尝试但失败 | attempted 与 success 区分；失败不能算 required success 命中 |
| 明确不应调用工具 | no_tools/forbidden 能抓到任意多余或危险工具行为 |
| 等价合法路径 | 未约束的工具路径变化不误报；替代组正确计数 |
| 工具报错后恢复 | 临时错误 fixture 后成功；验证实际结果而非仅 Trace 状态 |
| 需要用户补参/审批 | 按脚本回应；未声明输入时有终态，无死等和自动授权 |
| 缺证据和 worker 异常 | 记录 error/inconclusive，计划分母完整，退出码非零 |
| Judge 证据协议 | 参考答案和工具结果进入请求；引用校验、abstain、非法输出和超时有独立状态 |
| Judge 被材料诱导 | 被测回答和工具结果中的评分指令不能改变评判规则 |
| 成本未知/重试 | 未知不记零，target/Judge 分账，重试保留费用且不重复累计 |
| 旧库导入 | V1/V2、重复导入、截断 JSON、缺上下文均有明确结果，源库字节不变 |
| 用户数据隔离 | 默认 data/config/sessions/logs 无写入；UI 导出不泄漏 canary secret |
| 基线不兼容 | 少跑用例、改 fixture、换 Judge 模板时拒绝伪装成可比改善 |

负例应通过真实检查器得到失败，不只对假设的分数做断言。例如让脚本化模型直接声称“已保存”但不调用工具，检查器必须捕获。Judge 离线测试使用可控 client 验证协议，不能冒充已证明真实 Judge 的抗诱导能力；真实模型套件另报告这类结果。

## 13. 实施顺序与每步交付

首期定义为以下五个增量全部完成；不把“先搬目录”视为完成。各步保持现有桌面应用可运行，测试与新实现一并交付。

| 增量 | 主要改动 | 验收与退路 |
| --- | --- | --- |
| 1. 明确核心边界 | 抽取 CancellationToken / 运行配置 / 路径与 checkpoint 注入；网关和 Prompt Builder 去 cfg；公开中性运行结果；拆 desktop extra | 无 Qt 环境可执行生产 Agent；原桌面入口通过显式工厂保持行为；桌面与无界面测试都通过 |
| 2. 独立离线工具 | 建 evals 项目、契约、worker、snapshot/scenario、严格证据和 artifact 检查、JSON/JUnit/Markdown 报告 | reviewed core 在隔离环境确定通过；缺调用、假完成、异常和缺证据负例确定失败；不读写用户库 |
| 3. 迁移产品与旧数据 | 运行观测 V3 与兼容导入；移除 UI 评估入口；保留 Token/费用并实现脱敏导出；旧脚本迁移说明 | 旧 Trace 仍可查看，原表不删；源库只读导入；fresh DB 无评估表；应用安装不需要评估包 |
| 4. 按需真实评估 | 独立模型 profile、真实网关、Judge、预算/成本分账、复用证据再评判、显式基线比较 | 无配置不调用真实模型；可控 client 测试覆盖失败语义；维护者显式配置后完成一次小规模 smoke，记录实际模型条件与支出 |
| 5. 接入 CI 和清理 | 无 Qt 离线作业、依赖方向守卫、完整性门禁、移除旧 app/eval、文档与打包更新 | PR 自动发现故意注入的漏调/上下文丢失；现有 Windows 测试保持通过；发布包不含评估工具；所有迁移链路可追溯 |

增量 2 依赖 1；3 在 2 的导入契约稳定后实施；4 不改变普通用户启动链路；5 将前述验证固化为必跑门禁。若暂时无法提供真实模型凭据，不伪造 smoke 结果：离线与协议验收完成，真实服务联通验收单独标明待运行，不影响无密钥 CI 的完整性。

当前 Agent / hooks / context_manager / consolidator 及相关测试有维护者未提交改动。实施增量 1 时基于这些实际接口做局部改造，不回滚、覆盖或顺手重写本次上下文管理工作。

## 14. 完成定义与后续范围

首期完成时应同时满足：

1. 用户能查看运行记录、Token 和范围明确的估算成本，能预览并导出脱敏诊断；界面不再出现评估/打分入口。
2. nemo-eval 作为同仓库独立包运行，应用到评估的反向依赖为零；最小 CI 环境无 Qt，执行的是同一生产 Agent。
3. 多轮与单轮模式明确，缺上下文不伪装成精确回放；预期不再从旧实际调用自动推导。
4. 工具证据、参考材料和最终产物参与验收，执行正常结束无法掩盖任务失败。
5. 每个计划用例/attempt 有终态；缺证据、异常、截断和 Judge 失败不被当作通过。
6. 按需真实评估和 Judge 独立配置、独立记账；不读个人配置，不在普通聊天或必跑 CI 自动付费。
7. 旧运行记录和旧库可安全兼容；新用例和结果不依赖用户 traces.db。
8. 文档、安装命令、锁文件、CI、打包和迁移测试一起更新。

后续有实际需求再考虑：用户配置对比页、定时 live 回归、Judge 校准与发布门禁、平台专用工具的 VM 套件、复杂 RAG/视觉任务评测，以及独立仓库发布。它们不属于首期交付。

本文的命令与目录是拟定接口，须在实施时通过干净环境验证；本次没有创建评估包，也没有执行本文拟定的新命令。



## 15. 实施记录（2026-11-09）

产品边界已按确认结果落实：普通设置移除评估页、打分与保存用例入口；
运行记录保留 Token、范围明确的估算费用和可编辑预览的脱敏诊断导出。
应用不再导入评估包，fresh runtime DB 不创建 eval_* 表。
旧数据库迁移前备份，事务化复制无评分的迭代观测，旧表保留；
只读导入工具把历史用例保留为 draft，把旧 expected_tools 标为 observed_tools。

evals/ 是独立可编辑 Python 包，使用自己的 uv.lock、nemo-eval CLI 和配置。
适配器调用生产 Agent.run_sync 与生产 PromptBuilder、read_file/save_file；
每例使用临时工作区、独立进程和 deadline。已在单独创建的无 Qt 环境安装，
边界检查确认不存在 PyQt6、Fluent Widgets、pytest-qt 和 Windows 自动化依赖。
同仓库的普通应用和评估锁均通过 uv lock --offline --check 校验，
未升级已有第三方包版本。

确定性用例覆盖不用工具、多轮读写文件、失败后改用备用文件；
测试另外覆盖“只说成功但未调用工具”、工具失败不算成功、局部顺序、
用例超时/异常仍计入完整分母、缺失证据、旧库迁移和导入、预算、
独立 Judge 的证据引用、脱敏、重复评判和显式模型条件比较。
GitHub Actions 增加 Ubuntu 无 Qt 离线作业，桌面测试和打包显式安装 desktop extra。
CI 仅上传合成用例的 summary/JUnit/Markdown，完整证据留在本地。

Judge 使用独立 profile/client，接收任务、参考事实、rubric、实际工具结果和文件产物；
默认是可选诊断。结构化输出与证据引用须校验，脱敏请求与响应单独存档。
target/Judge 分账，缺 usage/价格保持未知，正常应用聊天不触发 Judge。
本轮未配置或调用真实付费模型；live/Judge 的集成路径通过受控 client 测试，
真实供应商 smoke 尚未执行。

当前实现比完整目标设计收敛的部分（均显式拒绝或写明限制）：

- fixture 仅支持文本 snapshot / 顺序用户步骤、临时文本文件、记忆文本、
  固定时钟与工具阻断；尚无附件、笔记数据库、桌面交互、中途人工输入或
  上下文整理适配器。工具 profile 目前为 none / workspace-files。
- 首期预算约束调用次数与输出 Token 预留，provider attempt 固定一次；
  尚无输入 Token 或美元支出上限。用户运行网关本身仍支持重试并逐 attempt 记录。
- 证据不静默截断：单文件超过 2 MB 或 Judge 输入超过 60,000 字符会报错；
  尚无通用媒体证据选择/裁剪。完整本地运行目录目前手动清理。
- manifest 包含用例/配置指纹、Git commit、dirty/source hash、Python/OS 和产物
  hash；锁文件与未跟踪源码包含在 source hash 中，未实现通用媒体资源索引。
- 本地桌面全套回归的贴图 glow 像素用例在 offscreen 模式失败；
  在 HEAD 原始代码的独立目录中同样复现，未改动该无关组件。

实际命令和可用契约以 [独立评估说明](../../evals/README.md) 为准；
本设计中的更广 fixture/治理能力保留为扩展目标，不作为已交付功能描述。
