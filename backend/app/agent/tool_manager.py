from typing import Any, Dict, Optional
import logging


logger = logging.getLogger(__name__)


class ToolManager:
    def __init__(self, tools: Dict[str, Any], enable_logging: bool = True):
        self.tools = tools
        self.enable_logging = enable_logging
        self.used_tool = "direct_answer"
        
    async def call_tool(self, action: str, params: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        if action not in self.tools:
            error_msg = f"工具 '{action}' 不存在"
            self._log_tool_error(session_id, action, error_msg)
            return {"error": error_msg, "fallback": "direct_answer"}
        
        try:
            self._log_tool_call(session_id, action, params)
            result = await self.tools[action](**params)
            self.used_tool = action
            self._log_tool_success(session_id, action)
            return result
        except Exception as exc:
            error_msg = f"工具执行失败: {exc}"
            self._log_tool_error(session_id, action, exc)
            return {"error": error_msg, "fallback": "direct_answer"}
    
    def _log_tool_call(self, session_id: str, action: str, params: Dict[str, Any]) -> None:
        if not self.enable_logging:
            return
        logger.info("Agent 调用工具 session=%s action=%s params=%s", 
                   session_id, action, params)
    
    def _log_tool_success(self, session_id: str, action: str) -> None:
        if not self.enable_logging:
            return
        logger.info("Agent 工具调用成功 session=%s action=%s", session_id, action)
    
    def _log_tool_error(self, session_id: str, action: str, error: Exception) -> None:
        logger.warning("Agent 工具调用失败，session=%s action=%s error=%s", 
                      session_id, action, error)
    
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
            summary = f"抓取状态: {status}，帖子 {total_posts} 条，评论 {total_comments} 条。"
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
        
        if thought:
            return f"{thought} (将调用工具：{action})"
        
        return f"Agent 判断当前问题需要调用工具 `{action}` 获取额外信息。"
