"""
Status tracking and progress reporting utilities for agent runs.

This module provides centralized status management with Redis backend
for real-time progress updates and monitoring.
"""

import json
import asyncio
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum

from services import redis
from utils.logger import logger
from utils.error_handler import AgentRunStatus, ProgressUpdate


@dataclass
class StatusUpdate:
    """Complete status update for an agent run."""
    agent_run_id: str
    status: AgentRunStatus
    message: str
    progress_percentage: int = 0
    current_tool: Optional[str] = None
    tools_executed: List[str] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 100
    started_at: Optional[datetime] = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "agent_run_id": self.agent_run_id,
            "status": self.status.value,
            "message": self.message,
            "progress_percentage": self.progress_percentage,
            "current_tool": self.current_tool,
            "tools_executed": self.tools_executed,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "updated_at": self.updated_at.isoformat(),
            "details": self.details,
            "error": self.error
        }


class StatusTracker:
    """Tracks and reports agent run status with Redis backend."""
    
    def __init__(self, agent_run_id: str, thread_id: str, project_id: str):
        self.agent_run_id = agent_run_id
        self.thread_id = thread_id
        self.project_id = project_id
        self.status_key = f"agent_run:{agent_run_id}:status"
        self.progress_channel = f"agent_run:{agent_run_id}:progress"
        self.heartbeat_key = f"agent_run:{agent_run_id}:heartbeat"
        self.current_status = AgentRunStatus.QUEUED
        self.started_at = datetime.now(timezone.utc)
        self.iteration = 0
        self.tools_executed: List[str] = []
        self._heartbeat_task: Optional[asyncio.Task] = None
        
    async def initialize(self):
        """Initialize status tracking."""
        await self.update_status(
            AgentRunStatus.INITIALIZING,
            "Starting agent initialization"
        )
        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
    async def cleanup(self):
        """Clean up resources."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
    
    async def _heartbeat_loop(self):
        """Send periodic heartbeat to indicate the agent is alive."""
        while True:
            try:
                await redis.set(
                    self.heartbeat_key,
                    json.dumps({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "status": self.current_status.value,
                        "iteration": self.iteration
                    }),
                    ex=30  # Expire after 30 seconds
                )
                await asyncio.sleep(10)  # Heartbeat every 10 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Heartbeat failed for {self.agent_run_id}: {e}")
                await asyncio.sleep(10)
    
    async def update_status(
        self,
        status: AgentRunStatus,
        message: str,
        progress_percentage: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ):
        """Update the agent run status."""
        self.current_status = status
        
        # Calculate progress if not provided
        if progress_percentage is None:
            progress_percentage = self._calculate_progress(status)
        
        update = StatusUpdate(
            agent_run_id=self.agent_run_id,
            status=status,
            message=message,
            progress_percentage=progress_percentage,
            tools_executed=self.tools_executed.copy(),
            iteration=self.iteration,
            started_at=self.started_at,
            details=details or {},
            error=error
        )
        
        # Store in Redis
        await redis.set(
            self.status_key,
            json.dumps(update.to_dict()),
            ex=3600  # Expire after 1 hour
        )
        
        # Publish progress update
        await redis.publish(
            self.progress_channel,
            json.dumps({
                "type": "progress",
                "data": update.to_dict()
            })
        )
        
        logger.info(f"[STATUS] {self.agent_run_id}: {status.value} - {message}")
    
    async def start_tool_execution(self, tool_name: str):
        """Mark the start of tool execution."""
        await self.update_status(
            AgentRunStatus.EXECUTING_TOOL,
            f"Executing tool: {tool_name}",
            details={"current_tool": tool_name}
        )
    
    async def complete_tool_execution(self, tool_name: str, success: bool):
        """Mark the completion of tool execution."""
        self.tools_executed.append(tool_name)
        status_msg = f"Tool '{tool_name}' {'completed' if success else 'failed'}"
        await self.update_status(
            AgentRunStatus.EXECUTING,
            status_msg,
            details={
                "last_tool": tool_name,
                "tool_success": success,
                "total_tools_executed": len(self.tools_executed)
            }
        )
    
    async def increment_iteration(self):
        """Increment the iteration counter."""
        self.iteration += 1
        await self.update_status(
            AgentRunStatus.EXECUTING,
            f"Starting iteration {self.iteration}",
            details={"iteration": self.iteration}
        )
    
    def _calculate_progress(self, status: AgentRunStatus) -> int:
        """Calculate progress percentage based on status."""
        progress_map = {
            AgentRunStatus.QUEUED: 0,
            AgentRunStatus.INITIALIZING: 5,
            AgentRunStatus.LOADING_AGENT: 10,
            AgentRunStatus.LOADING_TOOLS: 15,
            AgentRunStatus.LOADING_MCP: 20,
            AgentRunStatus.BUILDING_PROMPT: 25,
            AgentRunStatus.READY: 30,
            AgentRunStatus.EXECUTING: 40,
            AgentRunStatus.CALLING_LLM: 50,
            AgentRunStatus.PROCESSING_RESPONSE: 60,
            AgentRunStatus.EXECUTING_TOOL: 70,
            AgentRunStatus.WAITING_SANDBOX: 65,
            AgentRunStatus.STREAMING: 80,
            AgentRunStatus.COMPLETING: 90,
            AgentRunStatus.COMPLETED: 100,
            AgentRunStatus.FAILED: 100,
            AgentRunStatus.TIMEOUT: 100,
            AgentRunStatus.CANCELLED: 100,
            AgentRunStatus.STOPPED: 100
        }
        
        base_progress = progress_map.get(status, 50)
        
        # Adjust based on iteration if executing
        if status == AgentRunStatus.EXECUTING and self.iteration > 0:
            # Add progress based on iterations (up to 80%)
            iteration_progress = min(self.iteration * 5, 40)
            base_progress = min(40 + iteration_progress, 80)
        
        return base_progress


class StatusMonitor:
    """Monitor agent run status and detect stuck runs."""
    
    @staticmethod
    async def check_heartbeat(agent_run_id: str) -> bool:
        """Check if an agent run is still alive."""
        heartbeat_key = f"agent_run:{agent_run_id}:heartbeat"
        heartbeat_data = await redis.get(heartbeat_key)
        
        if not heartbeat_data:
            return False
        
        try:
            heartbeat = json.loads(heartbeat_data)
            last_heartbeat = datetime.fromisoformat(heartbeat["timestamp"])
            age_seconds = (datetime.now(timezone.utc) - last_heartbeat).total_seconds()
            
            # Consider dead if no heartbeat for 60 seconds
            return age_seconds < 60
        except Exception as e:
            logger.error(f"Error checking heartbeat for {agent_run_id}: {e}")
            return False
    
    @staticmethod
    async def get_status(agent_run_id: str) -> Optional[StatusUpdate]:
        """Get current status of an agent run."""
        status_key = f"agent_run:{agent_run_id}:status"
        status_data = await redis.get(status_key)
        
        if not status_data:
            return None
        
        try:
            data = json.loads(status_data)
            return StatusUpdate(
                agent_run_id=data["agent_run_id"],
                status=AgentRunStatus(data["status"]),
                message=data["message"],
                progress_percentage=data.get("progress_percentage", 0),
                current_tool=data.get("current_tool"),
                tools_executed=data.get("tools_executed", []),
                iteration=data.get("iteration", 0),
                max_iterations=data.get("max_iterations", 100),
                started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
                updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(timezone.utc),
                details=data.get("details", {}),
                error=data.get("error")
            )
        except Exception as e:
            logger.error(f"Error parsing status for {agent_run_id}: {e}")
            return None
    
    @staticmethod
    async def find_stuck_runs(max_age_seconds: int = 300) -> List[str]:
        """Find agent runs that appear to be stuck."""
        stuck_runs = []
        
        # Get all agent run keys
        pattern = "agent_run:*:heartbeat"
        keys = await redis.keys(pattern)
        
        for key in keys:
            # Extract agent_run_id from key
            parts = key.split(":")
            if len(parts) >= 3:
                agent_run_id = parts[1]
                
                # Check if heartbeat is stale
                if not await StatusMonitor.check_heartbeat(agent_run_id):
                    # Check status to see if it's in a running state
                    status = await StatusMonitor.get_status(agent_run_id)
                    if status and status.status not in [
                        AgentRunStatus.COMPLETED,
                        AgentRunStatus.FAILED,
                        AgentRunStatus.CANCELLED,
                        AgentRunStatus.STOPPED,
                        AgentRunStatus.TIMEOUT
                    ]:
                        stuck_runs.append(agent_run_id)
        
        return stuck_runs
    
    @staticmethod
    async def recover_stuck_run(agent_run_id: str) -> bool:
        """Attempt to recover a stuck agent run."""
        logger.warning(f"Attempting to recover stuck agent run: {agent_run_id}")
        
        # Get current status
        status = await StatusMonitor.get_status(agent_run_id)
        if not status:
            logger.error(f"Cannot recover {agent_run_id}: status not found")
            return False
        
        # Mark as failed with recovery message
        tracker = StatusTracker(agent_run_id, "", "")
        await tracker.update_status(
            AgentRunStatus.FAILED,
            "Agent run was stuck and has been terminated",
            error="Agent became unresponsive and was automatically terminated"
        )
        
        # Publish stop signal
        control_channel = f"agent_run:{agent_run_id}:control"
        await redis.publish(control_channel, "STOP")
        
        # Clean up locks
        lock_key = f"agent_run_lock:{agent_run_id}"
        await redis.delete(lock_key)
        
        logger.info(f"Recovered stuck agent run: {agent_run_id}")
        return True


class ProgressReporter:
    """Helper class for reporting progress to frontend."""
    
    @staticmethod
    async def send_progress(
        agent_run_id: str,
        stage: str,
        percentage: int,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        """Send a progress update to the frontend."""
        progress = ProgressUpdate(
            stage=AgentRunStatus(stage) if isinstance(stage, str) else stage,
            percentage=percentage,
            message=message,
            details=details or {}
        )
        
        channel = f"agent_run:{agent_run_id}:progress"
        await redis.publish(
            channel,
            json.dumps({
                "type": "progress",
                "data": progress.to_dict()
            })
        )
    
    @staticmethod
    async def send_error(
        agent_run_id: str,
        error_message: str,
        error_type: str,
        can_retry: bool = False
    ):
        """Send an error notification to the frontend."""
        channel = f"agent_run:{agent_run_id}:progress"
        await redis.publish(
            channel,
            json.dumps({
                "type": "error",
                "data": {
                    "message": error_message,
                    "error_type": error_type,
                    "can_retry": can_retry,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            })
        )
    
    @staticmethod
    async def send_heartbeat(agent_run_id: str):
        """Send a heartbeat to indicate the agent is alive."""
        channel = f"agent_run:{agent_run_id}:progress"
        await redis.publish(
            channel,
            json.dumps({
                "type": "heartbeat",
                "data": {
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            })
        )