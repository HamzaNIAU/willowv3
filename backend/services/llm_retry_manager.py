"""
Smart LLM Retry Manager

This module provides intelligent retry logic for LLM API calls with:
- Error-aware backoff strategies
- Model fallback chains based on capability and cost
- Token usage and cost tracking
- Request prioritization and queuing
- Adaptive timeout management
- Circuit breaker integration
"""

import asyncio
import time
import json
from enum import Enum
from typing import Dict, Any, Optional, List, Callable, TypeVar, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import random
import weakref
from collections import defaultdict, deque
import litellm

from utils.logger import logger
from utils.error_handler import (
    ErrorHandler, ErrorType, ErrorSeverity,
    TransientError, RateLimitError, BillingError
)

T = TypeVar('T')


class RequestPriority(Enum):
    """Priority levels for LLM requests."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


class ModelTier(Enum):
    """Model tiers based on capability and cost."""
    PREMIUM = "premium"      # Claude 3.7, GPT-5, etc.
    STANDARD = "standard"    # Claude 3.5, GPT-4, etc.
    EFFICIENT = "efficient"  # Claude 3 Haiku, GPT-3.5, etc.
    FALLBACK = "fallback"    # Cheapest available models


@dataclass
class ModelConfig:
    """Configuration for a specific model."""
    name: str
    tier: ModelTier
    cost_per_token: float  # Cost per 1k tokens
    max_tokens: int
    timeout: float
    rate_limit_rpm: int    # Requests per minute
    capabilities: List[str] = field(default_factory=list)
    fallback_models: List[str] = field(default_factory=list)


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter_factor: float = 0.1
    timeout_multiplier: float = 1.5
    cost_limit_per_request: float = 10.0  # Maximum cost per request in USD
    
    # Error-specific retry settings
    rate_limit_delay: float = 30.0
    timeout_retry_count: int = 2
    billing_retry_count: int = 0  # Don't retry billing errors
    network_retry_count: int = 3


@dataclass
class RequestContext:
    """Context for a specific request."""
    request_id: str
    priority: RequestPriority
    original_model: str
    capabilities_required: List[str]
    max_cost: float
    timeout: float
    created_at: float
    attempt_count: int = 0
    total_cost: float = 0.0
    model_history: List[str] = field(default_factory=list)
    error_history: List[str] = field(default_factory=list)


@dataclass
class ModelMetrics:
    """Performance metrics for a model."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    average_latency: float = 0.0
    average_cost: float = 0.0
    last_failure_time: Optional[float] = None
    consecutive_failures: int = 0
    rate_limit_count: int = 0
    success_rate: float = 100.0
    
    def update_success(self, latency: float, cost: float):
        """Update metrics for successful request."""
        self.total_requests += 1
        self.successful_requests += 1
        self.consecutive_failures = 0
        
        # Update averages using exponential moving average
        alpha = 0.1
        if self.average_latency == 0:
            self.average_latency = latency
            self.average_cost = cost
        else:
            self.average_latency = alpha * latency + (1 - alpha) * self.average_latency
            self.average_cost = alpha * cost + (1 - alpha) * self.average_cost
        
        self._update_success_rate()
    
    def update_failure(self, error_type: str):
        """Update metrics for failed request."""
        self.total_requests += 1
        self.failed_requests += 1
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        
        if error_type == "rate_limit":
            self.rate_limit_count += 1
        
        self._update_success_rate()
    
    def _update_success_rate(self):
        """Update success rate percentage."""
        if self.total_requests > 0:
            self.success_rate = (self.successful_requests / self.total_requests) * 100


class ModelFallbackChain:
    """Manages model fallback chains based on capabilities and cost."""
    
    def __init__(self):
        """Initialize with default model configurations."""
        self.models: Dict[str, ModelConfig] = {}
        self._initialize_default_models()
    
    def _initialize_default_models(self):
        """Initialize default model configurations."""
        models = [
            # Premium tier
            ModelConfig(
                name="anthropic/claude-3-7-sonnet-latest",
                tier=ModelTier.PREMIUM,
                cost_per_token=0.015,
                max_tokens=8192,
                timeout=60.0,
                rate_limit_rpm=50,
                capabilities=["reasoning", "coding", "analysis", "thinking"],
                fallback_models=["anthropic/claude-3-5-sonnet-20241022", "openai/gpt-4o"]
            ),
            ModelConfig(
                name="openai/gpt-5",
                tier=ModelTier.PREMIUM,
                cost_per_token=0.020,
                max_tokens=4096,
                timeout=45.0,
                rate_limit_rpm=30,
                capabilities=["reasoning", "coding", "analysis"],
                fallback_models=["openai/gpt-4o", "anthropic/claude-3-5-sonnet-20241022"]
            ),
            
            # Standard tier
            ModelConfig(
                name="anthropic/claude-3-5-sonnet-20241022",
                tier=ModelTier.STANDARD,
                cost_per_token=0.003,
                max_tokens=8192,
                timeout=30.0,
                rate_limit_rpm=100,
                capabilities=["reasoning", "coding", "analysis"],
                fallback_models=["openai/gpt-4o", "anthropic/claude-3-haiku-20240307"]
            ),
            ModelConfig(
                name="openai/gpt-4o",
                tier=ModelTier.STANDARD,
                cost_per_token=0.0025,
                max_tokens=4096,
                timeout=30.0,
                rate_limit_rpm=150,
                capabilities=["reasoning", "coding", "analysis"],
                fallback_models=["openai/gpt-4o-mini", "anthropic/claude-3-haiku-20240307"]
            ),
            
            # Efficient tier
            ModelConfig(
                name="anthropic/claude-3-haiku-20240307",
                tier=ModelTier.EFFICIENT,
                cost_per_token=0.00025,
                max_tokens=4096,
                timeout=15.0,
                rate_limit_rpm=200,
                capabilities=["basic-reasoning", "coding"],
                fallback_models=["openai/gpt-4o-mini", "openai/gpt-3.5-turbo"]
            ),
            ModelConfig(
                name="openai/gpt-4o-mini",
                tier=ModelTier.EFFICIENT,
                cost_per_token=0.00015,
                max_tokens=4096,
                timeout=15.0,
                rate_limit_rpm=300,
                capabilities=["basic-reasoning", "coding"],
                fallback_models=["openai/gpt-3.5-turbo"]
            ),
            
            # Fallback tier
            ModelConfig(
                name="openai/gpt-3.5-turbo",
                tier=ModelTier.FALLBACK,
                cost_per_token=0.0005,
                max_tokens=4096,
                timeout=10.0,
                rate_limit_rpm=500,
                capabilities=["basic-reasoning"],
                fallback_models=[]
            )
        ]
        
        for model in models:
            self.models[model.name] = model
    
    def get_fallback_chain(
        self,
        original_model: str,
        capabilities_required: List[str],
        max_cost_per_token: float
    ) -> List[str]:
        """Get fallback chain for a model based on requirements."""
        if original_model not in self.models:
            logger.warning(f"Unknown model {original_model}, using default fallback")
            return list(self.models.keys())[:3]  # Return first 3 models
        
        original_config = self.models[original_model]
        fallback_chain = [original_model]
        
        # Add explicit fallbacks first
        for fallback_model in original_config.fallback_models:
            if fallback_model in self.models:
                config = self.models[fallback_model]
                if (config.cost_per_token <= max_cost_per_token and
                    self._has_required_capabilities(config, capabilities_required)):
                    fallback_chain.append(fallback_model)
        
        # Add additional models by tier and capability
        for tier in [ModelTier.STANDARD, ModelTier.EFFICIENT, ModelTier.FALLBACK]:
            for model_name, config in self.models.items():
                if (model_name not in fallback_chain and
                    config.tier == tier and
                    config.cost_per_token <= max_cost_per_token and
                    self._has_required_capabilities(config, capabilities_required)):
                    fallback_chain.append(model_name)
                    
                    # Limit fallback chain length
                    if len(fallback_chain) >= 5:
                        break
            
            if len(fallback_chain) >= 5:
                break
        
        return fallback_chain
    
    def _has_required_capabilities(
        self,
        model_config: ModelConfig,
        required_capabilities: List[str]
    ) -> bool:
        """Check if model has required capabilities."""
        if not required_capabilities:
            return True
        
        return any(
            capability in model_config.capabilities
            for capability in required_capabilities
        )
    
    def get_model_config(self, model_name: str) -> Optional[ModelConfig]:
        """Get configuration for a model."""
        return self.models.get(model_name)


class SmartLLMRetryManager:
    """
    Smart retry manager for LLM API calls with adaptive behavior.
    
    Features:
    - Error-aware retry strategies
    - Model fallback chains based on capability and cost
    - Token usage and cost tracking
    - Request prioritization
    - Adaptive timeout management
    """
    
    def __init__(self, config: Optional[RetryConfig] = None):
        """Initialize retry manager."""
        self.config = config or RetryConfig()
        self.fallback_chain = ModelFallbackChain()
        self.error_handler = ErrorHandler()
        
        # Metrics tracking
        self.model_metrics: Dict[str, ModelMetrics] = defaultdict(ModelMetrics)
        self.total_cost: float = 0.0
        self.total_requests: int = 0
        
        # Request queue for priority management
        self.request_queues: Dict[RequestPriority, deque] = {
            priority: deque() for priority in RequestPriority
        }
        
        # Active requests tracking
        self.active_requests: Dict[str, RequestContext] = {}
        self._lock = asyncio.Lock()
        
        logger.info(f"Smart LLM retry manager initialized with config: {self.config}")
    
    async def execute_with_retry(
        self,
        request_id: str,
        llm_call: Callable,
        original_model: str,
        priority: RequestPriority = RequestPriority.NORMAL,
        capabilities_required: Optional[List[str]] = None,
        max_cost: float = 10.0,
        timeout: Optional[float] = None,
        **llm_kwargs
    ) -> Any:
        """
        Execute LLM call with smart retry and fallback logic.
        
        Args:
            request_id: Unique identifier for this request
            llm_call: The LLM function to call
            original_model: Original model to try first
            priority: Request priority level
            capabilities_required: Required model capabilities
            max_cost: Maximum cost limit for this request
            timeout: Request timeout
            **llm_kwargs: Additional arguments for LLM call
            
        Returns:
            LLM response
            
        Raises:
            Exception: If all retry attempts fail
        """
        capabilities_required = capabilities_required or []
        
        # Create request context
        context = RequestContext(
            request_id=request_id,
            priority=priority,
            original_model=original_model,
            capabilities_required=capabilities_required,
            max_cost=max_cost,
            timeout=timeout or self._get_model_timeout(original_model),
            created_at=time.time()
        )
        
        # Get fallback chain
        fallback_models = self.fallback_chain.get_fallback_chain(
            original_model,
            capabilities_required,
            max_cost / 1000  # Convert to per-token cost
        )
        
        logger.info(
            f"Starting LLM request {request_id} with fallback chain: {fallback_models}"
        )
        
        last_error = None
        
        for model_name in fallback_models:
            if context.total_cost >= context.max_cost:
                logger.warning(
                    f"Request {request_id} exceeded cost limit: "
                    f"{context.total_cost:.4f} >= {context.max_cost}"
                )
                break
            
            try:
                result = await self._try_model(context, llm_call, model_name, **llm_kwargs)
                
                # Record success metrics
                await self._record_success(
                    model_name,
                    context.total_cost,
                    time.time() - context.created_at
                )
                
                logger.info(
                    f"Request {request_id} succeeded with model {model_name} "
                    f"(attempt {context.attempt_count}, cost: ${context.total_cost:.4f})"
                )
                
                return result
                
            except Exception as e:
                last_error = e
                context.error_history.append(str(e))
                
                # Classify error and decide if we should continue
                error_info = self.error_handler.classify_error(e)
                await self._record_failure(model_name, error_info.error_type.value)
                
                logger.warning(
                    f"Request {request_id} failed with model {model_name}: {e} "
                    f"(type: {error_info.error_type.value})"
                )
                
                # Don't retry on permanent errors unless fallback model available
                if error_info.error_type == ErrorType.PERMANENT and len(fallback_models) == 1:
                    break
                
                # Apply delay before next attempt
                if model_name != fallback_models[-1]:  # Not the last model
                    delay = self._calculate_delay(context, error_info.error_type)
                    if delay > 0:
                        logger.debug(f"Waiting {delay:.2f}s before trying next model")
                        await asyncio.sleep(delay)
        
        # All attempts failed
        error_msg = (
            f"LLM request {request_id} failed after trying {len(fallback_models)} models. "
            f"Total cost: ${context.total_cost:.4f}. "
            f"Last error: {last_error}"
        )
        logger.error(error_msg)
        
        if last_error:
            raise last_error
        else:
            raise Exception(error_msg)
    
    async def _try_model(
        self,
        context: RequestContext,
        llm_call: Callable,
        model_name: str,
        **llm_kwargs
    ) -> Any:
        """Try executing LLM call with specific model."""
        context.attempt_count += 1
        context.model_history.append(model_name)
        
        # Get model configuration
        model_config = self.fallback_chain.get_model_config(model_name)
        if not model_config:
            raise Exception(f"Unknown model configuration: {model_name}")
        
        # Calculate estimated cost
        messages = llm_kwargs.get('messages', [])
        estimated_tokens = self._estimate_tokens(messages, llm_kwargs.get('max_tokens', 1000))
        estimated_cost = (estimated_tokens / 1000) * model_config.cost_per_token
        
        if context.total_cost + estimated_cost > context.max_cost:
            raise BillingError(
                f"Estimated cost ${estimated_cost:.4f} would exceed limit "
                f"(current: ${context.total_cost:.4f}, limit: ${context.max_cost:.4f})"
            )
        
        # Update LLM kwargs with model-specific settings
        llm_kwargs.update({
            'model': model_name,
            'timeout': min(context.timeout, model_config.timeout)
        })
        
        # Execute the call
        start_time = time.time()
        try:
            result = await llm_call(**llm_kwargs)
            
            # Calculate actual cost if available
            actual_cost = self._calculate_actual_cost(result, model_config)
            context.total_cost += actual_cost
            self.total_cost += actual_cost
            
            return result
            
        except Exception as e:
            # Even failed requests may incur some cost
            context.total_cost += estimated_cost * 0.1  # Minimal cost for failed request
            raise
    
    def _calculate_delay(self, context: RequestContext, error_type: ErrorType) -> float:
        """Calculate delay before next retry attempt."""
        if error_type == ErrorType.RATE_LIMIT:
            return self.config.rate_limit_delay + random.uniform(0, 5)
        
        elif error_type == ErrorType.TIMEOUT:
            return self.config.base_delay * (self.config.exponential_base ** context.attempt_count)
        
        elif error_type == ErrorType.NETWORK:
            base_delay = self.config.base_delay * (self.config.exponential_base ** context.attempt_count)
            jitter = base_delay * self.config.jitter_factor * random.uniform(-1, 1)
            return min(base_delay + jitter, self.config.max_delay)
        
        else:
            # For other errors, minimal delay
            return self.config.base_delay
    
    def _estimate_tokens(self, messages: List[Dict], max_tokens: int) -> int:
        """Estimate token count for messages."""
        # Simple estimation: ~4 characters per token
        total_chars = 0
        for message in messages:
            content = message.get('content', '')
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and 'text' in item:
                        total_chars += len(item['text'])
        
        input_tokens = total_chars // 4
        return input_tokens + max_tokens  # Input + estimated output
    
    def _calculate_actual_cost(self, result: Any, model_config: ModelConfig) -> float:
        """Calculate actual cost from LLM response."""
        try:
            if hasattr(result, 'usage') and result.usage:
                total_tokens = result.usage.prompt_tokens + result.usage.completion_tokens
                return (total_tokens / 1000) * model_config.cost_per_token
        except Exception as e:
            logger.debug(f"Could not calculate actual cost: {e}")
        
        # Fallback to estimation
        return 0.001  # Minimal cost if we can't calculate
    
    def _get_model_timeout(self, model_name: str) -> float:
        """Get timeout for specific model."""
        model_config = self.fallback_chain.get_model_config(model_name)
        return model_config.timeout if model_config else 30.0
    
    async def _record_success(self, model_name: str, cost: float, latency: float):
        """Record successful request metrics."""
        async with self._lock:
            self.model_metrics[model_name].update_success(latency, cost)
            self.total_requests += 1
    
    async def _record_failure(self, model_name: str, error_type: str):
        """Record failed request metrics."""
        async with self._lock:
            self.model_metrics[model_name].update_failure(error_type)
            self.total_requests += 1
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get current performance metrics."""
        async with self._lock:
            return {
                "total_requests": self.total_requests,
                "total_cost": self.total_cost,
                "average_cost_per_request": (
                    self.total_cost / self.total_requests
                    if self.total_requests > 0 else 0
                ),
                "models": {
                    model_name: {
                        "total_requests": metrics.total_requests,
                        "success_rate": metrics.success_rate,
                        "average_latency": metrics.average_latency,
                        "average_cost": metrics.average_cost,
                        "consecutive_failures": metrics.consecutive_failures,
                        "rate_limit_count": metrics.rate_limit_count,
                    }
                    for model_name, metrics in self.model_metrics.items()
                },
                "config": {
                    "max_attempts": self.config.max_attempts,
                    "cost_limit_per_request": self.config.cost_limit_per_request,
                    "rate_limit_delay": self.config.rate_limit_delay,
                }
            }
    
    async def reset_metrics(self):
        """Reset all metrics."""
        async with self._lock:
            self.model_metrics.clear()
            self.total_cost = 0.0
            self.total_requests = 0
            logger.info("LLM retry manager metrics reset")


# Global retry manager instance
_retry_manager: Optional[SmartLLMRetryManager] = None


def get_retry_manager() -> SmartLLMRetryManager:
    """Get the global retry manager instance."""
    global _retry_manager
    if _retry_manager is None:
        _retry_manager = SmartLLMRetryManager()
    return _retry_manager


def initialize_retry_manager(config: Optional[RetryConfig] = None):
    """Initialize the global retry manager."""
    global _retry_manager
    _retry_manager = SmartLLMRetryManager(config)
    logger.info("Smart LLM retry manager initialized")


async def execute_with_smart_retry(
    request_id: str,
    llm_call: Callable,
    model_name: str,
    priority: RequestPriority = RequestPriority.NORMAL,
    **kwargs
) -> Any:
    """Convenience function to execute LLM call with smart retry."""
    retry_manager = get_retry_manager()
    return await retry_manager.execute_with_retry(
        request_id, llm_call, model_name, priority, **kwargs
    )