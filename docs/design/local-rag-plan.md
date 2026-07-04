# 本地知识库（RAG）· 落地方案

> 生成日期：2026-06-28（2026-06-28 重构：目标从「笔记问答」扩展为「本地知识库」）
> 仅为设计方案，不含任何代码改动。
> 已定决策：**路线 C(本地 embedding,纯离线)** + **做法 2(图片转文字入库)** + **纯画面图 caption 走云端多模态 LLM** + **切块自己写** + **bge 中文模型** + **开关而非插件、不按需下载**。

---

## 给未来实现者的须知（开新会话先读这一节）

本方案是经过多轮讨论收敛的结果。**未来实现时，以下决策已锁定，不要重新发散讨论或推翻**——除非用户明确要求改变方向。若实现中发现某决策确有技术障碍，先在本节「待定/未决」记录，并征求用户，不要擅自换路线。

### A. 已锁定的核心决策（不要再问、不要改）

| # | 决策 | 为什么（避免重复纠结） |
|---|------|------------------------|
| 1 | 目标是**本地知识库**，不是只做笔记问答 | 笔记/便签是其中一个源，文件是另一个源，是超集 |
| 2 | **路线 C：本地 embedding，纯离线** | 不走云端 embedding(违背本地优先)，不做混合 |
| 3 | 模型用 **bge-small-zh-v1.5 int8 ONNX**(~30MB) | 复用已有 onnxruntime，不引 PyTorch |
| 4 | 向量存储用 **SQLite BLOB + numpy 余弦**，暂不引 sqlite-vec | 数据量到天花板(模块8)再换，别提前优化 |
| 5 | 切块**自己写**(chunker.py)，不引 LangChain/unstructured | 要和图文邻接强耦合，框架绑手 |
| 6 | 引擎**数据源无关**：`KnowledgeSource` 协议 + `source_type/source_ref` | 表不外键死绑 notes |
| 7 | 检索做成**工具** `search_knowledge`，AI 自主调用 | 不在每轮 prompt 里自动塞，符合「对话即调用工具」 |
| 8 | 图片走**做法 2**：有字 OCR，纯画面图云端 caption(可关、默认关) | 不引本地视觉模型 |
| 9 | 做**开关**(`ragEnabled`/`ragImageCaption`)，**不做插件** | 插件化是过度设计(YAGNI) |
| 10 | 模型**打包进分发包，不按需下载** | 开箱即用优先 |
| 11 | 管理面 = 主窗口**独立第四个 tab「知识库」**，设置页只留开关 | 高频内容操作归主窗口，配置归设置 |

### B. 明确不做（防止范围蔓延）

- ❌ 云端/混合 embedding（除图片 caption 外，检索全程离线）。
- ❌ 真正的「语义搜图」(以图搜图、图本身当检索目标的多模态 embedding)——本方案只做「图→文字→当文本检索」。
- ❌ 插件框架 / 依赖隔离 / 动态装卸 RAG 模块。
- ❌ 按需下载模型。
- ❌ 一次性堆砌多种文件格式——格式分阶段加，每种做扎实再加下一种。
- ❌ 把笔记页和知识库页合并（已定为两个独立 tab）。

### C. 涉及的文件清单（实现时的改动面）

**新增：**
- `app/core/embedder.py` —— 本地 embedding 引擎(模块1)
- `app/core/chunker.py` —— 文本切块(模块2)
- `app/core/knowledge_sources.py` —— 数据源抽象 + NoteSource/FileSource(模块3)
- `app/core/rag_manager.py` —— 索引/检索编排(模块6)
- `app/tools/knowledge.py`(或并入 notes 工具) —— `search_knowledge` 工具(模块7)
- `app/ui/knowledge_panel.py` —— 知识库 tab(模块6 UI)
- `assets/models/bge-small-zh-v1.5/`(或 data/) —— 模型文件
- `tests/test_embedder.py`、`test_chunker.py`、`test_rag_manager.py` —— 测试

**改动：**
- `app/core/db_manager.py` —— 加 `rag_chunks` / `rag_sources` 表(模块6)
- `app/core/file_parser.py` —— 多格式解析 + 图文占位符输出(模块4)
- `app/core/config.py` —— `ragEnabled` / `ragImageCaption`(模块7.1)
- `app/core/config_migrate.py` —— 同步两个新配置(否则老用户漏迁移)
- `app/core/note_manager.py` —— 删除/更新笔记时回调 rag_manager 清理 chunk
- `app/ui/main_window.py` —— stackedWidget 加第四页 + Dream 式后台索引
- `app/ui/title_bar.py` —— 导航加「知识库」项 + 搜索信号
- `app/ui/settings_pages/` —— 新增 RAG 开关页(或并入现有页)
- `requirements.txt` —— `tokenizers`，按阶段加 `python-docx` 等
- `Nemo_Assistant.spec` —— datas 纳入模型文件 + tokenizers hook

### D. 每阶段验收标准（做完怎么算「能用」）

| 阶段 | 验收标准（可演示/可测） |
|------|--------------------------|
| 1 | 单测：给定文本得到归一化向量；相似文本余弦 > 不相似；模型缺失时优雅报错不崩 |
| 2 | 单测：长文本切块大小/overlap 符合预期、图占位符不被切散；笔记 reindex 后 `rag_chunks` 有数据；内容未变不重算 |
| 3 | 集成：聊天里问「我记的关于X的笔记」，AI 调 `search_knowledge` 返回相关笔记并作答；`ragEnabled=False` 时工具不可用且优雅降级 |
| 4 | 导入一个 PDF/Word，能解析切块入库，检索能命中其中内容；>10MB 文件不被旧限制拦截 |
| 5 | 知识库 tab：导入/列表/进度/删除/重建全可用；删文件连带清 chunk；后台索引不卡 UI |
| 6 | 含图文档：图内文字可被检索；开 caption 后纯画面图可被语义召回；关 caption 时不崩、降级为相邻文字召回 |
| 7 | chunk 数超阈值有日志警告；文件移动/删除后检索跳过失效源标 error |

每个阶段都要有对应测试(项目用 pytest，见 `tests/`)，覆盖正常 + 降级路径。

### E. 实现前必做的核对（基于本项目历史教训）

- 信号类型、控件方法是否存在，**改前用最小脚本实测验证**，别盲信本文档或旧记忆(记忆 [[审查报告会误判]] 类教训：CLAUDE.md 已记多起「凭字面套用得出错误结论」)。
- 新配置项务必同步 `config_migrate.py`，默认值单一来源(记忆 [[config-migrate-missing-new-keys]])。
- 后台线程回主线程 emit 前做 `sip.isdeleted` 检查(记忆 [[qt-bg-thread-emit-after-delete]])。
- 嵌入式面板确认框用原生 `QMessageBox`，不用 qfluentwidgets `MessageBox`(CLAUDE.md)。
- 优先用 qfluentwidgets 组件(记忆 [[project_qfluentwidgets_policy]])。
- litellm 调用注意解释器/联网坑(记忆 [[litellm-loader-env-and-network]])——caption 走 llm_gateway 已封装，沿用即可。

### F. 待定 / 未决（实现时需向用户确认，别自作主张）

- 模型文件具体放 `assets/models/` 还是 `data/models/`，以及如何随仓库分发(模型二进制是否进 git / git-lfs / 首次解压)——**这是唯一与「不按需下载」可能冲突的点**，实现前要和用户敲定分发方式。
- RAG 开关是单列一个设置页，还是并入现有某页(如 tools_page)。
- `search_knowledge` 是独立工具文件，还是与 NoteTool 补全合并在 `notes.py`。
- Excel/PPT 的结构化内容如何切块（阶段 6 再设计，先不定）。

---

## 〇、目标

把攒在本机的各类资料（笔记/便签 + 导入的 PDF/Word/文本等）做成一个**纯离线的本地知识库**，在聊天里直接问，助手按语义召回相关内容并基于其回答。

**核心设计原则：检索引擎「数据源无关」，笔记/便签只是其中一个源，导入的文件是另一个源——是超集，不是替换。**

要求：
- 纯离线检索（embedding 在用户本机算，不联网）。
- 多源统一：笔记/便签源 + 文件源，同一引擎、同一向量空间、可跨源召回，也可按源过滤。
- 支持图文混排：图片中的文字(OCR)、纯画面图的描述(caption)都能参与召回，召回时图随所在文本块一起呈现。
- 贴合现有架构，复用 `db_manager` / `note_manager` / `file_parser` / `llm_gateway` / 已装的 `onnxruntime` `numpy`。

> 定位自检：本地文档知识库与 Codex/IDE agent 区分度**更强**（IDE agent 索引代码库、不索引你的个人资料库），且符合「桌面常驻生活/工作助手」定位与「本地优先」叙事。守住「格式少而精、宁可功能少而每个能用」即可，避免重蹈「又大又杂」。

---

## 一、整体数据流

```
                        ┌─────────────── 建索引(写时,离线) ───────────────┐
数据源 ──→ ①解析提取文本 ──→ ②切块(保留图文邻接) ──→ ③本地 embedding ──→ ④存向量
 ├ 笔记/便签   note_manager 取内容                    onnxruntime模型     rag_chunks表
 └ 导入文件    file_parser 扩展      自写 chunker                        (带 source_type)

                        ┌─────────────── 召回(读时,离线) ───────────────┐
用户查询 ──→ ③本地 embedding(查询1条) ──→ ⑤numpy算余弦相似度 取top-k ──→ ⑥拼进prompt ──→ LLM回答
                                          (可按 source_type 过滤)
```

关键认知：**embedding 在写时对每个块算一次存库；读时只对「查询那一句」算一次**，top-k 相似度是纯 numpy 计算，全程不联网。

---

## 二、依赖与模型增量

| 项 | 内容 | 体积/成本 |
|----|------|-----------|
| 新增 pip 依赖 | `tokenizers`(HuggingFace 分词器,纯 Rust 无 torch) | 几 MB |
| 文件格式解析 | `python-docx`(Word) 等，按阶段加；PDF 复用已有 PyPDF2(或换 pymupdf) | 各几 MB |
| 复用已有 | `onnxruntime`(rapidocr 带来)、`numpy`、`httpx`、`litellm`、`RapidOCR`、`PyPDF2` | 0 |
| 新增模型 | **bge-small-zh-v1.5** 的 int8 ONNX 量化版 | ~30 MB 磁盘 / ~100 MB 内存 |
| 向量存储 | 直接用 SQLite BLOB + numpy 算相似度，**暂不引入 sqlite-vec**（见模块 7 天花板） | 0 |
| 云端调用 | 仅「纯画面图」生成 caption 时调一次多模态 LLM | 偶发、可关闭 |

模型升级路径：效果不够时换 `bge-base-zh-v1.5`(int8 ~100MB);中英混杂多则换 `multilingual-e5-small`。维度需配套改(small=512, base=768)，换模型后须 `rebuild_all()`。

---

## 三、分模块设计

### 模块 1：本地 embedding 引擎(新增 `app/core/embedder.py`)

职责：加载 ONNX 模型 + tokenizer，把文本批量转成向量。

- 单例懒加载，参考 `file_parser.ocr_engine` 的懒加载 + `screenshot_overlay` 的后台预热写法。
- 接口设计：
  - `embed_texts(texts: list[str]) -> np.ndarray` —— 批量(建索引用)
  - `embed_query(text: str) -> np.ndarray` —— 单条(召回用，bge 系建议查询前加指令前缀 `"为这个句子生成表示以用于检索相关文章："`)
- 输出做 L2 归一化，这样余弦相似度 = 点积，召回时一次矩阵乘搞定。
- 模型文件放 `assets/models/` 或 `data/models/`，缺失时的降级见模块 8。

### 模块 2：文本切块(新增 `app/core/chunker.py`，自己写)

为什么自己写：切块逻辑要和「图文邻接」强耦合，现成库(LangChain/unstructured)切的是纯文本流，绑手且拖依赖。

核心规则：
1. 按 Markdown 标题 / 空行段落优先切分；
2. 每块目标 300-500 字，块间 overlap ~50 字(防语义被切断)；
3. **图文邻接**：解析阶段把图片表示为占位符(如 `![](attach://<id>)`)嵌在文本流里，切块时图片占位符跟随相邻段落进同一块，并在块的 metadata 里记录 `image_refs=[...]`；
4. 中文长度按字符数估算即可，不需要 tokenizer 精确算。

参考 LangChain `RecursiveCharacterTextSplitter` 的「递归分隔符」思路实现轻量版即可。切块逻辑与数据源无关——拿到「文本流 + 图片占位符」就切，不关心来自笔记还是 PDF。

### 模块 3：数据源抽象（新增 `app/core/knowledge_sources.py`）

引擎的核心扩展点。定义统一的「源」协议，让引擎不关心数据从哪来：

```python
# 伪代码
class KnowledgeSource(Protocol):
    source_type: str               # "note" | "file"
    def iter_items() -> Iterable[SourceItem]: ...   # 列出待索引项
    def load_text(item) -> ParsedDoc: ...           # 取「文本流 + 图片占位符」

# SourceItem: 唯一标识(source_ref) + 内容指纹(用于增量判断)
# ParsedDoc: text_stream + image_placeholders
```

两个实现：
- `NoteSource` —— 包 `note_manager`，`source_ref = note_id`，指纹用 `updated_at`。覆盖笔记 + 便签(都在 notes 表，按 note_type 区分)。
- `FileSource` —— 包扩展后的 `file_parser`，`source_ref = 绝对文件路径`，指纹用文件 `mtime + size`。

> 引擎层(chunker/embedder/存储/检索)对 source_type 完全无感，只认 `ParsedDoc`。新增源(将来如网页收藏)只实现一个 KnowledgeSource。

### 模块 4：文件解析扩展(改 `app/core/file_parser.py`)

现状：只支持 `.txt/.md/.png/.jpg/.jpeg`，图片走 OCR(`_parse_image`)，10MB 上限。

扩展点（**格式少而精，分阶段加，每种做扎实再加下一种**）：
| 格式 | 库 | 阶段 | 备注 |
|------|-----|------|------|
| txt/md | 已有 | 现有 | 一定能解析对 |
| PDF(文本层) | 已有 PyPDF2 / 建议换 pymupdf | 4 | 复杂排版/分栏是坑，先保证文本层 PDF |
| Word | `python-docx` | 4 | |
| 扫描件 PDF(图片型) | 现有 RapidOCR | 6 | 每页转图 OCR，慢，按需 |
| Excel | `openpyxl` | 6 | 结构化数据如何切块需单独设计 |
| PPT | `python-pptx` | 6 | 图文混排 |

- 图片处理(做法 2)分两类：
  - **图里有文字** → 复用现有 `_parse_image`(RapidOCR)，提取文字作为该图的文本表示。
  - **纯画面图(OCR 出不来/置信度低)** → 调云端多模态 LLM 生成一句 caption(见模块 5)。
- 解析输出要保留图文位置关系：返回「文本流 + 图片占位符」(对齐 `ParsedDoc`)，供 chunker 维持邻接。
- 大文件上限：知识库文件可能 > 10MB(如大 PDF)，需为知识库路径放宽或分流，不沿用聊天附件的 10MB 限制。

### 模块 5：图片 caption(走 `llm_gateway`，云端)

- 仅对「纯画面图」触发(OCR 无有效文字时的兜底)，不是每张图都调。
- 复用现有 LLM 网关与 vision 能力(项目已有 `vision_actions` / vision session，传图给多模态模型)。
- prompt 类似：「用一句话描述这张图片的主要内容，便于检索」。
- **必须可关闭**：`cfg.ragImageCaption`，默认关，尊重「本地优先」。关闭时纯画面图只靠相邻文字(做法 1)被动召回。
- caption 结果写回该图所在 chunk 的文本，参与 embedding。

### 模块 6：向量存储(改 `app/core/db_manager.py` + 新增 manager)

新增表(`db_manager._create_tables` 里加)。**关键：带 `source_type` + `source_ref`，不再外键死绑 notes**：

```sql
CREATE TABLE IF NOT EXISTS rag_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,      -- "note" | "file"
    source_ref  TEXT NOT NULL,      -- note_id(字符串化) 或 文件绝对路径
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,          -- 块文本(含 OCR/caption 注入后的内容)
    image_refs TEXT,                -- JSON: 该块关联的图片标识
    embedding BLOB NOT NULL,        -- np.float32 向量字节
    model_id TEXT NOT NULL,         -- 记录用哪个模型生成,换模型时据此重建
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_source ON rag_chunks(source_type, source_ref);

CREATE TABLE IF NOT EXISTS rag_sources (   -- 已索引文件源的台账(笔记源不必登记,以 notes 表为准)
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    fingerprint TEXT NOT NULL,       -- mtime+size,用于增量判断
    chunk_count INTEGER NOT NULL DEFAULT 0,
    indexed_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok'  -- ok | error | indexing
);
```

> ⚠️ 笔记源仍想要级联删除，但 `rag_chunks` 已不能用外键(source_ref 是混合类型)。改为：笔记删除时由 `rag_manager` 显式清理对应 chunk（在 note_manager 删除处挂回调，或 reindex 时对账）。这是从「笔记专用」泛化为「多源」付出的代价，需显式处理，别依赖 CASCADE。

新增 `app/core/rag_manager.py`：
- `reindex_source(source_type, source_ref)` —— 删旧 chunks → 经 KnowledgeSource 取文本 → 切块 → embedding → 写入。
- `search(query, top_k=5, source_type=None) -> list[Chunk]` —— embed 查询 → 取(可按源过滤的)chunk 向量 → numpy 余弦相似度 → top-k。
- 增量维护：笔记 `create`/`update` 后触发 reindex(后台线程，参考 `dream` 的 `threading.Thread(daemon=True)`)；文件源按 `rag_sources.fingerprint` 比对决定是否重建。
- `model_id` 不一致的 chunk 视为过期，提供 `rebuild_all()` 在换模型时全量重建。

> 现有 `notes` 表有 `update_notes_timestamp` 触发器，reindex 应在内容真正变化时才触发，避免无谓重算(参考记忆 [[setplaintext-resets-cursor]] 的「内容未变则跳过」思路)。

### 模块 7：检索注入 / 工具

**推荐做成工具**：新增 `search_knowledge`（取代原 `search_notes_rag`，更名以体现多源），让 AI 自主决定何时检索。
- 复用 `tools/registry.py` 的 `BuiltinTool` 模式，`read_only=True`、`retry_safe=True`。
- 参数支持 `source` 过滤(`note` / `file` / 全部)，让用户能说「只在我导入的资料里找」。
- 与「NoteTool 能力补全」呼应——可一并把 note 的 search/update/delete 补上。
- 符合「对话即调用工具」核心定位。

### 模块 8：向量库天花板监控

- 笔记是几十~几百条；知识库导入几十个 PDF 可能产生**几千~几万 chunk**。
- numpy 全量点积在 1-2 万 chunk 内仍是毫秒级(`N×维度` 矩阵乘)，**短期不引 sqlite-vec**。
- 但须设阈值监控：`rag_chunks` 行数超过约定线(如 2-3 万)时 `log` 警告，提示「该上 sqlite-vec / 近似检索」。**不静默扛**(对齐项目「No silent caps」原则)。
- 原文件**不复制进 data 目录**(可能 GB 级)，`rag_sources` 只存原路径 + 指纹；文件移动/删除时 search 要能跳过失效源并标 `status=error`。

---

## 四、图文混排召回效果说明

核心场景：文档里「架构图」+ 周围「部署架构/Nginx」文字，搜「部署架构」要把这段连图召回。

| 图的类型 | 入库时的文本表示 | 能否被「部署架构」召回 |
|----------|------------------|------------------------|
| 周围有相关文字 | 靠相邻段落(做法 1，同块) | ✅ 命中文字，图随块呈现 |
| 图里有文字(截图/表格) | RapidOCR 提取文字 | ✅ 命中图内文字 |
| 纯画面图 | 云端 LLM 生成 caption | ✅ 命中 caption(需开开关) |

召回结果是 chunk，chunk 的 `image_refs` 指向图片，UI 呈现时可把图一并显示。

---

## 五、中英混排说明

bge-small-zh 对「中文为主、夹英文术语/代码」几乎无损。整段英文或跨语言搜会打折。兜底：**保留 SQLite FTS5 关键词检索做并行召回**，英文专名/代码/报错这类字面词正好是 FTS5 强项，与向量短板互补。作为后续增强，不在本期必须。

---

## 六、知识库管理 UI（新增的主要工作面）

笔记 RAG 不需要新界面，但**知识库需要一个文件管理面**——这是扩展为知识库相比笔记 RAG 最大的额外工作量（不在算法，在 UI 与文件生命周期）。

### 6.1 位置决策（已定）

**管理面 = 主窗口独立第四个 tab「知识库」；设置页只留开关。**

- 主窗口从三页变四页：**聊天 / 笔记 / 知识库 / 工坊**。
- **为什么是主窗口 tab 而非设置页**：知识库管理是**日常高频的内容操作**(导入/看列表/查进度/删除重建)，与笔记/工坊同类；设置窗口的语义是「低频配置」(API Key/主题)，把高频操作埋进「打开设置→翻到某页」路径太深。项目现成模式也如此——内容在主窗口三页，配置在设置窗口。
- **设置里只放开关**：`ragEnabled`、`ragImageCaption` 两个配置项属「配置」，留在设置页(或单列一个 RAG 设置页)。开关是配置，管理面是操作，两者分开。
- **已知取舍**：独立 tab 让「笔记源」和「文件源」在 UI 上分属两页(笔记页 / 知识库页)，与「数据源无关」引擎在视图层略有出入——但引擎层仍统一(都是 `rag_chunks`)，只是呈现分两个入口。检索工具 `search_knowledge` 默认跨源召回，不受 UI 分页影响。

### 6.2 知识库 tab 需要承载

- **导入**：选文件/文件夹加入知识库（拖拽或按钮）。
- **列表**：已索引哪些文件、各自 chunk 数、索引时间、状态(ok/error/indexing)。
- **进度**：批量索引时的进度反馈（参考现有 `IndeterminateProgressBar` / toast）。
- **操作**：删除某文件(连带清 chunk)、重新索引、全量重建。
- **占用**：知识库总 chunk 数 / 接近天花板时的提示(模块 8)。

### 6.3 实现落点

- 新增 `app/ui/knowledge_panel.py`，作为第四页加入 `main_window` 的 `stackedWidget`，导航项加入 `title_bar`。
- 布局复用「工坊(能力管理器)」的左列表 + 右详情风格(splitter)。
- 用 qfluentwidgets 组件(项目策略 [[project_qfluentwidgets_policy]])。
- 嵌入式面板的确认框用原生 `QMessageBox`，不用 qfluentwidgets 的 `MessageBox`(CLAUDE.md 经验：`MaskDialogBase` 要求顶层窗口，嵌在 StackedWidget 内会卡死)。
- 列表区边距对齐另三个视图(CLAUDE.md：外层 `0,0,0,0`，内层面板 `8,10,8,8`)。
- 索引/重建是耗时操作，放后台线程(参考 `dream` 的 daemon thread)，回主线程更新 UI 前注意 `sip.isdeleted` 检查(记忆 [[qt-bg-thread-emit-after-delete]])。

---

## 七、开关与优雅降级（开关而非插件、不按需下载）

RAG 做成**开关 + 懒加载 + 优雅降级**，不做插件化(YAGNI)，模型文件**直接打包进分发包**(不按需下载)。开关目的是省运行时开销、可选关闭。

### 7.1 配置项（`app/core/config.py`，声明式 QConfig）

- `ragEnabled: bool = False` —— 总开关。关闭时 embedder 永不实例化、不建索引、检索工具隐藏/禁用。默认关，开箱不强加 ~100MB 内存。
- `ragImageCaption: bool = False` —— 纯画面图云端 caption 开关，依赖 `ragEnabled`。

> 新增配置项必须同步 `config_migrate.py`，否则老用户升级漏迁移(记忆 [[config-migrate-missing-new-keys]])。默认值用单一来源常量。

### 7.2 两层开关语义

- `cfg.ragEnabled` = 系统级总闸(控制 embedder 加载与索引维护)。
- 工坊里的 `search_knowledge` 工具开关 = AI 是否可调用检索。复用 `toolStates` / `apply_saved_states`。
- 总闸关时工具自动不可用，避免「工具开着但 embedder 没加载」的矛盾态。

### 7.3 懒加载

- embedder 单例懒加载，参考 `file_parser.ocr_engine` 的 `@property`。
- `ragEnabled=False` 时绝不触碰模型：不开 onnx 会话、不读模型文件、0 额外内存。
- 开启后首次使用再加载，可后台预热避免首查卡顿。

### 7.4 优雅降级

| 失败场景 | 期望行为 |
|----------|----------|
| `ragEnabled=False` | embedder 不加载；检索工具不可用；AI 退回普通 `note` 工具 |
| 模型文件缺失/损坏 | catch 住，记日志 + 提示「RAG 不可用」，不崩 UI |
| embedding 推理异常 | 单次检索返回空 + 错误说明，不影响整轮对话 |
| 索引为空 | 返回「暂无可检索内容」，引导先导入/索引 |
| 文件源失效(移动/删除) | search 跳过该源并标 `status=error`，不报错中断 |
| `ragImageCaption=False` | 纯画面图仅靠相邻文字被动召回 |

原则：**不静默吞错**(记日志)、**UI 给友好提示**、AI 侧降级而非中断。

### 7.5 打包与分发

- 模型 ~30MB **直接纳入** PyInstaller(`Nemo_Assistant.spec` 的 datas)，**不按需下载**。
- `tokenizers` 带原生扩展，确认 PyInstaller hook 能收集。
- onnxruntime 已在依赖里(rapidocr)，CPU provider 即可，无需 GPU。
- 默认关仍让不用的用户零运行时开销(模型躺磁盘不进内存)。

### 7.6 为什么不做插件

项目无成熟插件框架(`script_adapter` 仅供用户脚本工具)。为 RAG 搭插件加载 + 依赖隔离，复杂度远超其价值；唯一收益(省 30MB)已因「不按需下载」而无意义。属 YAGNI。

---

## 八、落地阶段拆分（建议顺序）

| 阶段 | 内容 | 产出 |
|------|------|------|
| 1 | embedder.py + 模型接入 + 自测向量正确 | 本地能把文本转向量 |
| 2 | chunker.py + db 表(带 source_type) + rag_manager(笔记源) | 笔记/便签可建索引、可检索 |
| 3 | `search_knowledge` 工具接入 agent | 聊天里能问笔记 |
| 4 | **source 抽象 + FileSource + 文件解析(PDF文本/Word/txt/md)** | 导入文件可检索(文本格式) |
| 5 | **知识库管理 UI(导入/列表/进度/删除/重建)** | 用户可管理知识库 |
| 6 | 图片 OCR 入库 + 纯画面图 caption(带开关) + 扫描PDF/Excel/PPT | 图文混排与更多格式 |
| 7 | 向量库天花板监控 + FTS5 并行召回(可选) | 规模化与中英增强 |

**阶段 1-3 是 MVP**(笔记源跑通,验证 RAG 链路);**阶段 4-5 才真正成为「知识库」**(文件源 + 管理界面)。先用笔记源验证引擎,再扩文件源,风险最低,每步都「能用」。

---

## 九、与现有「待办」的关系

- 笔记问答(本地 RAG)→ 升级为本地知识库。
- 与检索升级、NoteTool 补全合并推进。
- 记忆系统(`memory_manager.build_memory_context` 盲目截断)可复用同一套 embedder，后续把记忆注入改为按相关性 top-k(记忆可视作又一个 KnowledgeSource)。
