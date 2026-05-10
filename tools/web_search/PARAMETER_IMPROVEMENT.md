# 博查搜索引擎参数改进总结

## 📋 改进概览

**改进日期**: 2026-05-10  
**改进类型**: 功能增强  
**状态**: ✅ 完成并通过代码审查

---

## 🎯 问题背景

### 用户提出的问题
> "在当前的实现中，大模型会自己整合参数调用 API？"

### 发现的核心问题

**AI 无法根据用户意图动态调整搜索参数**

在原实现中，`summary`、`freshness`、`include`、`exclude` 四个高级参数被标记为 `"source": "config"`，这导致：

1. ❌ AI 看不到这些参数（不在 OpenAI function schema 中）
2. ❌ 参数值固定从配置读取，无法动态调整
3. ❌ 用户说"搜索最近一周的文章，要带摘要" → AI 无法响应

**实际调用流程**：
```
用户: "搜索最近一周关于 Python 的文章，要带摘要"
  ↓
AI 只能设置:
{
  "query": "Python",
  "count": 10
}
  ↓
系统自动注入固定配置:
{
  "summary": false,      // ❌ 固定值，无法响应用户需求
  "freshness": "noLimit" // ❌ 固定值，无法响应用户需求
}
```

---

## ✅ 改进方案

### 1. 参数来源调整

将四个高级参数从 `"source": "config"` 改为 `"source": "ai"`：

| 参数 | 改进前 | 改进后 | 效果 |
|------|--------|--------|------|
| `summary` | `config` | `ai` | ✅ AI 可根据用户需求决定是否启用摘要 |
| `freshness` | `config` | `ai` | ✅ AI 可根据时间要求设置搜索范围 |
| `include` | `config` | `ai` | ✅ AI 可根据用户指定限定搜索网站 |
| `exclude` | `config` | `ai` | ✅ AI 可根据用户要求排除特定网站 |

**保持不变**（安全性考虑）：
- `provider`: `config` - 搜索引擎由配置决定
- `api_key`: `config` - API Key 不暴露给 AI

### 2. 参数描述优化

根据 code-reviewer 建议，优化了参数描述的具体性和一致性：

**优化前**：
```json
"summary": {
  "description": "是否返回文本摘要（仅博查支持，由配置决定）"
}
```

**优化后**：
```json
"summary": {
  "description": "是否返回 AI 生成的文本摘要（默认 false）。仅当用户明确说'总结'、'摘要'、'详细内容'时设为 true。注意：会增加 API 成本（仅博查支持）"
}
```

**改进点**：
- ✅ 添加默认值说明
- ✅ 提供具体的触发词示例
- ✅ 添加成本提示
- ✅ 统一分隔符说明（|或,）

---

## 🎬 改进效果对比

### 场景 1: 用户要求摘要

**用户输入**：
```
"搜索阿里巴巴2024年ESG报告，要详细的摘要"
```

**改进前** ❌：
```json
{
  "query": "阿里巴巴2024年ESG报告",
  "count": 5,
  "summary": false  // 固定值，无法响应用户需求
}
```

**改进后** ✅：
```json
{
  "query": "阿里巴巴2024年ESG报告",
  "count": 5,
  "summary": true  // AI 识别到"详细的摘要"，自动设置
}
```

### 场景 2: 用户指定时间范围

**用户输入**：
```
"搜索最近一周关于 Python 的教程"
```

**改进前** ❌：
```json
{
  "query": "Python 教程",
  "count": 5,
  "freshness": "noLimit"  // 固定值，忽略时间要求
}
```

**改进后** ✅：
```json
{
  "query": "Python 教程",
  "count": 5,
  "freshness": "oneWeek"  // AI 识别到"最近一周"，自动设置
}
```

### 场景 3: 用户限定网站

**用户输入**：
```
"只在 GitHub 和 Stack Overflow 上搜索 Rust 异步编程"
```

**改进前** ❌：
```json
{
  "query": "Rust 异步编程",
  "count": 5,
  "include": ""  // 固定值，无法限定网站
}
```

**改进后** ✅：
```json
{
  "query": "Rust 异步编程",
  "count": 5,
  "include": "github.com|stackoverflow.com"  // AI 识别网站要求
}
```

---

## 🔒 安全性保障

### 保持安全的设计

1. **API Key 不暴露**：`api_key` 仍为 `"source": "config"`，AI 无法访问
2. **搜索引擎固定**：`provider` 仍为 `"source": "config"`，防止 AI 随意切换
3. **成本控制**：参数描述中明确"仅当用户明确要求"，避免过度使用

### Code Review 结果

```
✅ 无安全风险
✅ 批准合并
⚠️  MEDIUM 级别建议已优化
```

---

## 📊 技术实现细节

### 参数解析优先级

系统使用以下优先级合并参数：
```
manual > ai > config > default
```

**示例**：
```python
# AI 设置 summary=true
ai_params = {"query": "Python", "summary": true}

# 配置中有 provider 和 api_key
config_params = {"provider": "bocha", "api_key": "sk-xxx"}

# 最终合并结果
final_params = {
    "query": "Python",
    "summary": true,        # 来自 AI
    "provider": "bocha",    # 来自 config
    "api_key": "sk-xxx"     # 来自 config
}
```

### OpenAI Function Schema

**改进后 AI 看到的工具定义**：
```json
{
  "name": "web_search",
  "description": "搜索互联网...",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {...},
      "count": {...},
      "summary": {...},      // ✅ 新增
      "freshness": {...},    // ✅ 新增
      "include": {...},      // ✅ 新增
      "exclude": {...}       // ✅ 新增
    },
    "required": ["query"]
  }
}
```

---

## 🎯 用户体验提升

### 改进前的用户体验 ❌

```
用户: "搜索最近一周的 Python 教程，要带摘要"
AI: [调用 web_search]
    → 返回所有时间范围的结果，无摘要
用户: "为什么没有摘要？"
AI: "抱歉，需要在设置中启用摘要功能"
```

### 改进后的用户体验 ✅

```
用户: "搜索最近一周的 Python 教程，要带摘要"
AI: [调用 web_search，自动设置 freshness=oneWeek, summary=true]
    → 返回最近一周的结果，包含详细摘要
用户: "完美！"
```

---

## 📝 修改的文件

1. **tools/web_search/manifest.json**
   - 修改 `summary`、`freshness`、`include`、`exclude` 的 `source` 字段
   - 优化参数描述，添加具体示例和约束

---

## 🚀 后续建议

### 可选的进一步优化

1. **添加参数验证**：
   - 在 `tool.py` 中验证 `freshness` 的有效值
   - 验证 `include`/`exclude` 的域名格式

2. **使用统计**：
   - 记录 AI 使用高级参数的频率
   - 分析是否存在过度使用（成本控制）

3. **用户反馈**：
   - 收集用户对 AI 参数选择的满意度
   - 根据反馈调整参数描述

---

## 🎉 总结

本次改进通过将博查搜索的高级参数从配置驱动改为 AI 驱动，显著提升了用户体验：

- ✅ AI 能够理解用户的搜索意图
- ✅ 自动设置合适的搜索参数
- ✅ 保持 API Key 等敏感信息的安全性
- ✅ 通过描述约束避免过度使用

**改进效果**：用户无需手动配置，AI 自动根据对话上下文选择最佳搜索策略。
