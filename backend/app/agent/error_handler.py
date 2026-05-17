import logging
from typing import Any, Dict, Optional


logger = logging.getLogger(__name__)


class ErrorHandler:
    @staticmethod
    def build_error_response(
        query: str,
        error: Exception,
        short_memory: list,
        long_memory: dict,
        stage: str,
        used_tool: str = "direct_answer",
        decision_summary: Optional[str] = None,
        agent_trace: Optional[list] = None,
    ) -> Dict[str, Any]:
        error_msg = str(error)

        if "401" in error_msg or "Authentication" in error_msg:
            answer = f"API 认证失败：请检查 API Key 配置是否正确。错误详情：{error_msg}"
        elif "timeout" in error_msg.lower():
            answer = f"请求超时：请检查网络连接后重试。错误详情：{error_msg}"
        elif "connection" in error_msg.lower():
            answer = f"网络连接失败：请检查网络设置。错误详情：{error_msg}"
        else:
            answer = f"Agent 在{stage}处理失败：{error_msg}。请稍后重试。"

        return {
            "answer": answer,
            "used_tool": used_tool,
            "decision_summary": decision_summary or f"{stage}处理失败",
            "observation_summary": error_msg,
            "short_memory_turns": len(short_memory),
            "long_memory_hits": len(long_memory.get("results", [])),
            "tool_observation": {"error": error_msg},
            "agent_trace": agent_trace or [],
        }

    @staticmethod
    def log_tool_error(session_id: str, action: str, error: Exception) -> None:
        logger.warning("Agent 工具调用失败 session=%s action=%s error=%s", session_id, action, error)

    @staticmethod
    def log_llm_error(error: Exception) -> None:
        logger.error("LLM API call failed: %s", error, exc_info=True)

    @staticmethod
    def get_fallback_answer(query: str, observation: Dict[str, Any]) -> str:
        error = observation.get("error")
        if error:
            return (
                "我先直接回答：当前工具调用失败，"
                f"原因是“{error}”。请补充更具体的关键词，或先完成相关采集任务后再试。"
            )

        if observation.get("results"):
            count = len(observation["results"])
            return f"已检索到 {count} 条相关信息，但无法生成详细分析。请尝试更具体的问题。"

        return f"已收到你的问题：{query}。当前 Agent 无法访问大模型服务，请检查 API 配置后重试。"
