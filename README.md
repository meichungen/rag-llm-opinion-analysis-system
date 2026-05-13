# 融合 RAG 与 LLM 的多平台舆情智能分析系统

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)
![React](https://img.shields.io/badge/React-18.2+-61DAFB.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## 项目简介
这是一个端到端的多平台舆情智能分析系统，打通了：

`数据采集 -> 情感分析 -> 主题建模 -> RAG 问答 -> Agent 决策 -> 可视化展示 -> 报告导出`

系统当前已覆盖微博、B 站、抖音等平台，并补充了基于 Agent 的工具调度能力，适合课程设计、毕业设计、作品集展示和面试讲解。

## 核心亮点
- `RAG + LLM`：让问答结果尽量基于已采集数据，减少泛化回答和幻觉。
- `全栈闭环`：从采集、分析到前端展示与报告导出均已串通。
- `Agent 化升级`：支持自主决策、工具调用、短期记忆、长期检索。
- `可观测性增强`：支持 Cookie 健康检查、crawler 配置展示、风险指纹识别、结构化工具观测。
- `工程可扩展`：平台 crawler、Agent、分析模块和前端页面均支持持续扩展。

## 功能概览

| 模块 | 能力 |
| :--- | :--- |
| 多源数据采集 | 支持热榜监控与关键词任务采集，当前适配微博、B 站、抖音 |
| 舆情分析 | 评论级情感分析、LDA 主题建模、词云与趋势图展示 |
| RAG 问答 | 基于当前任务上下文检索并生成回答 |
| Agent 调度 | 单 Agent + ReAct + Tool Use，自主选择工具并输出结构化观测 |
| 风险诊断 | 识别 `412`、验证码、登录失效、空 JSON、WBI 失败等风险指纹 |
| 配置与运维 | 设置页可查看 Cookie 健康状态、crawler 配置，并支持恢复默认参数 |
| 报告导出 | 支持 PDF / Word 报告导出 |

## 技术栈

| 方向 | 方案 |
| :--- | :--- |
| 后端 | FastAPI, SQLAlchemy, APScheduler |
| 前端 | React 18, Vite, Ant Design, ECharts |
| 数据采集 | Playwright, 自研平台 crawler |
| AI / NLP | Transformers, Sentence-Transformers, Jieba, scikit-learn |
| 问答与 Agent | 通义千问兼容 OpenAI 接口, 自研 RAG 检索, 单 Agent 调度 |
| 存储 | MySQL, Redis |
| 工具链 | uv / pip, npm, Docker |

## Agent 架构
当前 Agent 层采用 `单 Agent + ReAct + Tool Use` 架构，尽量复用已有 REST API 与分析能力，不重写原有业务主链路。

```mermaid
flowchart TD
    U[用户问题] --> A[OpinionAgent]
    A --> M1[短期记忆]
    A --> M2[长期检索]
    A --> T1[fetch_data]
    A --> T2[sentiment_analysis]
    A --> T3[topic_modeling]
    A --> T4[vector_search]
    T1 --> S1[任务 / 帖子 / 评论]
    T2 --> S2[情感分析模块]
    T3 --> S3[LDA / 文本分析模块]
    T4 --> S4[向量索引 / RAG]
    A --> R[最终回答]
```

### Agent 当前特性
- 短期记忆保存最近多轮对话，支持连续追问。
- 长期记忆支持 `local_embedding / redis_vector / milvus` 等后端。
- 工具返回已结构化，包含 `status`、`warnings`、`diagnostics`、`risk_fingerprints`。
- 前端 Agent 页面已支持展示 `tool_observation` 和平台风控面板。

## 新增可观测性能力

### 1. Cookie 健康检查
- 设置页可查看平台 Cookie 是否存在、格式、数量、缺失关键字段。
- 后端接口：
  - `GET /api/settings/platform-cookie/health`
  - `POST /api/settings/platform-cookie`

### 2. Crawler 配置可视化
- 设置页支持查看并修改平台 crawler 配置，如重试次数、分页上限、降级开关。
- 后端接口：
  - `GET /api/settings/platform-crawler`

### 3. 风险指纹识别
- 当前已识别的典型风险包括：
  - `bilibili_412`
  - `captcha`
  - `login_required`
  - `empty_json`
  - `blocked`
  - `wbi_failed`

### 4. 任务级诊断摘要
- 分析页会展示任务执行状态、帖子/评论完成度、任务告警和风险指纹。
- `GET /api/tasks/{task_id}` 现已返回结构化 `warnings / diagnostics / risk_fingerprints`。

## 项目结构

```text
project/
├─ backend/
│  ├─ app/
│  │  ├─ agent/          # Agent 决策、记忆、工具调度
│  │  ├─ crawler/        # 平台 crawler 与 worker
│  │  ├─ qa/             # RAG / LLM 问答
│  │  ├─ sentiment/      # 情感分析
│  │  ├─ services/       # 任务执行、报告、文本分析
│  │  ├─ schemas/        # Pydantic schema
│  │  └─ main.py         # FastAPI 入口
│  └─ run.py             # Windows 友好的启动入口
├─ frontend/
│  ├─ src/pages/         # Home / Task / Analysis / Agent / Settings
│  ├─ src/services/      # API 封装
│  └─ vite.config.ts
└─ README.md
```

## 快速开始

### 环境要求
- Python `3.10+`
- Node.js `18+`
- MySQL `5.7+` 或本地 SQLite 调试环境
- Redis `可选但推荐`
- 可用的大模型 API Key，例如通义千问

## 安装

### 1. 克隆仓库

```bash
git clone https://github.com/meichungen/rag-llm-opinion-analysis-system.git
cd rag-llm-opinion-analysis-system
```

### 2. 安装后端依赖

使用 `pip`：

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

也可以使用 `uv`：

```bash
cd backend
uv sync
```

### 3. 安装前端依赖

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

### 本地调试模式
如果你只是想快速本地跑通接口，不依赖 MySQL，可先使用 SQLite：

```env
DATABASE_URL=sqlite+aiosqlite:///./local_dev.db

DASHSCOPE_API_KEY=your_api_key
DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
```

## 启动方式

### 后端

Windows 下推荐使用 `run.py`，因为项目里有 Playwright 和异步事件循环兼容处理：

```bash
cd backend
python run.py
```

或者使用 `uv`：

```bash
cd backend
uv run python run.py
```

默认后端地址：

`http://127.0.0.1:8000`

### 前端

```bash
cd frontend
npm run dev
```

Vite 默认前端地址通常为：

`http://127.0.0.1:5173`

前端已在 [vite.config.ts] 中代理 `/api` 到 `http://127.0.0.1:8000`。

## 推荐体验路径

### 任务链路
1. 进入“任务管理”创建任务
2. 等待采集和分析完成
3. 在“数据分析”页面查看情感分布、词云、LDA、任务风险摘要
4. 导出 PDF 报告

### Agent 链路
1. 进入“智能分析 Agent”
2. 选择一个任务，或者直接提问
3. 查看 Agent 的 `决策摘要 / 工具观察 / warnings / risk_fingerprints`
4. 在左侧“平台风控面板”中查看本轮会话的聚合风险

### 设置与运维
1. 进入“系统设置 -> 平台配置”
2. 查看平台 Cookie 健康状态
3. 调整 crawler 参数
4. 如有需要，点击“恢复默认 crawler 配置”

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

## 已知说明
- 首次运行 Playwright、模型依赖或 `uv` 临时环境时，下载时间可能较长。
- 如果使用完整情感分析和向量检索链路，建议准备足够的磁盘和网络带宽。
- 若本地只想验证接口和页面，可优先使用 SQLite，本地调试门槛更低。

## 后续可继续完善
- 增加更多平台接入，如小红书、知乎等
- 增加更多风险指纹规则与告警面板
- 为 Agent 增加更完整的执行链追踪
- 做更细粒度的权限和多用户能力
- 增加 Docker Compose 一键启动

## 参与贡献
欢迎通过 Issue 或 Pull Request 提出改进建议。

如果这个项目对你有帮助，欢迎点个 Star。
