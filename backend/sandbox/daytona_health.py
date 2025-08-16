"""
Daytona Service Health Check and Monitoring

This module provides health checks, connectivity tests, and monitoring
for the Daytona sandbox service to prevent tool hanging issues.
"""

import asyncio
import time
import aiohttp
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum
import os

from utils.logger import logger
from utils.error_handler import (
    ErrorHandler, ErrorType, ErrorSeverity,
    SandboxError, TransientError, TimeoutError
)


class DaytonaHealthStatus(Enum):
    """Health status for Daytona service."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNAVAILABLE = "unavailable"


@dataclass
class DaytonaHealthReport:
    """Health report for Daytona service."""
    status: DaytonaHealthStatus
    response_time_ms: Optional[float] = None
    api_version: Optional[str] = None
    error_message: Optional[str] = None
    last_check: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    consecutive_failures: int = 0
    
    def is_healthy(self) -> bool:
        """Check if service is healthy enough for operations."""
        return self.status in [DaytonaHealthStatus.HEALTHY, DaytonaHealthStatus.DEGRADED]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "status": self.status.value,
            "response_time_ms": self.response_time_ms,
            "api_version": self.api_version,
            "error_message": self.error_message,
            "last_check": self.last_check.isoformat(),
            "consecutive_failures": self.consecutive_failures,
            "is_healthy": self.is_healthy()
        }


class DaytonaHealthChecker:
    """Health checker for Daytona sandbox service."""
    
    def __init__(self):
        """Initialize health checker with configuration."""
        self.server_url = os.getenv("DAYTONA_SERVER_URL", "https://app.daytona.io/api")
        self.api_key = os.getenv("DAYTONA_API_KEY", "")
        self.target = os.getenv("DAYTONA_TARGET", "us")
        
        # Health check configuration
        self.health_check_timeout = 2.0  # 2 seconds for health checks (reduced to prevent blocking)
        self.connection_timeout = 1.0     # 1 second for initial connection
        self.max_consecutive_failures = 3  # Mark unhealthy after 3 failures
        
        # Caching
        self._health_cache: Optional[DaytonaHealthReport] = None
        self._cache_ttl = 30  # Cache for 30 seconds
        self._last_check_time: Optional[float] = None
        
        # Metrics
        self.total_checks = 0
        self.failed_checks = 0
        self.average_response_time = 0.0
        self.consecutive_failures = 0
        
        # Don't log server URL on init to prevent blocking
        if self.api_key:
            logger.debug("Daytona health checker initialized")
        else:
            logger.warning("Daytona health checker initialized but no API key configured")
    
    async def check_health(
        self,
        force_refresh: bool = False,
        detailed: bool = False
    ) -> DaytonaHealthReport:
        """
        Check Daytona service health.
        
        Args:
            force_refresh: Force a fresh health check
            detailed: Include detailed diagnostics
            
        Returns:
            DaytonaHealthReport with current health status
        """
        # Use cached result if available and not expired
        if not force_refresh and self._health_cache and self._last_check_time:
            cache_age = time.time() - self._last_check_time
            if cache_age < self._cache_ttl:
                logger.debug(f"Using cached Daytona health report (age: {cache_age:.1f}s)")
                return self._health_cache
        
        self.total_checks += 1
        start_time = time.time()
        
        try:
            # Perform health check
            report = await self._perform_health_check(detailed)
            
            # Update metrics
            response_time = (time.time() - start_time) * 1000
            report.response_time_ms = response_time
            self._update_metrics(response_time, success=True)
            
            # Cache result
            self._health_cache = report
            self._last_check_time = time.time()
            
            logger.info(
                f"Daytona health check: {report.status.value} "
                f"(response time: {response_time:.1f}ms)"
            )
            
            return report
            
        except Exception as e:
            self.failed_checks += 1
            self.consecutive_failures += 1
            
            error_msg = f"Daytona health check failed: {str(e)}"
            logger.error(error_msg)
            
            report = DaytonaHealthReport(
                status=DaytonaHealthStatus.UNAVAILABLE,
                error_message=error_msg,
                consecutive_failures=self.consecutive_failures
            )
            
            # Cache negative result for shorter time
            self._health_cache = report
            self._last_check_time = time.time()
            
            return report
    
    async def _perform_health_check(self, detailed: bool) -> DaytonaHealthReport:
        """Perform actual health check against Daytona API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Target": self.target,
            "Content-Type": "application/json"
        }
        
        # Try multiple endpoints to determine health
        health_endpoints = [
            "/health",
            "/api/health",
            "/v1/health",
            "/"  # Root endpoint as fallback
        ]
        
        async with aiohttp.ClientSession() as session:
            for endpoint in health_endpoints:
                try:
                    url = f"{self.server_url.rstrip('/')}{endpoint}"
                    
                    async with session.get(
                        url,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(
                            total=self.health_check_timeout,
                            connect=self.connection_timeout
                        )
                    ) as response:
                        if response.status in [200, 204]:
                            # Success - service is healthy
                            self.consecutive_failures = 0
                            
                            # Try to get version info if available
                            api_version = None
                            try:
                                data = await response.json()
                                api_version = data.get("version") or data.get("api_version")
                            except:
                                pass
                            
                            return DaytonaHealthReport(
                                status=DaytonaHealthStatus.HEALTHY,
                                api_version=api_version,
                                consecutive_failures=0
                            )
                        
                        elif response.status == 401:
                            # Authentication issue
                            return DaytonaHealthReport(
                                status=DaytonaHealthStatus.UNHEALTHY,
                                error_message="Authentication failed - check API key",
                                consecutive_failures=self.consecutive_failures
                            )
                        
                        elif response.status == 403:
                            # Authorization issue
                            return DaytonaHealthReport(
                                status=DaytonaHealthStatus.UNHEALTHY,
                                error_message="Authorization failed - check permissions",
                                consecutive_failures=self.consecutive_failures
                            )
                        
                        elif response.status == 429:
                            # Rate limited
                            return DaytonaHealthReport(
                                status=DaytonaHealthStatus.DEGRADED,
                                error_message="Rate limited - too many requests",
                                consecutive_failures=self.consecutive_failures
                            )
                        
                        elif response.status >= 500:
                            # Server error
                            return DaytonaHealthReport(
                                status=DaytonaHealthStatus.UNHEALTHY,
                                error_message=f"Server error: {response.status}",
                                consecutive_failures=self.consecutive_failures
                            )
                        
                except asyncio.TimeoutError:
                    continue  # Try next endpoint
                except aiohttp.ClientError as e:
                    logger.debug(f"Failed to check {endpoint}: {e}")
                    continue
        
        # All endpoints failed
        self.consecutive_failures += 1
        
        if self.consecutive_failures >= self.max_consecutive_failures:
            return DaytonaHealthReport(
                status=DaytonaHealthStatus.UNAVAILABLE,
                error_message="Service unavailable - all health checks failed",
                consecutive_failures=self.consecutive_failures
            )
        else:
            return DaytonaHealthReport(
                status=DaytonaHealthStatus.DEGRADED,
                error_message="Some health checks failed",
                consecutive_failures=self.consecutive_failures
            )
    
    def _update_metrics(self, response_time: float, success: bool):
        """Update internal metrics."""
        if success:
            self.consecutive_failures = 0
            
            # Update average response time using exponential moving average
            alpha = 0.1
            if self.average_response_time == 0:
                self.average_response_time = response_time
            else:
                self.average_response_time = (
                    alpha * response_time + 
                    (1 - alpha) * self.average_response_time
                )
        else:
            self.consecutive_failures += 1
    
    async def pre_flight_check(self) -> Tuple[bool, Optional[str]]:
        """
        Perform pre-flight check before tool execution.
        
        Returns:
            Tuple of (is_ready, error_message)
        """
        report = await self.check_health()
        
        if report.status == DaytonaHealthStatus.HEALTHY:
            return True, None
        
        elif report.status == DaytonaHealthStatus.DEGRADED:
            # Allow degraded service but log warning
            logger.warning(f"Daytona service degraded: {report.error_message}")
            return True, report.error_message
        
        else:
            # Don't allow unhealthy or unavailable service
            error_msg = (
                f"Daytona service {report.status.value}: {report.error_message}. "
                f"Tool execution may fail."
            )
            return False, error_msg
    
    async def wait_for_healthy(
        self,
        timeout: float = 30.0,
        check_interval: float = 2.0
    ) -> bool:
        """
        Wait for Daytona service to become healthy.
        
        Args:
            timeout: Maximum time to wait
            check_interval: Interval between health checks
            
        Returns:
            True if service became healthy, False if timeout
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            report = await self.check_health(force_refresh=True)
            
            if report.is_healthy():
                logger.info("Daytona service is healthy")
                return True
            
            logger.debug(
                f"Waiting for Daytona to become healthy "
                f"(current: {report.status.value})"
            )
            
            await asyncio.sleep(check_interval)
        
        logger.error(f"Daytona service did not become healthy within {timeout}s")
        return False
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics."""
        success_rate = (
            ((self.total_checks - self.failed_checks) / self.total_checks * 100)
            if self.total_checks > 0 else 100
        )
        
        return {
            "total_checks": self.total_checks,
            "failed_checks": self.failed_checks,
            "success_rate": success_rate,
            "average_response_time_ms": self.average_response_time,
            "consecutive_failures": self.consecutive_failures,
            "last_health_status": (
                self._health_cache.status.value 
                if self._health_cache else "unknown"
            )
        }


# Global health checker instance
_health_checker: Optional[DaytonaHealthChecker] = None


def get_daytona_health_checker() -> DaytonaHealthChecker:
    """Get the global Daytona health checker instance."""
    global _health_checker
    if _health_checker is None:
        _health_checker = DaytonaHealthChecker()
    return _health_checker


async def check_daytona_health(
    force_refresh: bool = False
) -> DaytonaHealthReport:
    """Check Daytona service health."""
    checker = get_daytona_health_checker()
    return await checker.check_health(force_refresh)


async def daytona_pre_flight_check() -> Tuple[bool, Optional[str]]:
    """Perform pre-flight check for Daytona service."""
    checker = get_daytona_health_checker()
    return await checker.pre_flight_check()