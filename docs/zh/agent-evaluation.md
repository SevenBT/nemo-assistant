# Agent 真实模型与提示词发布评估

在仓库根目录执行。维护真实任务集后，日常使用这一个评估命令：

```powershell
# 真实模型评估，自动执行必要的 Judge 并生成最终报告。
uv run --project evals --frozen nemo-eval evaluate
```

每次运行会自动创建新的结果目录，并打印报告的绝对路径。真实评估观察模型在指定任务中的表现。

代码的自动化回归由开发者维护，CI 自动运行，包含生产 Agent 的离线场景，无需另行维护或执行一套独立回归入口。开发时运行 `uv run --project evals --extra dev --frozen pytest evals/tests -q`；这些测试使用模拟模型验证代码，不代表真实模型质量。

## 第一次使用真实评估

安装 uv 后，复制模型配置：

```powershell
Copy-Item evals/configs/live.example.toml evals/configs/live.toml
Copy-Item evals/configs/judge.example.toml evals/configs/judge.toml
```

分别填写目标模型和 Judge 模型的 model、provider；使用代理或自定义服务时同时填写 base_url，必要时显式设置 api_protocol。max_tokens 是每次请求的最大输出量；budget 是整批运行的调用次数与输出 Token 预留上限。两份配置的预算各自独立，均不是美元或输入 Token 硬上限。

根据配置中的 api_key_env，在当前终端设置环境变量。例如默认名称为：

```powershell
$env:NEMO_EVAL_TARGET_API_KEY = '<目标模型密钥>'
$env:NEMO_EVAL_JUDGE_API_KEY = '<Judge 模型密钥>'
```

密钥不写入配置或仓库。也可以在系统环境中持久设置这些变量。之后日常只执行开头的单一命令。

默认真实评估运行 24 个任务，每例 3 次，共 72 次任务执行；一个任务可能多次请求模型。其中 5 个任务需要 Judge，默认共 15 次评判。配置或密钥不齐全会在付费调用前报错。

若只想检查目标模型连通和代表任务，可执行：

```powershell
uv run --project evals --frozen nemo-eval evaluate --suite live-smoke
```

它运行 4 个任务，每例 1 次，不需要 Judge 配置。所有模式均不会读取个人应用设置或实际用户数据。

## 难例与覆盖范围

新增的 12 个难例已包含在默认 `evaluate` 中。也可以只运行这些难例，每例一次，自动完成所需的 3 次 Judge：

```powershell
uv run --project evals --frozen nemo-eval evaluate --suite live-challenge
```

用例文件在 `evals/cases/live/`，套件清单在 `evals/suites/`。完整的新增任务与判定标准见[用例目录](../../evals/cases/README.md)。难度来自实际文件任务中的约束组合：订单去重与退款核对、区分草案和审批、多轮取消与重新授权、跨项目上下文、文件名冲突、截断补读、索引回退、权限拒绝、冲突澄清和文件中的指令注入。不会要求当前适配器尚未接入的联网、Shell、桌面操作或覆盖写入能力。

结构化内容按 JSON 值检查，允许键顺序、缩进和数值等价表示；需要固定任务名、数组顺序或严格输出时，用户任务中明确写出要求。自然语言的澄清、诚实说明和读取范围由 Judge 结合逐步回答与工具证据判断，不强制套用一句标准答案。难例不预设失败率，也不把模拟执行通过当成真实模型通过。

扩充任务集后，需要用同一新版任务集重新运行旧提示词作为基线；原 12 例报告仍能阅读，但不能直接与 24 例结果做严格对比。完整集比过去消耗更多请求，保留本地配置中的预算限制；如预算不足，按报告检查未执行任务，再自行调整预算或使用 `--repeat 1`。

## 发布新系统提示词

### 修改用户可编辑部分的提示词

在同一份应用代码上，为旧、新文本分别建立 TOML 变体。示例：

```toml
id = 'candidate'
[prompt]
source = 'text-file'
path = './candidate.txt'
```

path 相对变体文件。文本替换生产 Prompt Builder 中用户可编辑的部分；工具说明、时钟及多轮历史仍由生产实现构建。不要把被测提示词写进任务 fixture，否则无法保持任务标准不变。

先用旧变体执行一次 evaluate，保留它打印的运行目录作为基线。然后执行候选版本，一次完成运行、Judge、报告与对比：

```powershell
uv run --project evals --frozen nemo-eval evaluate --variant evals/variants/examples/custom-prompt.toml --baseline artifacts/eval/live/BASELINE_RUN --change prompt
```

将 BASELINE_RUN 替换为真实旧版目录。两边需要相同的用例、重复次数、模型配置、应用代码、评估器和 Judge 配置。基线不兼容会在候选模型调用前报错。

### 修改源码中的默认提示词、工具说明或构建器

分别在旧版、新版工作区执行 evaluate，默认使用对应源码的生产提示词。两边使用相同评估器、用例和模型条件。

新版命令指定旧版运行目录的绝对路径，并使用 `--change application`。此时报告明确记录应用源码变化；若同时改了 Agent 代码，不能把所有差异归因于提示词。

## 阅读报告

- `reports/initial/report.md`：单命令流水线的最终报告，包含选定的 Judge 结论。
- `summary.json`、`report.md`：不可变的原始执行和硬检查结果；必需 Judge 尚未合并时原始 verdict 可为 inconclusive，这是正常的阶段状态。
- `cases/<用例ID>/<重复编号>/execution.json`：实际模型请求、工具结果、逐步回答、文件内容和用量证据。
- `assessments/<ID>/`：独立评判、证据引用、请求和成本。
- `comparisons/baseline/report.md`：使用 --baseline 时生成的对比报告。

优先检查关键用例、新增失败和通过次数变化，例如 `3/3 → 1/3`。error、缺评判、预算不足而未执行的任务均保留在计划分母，不算通过。24 个任务的少量重复不能证明统计显著提升，也不代表完整桌面功能覆盖。

后续单独运行 judge 会创建新 assessment，不会改变最初流水线选用的评分。要查看新的评分，显式指定它：

```powershell
uv run --project evals --frozen nemo-eval report --run artifacts/eval/live/RUN --assessment ASSESSMENT_ID
```

费用未知不等于免费。评估器不维护单价、不根据 Token 估算金额；只汇总服务商明确返回的费用，按币种展示，target 与 Judge 分别记录。实际扣费到所用服务商官网账单查看，程序不自动查询账户账单。旧配置若含 `pricing`，删除该段后再运行；历史结果保留原样，其中旧估算不代表实际扣费。调用次数与输出 Token 预算继续有效，但不是金额上限。

## 发布决定与自动化

自动化代码测试在 CI 通过 pytest 运行；真实模型与 Judge 只在本地显式启动。评估不会创建标签、上传结果或自动发布。

退出码：0 为本批任务通过，1 为任务失败或观察到退化，2 为输入/配置/输出错误，3 为执行或必需评判未完成，130 为中断。这些状态用于本地诊断，不绑定自动发布门禁。

记录旧、新 run ID、所用 assessment、对比报告，以及接受已知问题的理由，再完成[发布检查清单](release-checklist.md)。首批覆盖基础对话、文件读写和多轮任务；笔记、记忆工具、定时任务、附件和桌面交互需要后续适配器及专门任务集。
