import logging
import time
from typing import Any, Dict, Optional

from pydantic import ValidationError

from app.agent.tools import ToolSpec


logger = logging.getLogger(__name__)


class ToolManager:
    def __init__(
        self,
        tools: Dict[str, Any],
        *,
        tool_specs: Optional[Dict[str, ToolSpec]] = None,
        enable_logging: bool = True,
    ):
        self.tools = tools
        self.tool_specs = tool_specs or {}
        self.enable_logging = enable_logging
        self.used_tool = "direct_answer"

    async def call_tool(self, action: str, params: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        if action not in self.tools:
            error_msg = f"工具 '{action}' 不存在。"
            self._log_tool_error(session_id, action, error_msg)
            return {"error": error_msg, "fallback": "direct_answer"}

        spec = self.tool_specs.get(action)
        validation = self.validate_parameters(action, params)
        if validation.get("error"):
            self._log_tool_error(session_id, action, validation["error"])
            return {"error": validation["error"], "fallback": "direct_answer"}

        safe_params = validation["parameters"]
        start_time = time.perf_counter()
        try:
            self._log_tool_call(session_id, action, safe_params)
            result = await self.tools[action](**safe_params)
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            self.used_tool = action
            self._log_tool_success(session_id, action, elapsed_ms)
            if isinstance(result, dict):
                result.setdefault("_tool_meta", {})
                result["_tool_meta"].update(
                    {
                        "name": action,
                        "elapsed_ms": elapsed_ms,
                        "risk_level": spec.risk_level if spec else "low",
                    }
                )
            return result
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            error_msg = f"工具执行失败: {exc}"
            self._log_tool_error(session_id, action, exc)
            return {
                "error": error_msg,
                "fallback": "direct_answer",
                "_tool_meta": {
                    "name": action,
                    "elapsed_ms": elapsed_ms,
                    "risk_level": spec.risk_level if spec else "low",
                },
            }

    def validate_parameters(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        spec = self.tool_specs.get(action)
        if not spec:
            return {"parameters": params}
        try:
            parsed = spec.parameters_model.model_validate(params)
        except ValidationError as exc:
            return {"error": f"工具参数校验失败: {exc.errors()}"}
        return {"parameters": parsed.model_dump()}

    def _log_tool_call(self, session_id: str, action: str, params: Dict[str, Any]) -> None:
        if not self.enable_logging:
            return
        logger.info("Agent 调用工具 session=%s action=%s params=%s", session_id, action, params)

    def _log_tool_success(self, session_id: str, action: str, elapsed_ms: float) -> None:
        if not self.enable_logging:
            return
        logger.info(
            "Agent 工具调用成功 session=%s action=%s elapsed_ms=%s",
            session_id,
            action,
            elapsed_ms,
        )

    def _log_tool_error(self, session_id: str, action: str, error: Any) -> None:
        logger.warning("Agent 工具调用失败 session=%s action=%s error=%s", session_id, action, error)

    def get_used_tool(self) -> str:
        return self.used_tool

    def reset_used_tool(self) -> None:
        self.used_tool = "direct_answer"

    def summarize_observation(self, observation: Dict[str, Any]) -> str:
        if observation.get("error"):
            return str(observation["error"])

        status = observation.get("status")
        if status in {"success", "partial_success", "failed"}:
            total_posts = observation.get("total_posts", 0)
            total_comments = observation.get("total_comments", 0)
            warnings = observation.get("warnings", []) or []
            summary = f"抓取状态 {status}，帖子 {total_posts} 条，评论 {total_comments} 条。"
            if warnings:
                summary += f" 告警 {len(warnings)} 条。"
            return summary

        if isinstance(observation.get("results"), list):
            count = len(observation["results"])
            return f"检索到 {count} 条相关结果。"

        if observation.get("message"):
            return str(observation["message"])

        for key in ("summary", "result", "data", "content"):
            if observation.get(key):
                text = str(observation[key])
                return text[:120] + "..." if len(text) > 120 else text

        return "工具已执行，但未返回可展示摘要。"

    def build_decision_summary(self, decision: Dict[str, Any]) -> str:
        action = decision.get("action", "direct_answer")
        thought = str(decision.get("thought", "")).strip()

        if action == "direct_answer":
            return thought or "Agent 判断当前问题可以直接回答，无需额外调用工具。"

        spec = self.tool_specs.get(action)
        risk = f"，风险等级：{spec.risk_level}" if spec else ""
        if thought:
            return f"{thought}（将调用工具：{action}{risk}）"

        return f"Agent 判断当前问题需要调用工具 `{action}` 获取额外信息{risk}。"
