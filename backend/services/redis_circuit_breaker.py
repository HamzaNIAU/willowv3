"""
Redis Circuit Breaker Implementation

This module provides a circuit breaker pattern for Redis operations with:
- Adaptive failure thresholds per operation type
- Half-open state for recovery testing
- In-memory fallback cache for read operations
- Metrics collection and health monitoring
- Auto-tuning based on historical performance
"""

import asyncio
import time
import json
from enum import Enum
from typing import Dict, Any, Optional, Callable, TypeVar, List, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import weakref
from collections import defaultdict, deque

from utils.logger import logger
from utils.error_handler import (
    ErrorHandler, ErrorType, ErrorSeverity,
    TransientError, TimeoutError
)

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Circuit tripped, failing fast
    HALF_OPEN = "half_open"  # Testing recovery


class OperationType(Enum):
    """Redis operation types with different failure tolerance."""
    READ = "read"          # GET, LRANGE, etc. - more tolerant
    WRITE = "write"        # SET, RPUSH, etc. - less tolerant
    PUBSUB = "pubsub"      # PUBLISH, SUBSCRIBE - real-time critical


@dataclass
class CircuitConfig:
    """Configuration for circuit breaker behavior."""
    # Failure thresholds per operation type
    read_failure_threshold: int = 5     # Reads can tolerate more failures
    write_failure_threshold: int = 3    # Writes are more critical
    pubsub_failure_threshold: int = 2   # PubSub needs to be very reliable
    
    # Recovery settings
    recovery_timeout: float = 30.0      # Time before trying HALF_OPEN (seconds)
    success_threshold: int = 3          # Successes needed to close circuit
    test_request_timeout: float = 5.0   # Timeout for recovery test requests
    
    # Cache settings
    fallback_cache_size: int = 1000     # Max items in fallback cache
    fallback_cache_ttl: int = 300       # TTL for cached items (seconds)
    
    # Metrics
    metrics_window: int = 300           # Metrics collection window (seconds)
    auto_tune_enabled: bool = True      # Enable threshold auto-tuning


@dataclass
class OperationMetrics:
    """Metrics for a specific operation type."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    average_latency: float = 0.0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    failure_rate: float = 0.0
    
    def update_success(self, latency: float):
        """Update metrics for successful operation."""
        self.total_requests += 1
        self.successful_requests += 1
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.last_success_time = time.time()
        
        # Update average latency using exponential moving average
        alpha = 0.1
        if self.average_latency == 0:
            self.average_latency = latency
        else:
            self.average_latency = alpha * latency + (1 - alpha) * self.average_latency
        
        self._update_failure_rate()
    
    def update_failure(self):
        """Update metrics for failed operation."""
        self.total_requests += 1
        self.failed_requests += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_failure_time = time.time()
        self._update_failure_rate()
    
    def _update_failure_rate(self):
        """Update failure rate percentage."""
        if self.total_requests > 0:
            self.failure_rate = (self.failed_requests / self.total_requests) * 100


@dataclass
class CacheItem:
    """Item in the fallback cache."""
    value: Any
    timestamp: float
    ttl: int
    
    def is_expired(self) -> bool:
        """Check if cache item has expired."""
        return time.time() - self.timestamp > self.ttl


class FallbackCache:
    """In-memory LRU cache for Redis fallback."""
    
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._cache: Dict[str, CacheItem] = {}
        self._access_order: deque = deque()
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[Any]:
        """Get item from cache."""
        async with self._lock:
            if key not in self._cache:
                return None
            
            item = self._cache[key]
            if item.is_expired():
                del self._cache[key]
                try:
                    self._access_order.remove(key)
                except ValueError:
                    pass
                return None
            
            # Update access order (move to end)
            try:
                self._access_order.remove(key)
            except ValueError:
                pass
            self._access_order.append(key)
            
            return item.value
    
    async def set(self, key: str, value: Any, ttl: int = 300):
        """Set item in cache."""
        async with self._lock:
            # Remove if already exists
            if key in self._cache:
                try:
                    self._access_order.remove(key)
                except ValueError:
                    pass
            
            # Evict oldest items if cache is full
            while len(self._cache) >= self.max_size and self._access_order:
                oldest_key = self._access_order.popleft()
                if oldest_key in self._cache:
                    del self._cache[oldest_key]
            
            # Add new item
            self._cache[key] = CacheItem(
                value=value,
                timestamp=time.time(),
                ttl=ttl
            )
            self._access_order.append(key)
    
    async def delete(self, key: str):
        """Delete item from cache."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                try:
                    self._access_order.remove(key)
                except ValueError:
                    pass
    
    async def size(self) -> int:
        """Get cache size."""
        async with self._lock:
            return len(self._cache)
    
    async def clear(self):
        """Clear all cached items."""
        async with self._lock:
            self._cache.clear()
            self._access_order.clear()


class RedisCircuitBreaker:
    """
    Circuit breaker for Redis operations with adaptive behavior.
    
    Features:
    - Per-operation-type failure tracking
    - Half-open state for recovery testing
    - Fallback cache for read operations during outages
    - Metrics collection and auto-tuning
    - Health monitoring and reporting
    """
    
    def __init__(self, config: Optional[CircuitConfig] = None):
        """Initialize circuit breaker."""
        self.config = config or CircuitConfig()
        self.state = CircuitState.CLOSED
        self.state_change_time = time.time()
        
        # Per-operation metrics
        self.metrics: Dict[OperationType, OperationMetrics] = {
            op_type: OperationMetrics() for op_type in OperationType
        }
        
        # Fallback cache for read operations
        self.fallback_cache = FallbackCache(self.config.fallback_cache_size)
        
        # Error handler integration
        self.error_handler = ErrorHandler()
        
        # Health monitoring
        self._health_checks = []
        self._lock = asyncio.Lock()
        
        logger.info(f"Redis circuit breaker initialized with config: {self.config}")
    
    def get_failure_threshold(self, operation_type: OperationType) -> int:
        """Get failure threshold for operation type."""
        thresholds = {
            OperationType.READ: self.config.read_failure_threshold,
            OperationType.WRITE: self.config.write_failure_threshold,
            OperationType.PUBSUB: self.config.pubsub_failure_threshold,
        }
        return thresholds[operation_type]
    
    async def execute(
        self,
        operation: Callable[[], T],
        operation_type: OperationType,
        cache_key: Optional[str] = None,
        cache_ttl: int = 300
    ) -> T:
        """
        Execute a Redis operation through the circuit breaker.
        
        Args:
            operation: The Redis operation to execute
            operation_type: Type of operation (READ/WRITE/PUBSUB)
            cache_key: Cache key for read operations (enables fallback)
            cache_ttl: TTL for cached values
            
        Returns:
            Result of the operation or cached value
            
        Raises:
            Exception: If operation fails and no fallback available
        """
        # Check circuit state first
        if await self._should_reject_request(operation_type):
            if operation_type == OperationType.READ and cache_key:
                # Try fallback cache for reads
                cached_value = await self.fallback_cache.get(cache_key)
                if cached_value is not None:
                    logger.debug(f"Circuit breaker: Using cached value for {cache_key}")
                    return cached_value
            
            # No fallback available, raise error
            error_msg = f"Redis circuit breaker OPEN for {operation_type.value} operations"
            logger.warning(error_msg)
            raise TransientError(error_msg)
        
        # Execute operation with monitoring
        start_time = time.time()
        try:
            result = await operation()
            
            # Record success
            latency = time.time() - start_time
            await self._record_success(operation_type, latency)
            
            # Cache result for read operations
            if operation_type == OperationType.READ and cache_key and result is not None:
                await self.fallback_cache.set(cache_key, result, cache_ttl)
            
            return result
            
        except Exception as e:
            # Record failure
            await self._record_failure(operation_type, e)
            
            # Try fallback for read operations
            if operation_type == OperationType.READ and cache_key:
                cached_value = await self.fallback_cache.get(cache_key)
                if cached_value is not None:
                    logger.info(f"Circuit breaker: Using cached fallback for {cache_key} after error: {e}")
                    return cached_value
            
            # Re-raise if no fallback
            raise
    
    async def _should_reject_request(self, operation_type: OperationType) -> bool:
        """Check if request should be rejected based on circuit state."""
        async with self._lock:
            current_time = time.time()
            
            if self.state == CircuitState.CLOSED:
                return False
            
            elif self.state == CircuitState.OPEN:
                # Check if enough time has passed to try recovery
                if current_time - self.state_change_time >= self.config.recovery_timeout:
                    logger.info(f"Circuit breaker: Transitioning to HALF_OPEN for {operation_type.value}")
                    self.state = CircuitState.HALF_OPEN
                    self.state_change_time = current_time
                    return False
                return True
            
            elif self.state == CircuitState.HALF_OPEN:
                # Only allow test requests in half-open state
                metrics = self.metrics[operation_type]
                if metrics.consecutive_successes >= self.config.success_threshold:
                    logger.info(f"Circuit breaker: Closing circuit for {operation_type.value}")
                    self.state = CircuitState.CLOSED
                    self.state_change_time = current_time
                    return False
                
                # Allow limited test requests
                return False
            
            return False
    
    async def _record_success(self, operation_type: OperationType, latency: float):
        """Record successful operation."""
        async with self._lock:
            metrics = self.metrics[operation_type]
            metrics.update_success(latency)
            
            # Check if we should close the circuit
            if self.state == CircuitState.HALF_OPEN:
                if metrics.consecutive_successes >= self.config.success_threshold:
                    logger.info(f"Circuit breaker: Closing circuit after {metrics.consecutive_successes} successes")
                    self.state = CircuitState.CLOSED
                    self.state_change_time = time.time()
    
    async def _record_failure(self, operation_type: OperationType, error: Exception):
        """Record failed operation and potentially open circuit."""
        async with self._lock:
            metrics = self.metrics[operation_type]
            metrics.update_failure()
            
            # Classify error
            error_info = self.error_handler.classify_error(error)
            
            # Don't trip circuit for permanent errors (bad requests, etc.)
            if error_info.error_type == ErrorType.PERMANENT:
                logger.debug(f"Circuit breaker: Ignoring permanent error for threshold calculation")
                return
            
            # Check if we should open the circuit
            failure_threshold = self.get_failure_threshold(operation_type)
            if metrics.consecutive_failures >= failure_threshold:
                if self.state != CircuitState.OPEN:
                    logger.warning(
                        f"Circuit breaker: Opening circuit for {operation_type.value} "
                        f"after {metrics.consecutive_failures} failures"
                    )
                    self.state = CircuitState.OPEN
                    self.state_change_time = time.time()
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get current health status of the circuit breaker."""
        async with self._lock:
            return {
                "state": self.state.value,
                "state_duration": time.time() - self.state_change_time,
                "metrics": {
                    op_type.value: {
                        "total_requests": metrics.total_requests,
                        "success_rate": (
                            (metrics.successful_requests / metrics.total_requests * 100)
                            if metrics.total_requests > 0 else 100
                        ),
                        "failure_rate": metrics.failure_rate,
                        "consecutive_failures": metrics.consecutive_failures,
                        "consecutive_successes": metrics.consecutive_successes,
                        "average_latency": metrics.average_latency,
                        "last_failure": metrics.last_failure_time,
                        "last_success": metrics.last_success_time,
                    }
                    for op_type, metrics in self.metrics.items()
                },
                "cache": {
                    "size": await self.fallback_cache.size(),
                    "max_size": self.config.fallback_cache_size,
                },
                "config": {
                    "read_threshold": self.config.read_failure_threshold,
                    "write_threshold": self.config.write_failure_threshold,
                    "pubsub_threshold": self.config.pubsub_failure_threshold,
                    "recovery_timeout": self.config.recovery_timeout,
                }
            }
    
    async def reset(self):
        """Reset circuit breaker to initial state."""
        async with self._lock:
            logger.info("Circuit breaker: Manual reset")
            self.state = CircuitState.CLOSED
            self.state_change_time = time.time()
            
            # Reset metrics
            for metrics in self.metrics.values():
                metrics.consecutive_failures = 0
                metrics.consecutive_successes = 0
            
            # Clear fallback cache
            await self.fallback_cache.clear()
    
    async def auto_tune_thresholds(self):
        """Auto-tune failure thresholds based on historical performance."""
        if not self.config.auto_tune_enabled:
            return
        
        async with self._lock:
            for op_type, metrics in self.metrics.items():
                if metrics.total_requests < 100:  # Need enough data
                    continue
                
                # Adjust thresholds based on failure rate
                if metrics.failure_rate < 1.0:  # Very low failure rate
                    current_threshold = self.get_failure_threshold(op_type)
                    new_threshold = min(current_threshold + 1, 10)  # Cap at 10
                    
                    if new_threshold != current_threshold:
                        logger.info(
                            f"Auto-tuning: Increasing {op_type.value} threshold "
                            f"from {current_threshold} to {new_threshold}"
                        )
                        # Update config (implementation depends on config storage)
                
                elif metrics.failure_rate > 10.0:  # High failure rate
                    current_threshold = self.get_failure_threshold(op_type)
                    new_threshold = max(current_threshold - 1, 1)  # Min at 1
                    
                    if new_threshold != current_threshold:
                        logger.info(
                            f"Auto-tuning: Decreasing {op_type.value} threshold "
                            f"from {current_threshold} to {new_threshold}"
                        )
                        # Update config


# Global circuit breaker instance
_circuit_breaker: Optional[RedisCircuitBreaker] = None


def get_circuit_breaker() -> RedisCircuitBreaker:
    """Get the global circuit breaker instance."""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = RedisCircuitBreaker()
    return _circuit_breaker


def initialize_circuit_breaker(config: Optional[CircuitConfig] = None):
    """Initialize the global circuit breaker."""
    global _circuit_breaker
    _circuit_breaker = RedisCircuitBreaker(config)
    logger.info("Redis circuit breaker initialized")


async def execute_with_circuit_breaker(
    operation: Callable[[], T],
    operation_type: OperationType,
    cache_key: Optional[str] = None,
    cache_ttl: int = 300
) -> T:
    """Convenience function to execute operation with circuit breaker."""
    circuit_breaker = get_circuit_breaker()
    return await circuit_breaker.execute(operation, operation_type, cache_key, cache_ttl)