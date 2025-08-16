"""
Health check and monitoring utilities for the sandbox system.

This module provides health checks, connectivity tests, and resource monitoring
for Daytona sandboxes to ensure reliability and early detection of issues.
"""

import asyncio
import time
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum

from daytona_sdk import AsyncSandbox, SandboxState
from utils.logger import logger
from utils.error_handler import (
    ErrorHandler, ErrorType, ErrorSeverity,
    SandboxError, TransientError
)


class SandboxHealthStatus(Enum):
    """Health status for sandbox components."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class SandboxHealthReport:
    """Complete health report for a sandbox."""
    sandbox_id: str
    status: SandboxHealthStatus
    state: Optional[str] = None
    connectivity: bool = False
    services: Dict[str, bool] = field(default_factory=dict)
    resources: Dict[str, Any] = field(default_factory=dict)
    response_time_ms: Optional[float] = None
    last_check: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "sandbox_id": self.sandbox_id,
            "status": self.status.value,
            "state": self.state,
            "connectivity": self.connectivity,
            "services": self.services,
            "resources": self.resources,
            "response_time_ms": self.response_time_ms,
            "last_check": self.last_check.isoformat(),
            "errors": self.errors,
            "warnings": self.warnings
        }


class SandboxHealthChecker:
    """Performs health checks on sandboxes."""
    
    def __init__(self, daytona_client):
        """Initialize health checker with Daytona client."""
        self.daytona = daytona_client
        self._health_cache: Dict[str, SandboxHealthReport] = {}
        self._cache_ttl = 30  # Cache health reports for 30 seconds
    
    async def check_sandbox_health(
        self,
        sandbox_id: str,
        detailed: bool = False,
        use_cache: bool = True
    ) -> SandboxHealthReport:
        """
        Perform a comprehensive health check on a sandbox.
        
        Args:
            sandbox_id: ID of the sandbox to check
            detailed: Whether to perform detailed service checks
            use_cache: Whether to use cached results if available
            
        Returns:
            SandboxHealthReport with health status
        """
        # Check cache first
        if use_cache and sandbox_id in self._health_cache:
            cached_report = self._health_cache[sandbox_id]
            cache_age = (datetime.now(timezone.utc) - cached_report.last_check).total_seconds()
            if cache_age < self._cache_ttl:
                logger.debug(f"Using cached health report for sandbox {sandbox_id} (age: {cache_age:.1f}s)")
                return cached_report
        
        report = SandboxHealthReport(sandbox_id=sandbox_id)
        start_time = time.time()
        
        try:
            # 1. Check sandbox existence and state
            sandbox_state = await self._check_sandbox_state(sandbox_id)
            report.state = sandbox_state
            
            if sandbox_state == SandboxState.RUNNING:
                # 2. Check connectivity
                report.connectivity = await self._check_connectivity(sandbox_id)
                
                # 3. Check essential services (if detailed)
                if detailed:
                    report.services = await self._check_services(sandbox_id)
                
                # 4. Check resource usage (if detailed)
                if detailed:
                    report.resources = await self._check_resources(sandbox_id)
                
                # Determine overall status
                if not report.connectivity:
                    report.status = SandboxHealthStatus.UNHEALTHY
                    report.errors.append("Sandbox is not reachable")
                elif report.services and not all(report.services.values()):
                    report.status = SandboxHealthStatus.DEGRADED
                    failed_services = [s for s, healthy in report.services.items() if not healthy]
                    report.warnings.append(f"Services degraded: {', '.join(failed_services)}")
                else:
                    report.status = SandboxHealthStatus.HEALTHY
                    
            elif sandbox_state in [SandboxState.STOPPED, SandboxState.ARCHIVED]:
                report.status = SandboxHealthStatus.UNHEALTHY
                report.errors.append(f"Sandbox is {sandbox_state}")
            else:
                report.status = SandboxHealthStatus.UNKNOWN
                report.warnings.append(f"Unknown sandbox state: {sandbox_state}")
        
        except asyncio.TimeoutError:
            report.status = SandboxHealthStatus.UNHEALTHY
            report.errors.append("Health check timed out")
            logger.error(f"Health check timeout for sandbox {sandbox_id}")
        except Exception as e:
            report.status = SandboxHealthStatus.UNKNOWN
            report.errors.append(f"Health check error: {str(e)}")
            logger.error(f"Error checking health of sandbox {sandbox_id}: {e}")
        
        # Calculate response time
        report.response_time_ms = (time.time() - start_time) * 1000
        
        # Cache the report
        self._health_cache[sandbox_id] = report
        
        # Log health status
        logger.info(
            f"Sandbox {sandbox_id} health: {report.status.value} "
            f"(state: {report.state}, connectivity: {report.connectivity}, "
            f"response_time: {report.response_time_ms:.1f}ms)"
        )
        
        return report
    
    async def _check_sandbox_state(self, sandbox_id: str) -> Optional[str]:
        """Check the current state of a sandbox."""
        try:
            sandbox = await asyncio.wait_for(
                self.daytona.get(sandbox_id),
                timeout=5.0
            )
            return sandbox.state if sandbox else None
        except asyncio.TimeoutError:
            logger.warning(f"Timeout checking state of sandbox {sandbox_id}")
            raise
        except Exception as e:
            logger.error(f"Error checking state of sandbox {sandbox_id}: {e}")
            return None
    
    async def _check_connectivity(self, sandbox_id: str) -> bool:
        """Check if sandbox is reachable via network."""
        try:
            sandbox = await asyncio.wait_for(
                self.daytona.get(sandbox_id),
                timeout=5.0
            )
            
            # Try to execute a simple command
            result = await asyncio.wait_for(
                sandbox.process.execute("echo 'health_check'"),
                timeout=5.0
            )
            
            return result and "health_check" in str(result)
        except asyncio.TimeoutError:
            logger.warning(f"Connectivity check timeout for sandbox {sandbox_id}")
            return False
        except Exception as e:
            logger.warning(f"Connectivity check failed for sandbox {sandbox_id}: {e}")
            return False
    
    async def _check_services(self, sandbox_id: str) -> Dict[str, bool]:
        """Check status of essential services in the sandbox."""
        services = {}
        
        try:
            sandbox = await self.daytona.get(sandbox_id)
            
            # Check supervisord
            services["supervisord"] = await self._check_service(
                sandbox, "pgrep supervisord", "supervisord"
            )
            
            # Check Chrome/browser if needed
            services["chrome"] = await self._check_service(
                sandbox, "pgrep chrome || pgrep chromium", "chrome"
            )
            
            # Check VNC server if needed
            services["vnc"] = await self._check_service(
                sandbox, "pgrep Xvnc || pgrep x11vnc", "vnc"
            )
            
        except Exception as e:
            logger.error(f"Error checking services for sandbox {sandbox_id}: {e}")
        
        return services
    
    async def _check_service(
        self,
        sandbox: AsyncSandbox,
        check_command: str,
        service_name: str
    ) -> bool:
        """Check if a specific service is running."""
        try:
            result = await asyncio.wait_for(
                sandbox.process.execute(check_command),
                timeout=3.0
            )
            is_running = result and result.exit_code == 0
            logger.debug(f"Service {service_name}: {'running' if is_running else 'not running'}")
            return is_running
        except asyncio.TimeoutError:
            logger.warning(f"Timeout checking service {service_name}")
            return False
        except Exception as e:
            logger.warning(f"Error checking service {service_name}: {e}")
            return False
    
    async def _check_resources(self, sandbox_id: str) -> Dict[str, Any]:
        """Check resource usage of the sandbox."""
        resources = {}
        
        try:
            sandbox = await self.daytona.get(sandbox_id)
            
            # Check disk usage
            disk_result = await sandbox.process.execute("df -h / | tail -1 | awk '{print $5}'")
            if disk_result and disk_result.exit_code == 0:
                resources["disk_usage"] = disk_result.stdout.strip()
            
            # Check memory usage
            mem_result = await sandbox.process.execute(
                "free -m | grep Mem | awk '{printf \"%.1f%%\", $3/$2 * 100}'"
            )
            if mem_result and mem_result.exit_code == 0:
                resources["memory_usage"] = mem_result.stdout.strip()
            
            # Check CPU load
            cpu_result = await sandbox.process.execute("uptime | awk -F'load average:' '{print $2}'")
            if cpu_result and cpu_result.exit_code == 0:
                resources["cpu_load"] = cpu_result.stdout.strip()
            
        except Exception as e:
            logger.error(f"Error checking resources for sandbox {sandbox_id}: {e}")
        
        return resources
    
    async def batch_health_check(
        self,
        sandbox_ids: List[str],
        detailed: bool = False
    ) -> Dict[str, SandboxHealthReport]:
        """
        Perform health checks on multiple sandboxes in parallel.
        
        Args:
            sandbox_ids: List of sandbox IDs to check
            detailed: Whether to perform detailed checks
            
        Returns:
            Dictionary mapping sandbox IDs to health reports
        """
        tasks = [
            self.check_sandbox_health(sid, detailed=detailed)
            for sid in sandbox_ids
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        reports = {}
        for sandbox_id, result in zip(sandbox_ids, results):
            if isinstance(result, Exception):
                logger.error(f"Health check failed for {sandbox_id}: {result}")
                reports[sandbox_id] = SandboxHealthReport(
                    sandbox_id=sandbox_id,
                    status=SandboxHealthStatus.UNKNOWN,
                    errors=[str(result)]
                )
            else:
                reports[sandbox_id] = result
        
        return reports


class SandboxMonitor:
    """Monitor sandbox health and automatically recover unhealthy instances."""
    
    def __init__(self, health_checker: SandboxHealthChecker, daytona_client):
        """Initialize monitor with health checker and Daytona client."""
        self.health_checker = health_checker
        self.daytona = daytona_client
        self._monitoring_tasks: Dict[str, asyncio.Task] = {}
        self._recovery_attempts: Dict[str, int] = {}
        self._max_recovery_attempts = 3
    
    async def start_monitoring(
        self,
        sandbox_id: str,
        interval: int = 60,
        auto_recover: bool = True
    ):
        """
        Start monitoring a sandbox with periodic health checks.
        
        Args:
            sandbox_id: ID of the sandbox to monitor
            interval: Health check interval in seconds
            auto_recover: Whether to automatically attempt recovery
        """
        if sandbox_id in self._monitoring_tasks:
            logger.warning(f"Monitoring already active for sandbox {sandbox_id}")
            return
        
        async def monitor_loop():
            """Monitoring loop for a sandbox."""
            logger.info(f"Starting health monitoring for sandbox {sandbox_id}")
            
            while True:
                try:
                    # Perform health check
                    report = await self.health_checker.check_sandbox_health(
                        sandbox_id,
                        detailed=True,
                        use_cache=False
                    )
                    
                    # Handle unhealthy sandbox
                    if report.status == SandboxHealthStatus.UNHEALTHY and auto_recover:
                        await self._handle_unhealthy_sandbox(sandbox_id, report)
                    elif report.status == SandboxHealthStatus.DEGRADED:
                        logger.warning(
                            f"Sandbox {sandbox_id} is degraded: {report.warnings}"
                        )
                    
                    # Reset recovery attempts on healthy status
                    if report.status == SandboxHealthStatus.HEALTHY:
                        self._recovery_attempts[sandbox_id] = 0
                    
                    await asyncio.sleep(interval)
                    
                except asyncio.CancelledError:
                    logger.info(f"Stopping health monitoring for sandbox {sandbox_id}")
                    break
                except Exception as e:
                    logger.error(f"Error in monitoring loop for {sandbox_id}: {e}")
                    await asyncio.sleep(interval)
        
        # Start monitoring task
        task = asyncio.create_task(monitor_loop())
        self._monitoring_tasks[sandbox_id] = task
    
    async def stop_monitoring(self, sandbox_id: str):
        """Stop monitoring a sandbox."""
        if sandbox_id in self._monitoring_tasks:
            task = self._monitoring_tasks[sandbox_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del self._monitoring_tasks[sandbox_id]
            logger.info(f"Stopped monitoring sandbox {sandbox_id}")
    
    async def _handle_unhealthy_sandbox(
        self,
        sandbox_id: str,
        report: SandboxHealthReport
    ):
        """Handle an unhealthy sandbox with recovery attempts."""
        attempts = self._recovery_attempts.get(sandbox_id, 0)
        
        if attempts >= self._max_recovery_attempts:
            logger.error(
                f"Max recovery attempts ({self._max_recovery_attempts}) reached "
                f"for sandbox {sandbox_id}. Manual intervention required."
            )
            # Could send alert/notification here
            return
        
        logger.warning(
            f"Attempting recovery for unhealthy sandbox {sandbox_id} "
            f"(attempt {attempts + 1}/{self._max_recovery_attempts})"
        )
        
        try:
            # Try to recover based on the issue
            if report.state in [SandboxState.STOPPED, SandboxState.ARCHIVED]:
                # Try to start the sandbox
                await self._restart_sandbox(sandbox_id)
            elif not report.connectivity:
                # Try to restart services
                await self._restart_services(sandbox_id)
            
            self._recovery_attempts[sandbox_id] = attempts + 1
            
        except Exception as e:
            logger.error(f"Recovery failed for sandbox {sandbox_id}: {e}")
            self._recovery_attempts[sandbox_id] = attempts + 1
    
    async def _restart_sandbox(self, sandbox_id: str):
        """Restart a stopped sandbox."""
        logger.info(f"Restarting sandbox {sandbox_id}")
        
        try:
            from sandbox.sandbox import get_or_start_sandbox
            await get_or_start_sandbox(sandbox_id)
            logger.info(f"Successfully restarted sandbox {sandbox_id}")
        except Exception as e:
            logger.error(f"Failed to restart sandbox {sandbox_id}: {e}")
            raise
    
    async def _restart_services(self, sandbox_id: str):
        """Restart essential services in a sandbox."""
        logger.info(f"Restarting services in sandbox {sandbox_id}")
        
        try:
            sandbox = await self.daytona.get(sandbox_id)
            
            # Restart supervisord
            from sandbox.sandbox import start_supervisord_session
            await start_supervisord_session(sandbox)
            
            logger.info(f"Successfully restarted services in sandbox {sandbox_id}")
        except Exception as e:
            logger.error(f"Failed to restart services in sandbox {sandbox_id}: {e}")
            raise


# Global instances for easy access
_health_checker: Optional[SandboxHealthChecker] = None
_monitor: Optional[SandboxMonitor] = None


def initialize_health_monitoring(daytona_client):
    """Initialize global health monitoring instances."""
    global _health_checker, _monitor
    
    _health_checker = SandboxHealthChecker(daytona_client)
    _monitor = SandboxMonitor(_health_checker, daytona_client)
    
    logger.info("Sandbox health monitoring initialized")


def get_health_checker() -> Optional[SandboxHealthChecker]:
    """Get the global health checker instance."""
    return _health_checker


def get_monitor() -> Optional[SandboxMonitor]:
    """Get the global monitor instance."""
    return _monitor