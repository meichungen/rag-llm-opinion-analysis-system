from typing import Any, Dict, List, Optional
from datetime import datetime
import logging


logger = logging.getLogger(__name__)


class ConversationManager:
    def __init__(self, max_history: int = 20):
        self.conversation_history: Dict[str, List[Dict[str, Any]]] = {}
        self.max_history = max_history
        
    async def add_message(self, session_id: str, role: str, content: str) -> None:
        if session_id not in self.conversation_history:
            self.conversation_history[session_id] = []
        
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now()
        }
        
        self.conversation_history[session_id].append(message)
        
        if len(self.conversation_history[session_id]) > self.max_history:
            self.conversation_history[session_id] = self.conversation_history[session_id][-self.max_history:]
        
        logger.debug(f"对话历史更新：session={session_id}, role={role}, 内容长度={len(content)}")
    
    def get_conversation_context(self, session_id: str, max_turns: int = 5) -> List[Dict[str, Any]]:
        if session_id not in self.conversation_history:
            return []
        
        history = self.conversation_history[session_id]
        return history[-max_turns:] if len(history) > max_turns else history
    
    def get_full_conversation(self, session_id: str) -> List[Dict[str, Any]]:
        return self.conversation_history.get(session_id, [])
    
    def get_conversation_summary(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self.conversation_history:
            return {"total_messages": 0, "last_message": None}
        
        history = self.conversation_history[session_id]
        last_message = history[-1] if history else None
        
        user_messages = sum(1 for msg in history if msg["role"] == "user")
        assistant_messages = sum(1 for msg in history if msg["role"] == "assistant")
        
        return {
            "session_id": session_id,
            "total_messages": len(history),
            "user_messages": user_messages,
            "assistant_messages": assistant_messages,
            "last_message_time": last_message["timestamp"].isoformat() if last_message else None,
            "last_message_role": last_message["role"] if last_message else None,
            "last_message_preview": last_message["content"][:50] + "..." if last_message and len(last_message["content"]) > 50 else last_message["content"] if last_message else None
        }
    
    def clear_conversation(self, session_id: str) -> None:
        if session_id in self.conversation_history:
            del self.conversation_history[session_id]
            logger.info(f"对话历史已清除：session={session_id}")
    
    def get_all_sessions(self) -> List[str]:
        return list(self.conversation_history.keys())
    
    def get_session_stats(self) -> Dict[str, Any]:
        total_sessions = len(self.conversation_history)
        total_messages = sum(len(history) for history in self.conversation_history.values())
        
        return {
            "total_sessions": total_sessions,
            "total_messages": total_messages,
            "average_messages_per_session": round(total_messages / total_sessions, 2) if total_sessions > 0 else 0
        }
    
    def export_conversation(self, session_id: str, format: str = "json") -> Optional[Any]:
        if session_id not in self.conversation_history:
            return None
        
        history = self.conversation_history[session_id]
        
        if format == "json":
            return [
                {
                    "role": msg["role"],
                    "content": msg["content"],
                    "timestamp": msg["timestamp"].isoformat()
                }
                for msg in history
            ]
        elif format == "text":
            text_lines = []
            for msg in history:
                timestamp = msg["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
                text_lines.append(f"[{timestamp}] {msg['role'].upper()}: {msg['content']}")
            return "\n".join(text_lines)
        
        return None