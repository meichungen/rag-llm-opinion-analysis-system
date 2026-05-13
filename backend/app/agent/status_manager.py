from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import asyncio
import logging


logger = logging.getLogger(__name__)


class AgentStatus:
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.status = "idle"
        self.current_session: Optional[str] = None
        self.current_task: Optional[str] = None
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.progress = 0.0
        self.metrics: Dict[str, Any] = {
            "total_queries": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "total_tool_calls": 0,
            "average_response_time": 0.0,
            "last_error": None
        }
        self.recent_activities: List[Dict[str, Any]] = []
        self.max_activities = 50
        
    def start_session(self, session_id: str, task: str = None) -> None:
        self.status = "active"
        self.current_session = session_id
        self.current_task = task
        self.start_time = datetime.now()
        self.progress = 0.0
        
        self._add_activity("session_started", {
            "session_id": session_id,
            "task": task,
            "timestamp": self.start_time.isoformat()
        })
        
        logger.info(f"Agent {self.agent_id} 开始会话：{session_id}，任务：{task}")
    
    def update_progress(self, progress: float, message: str = None) -> None:
        self.progress = max(0.0, min(100.0, progress))
        
        if message:
            self._add_activity("progress_updated", {
                "progress": self.progress,
                "message": message,
                "timestamp": datetime.now().isoformat()
            })
        
        logger.debug(f"Agent {self.agent_id} 进度更新：{self.progress}%")
    
    def record_query(self, success: bool, response_time: float = None, error: str = None) -> None:
        self.metrics["total_queries"] += 1
        
        if success:
            self.metrics["successful_queries"] += 1
        else:
            self.metrics["failed_queries"] += 1
            self.metrics["last_error"] = error
        
        if response_time is not None:
            current_avg = self.metrics["average_response_time"]
            total_queries = self.metrics["total_queries"]
            self.metrics["average_response_time"] = (
                (current_avg * (total_queries - 1) + response_time) / total_queries
            )
    
    def record_tool_call(self, tool_name: str, success: bool) -> None:
        self.metrics["total_tool_calls"] += 1
        
        self._add_activity("tool_called", {
            "tool": tool_name,
            "success": success,
            "timestamp": datetime.now().isoformat()
        })
    
    def end_session(self, success: bool = True, summary: str = None) -> None:
        self.status = "idle"
        self.end_time = datetime.now()
        
        duration = None
        if self.start_time and self.end_time:
            duration = (self.end_time - self.start_time).total_seconds()
        
        self._add_activity("session_ended", {
            "session_id": self.current_session,
            "success": success,
            "duration": duration,
            "summary": summary,
            "timestamp": self.end_time.isoformat()
        })
        
        logger.info(f"Agent {self.agent_id} 结束会话：{self.current_session}，"
                   f"成功：{success}，时长：{duration}秒")
        
        self.current_session = None
        self.current_task = None
        self.progress = 0.0
    
    def get_status_report(self) -> Dict[str, Any]:
        current_time = datetime.now()
        uptime = None
        if self.start_time:
            uptime = (current_time - self.start_time).total_seconds()
        
        return {
            "agent_id": self.agent_id,
            "status": self.status,
            "current_session": self.current_session,
            "current_task": self.current_task,
            "progress": self.progress,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "uptime": uptime,
            "metrics": self.metrics.copy(),
            "recent_activities": self.recent_activities[-10:] if self.recent_activities else []
        }
    
    def get_performance_report(self, time_range: str = "day") -> Dict[str, Any]:
        now = datetime.now()
        
        if time_range == "hour":
            start_time = now - timedelta(hours=1)
        elif time_range == "day":
            start_time = now - timedelta(days=1)
        elif time_range == "week":
            start_time = now - timedelta(weeks=1)
        else:
            start_time = now - timedelta(days=1)
        
        recent_activities = [
            activity for activity in self.recent_activities
            if datetime.fromisoformat(activity["timestamp"]) >= start_time
        ]
        
        successful_queries = sum(1 for activity in recent_activities 
                               if activity["type"] == "query_completed" and activity.get("success"))
        failed_queries = sum(1 for activity in recent_activities 
                            if activity["type"] == "query_completed" and not activity.get("success"))
        tool_calls = sum(1 for activity in recent_activities 
                        if activity["type"] == "tool_called")
        
        return {
            "time_range": time_range,
            "start_time": start_time.isoformat(),
            "end_time": now.isoformat(),
            "total_queries": successful_queries + failed_queries,
            "successful_queries": successful_queries,
            "failed_queries": failed_queries,
            "success_rate": (successful_queries / (successful_queries + failed_queries) * 100 
                           if (successful_queries + failed_queries) > 0 else 0),
            "tool_calls": tool_calls,
            "recent_errors": [
                activity for activity in recent_activities
                if activity["type"] == "error_occurred"
            ][-5:]
        }
    
    def _add_activity(self, activity_type: str, data: Dict[str, Any]) -> None:
        activity = {
            "type": activity_type,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        
        self.recent_activities.append(activity)
        
        if len(self.recent_activities) > self.max_activities:
            self.recent_activities = self.recent_activities[-self.max_activities:]


class StatusManager:
    def __init__(self):
        self.agents: Dict[str, AgentStatus] = {}
        self.system_status = "running"
        self.system_start_time = datetime.now()
        self.system_metrics: Dict[str, Any] = {
            "total_agents": 0,
            "active_agents": 0,
            "total_sessions": 0,
            "active_sessions": 0,
            "total_queries": 0,
            "queries_per_minute": 0.0,
            "last_health_check": None
        }
    
    def register_agent(self, agent_id: str) -> AgentStatus:
        if agent_id not in self.agents:
            self.agents[agent_id] = AgentStatus(agent_id)
            self.system_metrics["total_agents"] += 1
            logger.info(f"注册 Agent：{agent_id}")
        
        return self.agents[agent_id]
    
    def unregister_agent(self, agent_id: str) -> None:
        if agent_id in self.agents:
            del self.agents[agent_id]
            self.system_metrics["total_agents"] -= 1
            logger.info(f"注销 Agent：{agent_id}")
    
    def get_agent_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        if agent_id in self.agents:
            return self.agents[agent_id].get_status_report()
        return None
    
    def get_all_agents_status(self) -> Dict[str, Any]:
        agents_status = {}
        active_agents = 0
        active_sessions = 0
        
        for agent_id, agent in self.agents.items():
            agents_status[agent_id] = agent.get_status_report()
            if agent.status == "active":
                active_agents += 1
                active_sessions += 1 if agent.current_session else 0
        
        self.system_metrics["active_agents"] = active_agents
        self.system_metrics["active_sessions"] = active_sessions
        
        return {
            "system_status": self.system_status,
            "system_uptime": (datetime.now() - self.system_start_time).total_seconds(),
            "system_metrics": self.system_metrics.copy(),
            "agents": agents_status,
            "total_registered_agents": len(self.agents)
        }
    
    def record_system_query(self) -> None:
        self.system_metrics["total_queries"] += 1
    
    def update_health_check(self) -> None:
        self.system_metrics["last_health_check"] = datetime.now().isoformat()
    
    def set_system_status(self, status: str) -> None:
        valid_statuses = ["running", "maintenance", "degraded", "stopped"]
        if status in valid_statuses:
            self.system_status = status
            logger.info(f"系统状态更新为：{status}")
    
    def get_system_health(self) -> Dict[str, Any]:
        now = datetime.now()
        last_check = self.system_metrics.get("last_health_check")
        
        health_status = "healthy"
        if last_check:
            last_check_time = datetime.fromisoformat(last_check)
            if (now - last_check_time).total_seconds() > 300:
                health_status = "degraded"
        
        return {
            "status": health_status,
            "timestamp": now.isoformat(),
            "system_uptime": (now - self.system_start_time).total_seconds(),
            "agents_health": {
                agent_id: "healthy" if agent.status != "error" else "unhealthy"
                for agent_id, agent in self.agents.items()
            }
        }
    
    def cleanup_old_activities(self, max_age_hours: int = 24) -> None:
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        for agent in self.agents.values():
            agent.recent_activities = [
                activity for activity in agent.recent_activities
                if datetime.fromisoformat(activity["timestamp"]) >= cutoff_time
            ]