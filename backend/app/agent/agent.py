import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.api_config import APIConfig
from app.agent.conversation_manager import ConversationManager
from app.agent.decision import parse_llm_decision
from app.agent.error_handler import ErrorHandler
from app.agent.memory import AgentMemory
from app.agent.prompts import build_answer_prompt, build_decision_prompt
from app.agent.status_manager import StatusManager
from app.agent.task_chain import TaskChain
from app.agent.tool_manager import ToolManager
from app.agent.tools import AgentTools
from app.core.settings import DEFAULT_SETTINGS


logger = logging.getLogger(__name__)


_PLATFORM_ALIASES = {
    "weibo": ("weibo", "微博"),
    "douyin": ("douyin", "抖音", "douyin"),
    "bilibili": ("bilibili", "b站", "B站", "哔哩哔哩", "bili"),
}

_HIGH_RISK_CONFIRMATION_KEYWORDS = [
    "实时采集",
    "实时抓取",
    "现在采集",
    "现在抓取",
    "重新采集",
    "运行爬虫",
    "调用爬虫",
    "启动爬虫",
    "允许爬虫",
    "确认采集",
    "同意采集",
    "开始采集",
    "立即采集",
    "帮我采集",
    "请采集",
]

_HIGH_RISK_CONFIRMATION_PATTERNS = [
    r"(允许|同意|确认|可以|准许|批准|继续|执行|开始|启动|运行).{0,12}(爬虫|采集|抓取|crawl_data)",
    r"(爬虫|采集|抓取|crawl_data).{0,12}(允许|同意|确认|可以|准许|批准|继续|执行|开始|启动|运行)",
    r"(明确要求|明确需要|需要|请|帮我|立即|现在|实时|重新).{0,20}(采集|抓取|爬取|爬虫)",
    r"(采集|抓取|爬取).{0,30}(帖子|评论|数据|内容|抖音|微博|b站|哔哩哔哩|bilibili)",
]


class OpinionAgent:
    def __init__(
        self,
        db: AsyncSession,
        llm_config: Optional[Dict[str, Any]] = None,
        agent_config: Optional[Dict[str, Any]] = None,
    ):
        self.db = db
        self.llm_config = llm_config or {}
        self.agent_config = {**DEFAULT_SETTINGS["agent"], **(agent_config or {})}

        self.toolkit = AgentTools(db, self.agent_config)
        self.tool_specs = self.toolkit.list_tool_specs()
        self.tools = self.toolkit.list_tools()
        self.tool_manager = ToolManager(
            self.tools,
            tool_specs=self.tool_specs,
            enable_logging=bool(self.agent_config.get("enable_tool_logging", True)),
        )

        self.memory = AgentMemory(searcher=self._search_long_term, config=self.agent_config)
        self.conversation_manager = ConversationManager(
            max_history=int(self.agent_config.get("max_conversation_history", 20))
        )

        self.status_manager = StatusManager()
        self.agent_id = f"agent-{id(self)}"
        self.status_manager.register_agent(self.agent_id)
        self.agent_status = self.status_manager.agents[self.agent_id]

        self.active_chains: Dict[str, TaskChain] = {}
        self.model = self.llm_config.get("model", "qwen-plus")
        self.temperature = float(self.llm_config.get("temperature", 0.3))
        self.max_tokens = int(self.llm_config.get("max_tokens", 1000))
        self.max_steps = int(self.agent_config.get("max_agent_steps", 3))
        self.llm_timeout_seconds = float(self.agent_config.get("llm_timeout_seconds", 60))
        self.answer_llm_timeout_seconds = float(
            self.agent_config.get("answer_llm_timeout_seconds", 30)
        )
        self.llm_max_retries = int(self.agent_config.get("llm_max_retries", 1))

        logger.info("OpinionAgent initialized with model=%s agent_id=%s", self.model, self.agent_id)

    async def run(self, query: str, session_id: str) -> str:
        result = await self.run_detail(query, session_id)
        return result["answer"]

    async def run_detail(self, query: str, session_id: str) -> Dict[str, Any]:
        start_time = datetime.now()
        trace: List[Dict[str, Any]] = []
        observation: Dict[str, Any] = {"message": "本轮直接回答，无需调用工具。"}
        decision_summary = ""

        self.agent_status.start_session(session_id, query)
        self.agent_status.update_progress(10, "开始处理查询")
        await self.conversation_manager.add_message(session_id, "user", query)

        self.agent_status.update_progress(20, "读取记忆")
        short_memory = await self.memory.get(session_id)
        direct_crawl_decision = self._build_direct_crawl_decision(query, short_memory)
        missing_crawl_context = self._build_missing_crawl_context_observation(
            query,
            direct_crawl_decision,
        )
        top_k = int(self.agent_config.get("retrieval_top_k", 3))
        long_memory = (
            {"query": query, "results": []}
            if direct_crawl_decision or missing_crawl_context
            else await self.memory.search_long_term(query, top_k=top_k)
        )
        if missing_crawl_context:
            trace.append(
                {
                    "step": 1,
                    "thought": "用户表达了采集或爬虫许可，但缺少平台或关键词，使用本地澄清避免额外 LLM 调用。",
                    "action": "crawl_data",
                    "parameters": {},
                    "status": "blocked",
                    "risk_level": "high",
                    "observation_summary": missing_crawl_context["message"],
                }
            )
            return await self._finalize_response(
                query=query,
                session_id=session_id,
                start_time=start_time,
                answer=missing_crawl_context["message"],
                observation=missing_crawl_context,
                decision_summary="需要补充平台、关键词和采集数量后才能安全调用实时采集工具。",
                short_memory=short_memory,
                long_memory=long_memory,
                trace=trace,
                success=True,
            )

        try:
            observation, decision_summary = await self._execute_steps(
                query=query,
                session_id=session_id,
                short_memory=short_memory,
                long_memory=long_memory,
                trace=trace,
                direct_decision=direct_crawl_decision,
            )
        except RuntimeError as llm_error:
            self.agent_status.update_progress(90, "决策阶段失败")
            error_response = ErrorHandler.build_error_response(
                query=query,
                error=llm_error,
                short_memory=short_memory,
                long_memory=long_memory,
                stage="决策阶段",
                used_tool=self.tool_manager.get_used_tool(),
                agent_trace=trace,
            )
            await self.conversation_manager.add_message(session_id, "assistant", error_response["answer"])
            self.agent_status.end_session(success=False, summary="决策阶段失败")
            return error_response

        if self._should_skip_answer_llm(observation):
            self.agent_status.update_progress(85, "生成本地工具摘要")
            answer = ErrorHandler.get_fallback_answer(query, observation)
        else:
            self.agent_status.update_progress(75, "构建回答提示")
            answer_prompt = build_answer_prompt(
                query=query,
                short_memory=short_memory,
                long_memory=long_memory,
                used_tool=self.tool_manager.get_used_tool(),
                observation=observation,
                trace=trace,
            )

            try:
                self.agent_status.update_progress(85, "调用 LLM 生成回答")
                answer = await self._chat(
                    answer_prompt,
                    temperature=self.temperature,
                    timeout_seconds=self.answer_llm_timeout_seconds,
                    max_retries=0,
                )
            except RuntimeError as llm_error:
                self.agent_status.update_progress(90, "回答生成阶段降级")
                answer = ErrorHandler.get_fallback_answer(
                    query=query,
                    observation=observation,
                    generation_error=llm_error,
                )

        if not answer:
            answer = ErrorHandler.get_fallback_answer(query, observation)

        return await self._finalize_response(
            query=query,
            session_id=session_id,
            start_time=start_time,
            answer=answer,
            observation=observation,
            decision_summary=decision_summary,
            short_memory=short_memory,
            long_memory=long_memory,
            trace=trace,
        )

    async def _execute_steps(
        self,
        *,
        query: str,
        session_id: str,
        short_memory: List[Dict[str, Any]],
        long_memory: Dict[str, Any],
        trace: List[Dict[str, Any]],
        direct_decision: Optional[Dict[str, Any]] = None,
    ) -> tuple[Dict[str, Any], str]:
        observation: Dict[str, Any] = {"message": "本轮直接回答，无需调用工具。"}
        decision_summary = "Agent 判断当前问题可以直接回答，无需额外调用工具。"

        for step in range(1, self.max_steps + 1):
            progress = min(70, 25 + step * 12)
            if direct_decision and step == 1:
                self.agent_status.update_progress(progress, "第 1 步：本地规则命中实时采集")
                decision = direct_decision
            else:
                self.agent_status.update_progress(progress, f"第 {step} 步：生成决策")
                decision_prompt = build_decision_prompt(
                    query,
                    short_memory,
                    long_memory,
                    self.tools,
                    trace=trace,
                    step=step,
                    max_steps=self.max_steps,
                )
                decision_text = await self._chat(decision_prompt, temperature=0.2)
                decision = parse_llm_decision(decision_text, self.tools, query)
            action = decision["action"]
            params = decision["parameters"]
            decision_summary = self.tool_manager.build_decision_summary(decision)

            trace_step: Dict[str, Any] = {
                "step": step,
                "thought": decision.get("thought", ""),
                "action": action,
                "parameters": params,
                "status": "planned",
                "risk_level": self.tool_specs.get(action).risk_level if action in self.tool_specs else "low",
            }

            if action == "direct_answer":
                trace_step.update(
                    {
                        "status": "final",
                        "observation_summary": "模型判断当前上下文足够，进入最终回答。",
                    }
                )
                trace.append(trace_step)
                break

            spec = self.tool_specs.get(action)
            if spec and spec.requires_confirmation and not self._query_allows_high_risk_tool(query):
                observation = {
                    "error": "该问题没有明确要求实时采集，已阻止高风险爬虫工具调用。",
                    "fallback": "direct_answer",
                    "message": "请明确说明需要实时采集后再触发爬虫。",
                }
                trace_step.update(
                    {
                        "status": "blocked",
                        "observation_summary": observation["error"],
                    }
                )
                trace.append(trace_step)
                break

            self.agent_status.update_progress(min(72, progress + 5), f"第 {step} 步：调用工具 {action}")
            observation = await self.tool_manager.call_tool(action, params, session_id)
            self.agent_status.record_tool_call(action, success=observation.get("error") is None)
            trace_step.update(
                {
                    "status": "failed" if observation.get("error") else "success",
                    "observation_summary": self.tool_manager.summarize_observation(observation),
                    "elapsed_ms": observation.get("_tool_meta", {}).get("elapsed_ms"),
                }
            )
            trace.append(trace_step)

            if observation.get("error") or decision.get("final") or step == self.max_steps:
                break

        return observation, decision_summary

    async def _finalize_response(
        self,
        *,
        query: str,
        session_id: str,
        start_time: datetime,
        answer: str,
        observation: Dict[str, Any],
        decision_summary: str,
        short_memory: List[Dict[str, Any]],
        long_memory: Dict[str, Any],
        trace: List[Dict[str, Any]],
        success: Optional[bool] = None,
    ) -> Dict[str, Any]:
        self.agent_status.update_progress(92, "保存记忆和对话历史")
        await self.memory.add(session_id, {"role": "user", "content": query})
        await self.memory.add(session_id, {"role": "assistant", "content": answer})
        await self.conversation_manager.add_message(session_id, "assistant", answer)

        if self._should_create_task_chain(query):
            chain_id = await self._create_task_chain(session_id, query)
            logger.info("自动创建任务链：%s", chain_id)

        response_time = (datetime.now() - start_time).total_seconds()
        if success is None:
            success = bool(answer) and not answer.startswith("我先直接回答：当前工具调用失败")

        self.agent_status.record_query(success=success, response_time=response_time)
        self.agent_status.update_progress(100, "处理完成")
        self.agent_status.end_session(success=success, summary=f"处理完成，用时 {response_time:.2f} 秒")

        response = {
            "answer": answer,
            "used_tool": self.tool_manager.get_used_tool(),
            "decision_summary": decision_summary,
            "observation_summary": self.tool_manager.summarize_observation(observation),
            "tool_observation": observation,
            "short_memory_turns": len(short_memory),
            "long_memory_hits": len(long_memory.get("results", [])),
            "conversation_context": self.conversation_manager.get_conversation_context(session_id),
            "session_stats": self.conversation_manager.get_conversation_summary(session_id),
            "processing_time": response_time,
            "agent_status": self.agent_status.get_status_report(),
            "agent_trace": trace,
        }

        self.tool_manager.reset_used_tool()
        return response

    async def create_task_chain(self, session_id: str, queries: List[str]) -> str:
        chain_id = f"chain-{len(self.active_chains) + 1}"
        chain = TaskChain(self, session_id)

        for i, query in enumerate(queries):
            priority = len(queries) - i
            await chain.add_task(query, priority)

        self.active_chains[chain_id] = chain
        chain.status = "ready"

        logger.info("创建任务链：%s，包含 %s 个任务", chain_id, len(queries))
        return chain_id

    async def execute_task_chain(self, chain_id: str) -> List[Dict[str, Any]]:
        if chain_id not in self.active_chains:
            raise ValueError(f"任务链 {chain_id} 不存在。")

        chain = self.active_chains[chain_id]
        results = await chain.execute_all()

        logger.info("任务链执行完成：%s，成功 %s 个任务", chain_id, len(results))
        return results

    async def get_chain_status(self, chain_id: str) -> Dict[str, Any]:
        if chain_id not in self.active_chains:
            raise ValueError(f"任务链 {chain_id} 不存在。")
        return self.active_chains[chain_id].get_progress_report()

    async def get_all_chains_status(self) -> Dict[str, Any]:
        chains_status = {
            chain_id: chain.get_summary() for chain_id, chain in self.active_chains.items()
        }
        return {
            "total_chains": len(self.active_chains),
            "chains": chains_status,
            "active_chains": sum(
                1 for item in self.active_chains.values() if item.status in ["executing", "ready"]
            ),
            "completed_chains": sum(
                1 for item in self.active_chains.values() if item.status == "completed"
            ),
        }

    async def pause_chain(self, chain_id: str) -> None:
        if chain_id not in self.active_chains:
            raise ValueError(f"任务链 {chain_id} 不存在。")
        await self.active_chains[chain_id].pause()

    async def resume_chain(self, chain_id: str) -> None:
        if chain_id not in self.active_chains:
            raise ValueError(f"任务链 {chain_id} 不存在。")
        await self.active_chains[chain_id].resume()

    async def cancel_chain(self, chain_id: str) -> None:
        if chain_id not in self.active_chains:
            raise ValueError(f"任务链 {chain_id} 不存在。")
        await self.active_chains[chain_id].cancel()

    async def get_conversation_history(
        self, session_id: str, max_turns: int = 10
    ) -> List[Dict[str, Any]]:
        return self.conversation_manager.get_conversation_context(session_id, max_turns)

    async def clear_conversation(self, session_id: str) -> None:
        self.conversation_manager.clear_conversation(session_id)
        logger.info("对话历史已清除：session=%s", session_id)

    async def get_session_stats(self) -> Dict[str, Any]:
        return self.conversation_manager.get_session_stats()

    async def _chat(
        self,
        prompt: str,
        temperature: float,
        *,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> str:
        api_key = APIConfig.get_combined_api_key(self.llm_config)
        base_url = APIConfig.get_combined_base_url(self.llm_config)

        if not api_key:
            raise RuntimeError("LLM API Key 未配置。")

        request_timeout = timeout_seconds if timeout_seconds is not None else self.llm_timeout_seconds
        request_retries = max_retries if max_retries is not None else self.llm_max_retries

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(request_timeout)) as http_client:
                temp_client = AsyncOpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    http_client=http_client,
                    max_retries=request_retries,
                )
                response = await temp_client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "你是舆情分析系统的多工具 Agent。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    max_tokens=self.max_tokens,
                )
            content = response.choices[0].message.content
            if not content:
                logger.warning("LLM returned empty content")
                return ""
            return content
        except Exception as exc:
            ErrorHandler.log_llm_error(exc)
            raise RuntimeError(f"LLM API 调用失败: {exc}") from exc

    async def _search_long_term(self, query: str, top_k: int) -> Dict[str, Any]:
        try:
            return await self.toolkit.vector_search(query=query, top_k=top_k)
        except Exception as exc:
            logger.error("长期记忆搜索失败：%s", exc)
            return {"query": query, "results": []}

    def _should_create_task_chain(self, query: str) -> bool:
        if len(query) < 10:
            return False
        chain_keywords = ["多个任务", "分别分析", "逐一", "依次", "先", "再", "然后"]
        return any(keyword in query for keyword in chain_keywords)

    async def _create_task_chain(self, session_id: str, query: str) -> str:
        chain_id = f"auto-chain-{len(self.active_chains) + 1}"
        chain = TaskChain(self, session_id)

        tasks = self._extract_tasks_from_query(query)
        for i, task_query in enumerate(tasks):
            priority = len(tasks) - i
            await chain.add_task(task_query, priority)

        self.active_chains[chain_id] = chain
        chain.status = "ready"
        return chain_id

    async def get_agent_status_report(self) -> Dict[str, Any]:
        return self.agent_status.get_status_report()

    async def get_agent_performance_report(self, time_range: str = "day") -> Dict[str, Any]:
        return self.agent_status.get_performance_report(time_range)

    async def get_system_status(self) -> Dict[str, Any]:
        return self.status_manager.get_all_agents_status()

    async def get_system_health(self) -> Dict[str, Any]:
        return self.status_manager.get_system_health()

    async def update_health_check(self) -> None:
        self.status_manager.update_health_check()

    async def cleanup_old_activities(self, max_age_hours: int = 24) -> None:
        self.status_manager.cleanup_old_activities(max_age_hours)

    def _extract_tasks_from_query(self, query: str) -> List[str]:
        tasks = []
        if "情感分析" in query:
            tasks.append("进行情感分析")
        if "主题分析" in query:
            tasks.append("进行主题分析")
        if "趋势分析" in query:
            tasks.append("分析趋势变化")
        if "收集" in query or "获取" in query or "采集" in query:
            tasks.append("收集相关数据")
        if "总结" in query or "汇总" in query:
            tasks.append("总结分析结果")
        if "报告" in query:
            tasks.append("生成分析报告")
        return tasks if tasks else [query]

    def _build_direct_crawl_decision(
        self,
        query: str,
        short_memory: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self._query_allows_high_risk_tool(query):
            return None

        source_text = self._resolve_crawl_context_query(query, short_memory or [])
        platform = self._infer_platform_from_query(source_text)
        keyword = self._infer_keyword_from_query(source_text)
        if not platform or not keyword:
            return None

        return {
            "thought": "用户已明确要求实时采集，使用本地规则直接调用 crawl_data，避免额外 LLM 决策消耗。",
            "action": "crawl_data",
            "parameters": {
                "platform": platform,
                "keyword": keyword,
                "post_count": self._infer_count_from_query(source_text, "post_count", 10),
                "comment_count": self._infer_count_from_query(source_text, "comment_count", 10),
            },
            "final": True,
        }

    def _resolve_crawl_context_query(
        self,
        query: str,
        short_memory: List[Dict[str, Any]],
    ) -> str:
        if self._infer_platform_from_query(query) and self._infer_keyword_from_query(query):
            return query
        for item in reversed(short_memory):
            if item.get("role") != "user":
                continue
            previous = str(item.get("content") or "")
            if self._query_allows_high_risk_tool(previous) and self._infer_platform_from_query(previous):
                return previous
        return query

    def _build_missing_crawl_context_observation(
        self,
        query: str,
        direct_decision: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if direct_decision or not self._looks_like_crawl_confirmation(query):
            return None
        return {
            "error": "缺少实时采集所需的平台或关键词。",
            "fallback": "direct_answer",
            "message": (
                "我已收到爬虫调用许可，但还缺少采集对象。请在同一句里说明平台、关键词和数量，"
                "例如：实时采集抖音关于“首届南北早餐争霸赛”的前10个帖子及共100条评论。"
            ),
        }

    def _should_skip_answer_llm(self, observation: Dict[str, Any]) -> bool:
        tool_meta = observation.get("_tool_meta") or {}
        return tool_meta.get("name") == "crawl_data" or (
            "success" in observation
            and "total_posts" in observation
            and "total_comments" in observation
            and observation.get("status") in {"success", "partial_success", "failed"}
        )

    def _infer_platform_from_query(self, query: str) -> Optional[str]:
        lowered = query.lower()
        for platform, aliases in _PLATFORM_ALIASES.items():
            if any(alias.lower() in lowered for alias in aliases):
                return platform
        return None

    def _infer_keyword_from_query(self, query: str) -> str:
        text = query
        quoted = re.search(r"[“\"']([^”\"']{2,80})[”\"']", text)
        if quoted:
            return quoted.group(1).strip()

        segment = self._extract_keyword_segment(query)
        if segment:
            text = segment

        for aliases in _PLATFORM_ALIASES.values():
            for alias in aliases:
                text = re.sub(re.escape(alias), " ", text, flags=re.IGNORECASE)

        text = re.split(
            r"(?:的)?(?:前|最新)?\s*\d+\s*(?:个|条)?\s*(?:帖子|评论|视频|作品)"
            r"|(?:共|总共|总计|合计)\s*\d+\s*(?:条)?\s*评论"
            r"|(?:将|请|帮我|给我|输出|总结|汇总|概括|摘要|不超过|需|需要|最新)",
            text,
            maxsplit=1,
        )[0]
        text = re.sub(r"(前|最新)\s*\d+\s*(个|条)?\s*(帖子|评论|视频|作品)?", " ", text)
        text = re.sub(r"\d+\s*(个|条)?\s*(帖子|评论|视频|作品)", " ", text)
        text = re.sub(r"\d+\s*字", " ", text)
        text = re.sub(r"(共|总共|总计|合计|每条|每个|每篇|每则)?\s*\d+\s*(条)?\s*评论", " ", text)
        stop_words = [
            "用户",
            "明确",
            "要求",
            "需要",
            "帮我",
            "请",
            "实时",
            "现在",
            "重新",
            "立即",
            "采集",
            "抓取",
            "爬取",
            "获取",
            "搜索",
            "搜",
            "检索",
            "查询",
            "调用",
            "启动",
            "运行",
            "允许",
            "爬虫",
            "工具",
            "帖子",
            "评论",
            "数据",
            "内容",
            "总结",
            "汇总",
            "概括",
            "摘要",
            "输出",
            "超过",
            "不超过",
            "总计",
            "总共",
            "合计",
            "最新",
            "关于",
            "平台",
            "将",
            "给我",
            "需",
            "及",
            "和",
            "的",
        ]
        for word in stop_words:
            text = text.replace(word, " ")
        text = re.sub(r"[，。！？、；：:,.!?/\\|()\[\]{}<>《》]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _extract_keyword_segment(self, query: str) -> str:
        aliases = sorted(
            {alias for group in _PLATFORM_ALIASES.values() for alias in group},
            key=len,
            reverse=True,
        )
        platform_pattern = "|".join(re.escape(alias) for alias in aliases)
        separators = r"，。！？；;,.!?\n"
        patterns = [
            rf"(?:{platform_pattern})\s*(?:搜索|搜|检索|查询|查找|关于|话题)?\s*([^{separators}]{{2,80}})",
            rf"(?:搜索|搜|检索|查询|查找|关于|话题)\s*([^{separators}]{{2,80}})",
        ]
        for pattern in patterns:
            match = re.search(pattern, query, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return ""

    def _infer_count_from_query(self, query: str, name: str, default: int) -> int:
        patterns = {
            "post_count": [
                r"(\d+)\s*(?:个|条)?\s*(?:帖子|视频|作品)",
                r"(?:前|最新)\s*(\d+)\s*(?:个|条)?\s*(?:帖子|视频|作品)",
                r"(?:帖子|视频|作品)\s*(\d+)\s*(?:个|条)?",
            ],
            "comment_count": [
                r"(?:共|总共|总计|合计|每条|每个|每篇|每则)?\s*(\d+)\s*(?:条)?\s*评论",
                r"评论\s*(\d+)\s*(?:条)?",
            ],
        }
        for pattern in patterns.get(name, []):
            match = re.search(pattern, query)
            if match:
                value = int(match.group(1))
                if name == "post_count":
                    return max(1, min(value, 100))
                return max(1, min(value, 500))
        return default

    def _query_allows_high_risk_tool(self, query: str) -> bool:
        normalized = re.sub(r"\s+", "", query.lower())
        if self._looks_like_existing_data_query(normalized):
            return False

        if any(keyword.lower() in normalized for keyword in _HIGH_RISK_CONFIRMATION_KEYWORDS):
            return True

        return any(re.search(pattern, normalized) for pattern in _HIGH_RISK_CONFIRMATION_PATTERNS)

    def _looks_like_existing_data_query(self, normalized_query: str) -> bool:
        existing_terms = [
            "已采集",
            "已抓取",
            "已有",
            "现有",
            "历史",
            "之前采集",
            "任务数据",
            "当前任务",
        ]
        explicit_terms = [
            "实时采集",
            "实时抓取",
            "现在采集",
            "现在抓取",
            "重新采集",
            "重新抓取",
            "立即采集",
            "立即抓取",
            "开始采集",
            "开始抓取",
            "运行爬虫",
            "调用爬虫",
            "启动爬虫",
            "允许爬虫",
            "允许采集",
            "同意采集",
            "确认采集",
        ]
        return any(term in normalized_query for term in existing_terms) and not any(
            term in normalized_query for term in explicit_terms
        )

    def _looks_like_crawl_confirmation(self, query: str) -> bool:
        normalized = re.sub(r"\s+", "", query.lower())
        terms = [
            "允许爬虫",
            "同意采集",
            "确认采集",
            "允许采集",
            "可以采集",
            "继续采集",
            "调用爬虫",
            "启动爬虫",
            "运行爬虫",
            "允许crawl_data",
        ]
        if any(term in normalized for term in terms):
            return True
        return any(
            re.search(pattern, normalized)
            for pattern in [
                r"(允许|同意|确认|可以|继续|执行|开始|启动|运行).{0,12}(爬虫|采集|抓取|crawl_data)",
                r"(爬虫|采集|抓取|crawl_data).{0,12}(允许|同意|确认|可以|继续|执行|开始|启动|运行)",
            ]
        )
