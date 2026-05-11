# 融合 RAG 与 LLM 的多平台舆情智能分析系统

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)
![React](https://img.shields.io/badge/React-18.2+-61DAFB.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## 📋 项目简介

本项目是一个端到端的多平台舆情智能分析系统，打通了从数据采集、智能分析到交互式问答和可视化的全过程。

**核心亮点**

- **RAG技术融合**：将大语言模型（LLM）与检索增强生成（RAG）架构深度结合，系统能够从实时抓取的舆情数据中检索关键信息，让AI的回答**严格依据事实**，有效避免通用大模型在特定事件上的“幻觉”问题。
- **全栈工程闭环**：完整实现了 **采集 → 分析 → 问答 → 展示 → 报告** 的一站式链路，覆盖了舆情分析的主要业务场景。

## ✨ 核心功能

| 功能模块 | 具体能力 |
| :--- | :--- |
| **多源数据采集** | 支持热榜监控与关键词任务采集，目前已适配微博、B站、抖音，并为其他主流社交平台预留了扩展接口。 |
| **舆情智能分析** | **评论级情感分析**（正/负/中性）、**LDA主题模型**提取讨论焦点、**词云**与**时间趋势图**展示。 |
| **RAG 智能问答** | 支持基于当前任务上下文进行**流式交互**问答，让用户通过自然语言深度挖掘舆情信息。 |
| **可视化大屏** | 通过 **ECharts** 动态展示情感分布、热度趋势、词云和主题模型结果，一目了然。 |
| **报告自动生成** | 支持一键导出 **PDF / Word** 格式的详细舆情分析报告，便于汇报与存档。 |

## 🛠️ 技术栈

| 技术方向 | 采用方案 |
| :--- | :--- |
| **后端框架** | FastAPI（异步高性能） |
| **AI & 大模型** | **LLM**：通义千问（兼容OpenAI接口）；**Embedding**：m3e-base；**框架**：LangChain / LlamaIndex；**RAG**：自研向量检索 |
| **数据处理** | Pandas, NumPy, NLTK, LDA, Transformers（Hugging Face） |
| **数据采集** | Playwright（动态页面）, Scrapy, 第三方热榜聚合API |
| **前端** | React 18, ECharts, Axios |
| **数据库与存储** | MySQL（主业务库）, Redis（向量缓存与分布式锁） |
| **部署与工具** | Docker, Git, python-dotenv |

## 📦 快速开始

### 环境准备

- **Python** 3.10 或更高版本
- **Node.js** 18 或更高版本
- **MySQL** 5.7 或更高版本（需提前创建数据库）
- **Redis**（用于缓存和向量存储）
- **大模型 API Key**（如通义千问、OpenAI 等）

### 安装与配置

1. **克隆仓库**
   ```bash
   git clone https://github.com/meichungen/rag-llm-opinion-analysis-system.git
   cd rag-llm-opinion-analysis-system
配置后端环境

进入后端目录并创建虚拟环境：

bash
cd backend
python -m venv venv
激活虚拟环境：

Windows：.\venv\Scripts\activate

Linux / macOS：source venv/bin/activate

安装依赖：

bash
pip install -r requirements.txt
⚠️ 重要：配置环境变量
本项目使用 .env 文件管理敏感信息。请复制 .env.example 并重命名为 .env，然后填入你真实的配置：

text
# 大模型 API 配置
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 数据库配置
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=opinion_db

# Redis 配置
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
配置前端环境

打开一个新的终端，进入 frontend 目录：

bash
cd ../frontend
npm install
启动应用
启动后端服务（在 backend 目录下的终端中）

bash
python main.py # 或者使用 uvicorn 直接启动
uvicorn main:app --reload --port 8000
后端 API 服务将运行在 http://localhost:8000

启动前端开发服务器（在 frontend 目录下的终端中）

bash
npm start
前端页面将运行在 http://localhost:3000

现在你就可以开始使用系统了 🎉

🤝 参与贡献
欢迎通过 Issue 或 Pull Request 提出改进建议，共同完善项目。
