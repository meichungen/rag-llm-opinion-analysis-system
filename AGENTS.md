# AGENTS.md

本文件面向 AI 编程助手。默认使用中文沟通，回答要具体、可执行，并优先贴合当前真实代码，而不是历史说明、示例配置或泛化惯例。

## 作用域与优先级

- 本文件作用于当前仓库 `c:\Users\meichungen\Desktop\project`。
- 如果子目录存在更近的 `AGENTS.md`，以更近文件为准。
- 用户当前对话里的明确要求优先于本文件。
- 不要覆盖用户已有的未提交改动；修改前先看工作区状态。
- 当 README、界面文案、代码实现不一致时，以真实运行时代码为准。

推荐的事实优先级：

1. 后端运行时代码：`backend/app/main.py`、`backend/app/services/services.py`、`backend/app/agent/`、`backend/app/core/settings.py`
2. 前端真实 API 适配层与页面：`frontend/src/services/api.ts`、`frontend/src/pages/AgentPage.tsx`、`frontend/src/pages/SettingsPage.tsx`
3. 根目录 `README.md`
4. 其他零散说明或界面中的静态文案

---

## 仓库定位

这是一个前后端同仓库维护的多平台舆情智能分析系统，主线覆盖：

```text
微博 / B站 / 抖音 热点与关键词采集
  -> 任务执行与进度跟踪
  -> 评论级情感分析
  -> 词云与 LDA 主题分析
  -> 报告导出
  -> QA / Agent 问答
  -> 平台 Cookie 健康检查与 crawler 配置管理
  -> React 可视化展示
```

当前仓库重点是：

- FastAPI 后端
- Playwright / 多平台 crawler
- SQLAlchemy 异步数据库访问
- 情感分析与文本分析
- Agent 工具调度、长期检索与会话记忆
- React + Vite 前端页面与 API 封装

这是一个前后端同仓库项目，不是“后端主仓 + 外部前端”的结构：

- 后端目录：`backend/`
- 前端目录：`frontend/`

默认只修改与当前请求直接相关的一侧；只有在接口契约、页面展示或联调明确受影响时，才同时检查前后端。

不要在仓库里新建第二套 `frontend/`、`backend/` 或“新版 API”目录来绕过现有结构。

---

## 项目一句话

多平台舆情智能分析系统，主线是：

- 采集微博 / 抖音 / B 站等平台数据
- 管理任务与执行进度
- 对评论进行情感分析
- 对帖子和评论做词云、LDA 与趋势分析
- 提供 QA 与 Agent 智能问答
- 在前端展示分析结果、平台诊断与导出报告

---

## 任务路由

遇到需求时，先按任务定位代码，不要全仓盲改：

| 用户要做什么 | 优先查看/修改 |
|--------------|---------------|
| 启动或修 API | `backend/run.py`、`backend/app/main.py`、`backend/app/core/database.py` |
| 任务创建、暂停、恢复、删除、进度问题 | `backend/app/main.py`、`backend/app/services/services.py`、`backend/app/models/sql_models.py` |
| 爬虫执行、平台适配、Windows 兼容 | `backend/app/crawler/`、`backend/app/crawler/worker.py`、`backend/app/services/services.py` |
| 情感分析 | `backend/app/sentiment/analyzer.py`、`backend/app/services/services.py` |
| 词云、LDA、文本分析 | `backend/app/services/text_analysis.py`、`backend/app/main.py` |
| Agent 对话、工具调用、记忆、状态 | `backend/app/agent/agent.py`、`backend/app/agent/tools.py`、`backend/app/agent/` |
| QA / 问答 | `backend/app/qa/llm_service.py`、`backend/app/main.py` |
| 报告导出 | `backend/app/services/report_service.py`、`backend/app/main.py` |
| 仪表盘指标 | `backend/app/services/dashboard_service.py`、`backend/app/main.py` |
| 系统设置、LLM 配置、平台配置、Cookie 健康 | `backend/app/core/settings.py`、`backend/app/main.py`、`frontend/src/pages/SettingsPage.tsx` |
| 前端 API 对接 | `frontend/src/services/api.ts`、相关页面 `frontend/src/pages/*.tsx` |
| Agent 页面展示与工具观测 | `frontend/src/pages/AgentPage.tsx`、`frontend/src/services/api.ts` |
| 首页、分析页、任务页 UI | `frontend/src/pages/HomePage.tsx`、`AnalysisPage.tsx`、`TaskManagementPage.tsx`、`HotTopicsPage.tsx` |

优先修改 `backend/app/` 和 `frontend/src/` 里的可复用核心逻辑；不要把正式业务逻辑塞进临时脚本。

---

## 架构边界

- `backend/app/main.py` 是 FastAPI 入口和路由聚合点；新增复杂逻辑时优先下沉到 `services/`、`agent/`、`qa/` 或 `crawler/`。
- 任务执行主链路由 `backend/app/services/services.py` 的 `run_task_logic()` 负责，流程是“爬虫子进程 -> 情感分析 -> 聚合分析 -> 知识同步”。
- Windows 下爬虫通过 `backend/app/crawler/worker.py` 子进程执行，目的是规避 Playwright 和事件循环兼容问题；不要轻易改回主进程直跑。
- Agent 编排集中在 `backend/app/agent/agent.py`，工具能力放在 `backend/app/agent/tools.py`、`tool_manager.py`、`retriever.py`、`vector_backends.py`。
- 系统设置优先通过 `backend/app/core/settings.py` 的 `DEFAULT_SETTINGS`、`SystemConfig` 和相关辅助函数读取与合并，不要在路由或页面里散写默认值。
- 数据库是异步 SQLAlchemy，启动时会在 `backend/app/main.py` 生命周期里执行 `Base.metadata.create_all()`；当前没有看到 Alembic 迁移体系，改模型字段时必须说明迁移或重建影响。
- 前端真实 API 入口是 `frontend/src/services/api.ts`；接口路径改动时，必须同步检查这里的 `endpoints` 常量和对应页面调用。
- 前端开发环境通过 `frontend/vite.config.ts` 代理 `/api` 到 `http://127.0.0.1:8000`；如果改动接口前缀或跨域行为，要一起评估。

---

## 数据与配置约束

- `.env`、数据库连接串、LLM API Key、Cookie 内容、运行日志都属于敏感信息，不要在回复里回显真实值。
- `backend/cookies_weibo.json`、`backend/cookies_douyin.json`、`backend/cookies_bili.json` 等 Cookie 文件属于敏感运行资产；如需修改，优先做最小变更，并提醒用户影响。
- `backend/app/core/settings.py` 已明确 `embedding_allow_download=False`；不要因为导入或测试而静默下载大模型、embedding 权重或 Playwright 浏览器资源。
- 后端数据库连接来自环境变量 `DATABASE_URL`；默认代码会把 `mysql+pymysql` 转成 `mysql+asyncmy`，不要把连接串硬编码进业务代码。
- LLM 配置支持环境变量与数据库设置混合读取；涉及 `api_key` 字段时，注意保留已有密钥并继续使用脱敏展示逻辑。
- 平台 Cookie 健康检查依赖关键字段，如 `SUB`、`SESSDATA`、`ttwid` 等；修改 Cookie 解析或健康检查时，不要破坏现有兼容“原始串 + JSON 数组”两种输入格式。
- 任务分析结果会写入 `AnalysisResult`，Agent 长期检索会在任务完成后尝试同步知识；改动任务收尾逻辑时要考虑下游影响。

---

## 前后端协作规则

- 改后端接口路径、请求参数、响应结构时，必须同步检查 `frontend/src/services/api.ts` 和受影响页面。
- 改 `/api/agent/chat` 返回结构时，优先检查 `frontend/src/pages/AgentPage.tsx` 对 `used_tool`、`decision_summary`、`tool_observation`、`risk_fingerprints` 的消费。
- 改 `/api/settings`、`/api/settings/platform-cookie`、`/api/settings/platform-crawler` 时，优先检查 `frontend/src/pages/SettingsPage.tsx`。
- 改任务详情、分析预览、词云、LDA、情感分析接口时，优先检查 `frontend/src/pages/AnalysisPage.tsx`、`TaskManagementPage.tsx` 及相关数据展示逻辑。
- 改仪表盘指标接口 `/api/v1/dashboard/metrics` 时，优先检查首页或统计页面的数据适配。
- 如果前端表单、默认值、下拉选项和后端真实配置不一致，以“后端真实路由 + 前端真实 API 调用代码”共同校验，不要只信 README 或页面静态文案。

当前已知容易漂移的点：

- `README.md` 中的示例和页面中的默认文案，可能比真实后端支持范围更宽。
- `SettingsPage.tsx` 含有部分模拟用户管理数据；不要误以为后端已经完整提供对应用户管理 API。
- 前端 `QAPage`、`AgentPage`、设置页对返回字段较敏感，改名容易造成直接报错。

---

## 何时必须先问用户

以下动作不能自行执行：

- 运行真实爬虫采集线上平台数据
- 覆盖、重写或清空 Cookie 文件
- 下载大模型、embedding 权重、Playwright 浏览器依赖
- 安装或升级重依赖，尤其是 `torch`、`transformers`、`sentence-transformers`、`playwright`
- 修改数据库结构、删除历史数据、重建库表
- 大范围重构、跨模块移动文件、重命名公共接口
- 同时大改前后端，但用户没有明确要求联动改造

可以直接做的小动作：

- 阅读文件并梳理调用链
- 修改与当前请求直接相关的小范围代码或文档
- 运行轻量语法检查、类型检查或聚焦测试
- 校对后端接口与前端 API 适配层是否一致

---

## 常用命令

安装后端依赖：

```bash
cd backend
pip install -r requirements.txt
```

启动后端：

```bash
cd backend
python run.py
```

后端健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

安装前端依赖：

```bash
cd frontend
npm install
```

启动前端：

```bash
cd frontend
npm run dev
```

后端基础语法校验：

```bash
python -m compileall backend/app
```

后端测试：

```bash
cd backend
pytest
```

前端构建：

```bash
cd frontend
npm run build
```

前端测试：

```bash
cd frontend
npm run test
```

---

## 校验矩阵

当前仓库没有看到统一的 Python 打包配置文件；校验要按改动范围选择最轻量、最安全的命令。

| 改动类型 | 建议校验 |
|----------|----------|
| 只改 Markdown 文档 | 通读结构、命令、路径和事实是否与当前仓库一致 |
| 只改后端 Python 语法或导入 | `python -m compileall backend/app` 或聚焦到具体目录 |
| 改 API 路由 | 编译 `backend/app/main.py` 及相关模块；必要时再做轻量导入校验 |
| 改任务执行链 | 编译 `backend/app/services/services.py`、`backend/app/crawler/`，不要未经确认直接跑采集 |
| 改 Agent | 编译 `backend/app/agent/`，如依赖齐全可运行聚焦测试文件 |
| 改情感分析 / 文本分析 | 编译 `backend/app/sentiment/`、`backend/app/services/text_analysis.py`，不要未经确认触发大模型下载 |
| 改设置 / Cookie / 平台配置 | 编译 `backend/app/core/settings.py`、`backend/app/main.py`，并检查 `frontend/src/pages/SettingsPage.tsx` |
| 改前端页面或 API 封装 | 优先 `cd frontend && npm run build`；如成本过高，至少通读类型与调用链 |
| 改前后端接口契约 | 后端编译相关模块，并检查 `frontend/src/services/api.ts` 与受影响页面 |

如果因为缺少 `.env`、数据库、LLM Key、浏览器依赖、模型权重或网络而无法完成校验，要在最终回复里明确说明。

---

## 关键文档入口

- 总览说明：`README.md`
- 后端入口：`backend/app/main.py`
- 任务执行链：`backend/app/services/services.py`
- Agent 主入口：`backend/app/agent/agent.py`
- 系统设置与 Cookie 规则：`backend/app/core/settings.py`
- 前端 API 适配层：`frontend/src/services/api.ts`
- Agent 页面：`frontend/src/pages/AgentPage.tsx`
- 设置页面：`frontend/src/pages/SettingsPage.tsx`

这些文件优先级高于 README 中的抽象描述。

---

## 完成任务前自检

1. 是否确认这次需求只改后端、只改前端，还是需要前后端联动？
2. 如果改了接口契约，是否同步检查了 `frontend/src/services/api.ts` 和受影响页面？
3. 是否保护了 `.env`、Cookie、数据库连接、API Key 等敏感信息？
4. 是否保持 `backend/app/main.py` 以路由聚合为主，没有把过重逻辑继续堆进去？
5. 如果改了任务执行、爬虫、Agent 或设置逻辑，是否考虑了前端页面的消费字段？
6. 如果改了模型字段或数据库模型，是否说明了迁移或重建影响？
7. 是否只运行了与本次改动直接相关、可安全执行的轻量校验？
8. 是否没有覆盖用户已有的未提交改动？
