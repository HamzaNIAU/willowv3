"""
Daytona Service Circuit Breaker

This module provides a circuit breaker specifically for Daytona API calls
to prevent cascading failures and improve resilience.
"""

import asyncio
import time
from enum import Enum
from typing import TypeVar, Callable, Optional, Any
from dataclasses import dataclass
import functools

from utils.logger import logger
from utils.error_handler import TransientError, SandboxError, TimeoutError
from sandbox.daytona_health import get_daytona_health_checker, DaytonaHealthStatus

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Circuit tripped, failing fast
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class DaytonaCircuitConfig:
    """Configuration for Daytona circuit breaker."""
    failure_threshold: int = 3          # Failures before opening circuit
    recovery_timeout: float = 30.0      # Time before trying HALF_OPEN
    success_threshold: int = 2          # Successes needed to close circuit
    timeout: float = 15.0               # Default timeout for operations
    
    # Operation-specific timeouts
    create_sandbox_timeout: float = 30.0
    get_sandbox_timeout: float = 10.0
    execute_command_timeout: float = 20.0


class DaytonaCircuitBreaker:
    """Circuit breaker for Daytona service operations."""
    
    def __init__(self, config: Optional[DaytonaCircuitConfig] = None):
        """Initialize circuit breaker."""
        self.config = config or DaytonaCircuitConfig()
        self.state = CircuitState.CLOSED
        self.state_change_time = time.time()
        
        # Metrics
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.total_requests = 0
        self.failed_requests = 0
        
        # Health checker integration
        self.health_checker = get_daytona_health_checker()
        
        logger.info("Daytona circuit breaker initialized")
    
    async def execute(
        self,
        operation: Callable[[], T],
        operation_name: str = "daytona_operation",
        timeout: Optional[float] = None
    ) -> T:
        """
        Execute a Daytona operation through the circuit breaker.
        
        Args:
            operation: The async operation to execute
            operation_name: Name for logging
            timeout: Operation timeout (uses default if not specified)
            
        Returns:
            Result of the operation
            
        Raises:
            SandboxError: If circuit is open
            TimeoutError: If operation times out
            Exception: If operation fails
        """
        # Check circuit state
        if not await self._should_allow_request():
            error_msg = f"Daytona circuit breaker OPEN - {operation_name} rejected"
            logger.warning(error_msg)
            
            # Check if service has recovered
            health_report = await self.health_checker.check_health()
            if health_report.is_healthy():
                logger.info("Daytona service appears healthy, transitioning to HALF_OPEN")
                self.state = CircuitState.HALF_OPEN
                self.state_change_time = time.time()
            else:
                raise SandboxError(f"{error_msg}. Service status: {health_report.status.value}")
        
        # Execute operation with timeout
        timeout = timeout or self.config.timeout
        start_time = time.time()
        
        try:
            logger.debug(f"Executing {operation_name} (timeout: {timeout}s)")
            
            result = await asyncio.wait_for(
                operation(),
                timeout=timeout
            )
            
            # Record success
            latency = time.time() - start_time
            await self._record_success(latency)
            
            logger.info(f"{operation_name} succeeded in {latency:.2f}s")
            return result
            
        except asyncio.TimeoutError:
            await self._record_failure()
            error_msg = f"{operation_name} timed out after {timeout}s"
            logger.error(error_msg)
            raise TimeoutError(error_msg)
            
        except Exception as e:
            await self._record_failure()
            logger.error(f"{operation_name} failed: {e}")
            raise
    
    async def _should_allow_request(self) -> bool:
        """Check if request should be allowed based on circuit state."""
        current_time = time.time()
        
        if self.state == CircuitState.CLOSED:
            return True
        
        elif self.state == CircuitState.OPEN:
            # Check if enough time has passed to try recovery
            if current_time - self.state_change_time >= self.config.recovery_timeout:
                logger.info("Circuit breaker: Transitioning to HALF_OPEN")
                self.state = CircuitState.HALF_OPEN
                self.state_change_time = current_time
                return True
            return False
        
        elif self.state == CircuitState.HALF_OPEN:
            # Allow limited test requests
            return True
        
        return False
    
    async def _record_success(self, latency: float):
        """Record successful operation."""
        self.total_requests += 1
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        
        # Check if we should close the circuit
        if self.state == CircuitState.HALF_OPEN:
            if self.consecutive_successes >= self.config.success_threshold:
                logger.info(
                    f"Circuit breaker: Closing after {self.consecutive_successes} successes"
                )
                self.state = CircuitState.CLOSED
                self.state_change_time = time.time()
    
    async def _record_failure(self):
        """Record failed operation and potentially open circuit."""
        self.total_requests += 1
        self.failed_requests += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        
        # Check if we should open the circuit
        if self.consecutive_failures >= self.config.failure_threshold:
            if self.state != CircuitState.OPEN:
                logger.warning(
                    f"Circuit breaker: Opening after {self.consecutive_failures} failures"
                )
                self.state = CircuitState.OPEN
                self.state_change_time = time.time()
    
    def get_state(self) -> str:
        """Get current circuit state."""
        return self.state.value
    
    def get_metrics(self) -> dict:
        """Get circuit breaker metrics."""
        success_rate = (
            ((self.total_requests - self.failed_requests) / self.total_requests * 100)
            if self.total_requests > 0 else 100
        )
        
        return {
            "state": self.state.value,
            "state_duration": time.time() - self.state_change_time,
            "total_requests": self.total_requests,
            "failed_requests": self.failed_requests,
            "success_rate": success_rate,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
        }
    
    async def reset(self):
        """Manually reset circuit breaker."""
        logger.info("Circuit breaker: Manual reset")
        self.state = CircuitState.CLOSED
        self.state_change_time = time.time()
        self.consecutive_failures = 0
        self.consecutive_successes = 0


# Global circuit breaker instance
_circuit_breaker: Optional[DaytonaCircuitBreaker] = None


def get_daytona_circuit_breaker() -> DaytonaCircuitBreaker:
    """Get the global Daytona circuit breaker instance."""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = DaytonaCircuitBreaker()
    return _circuit_breaker


async def execute_with_circuit_breaker(
    operation: Callable[[], T],
    operation_name: str = "daytona_operation",
    timeout: Optional[float] = None
) -> T:
    """Execute operation with circuit breaker protection."""
    circuit_breaker = get_daytona_circuit_breaker()
    return await circuit_breaker.execute(operation, operation_name, timeout)


def with_circuit_breaker(
    operation_name: str = None,
    timeout: Optional[float] = None
):
    """
    Decorator to apply circuit breaker to async functions.
    
    Usage:
        @with_circuit_breaker("create_sandbox", timeout=30)
        async def create_sandbox(...):
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            name = operation_name or func.__name__
            circuit_breaker = get_daytona_circuit_breaker()
            
            async def operation():
                return await func(*args, **kwargs)
            
            return await circuit_breaker.execute(operation, name, timeout)
        
        return wrapper
    return decorator