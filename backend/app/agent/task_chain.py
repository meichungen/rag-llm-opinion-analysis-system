import asyncio
from typing import Any, Dict, List, Optional
from datetime import datetime
import logging


logger = logging.getLogger(__name__)


class TaskChain:
    def __init__(self, agent: Any, session_id: str):
        self.agent = agent
        self.session_id = session_id
        self.tasks: List[Dict[str, Any]] = []
        self.current_step = 0
        self.status = "idle"
        self.results: List[Dict[str, Any]] = []
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        
    async def add_task(self, query: str, priority: int = 1) -> str:
        task_id = f"task-{len(self.tasks)+1}"
        task = {
            "id": task_id,
            "query": query,
            "priority": priority,
            "status": "pending",
            "created_at": datetime.now(),
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": None
        }
        self.tasks.append(task)
        self.tasks.sort(key=lambda x: x["priority"], reverse=True)
        self.updated_at = datetime.now()
        
        logger.info(f"任务链添加任务：{task_id}，优先级：{priority}")
        return task_id
    
    async def execute_next(self) -> Optional[Dict[str, Any]]:
        if not self.tasks or self.current_step >= len(self.tasks):
            return None
            
        task = self.tasks[self.current_step]
        task["status"] = "executing"
        task["started_at"] = datetime.now()
        self.status = "executing"
        self.updated_at = datetime.now()
        
        logger.info(f"任务链执行任务：{task['id']}，查询：{task['query']}")
        
        try:
            result = await self.agent.run_detail(task["query"], self.session_id)
            task["status"] = "completed"
            task["result"] = result
            task["completed_at"] = datetime.now()
            self.results.append(result)
            self.current_step += 1
            
            if self.current_step >= len(self.tasks):
                self.status = "completed"
            
            self.updated_at = datetime.now()
            logger.info(f"任务链任务完成：{task['id']}")
            return result
        except Exception as exc:
            task["status"] = "failed"
            task["error"] = str(exc)
            task["completed_at"] = datetime.now()
            self.current_step += 1
            
            if self.current_step >= len(self.tasks):
                self.status = "completed_with_errors"
            
            self.updated_at = datetime.now()
            logger.error(f"任务链任务失败：{task['id']}，错误：{exc}")
            return None
    
    async def execute_all(self) -> List[Dict[str, Any]]:
        results = []
        self.status = "executing"
        self.updated_at = datetime.now()
        
        logger.info(f"任务链开始执行所有任务，共 {len(self.tasks)} 个任务")
        
        while True:
            result = await self.execute_next()
            if result is None:
                break
            results.append(result)
            await asyncio.sleep(0.1)
        
        if self.status == "executing":
            self.status = "completed"
        
        self.updated_at = datetime.now()
        logger.info(f"任务链执行完成，成功 {len(results)} 个任务")
        return results
    
    def get_summary(self) -> Dict[str, Any]:
        completed = sum(1 for t in self.tasks if t["status"] == "completed")
        failed = sum(1 for t in self.tasks if t["status"] == "failed")
        pending = sum(1 for t in self.tasks if t["status"] == "pending")
        executing = sum(1 for t in self.tasks if t["status"] == "executing")
        
        progress = 0
        if self.tasks:
            progress = (completed + failed) / len(self.tasks) * 100
        
        return {
            "chain_id": id(self),
            "session_id": self.session_id,
            "total_tasks": len(self.tasks),
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "executing": executing,
            "current_step": self.current_step,
            "status": self.status,
            "progress": round(progress, 1),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "duration": (self.updated_at - self.created_at).total_seconds()
        }
    
    def get_task_details(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": task["id"],
                "query": task["query"],
                "priority": task["priority"],
                "status": task["status"],
                "created_at": task["created_at"].isoformat() if task["created_at"] else None,
                "started_at": task["started_at"].isoformat() if task["started_at"] else None,
                "completed_at": task["completed_at"].isoformat() if task["completed_at"] else None,
                "error": task["error"]
            }
            for task in self.tasks
        ]
    
    def get_progress_report(self) -> Dict[str, Any]:
        summary = self.get_summary()
        tasks = self.get_task_details()
        
        return {
            "summary": summary,
            "tasks": tasks,
            "current_task": tasks[self.current_step] if self.current_step < len(tasks) else None,
            "next_task": tasks[self.current_step + 1] if self.current_step + 1 < len(tasks) else None
        }
    
    async def pause(self) -> None:
        if self.status == "executing":
            self.status = "paused"
            self.updated_at = datetime.now()
            logger.info(f"任务链已暂停")
    
    async def resume(self) -> None:
        if self.status == "paused":
            self.status = "ready"
            self.updated_at = datetime.now()
            logger.info(f"任务链已恢复")
    
    async def cancel(self) -> None:
        self.status = "cancelled"
        self.updated_at = datetime.now()
        
        for task in self.tasks:
            if task["status"] in ["pending", "executing"]:
                task["status"] = "cancelled"
                task["completed_at"] = datetime.now()
        
        logger.info(f"任务链已取消")