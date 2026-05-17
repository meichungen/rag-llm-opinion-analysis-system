import logging
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
        top_k = int(self.agent_config.get("retrieval_top_k", 3))
        long_memory = await self.memory.search_long_term(query, top_k=top_k)

        try:
            observation, decision_summary = await self._execute_steps(
                query=query,
                session_id=session_id,
                short_memory=short_memory,
                long_memory=long_memory,
                trace=trace,
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
            answer = await self._chat(answer_prompt, temperature=self.temperature)
        except RuntimeError as llm_error:
            self.agent_status.update_progress(90, "回答生成阶段失败")
            error_response = ErrorHandler.build_error_response(
                query=query,
                error=llm_error,
                short_memory=short_memory,
                long_memory=long_memory,
                stage="回答生成阶段",
                used_tool=self.tool_manager.get_used_tool(),
                decision_summary=decision_summary,
                agent_trace=trace,
            )
            await self.conversation_manager.add_message(session_id, "assistant", error_response["answer"])
            self.agent_status.end_session(success=False, summary="回答生成阶段失败")
            return error_response

        if not answer:
            answer = ErrorHandler.get_fallback_answer(query, observation)

        self.agent_status.update_progress(92, "保存记忆和对话历史")
        await self.memory.add(session_id, {"role": "user", "content": query})
        await self.memory.add(session_id, {"role": "assistant", "content": answer})
        await self.conversation_manager.add_message(session_id, "assistant", answer)

        if self._should_create_task_chain(query):
            chain_id = await self._create_task_chain(session_id, query)
            logger.info("自动创建任务链：%s", chain_id)

        response_time = (datetime.now() - start_time).total_seconds()
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

    async def _execute_steps(
        self,
        *,
        query: str,
        session_id: str,
        short_memory: List[Dict[str, Any]],
        long_memory: Dict[str, Any],
        trace: List[Dict[str, Any]],
    ) -> tuple[Dict[str, Any], str]:
        observation: Dict[str, Any] = {"message": "本轮直接回答，无需调用工具。"}
        decision_summary = "Agent 判断当前问题可以直接回答，无需额外调用工具。"

        for step in range(1, self.max_steps + 1):
            progress = min(70, 25 + step * 12)
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

    async def _chat(self, prompt: str, temperature: float) -> str:
        api_key = APIConfig.get_combined_api_key(self.llm_config)
        base_url = APIConfig.get_combined_base_url(self.llm_config)

        if not api_key:
            raise RuntimeError("LLM API Key 未配置。")

        temp_client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=httpx.AsyncClient(timeout=httpx.Timeout(60.0)),
        )

        try:
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

    def _query_allows_high_risk_tool(self, query: str) -> bool:
        keywords = ["实时采集", "实时抓取", "现在采集", "现在抓取", "重新采集", "运行爬虫"]
        return any(keyword in query for keyword in keywords)
