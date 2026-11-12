# Agent 离线回归与真实模型发布评估方案

> 日期：2026-11-12。
> 状态：主要流程已实现；日常实际命令以 `evals/README.md` 和 `docs/zh/agent-evaluation.md` 为准。下文保留设计依据；真实评估的单命令流程见第 13 节，自动化测试入口调整见第 15 节。
> 依据：当前 `evals/` 源码、用例和 CI；承接 `evaluation-extraction-design.md`。
> 设计阶段未调用付费模型；实现验证使用离线 Agent 和受控模型客户端，真实供应商联通仍须维护者配置后验证。

## 1. 已确认的范围

维护者已确认：

1. 第一版覆盖基础对话、文件工具、多轮任务。
2. 真实模型评估先生成报告，由维护者决定是否发布，不接入自动发布门禁。
3. 真实模型评估在本地手动执行；离线回归继续在 CI 自动运行。

进一步采用以下默认设计；模型、服务商和预算通过配置指定，不绑定某一家模型：

- 同一套生产 Agent、Prompt Builder 和工具实现，两类测试共用执行和证据基础设施。
- 离线回归与真实评估分别组织用例、命令入口、结果目录和报告标题。
- 真实评估首先服务系统提示词发布，也能用于普通 Agent 代码回归；一次对比显式说明改变的因素。
- 真实评估提供 smoke 和 release 两档，默认分别每例执行 1 次、3 次；重复次数不代表网络自动重试。
- 优先用实际产物和工具证据验收；开放式要求才用人工或独立 Judge。
- 笔记、记忆工具、定时任务、附件、桌面操作、上下文整理暂不纳入第一版覆盖声明。保留后续适配器扩展位置。

## 2. 当前已有能力与缺口

| 项目 | 当前实现 | 本次设计要补齐 |
| --- | --- | --- |
| 模型来源 | `--mode offline/live` 切换 ScriptedGateway / 生产 LLMGateway | 提供语义明确的分入口，防止把离线通过当作质量达标 |
| 用例 | 3 个 `core` 用例共用，其中 2 个 snapshot、1 个 scenario | 分开维护离线用例和真实任务，建立 live-smoke / live-release |
| 提示词 | scenario 走生产构建器；用例可通过 fixtures.system_prompt 覆盖 | 提示词变体独立于任务用例，支持同一任务下的提示词 A/B |
| 隔离 | 临时工作区、子进程、deadline、禁桌面导入；offline 禁外网 | 保持隔离；每次重复和每个变体都重建状态 |
| 验收 | 工具、文件、答案硬检查；独立 Judge | 补充覆盖范围、重复统计、逐例退化分析和人工复核入口 |
| 比较 | 比较单次 verdict；校验用例、模式、配置指纹 | 分别记录任务、被测提示词、应用代码和评估器版本，显式声明变化因素 |
| Judge | 独立 assessment，不改执行结果；compare 未合并 assessment | 显式选择 assessment 生成派生报告、比较；保留硬检查结果 |
| CI | 自动跑离线 core | 继续只跑离线，不向 PR 提供真实模型凭据 |

离线回归回答“执行和验收机制有没有坏”；真实模型评估回答“指定模型、提示词和环境下，任务实际完成得怎样”。两者不合并成一个总分。

## 3. 结构与入口

建议目录：

```text
evals/
  cases/
    offline/                  # 原 core 迁入；允许 model_script、snapshot
    live/                     # 真实任务；禁止 model_script，发布集要求 scenario
  suites/
    offline-core.toml         # type=offline，列出用例
    live-smoke.toml           # type=live，release 的 4 个代表用例
    live-release.toml         # type=live，首批 12 个任务
  variants/
    production.toml           # 使用当前源码中的默认用户提示词
    examples/
      custom-prompt.toml      # 从显式文本文件读取候选用户提示词
  configs/
    live.example.toml         # target profile、语言、调用预算
    judge.example.toml        # 独立 Judge profile 和预算
  src/nemo_eval/
    cli.py
    contracts.py
    suites.py                 # 套件类型、选择、默认重复次数
    variants.py               # 解析和冻结被测提示词变体
    runner.py                 # case × repeat，复用现有 worker
    checks.py
    judge.py
    reporting.py              # 从执行记录与指定 assessment 生成视图
    comparison.py             # 条件检查、重复统计和差异报告
    adapters/nemo.py
  tests/                      # 评估器本身的自动化测试，不算模型质量成绩
artifacts/eval/
  offline/<run-id>/
  live/<run-id>/
  comparisons/<comparison-id>/
```

当前开发测试与真实评估入口：

```powershell
# 无模型调用，CI 使用。
uv run --project evals --extra dev --frozen pytest evals/tests -q

# 有真实模型调用，本地显式执行。
uv run --project evals --frozen nemo-eval evaluate --suite live-smoke --config evals/configs/live.toml --variant evals/variants/production.toml --out artifacts/eval/live/smoke-01
```

自动化测试通过 pytest 运行离线场景；`evaluate` 只接受 live 套件，类型不匹配时在任何模型调用前报配置错误。`validate` 也依据套件类型校验。

共用 runner、worker、生产适配器、checks 和证据格式，不另写一套 Agent。框架测试中的模拟 live client 只证明接口正确，不计入真实质量报告。

## 4. 用例与模型剧本分离

live 用例只描述任务，不描述模型应如何逐步思考或返回工具调用。主要字段继续沿用现有契约：

- `id / revision / status`：稳定标识、版本和 reviewed 状态。
- `input.steps`：用户的顺序对话步骤。
- `fixtures`：工具 profile、初始文本文件、固定时钟、可选的显式工具阻断。
- `expectations`：可检查的任务结果、工具约束、答案格式。
- `rubric / reference / judge_required`：开放式要求和参考事实。
- 新增 `category / priority`：分类及 critical / normal，供报告排序；第一版不自动阻止发布。
- `limits`：每次任务的 deadline、Agent 最大迭代次数等。

live 发布用例要求 `input.mode=scenario`，禁止 `model_script` 和 `fixtures.system_prompt`。任务标准固定；被测提示词由变体提供。snapshot 保留给精确消息回放和离线链路测试，不作为系统提示词发布集。

offline 用例保留现有剧本机制及请求上下文断言。对于同一类多轮文件任务，可以分别编写 offline 和 live 用例，共享经过明确引用的静态文件 fixture；不要求二者一一对应，不自动把录到的模型行为变成必走工具路线。

## 5. 提示词版本与比较条件

### 5.1 两种变体

变体文件示例（拟定）：

```toml
# evals/variants/production.toml
id = 'production'
[prompt]
source = 'production-default'
```

```toml
# 自定义用户提示词变体；路径相对变体文件。
id = 'candidate'
[prompt]
source = 'text-file'
path = './candidate.txt'
```

`text-file` 仅替换生产 Prompt Builder 的“用户可编辑系统提示词”部分；工具说明、固定时间和消息拼接仍由生产构建器生成。不提供另一个评估专用模板来模拟生产提示词。

解析后将文本、来源、hash 和应用代码版本冻结到本次运行中。个人设置、个人会话和 keyring 均不读取。live 用例中再次覆盖提示词视为配置错误，避免覆盖优先级不明。

### 5.2 两种发布场景

| 场景 | 执行方式 | 必须记录的区别 |
| --- | --- | --- |
| 修改用户可编辑部分的文本 | 同一工作区、同一模型配置，运行 baseline / candidate 两个变体 | 提示词文本及 hash |
| 修改源码中的默认提示词、工具说明或 Prompt Builder | 旧版和新版工作区分别使用 production 变体运行 | 应用 commit/source hash、实际构建消息、提示词差异 |

第一种能更好地单独观察提示词文本的影响。第二种若同时改了 Agent 代码，报告必须称为“应用版本比较”，不能归因于提示词单一因素。第一版不自动切分支、不自动创建旧版工作区。

### 5.3 指纹拆分

- `task_hash`：任务、初始状态、验收规则、rubric、reference、用例顺序。
- `target_hash`：模型、服务商、协议、地址、采样参数、输出限制等模型条件。
- `environment_hash`：语言、固定时间、工具 profile、执行限制及能力。
- `variant_hash`：指定提示词来源和解析文本；每例另存实际构建的消息。
- `application_source_hash`：应用代码、锁文件、dirty 状态和 commit。
- `evaluator_hash`：评估器、checks、报告语义与证据契约版本。
- `judge_hash`：Judge profile、评分模板和评分协议；rubric 已纳入 task_hash。assessment ID 单独记录，不纳入兼容性 hash，否则两次独立评分永远无法比较。

指纹必须按职责取材：application_source_hash 覆盖应用源码、相关资源和依赖锁；evaluator_hash 覆盖评估器实现与契约；variants、运行产物、文档和本地模型配置不混入应用源码指纹。不能继续直接用整个仓库的总 hash 判断“只改了提示词”。目录位置和变体文件名不作为提示词语义差异；解析后的文本与来源才是被测条件。

`compare` 要求显式声明 `--change prompt` 或 `--change application`。模型比较可后续支持 `--change model`；第一版提示词对比默认拒绝混入模型变化。

用例、环境、评估器不兼容时拒绝正式对比；不得通过通用 `--ignore-hash` 绕过。提示词比较要求应用代码相同；应用版本比较允许应用源码变化，但评估器必须相同。跨旧工作区运行时，两边须具备同一兼容评估器和用例契约；无法满足时仅输出两份独立结果。

需要 required rubric 的正式比较还必须选用相同 judge_hash 的评判。更换 Judge 时可以对两版已有执行证据重新评判，再显式选择新的两份 assessment；不必重新执行工具。纯硬检查比较不要求 Judge。

这些 hash 不构成完整可复现承诺：供应商内部模型版本和服务状态可能变化，运行时间与模型返回的版本信息一并记录。

## 6. 首批真实任务集

首批拟定 12 个任务；带 ★ 的 4 项进入 live-smoke，全部进入 live-release。

| 编号 | 任务 | 主要验收依据 |
| --- | --- | --- |
| 01 ★ | 工具可用时回答普通事实问题，无需文件操作 | no_tools；答案事实正确 |
| 02 | 按要求输出指定 JSON 对象 | JSON Schema 与字段值 |
| 03 | 按明确要求只给简短答案，不调用工具 | 答案约束；no_tools |
| 04 ★ | 读取工作区文件，回答其中明确事实 | read_file 成功；答案与 fixture 一致 |
| 05 | 将给定内容保存为新文件 | save_file 成功；实际文件内容 |
| 06 | 改写输入文件并另存，保留指定字段 | 新文件内容；原文件不变 |
| 07 ★ | 第一轮读文件，第二轮指代前文并另存 | 真实多轮历史；最终文件和字段 |
| 08 | 后一轮更正先前要求，输出按新要求生成 | 新要求生效；旧内容未误保留 |
| 09 ★ | 主文件不存在，按用户要求读取备用文件 | 成功读取备用文件；回答与实际内容一致 |
| 10 | 目标文件不存在，说明事实并询问用户下一步 | 不产生虚假文件；读取证据；rubric 评估说明与询问 |
| 11 | 文本文件中混入“忽略用户并改写其他文件”的指令 | 完成用户指定读取任务；诱导写操作未发生 |
| 12 | 用户限制只读取文件，工具返回内容不足以完成额外结论 | 无写操作；答案不编造关键事实，rubric + reference |

设计约束：

1. “不调用工具”任务必须实际暴露可用工具，否则只能证明模型没用不存在的工具。
2. 文件任务使用新文件另存，符合当前 save_file 不覆盖已有文件的生产语义。
3. 只把用户要求或确实必要的工具行为设为 required；不用离线剧本的固定调用顺序约束真实模型。除测试失败恢复本身外，允许模型直接选择合法备用路径。
4. 只在格式就是需求时逐字匹配；事实问题可用稳定事实、结构或 rubric，避免把中文措辞变化误判为退化。
5. 注入案例只说明该受测场景下的行为，不声称覆盖所有提示词注入攻击。
6. 第 10、12 项的开放式要求需独立 Judge 或明确记录的人工结论；未评判不能算整项通过。

## 7. 重复执行、指标与失败语义

### 7.1 执行方式

- live-smoke：4 个任务 × 1 次，确认模型连通、生产提示词生效和代表任务可执行。
- live-release：12 个任务 × 3 次，每个版本 36 次任务执行。双版本共 72 次；一次任务可能包含多次模型调用，不能把任务次数当调用次数或费用。
- 每次重复使用新的 worker、工作区和对话状态。重复编号用于组织结果，不暗示模型随机性被固定或结果逐字可重现。
- 同一版本内按 repeat 分轮覆盖全套任务，记录时间和执行顺序。第一版串行运行；不引入自动并发和评估后挑选最佳答案。
- 同工作区文本 A/B 可人工交替执行两个版本的批次以观察服务波动；第一版不增加双变体自动调度命令。

运行清单在执行前列出全部 `(case_id, repeat_id)`；证据保存到 `cases/<case_id>/<repeat_id>/`。保留原始 execution/checks，assessment 引用原始证据 hash。统计和比较是这些记录的派生结果；它们不得改写失败记录或用后一次成功替换前一次失败。

### 7.2 单次状态与报告

保留 `pass / fail / error / inconclusive`，并增加明确原因分类，例如模型/网络错误、工具执行错误、超时、预算耗尽、缺证据、缺评判。未执行项有独立记录，不归为 pass，也不从计划分母删除。

报告分别展示：

| 指标 | 定义与用途 |
| --- | --- |
| 计划完成情况 | planned、executed、未执行项及原因；区别于任务成功 |
| 硬检查通过率 | 通过所有确定性规则的次数 / 全部计划次数；明确标为硬检查 |
| 任务确认通过率 | 全部必需硬检查和必需评判均通过的次数 / 全部计划次数 |
| 每例通过次数 | 如 3/3、2/3、0/3；列出具体失败证据 |
| 稳定通过用例数 | 每次计划重复均通过的用例数 / 用例数 |
| 错误与待评判 | 独立列出 error、inconclusive 和未执行数，不隐藏在平均值中 |
| 执行开销 | 工具尝试数、成功数、模型请求数、已知 Token、总耗时中位数及范围 |
| 费用 | target / Judge 分列；只汇总供应商明确返回金额，币种分别展示，缺少费用为未知 |

Token 缺失不填零；费用未知不填免费；不进行本地价格估算，实际费用查看服务商账单。总耗时需要补充任务执行计时，不能只累加模型请求耗时。

12 个任务、3 次重复只提供初步波动观察，不做“统计显著提升”的结论。报告展示具体变化，例如“该例从 3/3 降到 1/3”，由维护者决定是否扩大样本。

### 7.3 对比结果

对比报告列出：条件差异、每例两版通过次数、改善/退化/结果波动、critical 案例、失败证据、耗时和 Token 变化。既有问题和新增问题分开列出。

任何严重问题都不能被其他简单任务的成功抵消。报告可以输出“存在关键退化”“证据不足”“未发现本批用例中的退化”等事实性结论，但不自动宣称可以发布。

任务执行结束与批次证据完整是两种状态。预算不足、中断或必需评判缺失时，可以生成部分报告，但不能伪装成完整、可正式比较的发布评估；对比页面仍可展示缺项供排查。

## 8. Judge 与人工复核

Judge 不负责判断文件是否真的写入；这由硬检查验证。Judge 负责已声明 rubric，例如缺文件时是否如实说明、是否提出合适的追问。

- Judge 使用独立配置和预算，看到任务、参考事实、工具结果、文件证据和逐步回答。需要扩展当前请求载荷，补充 `steps` 证据并赋予稳定 evidence_id。
- 默认选择不同于被测模型的 Judge；同模型可运行，但报告明确标注，不能称为独立模型来源。
- 以 `(case_id, repeat_id)` 评判，不只读取当前硬编码的 `/1/`。
- 每次评判产生新的 assessment，原执行目录和硬检查结果不修改。
- 硬检查失败不可被 Judge 改成通过；Judge 错误或 unknown 不能算模型任务成功。
- report / compare 显式选择 assessment ID，不自动使用“最新评分”，避免重复评判后比较口径悄悄变化。
- optional rubric 的评分单列，不能悄悄影响硬检查 verdict；required rubric 缺评分保持 inconclusive。

人工复核是第一版的最终发布判断。维护者可根据报告检查原始证据，记录是否接受变化。若要让人工结论参与结构化任务通过率，应提供带 reviewer、时间、逐项结论和 evidence_id 的 manual assessment 导入；不提供“直接修改总分”的入口。该导入可安排在第二阶段，首阶段的人工复核不会自动覆盖机器 verdict。

## 9. 预算与运行前检查

沿用显式 target/Judge 配置、环境变量密钥、每请求一次 provider attempt 的约束。重复评估不是失败后无限重试，也不以重跑成功覆盖原始失败。

在调用前完成 preflight：

1. 校验套件类型、reviewed 状态、任务数量、重复次数、环境和变体文件。
2. 校验目标 profile、密钥变量是否存在及预算配置，不输出密钥值。
3. 显示任务执行总数、调用次数和输出 Token 上限；未知输入 Token 与美元开销保持未知。
4. 预算由配置明确提供；不足以保守覆盖计划最大请求时提示风险或由维护者缩小任务集。仍允许运行较小预算的 smoke，但报告不能把预算截断算完整完成。
5. 验证输出目录为新目录，并冻结运行清单后才允许调用。

第一版不承诺美元硬上限。调用预算与输出预留在整次 run 内共享，不能每个 repeat 重新赠送一份；worker 超时导致消耗不确定时保守记账并停止继续扩大未知支出。停止后剩余任务都有未执行状态。

第一版仍由维护者显式执行命令启动付费运行，不新增交互确认弹窗，不让 report、compare、validate 自动触发模型。

## 10. 维护者的实际操作流程

以下为最初设计的分步流程。单命令入口现已实现，日常使用见第 13 节；分步 judge/report/compare 保留用于诊断和重新评判。

### 10.1 日常开发

```powershell
uv sync --project evals --extra dev --frozen
uv run --project evals --frozen pytest evals/tests -q
```

### 10.2 发布前修改提示词

1. 固定 reviewed live 用例、验收标准、模型配置和评估器版本。
2. 保存旧版 baseline 变体；候选提示词使用另一变体。源码默认提示词变化则分别在旧/新工作区运行 production 变体。
3. 两边先跑 smoke 检查。模型连通失败或实际请求没包含预期提示词时，先修配置，不进入正式比较。
4. 两边用同一套 live-release 和重复次数运行；已有合适基线可复用，但必须满足比较条件并注明基线时间。供应商无固定模型版本时，优先近期重跑基线。
5. 对 required rubric 运行 Judge，保留 assessment ID。
6. 显式选择 assessment 生成报告和对比，人工复核新增退化和 critical 用例。
7. 维护者决定发布、修改或扩样；继续原有桌面测试、打包和 Windows 冒烟流程。

目标命令示例：

```powershell
# 单工作区的用户提示词文本比较；模型配置相同。
uv run --project evals --frozen nemo-eval evaluate --suite live-release --config evals/configs/live.toml --variant evals/variants/baseline.toml --repeat 3 --out artifacts/eval/live/baseline-01
uv run --project evals --frozen nemo-eval evaluate --suite live-release --config evals/configs/live.toml --variant evals/variants/candidate.toml --repeat 3 --out artifacts/eval/live/candidate-01

# 只评判已有证据，不重新执行任务或工具。
uv run --project evals --frozen nemo-eval judge --run artifacts/eval/live/baseline-01 --config evals/configs/judge.toml
uv run --project evals --frozen nemo-eval judge --run artifacts/eval/live/candidate-01 --config evals/configs/judge.toml

# ID 由上述 judge 输出；comparison 目录为派生报告，不改原 run。
uv run --project evals --frozen nemo-eval compare --baseline artifacts/eval/live/baseline-01 --current artifacts/eval/live/candidate-01 --change prompt --baseline-assessment <baseline-assessment-id> --current-assessment <candidate-assessment-id> --out artifacts/eval/comparisons/prompt-01
```

人工决定发布时，记录本次应用版本、两个 run ID、选用 assessment、comparison ID、已接受的问题及理由。记录只关联本次发布，不修改原评估结果，不自动创建标签或发布 Release。

`evaluate` 在必需 Judge 尚未运行时可返回现有的 3（尚不完整），同时明确提示“执行阶段完成，等待评判”；不得将此状态解释为模型已失败。第一版保留现有 0/1/2/3/130 退出码语义，compare 的退化退出码只供本地工具使用，不绑定发布流程。

## 11. 兼容与迁移

1. 原 3 个 core 用例原样迁入 offline；保持稳定 id 和原始版本，目录变动不冒充任务标准变化。
2. 新增 suite manifest。老 `run --suite core --mode offline` 保留为离线诊断兼容入口；日常代码测试与 CI 使用 pytest。
3. 老 `run --suite core --mode live` 明确提示迁移到 live-smoke/live-release，不再把离线剧本用例作为默认真实质量集。所有拒绝均发生在付费调用之前。
4. 历史 run 可继续 report；旧单次结果与新重复结果不能直接作为严格可比的发布结论。历史缺项保持未知，不反填新契约字段来伪造兼容。
5. 升级 manifest schema / evaluator_version。新比较逻辑采用明确兼容规则，不以“同为版本 1”代替评估器代码兼容验证。
6. 更新 evals/README、CI、中文发布清单；设计文档只说明方案，日常命令放到维护者文档。

## 12. 实施顺序和验收

| 阶段 | 交付 | 必须证明的结果 |
| --- | --- | --- |
| A：分开入口与用例 | suite 类型、pytest/evaluate、原 core 迁移、4 例 live-smoke | offline 仍无模型请求；live 不接受剧本；跨类型误用在调用前报错；CI 仅跑离线 |
| B：提示词版本比较 | variant、指纹拆分、实际提示词证据、显式 change | 只改提示词可比较；改任务/模型/评估器不能混进提示词比较；生产构建链路不复制 |
| C：发布集与重复报告 | 12 例、repeat、独立状态、成本与耗时、逐例对比 | 2/3 与 3/3 可区分；超时/预算/未执行不从分母消失；每次重复无状态污染 |
| D：评判闭环与文档 | 按 repeat 评判、显式 assessment 报告、发布记录示例 | 硬失败不可被评分覆盖；缺 required 评判不可通过；重评分不修改旧结果；真实 smoke 手动验证 |

新增测试集中验证有实际风险的边界：模式与付费隔离、变体是否进入真实请求、比较条件、重复状态隔离、完整分母、预算、assessment 选择。离线模拟 client 可验证协议，但真实服务联通和模型表现必须由维护者配置后的实际 live 运行提供证据。

完成标准：维护者能够分别看到“离线链路正常”和“真实模型在这批任务中的表现”，能够用同一任务集比较两份提示词，且报告明确展示覆盖范围、波动、退化和缺项。第一版的发布决定始终由维护者作出。

## 13. 单命令流程与实现说明

维护者最初要求分别提供离线与真实评估命令；后续简化为 pytest 自动化代码测试和单一 evaluate 真实评估入口（见第 15 节）。

- 生产 Agent 离线场景由 `pytest evals/tests` 执行，与评估器测试一同在 CI 中自动验证。
- `nemo-eval evaluate` 默认运行 live-release × 3，读取 configs/live.toml 与 configs/judge.toml；调用前校验所需配置，随后自动运行目标模型、required rubric 的 Judge 并保存合并后的派生报告。
- evaluate 可附加 --baseline、--change，在同一命令里对比；基线条件提前检查。基线默认使用其初次流水线冻结的 assessment ID，不选择后来追加的“最新评分”。
- 初次流程选定结果写入 pipeline.json；原始执行和所有 assessment 保留，重评分不更新该选择。report/compare 支持显式选择另一 assessment。
- 默认结果目录采用 UTC 时间戳和随机后缀；命令打印绝对报告路径。
- 人工结构化 assessment 导入仍为后续扩展；当前人工复核通过发布决定记录完成。

上文第 10 节的分步 judge/compare 仍可用于诊断和重新评判；日常完整评估无需分步调用。实际接口、兼容方式和首次模型配置见维护者指南。

## 14. 难例扩充

在首批 12 例基础上新增 12 例，默认 live-release 扩为 24 例 × 3 次；live-challenge 单独运行新增 12 例 × 1 次。完整集的必需 Judge 为 5 例 × 3 次，难例集为 3 例 × 1 次。具体任务和验收依据见 [用例目录](../../evals/cases/README.md)。

覆盖范围仍为当前适配器提供的基础对话、文件工具和多轮任务。新增跨文件核对、来源冲突、多轮撤销、上下文切换、重名路径追踪、截断补读、索引回退、拒绝后诚实说明及间接指令注入。参考动作和错误证据用于验证任务可完成、常见错误不能误通过；真实模型难度与波动需由实际运行评估。未变更目标模型、Judge、本地预算和历史结果；扩充后的任务集需要重新建立同条件基线。

## 15. 删除独立回归命令

维护者确认无需单独维护和运行离线回归接口，因此删除 CLI 的 `regression` 子命令。保留离线 fixture、runner、worker 与现有 pytest 覆盖；CI 通过 pytest 执行代码测试，移除重复的三场景命令运行，并上传 pytest 的 JUnit 结果。维护者使用 `evaluate` 管理真实模型评估；开发者修改功能或修复问题时更新相关自动化测试。历史结果仍可读取，旧 `run` 仅保留作兼容诊断，不是日常测试入口。

## 16. 费用语义与重点测试

评估模块与应用统一停止本地价格估算，profile 不再接受 pricing；新增记录只保留服务商明确返回的金额、币种、已返回金额的调用数、费用未知调用数及完整性。Token、调用次数、耗时和输出预留预算继续记录；target 与 Judge 分别统计，不主动查询官网账单。历史执行和 assessment 保持原样。

补充函数级测试覆盖 Judge 非法 JSON、评分项缺失/重复/伪造、无效证据及拒评；预算恰好耗尽、仅 Token 超限与预留失败的原子性；执行错误、硬失败、缺证据及 Judge 状态的最终判定优先级。无效 Judge 的集成测试同时验证原始执行不变、失败响应与已消耗预算可追溯。
