# 基于 ReAct 的多平台舆情智能分析与问答 Agent 系统

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)
![React](https://img.shields.io/badge/React-18.2+-61DAFB.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## 项目简介

这是一个面向多平台舆情场景的智能分析系统，覆盖从数据采集、任务执行、文本分析到 Agent 问答和报告导出的完整链路：

```text
微博 / B站 / 抖音 数据采集
  -> 评论级情感分析
  -> 词云与 LDA 主题建模
  -> RAG 问答
  -> ReAct 多步 Agent
  -> 可视化分析
  -> 报告导出
```

系统后端基于 FastAPI，前端基于 React + Vite + Ant Design，适合作为 Python 后端、数据采集、RAG 和 Agent 工程化综合项目。

## 核心亮点

- **全链路舆情分析**：支持采集任务管理、帖子/评论入库、情感分析、词云、LDA 主题建模、报告导出与可视化展示。
- **多步 Agent 主链路**：基于 ReAct 思路实现“计划 -> 工具调用 -> 观察 -> 最终回答”的闭环。
- **标准化 Tool Registry**：为 Agent 工具定义描述、参数 Schema、风险等级和调用约束。
- **Pydantic 参数校验**：对 LLM 生成的工具参数进行修复和校验，工具失败时支持降级回答。
- **双层记忆机制**：结合短期会话记忆与长期任务检索，使回答尽量基于已采集任务数据。
- **Agent 可观测性**：`/api/agent/chat` 返回 `agent_trace`，前端以时间线展示每一步决策、工具、入参、状态、风险等级、耗时与观察结果。
- **采集风险门控**：对实时采集工具增加安全门控，默认优先分析已有数据，避免 Agent 无确认触发高风险爬虫动作。
- **平台诊断能力**：支持 Cookie 健康检查、crawler 配置管理、风险指纹识别和任务级诊断摘要。

## 功能概览

| 模块 | 能力 |
| :--- | :--- |
| 多源数据采集 | 支持微博、B站、抖音关键词采集和热榜监控 |
| 任务管理 | 创建、暂停、恢复、删除任务，并跟踪执行进度 |
| 舆情分析 | 评论级情感分析、情感趋势、词云、LDA 主题建模 |
| RAG 问答 | 基于任务上下文和历史分析结果生成回答 |
| Agent 调度 | 多步规划、工具调用、观察记录、失败降级和最终回答 |
| 工具治理 | Tool Registry、Pydantic 参数校验、风险等级和高风险工具门控 |
| 可观测性 | `agent_trace` 时间线、工具观察、风险指纹、Cookie 健康检查 |
| 报告导出 | 支持任务分析报告导出 |

## 技术栈

| 方向 | 技术 |
| :--- | :--- |
| 后端 | FastAPI, SQLAlchemy Async, APScheduler, Pydantic |
| 前端 | React 18, Vite, Ant Design, ECharts |
| 数据采集 | Playwright, 平台 crawler, Cookie 健康检查 |
| AI / NLP | LLM, RAG, Transformers, Sentence-Transformers, Jieba, scikit-learn |
| Agent | ReAct, Tool Use, Tool Registry, 参数校验, Trace 可观测 |
| 存储 | MySQL, Redis, SQLite 本地调试 |
| 工程化 | pytest, TypeScript, npm, Docker |

## Agent 架构

当前 Agent 采用单 Agent + 多工具协作架构，尽量复用已有业务能力，不重写采集、分析和问答主链路。

```mermaid
flowchart TD
    U["用户问题"] --> A["OpinionAgent"]
    A --> M1["短期会话记忆"]
    A --> M2["长期任务检索"]
    A --> P["ReAct 多步规划"]
    P --> TR["Tool Registry"]
    TR --> V["Pydantic 参数校验"]
    V --> T1["fetch_data"]
    V --> T2["sentiment_analysis"]
    V --> T3["topic_modeling"]
    V --> T4["vector_search"]
    V --> T5["crawl_data"]
    T1 --> D1["任务 / 帖子 / 评论"]
    T2 --> D2["情感分析模块"]
    T3 --> D3["LDA / 文本分析模块"]
    T4 --> D4["长期记忆 / RAG"]
    T5 --> G["高风险工具门控"]
    P --> Trace["agent_trace"]
    Trace --> UI["前端执行轨迹时间线"]
    A --> R["最终回答"]
```

### Agent 工具

| 工具 | 说明 | 风险等级 |
| :--- | :--- | :--- |
| `fetch_data` | 按关键词和平台查询已采集任务数据 | low |
| `sentiment_analysis` | 对单条文本做情感分析 | low |
| `topic_modeling` | 基于已采集文本执行 LDA 主题建模 | medium |
| `vector_search` | 检索长期任务记忆 | low |
| `crawl_data` | 实时采集平台数据 | high |
| `summarize_crawled_data` | 对实时采集结果做摘要预处理 | low |

### Agent 响应观测字段

`POST /api/agent/chat` 会保留旧字段并额外返回执行轨迹：

```json
{
  "answer": "...",
  "used_tool": "fetch_data",
  "decision_summary": "...",
  "observation_summary": "...",
  "tool_observation": {},
  "agent_trace": [
    {
      "step": 1,
      "thought": "需要先查询历史任务数据",
      "action": "fetch_data",
      "parameters": {"keyword": "小米", "platform": "weibo"},
      "status": "success",
      "risk_level": "low",
      "elapsed_ms": 23.4,
      "observation_summary": "工具已执行"
    }
  ]
}
```

## 项目结构

```text
project/
├── backend/
│   ├── app/
│   │   ├── agent/          # Agent 决策、记忆、工具注册、Trace
│   │   ├── crawler/        # 平台 crawler 和 worker
│   │   ├── qa/             # RAG / LLM 问答
│   │   ├── sentiment/      # 情感分析
│   │   ├── services/       # 任务执行、报告、文本分析
│   │   ├── schemas/        # Pydantic schema
│   │   └── main.py         # FastAPI 入口
│   └── run.py              # 后端启动入口
├── frontend/
│   ├── src/pages/          # Home / Task / Analysis / Agent / Settings
│   ├── src/services/       # API 封装
│   └── vite.config.ts
├── AGENTS.md               # AI 编程助手协作规则
└── README.md
```

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- MySQL 5.7+，也可以使用 SQLite 做本地调试
- Redis 可选，默认可使用本地会话记忆
- 可用的大模型 API Key，例如通义千问兼容 OpenAI 接口

### 安装后端依赖

```bash
cd backend
python -m venv venv
```

Windows:

```bash
.\venv\Scripts\activate
```

Linux / macOS:

```bash
source venv/bin/activate
```

安装依赖：

```bash
pip install -r requirements.txt
```

### 安装前端依赖

```bash
cd frontend
npm install
```

## 环境变量

建议在 `backend` 目录下创建 `.env` 文件。

### MySQL 模式

```env
DATABASE_URL=mysql+pymysql://root:your_password@localhost:3306/social_media_analysis
DASHSCOPE_API_KEY=your_api_key
DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
REDIS_URL=redis://localhost:6379/0
```

### SQLite 本地调试

```env
DATABASE_URL=sqlite+aiosqlite:///./local_dev.db
DASHSCOPE_API_KEY=your_api_key
DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
```

## 启动方式

### 后端

Windows 下推荐使用 `run.py`：

```bash
cd backend
python run.py
```

默认后端地址：

```text
http://127.0.0.1:8000
```

### 前端

```bash
cd frontend
npm run dev
```

默认前端地址通常为：

```text
http://127.0.0.1:5173
```

前端通过 `frontend/vite.config.ts` 将 `/api` 代理到 `http://127.0.0.1:8000`。

## 推荐体验路径

### 任务分析链路

1. 进入“任务管理”创建采集任务。
2. 等待采集和分析完成。
3. 在“数据分析”页面查看情感分布、词云、LDA 和任务风险摘要。
4. 导出分析报告。

### Agent 链路

1. 进入“智能分析 Agent”页面。
2. 选择一个任务，或直接输入问题。
3. 查看 Agent 的决策摘要、工具观察和执行轨迹。
4. 在时间线中检查每一步工具调用、耗时、风险等级与观察结果。

### 设置与诊断

1. 进入“系统设置 -> 平台配置”。
2. 查看平台 Cookie 健康状态。
3. 调整 crawler 参数。
4. 检查平台风险指纹和任务诊断结果。

## 常用接口

### 基础任务

- `POST /api/tasks`
- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `POST /api/tasks/{task_id}/action`
- `GET /api/tasks/{task_id}/report`

### 分析

- `GET /api/analysis/sentiment/{task_id}`
- `GET /api/analysis/wordcloud/{task_id}`
- `GET /api/analysis/lda/{task_id}`
- `GET /api/analysis/preview/{task_id}`
- `GET /api/analysis/report/{task_id}/pdf`

### Agent

- `POST /api/agent/chat`

### 设置

- `GET /api/settings`
- `POST /api/settings`
- `POST /api/settings/platform-cookie`
- `GET /api/settings/platform-cookie/health`
- `GET /api/settings/platform-crawler`

## 校验命令

后端语法检查：

```bash
python -m compileall backend/app
```

Agent 聚焦测试：

```bash
cd backend
pytest tests/test_agent_chat.py tests/test_agent_retriever.py tests/test_agent_indexer.py
```

前端类型与构建：

```bash
cd frontend
npm run build
```

## 已知说明

- 首次运行 Playwright、模型依赖或大模型相关能力时，可能需要较长下载或初始化时间。
- 如只想快速验证接口和页面，可优先使用 SQLite，本地调试门槛更低。
- 实时采集依赖平台 Cookie 与网络状态，建议先在设置页检查 Cookie 健康状态。
- 默认 Agent 会优先分析已有任务数据；实时采集属于高风险工具，需要用户明确提出实时采集意图。

## 后续规划

- 增加更多平台接入，如小红书、知乎等。
- 增加更多风险指纹规则和告警面板。
- 扩展 Agent 行为评测集，覆盖工具选择准确率、参数修复和安全门控。
- 增加更细粒度的权限和多用户能力。
- 增加 Docker Compose 一键启动配置。

## 参与贡献

欢迎通过 Issue 或 Pull Request 提出改进建议。
