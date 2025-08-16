"""
Comprehensive error handling utilities for Kortix agent system.

This module provides base classes, enums, and utilities for consistent
error handling and status tracking throughout the system.
"""

from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from dataclasses import dataclass, field
import traceback
import json
from utils.logger import logger


class ErrorType(Enum):
    """Classification of error types for proper handling."""
    TRANSIENT = "transient"          # Can retry immediately
    PERMANENT = "permanent"          # Cannot retry
    RATE_LIMIT = "rate_limit"        # Wait and retry
    BILLING = "billing"              # Requires user action
    SANDBOX = "sandbox"              # Sandbox-specific issues
    TOOL = "tool"                    # Tool execution failures
    LLM = "llm"                      # LLM-related errors
    NETWORK = "network"              # Connection issues
    TIMEOUT = "timeout"              # Operation timed out
    VALIDATION = "validation"        # Input validation errors
    AUTHENTICATION = "authentication" # Auth failures
    AUTHORIZATION = "authorization"   # Permission denied
    CONFIGURATION = "configuration"   # Config issues


class ErrorSeverity(Enum):
    """Severity levels for errors."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AgentRunStatus(Enum):
    """Detailed status tracking for agent runs."""
    QUEUED = "queued"                           # In queue, not started
    INITIALIZING = "initializing"               # Setting up resources
    LOADING_AGENT = "loading_agent"             # Loading agent config
    LOADING_TOOLS = "loading_tools"             # Registering tools
    LOADING_MCP = "loading_mcp"                 # Initializing MCP servers
    BUILDING_PROMPT = "building_prompt"         # Constructing system prompt
    READY = "ready"                             # Ready to execute
    EXECUTING = "executing"                      # Main execution loop
    CALLING_LLM = "calling_llm"                 # Waiting for LLM response
    PROCESSING_RESPONSE = "processing_response" # Processing LLM output
    EXECUTING_TOOL = "executing_tool"           # Running tool
    WAITING_SANDBOX = "waiting_sandbox"         # Waiting for sandbox
    STREAMING = "streaming"                      # Streaming response
    COMPLETING = "completing"                    # Finalizing execution
    COMPLETED = "completed"                      # Successfully completed
    FAILED = "failed"                           # Failed with error
    TIMEOUT = "timeout"                         # Timed out
    CANCELLED = "cancelled"                     # User cancelled
    STOPPED = "stopped"                         # Stopped by system


@dataclass
class ErrorContext:
    """Context information for an error."""
    error_type: ErrorType
    severity: ErrorSeverity
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    traceback: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    can_retry: bool = False
    user_message: Optional[str] = None
    recovery_action: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "error_type": self.error_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "traceback": self.traceback,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "can_retry": self.can_retry,
            "user_message": self.user_message,
            "recovery_action": self.recovery_action
        }


@dataclass
class ProgressUpdate:
    """Progress update for long-running operations."""
    stage: AgentRunStatus
    percentage: int
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "stage": self.stage.value,
            "percentage": self.percentage,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat()
        }


class KortixError(Exception):
    """Base exception for all Kortix errors."""
    
    def __init__(
        self,
        message: str,
        error_type: ErrorType = ErrorType.PERMANENT,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        details: Optional[Dict[str, Any]] = None,
        user_message: Optional[str] = None,
        recovery_action: Optional[str] = None,
        can_retry: bool = False
    ):
        super().__init__(message)
        self.context = ErrorContext(
            error_type=error_type,
            severity=severity,
            message=message,
            details=details or {},
            traceback=traceback.format_exc(),
            can_retry=can_retry,
            user_message=user_message,
            recovery_action=recovery_action
        )
    
    def to_response(self) -> Dict[str, Any]:
        """Convert to API response format."""
        return {
            "error": True,
            "message": self.context.user_message or self.context.message,
            "type": self.context.error_type.value,
            "details": self.context.details,
            "recovery_action": self.context.recovery_action,
            "can_retry": self.context.can_retry
        }


class TransientError(KortixError):
    """Error that can be retried."""
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            error_type=ErrorType.TRANSIENT,
            can_retry=True,
            **kwargs
        )


class SandboxError(KortixError):
    """Sandbox-related error."""
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            error_type=ErrorType.SANDBOX,
            severity=ErrorSeverity.WARNING,
            user_message="Sandbox service is temporarily unavailable. Some tools may not work.",
            recovery_action="The system will retry automatically or use alternative methods.",
            can_retry=True,
            **kwargs
        )


class ToolExecutionError(KortixError):
    """Tool execution error."""
    def __init__(self, tool_name: str, message: str, **kwargs):
        super().__init__(
            message,
            error_type=ErrorType.TOOL,
            details={"tool_name": tool_name},
            user_message=f"Tool '{tool_name}' failed to execute",
            **kwargs
        )


class LLMError(KortixError):
    """LLM-related error."""
    def __init__(self, message: str, model: Optional[str] = None, **kwargs):
        super().__init__(
            message,
            error_type=ErrorType.LLM,
            details={"model": model} if model else {},
            **kwargs
        )


class RateLimitError(KortixError):
    """Rate limit exceeded error."""
    def __init__(self, message: str, retry_after: Optional[int] = None, **kwargs):
        super().__init__(
            message,
            error_type=ErrorType.RATE_LIMIT,
            severity=ErrorSeverity.WARNING,
            details={"retry_after": retry_after} if retry_after else {},
            user_message="Rate limit reached. Please wait a moment.",
            recovery_action=f"Retry after {retry_after} seconds" if retry_after else "Retry in a few seconds",
            can_retry=True,
            **kwargs
        )


class BillingError(KortixError):
    """Billing-related error."""
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            error_type=ErrorType.BILLING,
            severity=ErrorSeverity.ERROR,
            user_message="Billing limit reached. Please upgrade your plan.",
            recovery_action="Upgrade your subscription to continue.",
            can_retry=False,
            **kwargs
        )


class TimeoutError(KortixError):
    """Operation timeout error."""
    def __init__(self, operation: str, timeout_seconds: int, **kwargs):
        super().__init__(
            f"Operation '{operation}' timed out after {timeout_seconds} seconds",
            error_type=ErrorType.TIMEOUT,
            severity=ErrorSeverity.WARNING,
            details={"operation": operation, "timeout_seconds": timeout_seconds},
            user_message=f"Operation timed out. This is taking longer than expected.",
            recovery_action="The system will retry with a longer timeout.",
            can_retry=True,
            **kwargs
        )


class ErrorHandler:
    """Centralized error handling and recovery logic."""
    
    @staticmethod
    def classify_error(error: Exception) -> ErrorContext:
        """Classify an exception into an ErrorContext."""
        if isinstance(error, KortixError):
            return error.context
        
        error_str = str(error).lower()
        error_type_name = type(error).__name__
        
        # Network-related errors
        if any(x in error_str for x in ["connection", "network", "socket", "refused"]):
            return ErrorContext(
                error_type=ErrorType.NETWORK,
                severity=ErrorSeverity.WARNING,
                message=str(error),
                can_retry=True,
                user_message="Network connection issue. Retrying...",
                recovery_action="Check your internet connection."
            )
        
        # Timeout errors
        if "timeout" in error_str or "timed out" in error_str:
            return ErrorContext(
                error_type=ErrorType.TIMEOUT,
                severity=ErrorSeverity.WARNING,
                message=str(error),
                can_retry=True,
                user_message="Operation timed out. Retrying with longer timeout...",
                recovery_action="The system will retry automatically."
            )
        
        # Rate limiting
        if "rate" in error_str and "limit" in error_str:
            return ErrorContext(
                error_type=ErrorType.RATE_LIMIT,
                severity=ErrorSeverity.WARNING,
                message=str(error),
                can_retry=True,
                user_message="Rate limit reached. Waiting before retry...",
                recovery_action="Please wait a moment."
            )
        
        # Authentication/Authorization
        if any(x in error_str for x in ["unauthorized", "forbidden", "401", "403"]):
            return ErrorContext(
                error_type=ErrorType.AUTHORIZATION,
                severity=ErrorSeverity.ERROR,
                message=str(error),
                can_retry=False,
                user_message="Permission denied.",
                recovery_action="Check your permissions or contact support."
            )
        
        # Default classification
        return ErrorContext(
            error_type=ErrorType.PERMANENT,
            severity=ErrorSeverity.ERROR,
            message=str(error),
            traceback=traceback.format_exc(),
            can_retry=False,
            user_message="An unexpected error occurred.",
            recovery_action="Please try again or contact support if the issue persists."
        )
    
    @staticmethod
    def should_retry(context: ErrorContext) -> bool:
        """Determine if an error should be retried."""
        if not context.can_retry:
            return False
        
        if context.retry_count >= context.max_retries:
            return False
        
        # Error types that should always retry
        retriable_types = [
            ErrorType.TRANSIENT,
            ErrorType.NETWORK,
            ErrorType.TIMEOUT,
            ErrorType.RATE_LIMIT,
            ErrorType.SANDBOX
        ]
        
        return context.error_type in retriable_types
    
    @staticmethod
    def get_retry_delay(context: ErrorContext) -> int:
        """Get retry delay in seconds based on error context."""
        if context.error_type == ErrorType.RATE_LIMIT:
            # Check if we have a specific retry_after value
            retry_after = context.details.get("retry_after")
            if retry_after:
                return retry_after
            return 30  # Default rate limit delay
        
        # Exponential backoff for other errors
        base_delay = 1
        if context.error_type == ErrorType.NETWORK:
            base_delay = 2
        elif context.error_type == ErrorType.TIMEOUT:
            base_delay = 5
        elif context.error_type == ErrorType.SANDBOX:
            base_delay = 3
        
        # Exponential backoff: 1, 2, 4, 8, etc.
        return min(base_delay * (2 ** context.retry_count), 60)
    
    @staticmethod
    def log_error(context: ErrorContext, component: str = "unknown"):
        """Log error with appropriate severity."""
        log_message = f"[{component}] {context.message}"
        details = {
            "component": component,
            "error_type": context.error_type.value,
            "details": context.details,
            "can_retry": context.can_retry,
            "retry_count": context.retry_count
        }
        
        if context.severity == ErrorSeverity.DEBUG:
            logger.debug(log_message, extra=details)
        elif context.severity == ErrorSeverity.INFO:
            logger.info(log_message, extra=details)
        elif context.severity == ErrorSeverity.WARNING:
            logger.warning(log_message, extra=details)
        elif context.severity == ErrorSeverity.ERROR:
            logger.error(log_message, extra=details, exc_info=True)
        elif context.severity == ErrorSeverity.CRITICAL:
            logger.critical(log_message, extra=details, exc_info=True)


def wrap_with_error_handling(component: str):
    """Decorator to add error handling to async functions."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                context = ErrorHandler.classify_error(e)
                ErrorHandler.log_error(context, component)
                
                if ErrorHandler.should_retry(context):
                    context.retry_count += 1
                    delay = ErrorHandler.get_retry_delay(context)
                    logger.info(f"Retrying {func.__name__} after {delay} seconds (attempt {context.retry_count}/{context.max_retries})")
                    import asyncio
                    await asyncio.sleep(delay)
                    return await wrapper(*args, **kwargs)
                
                # Re-raise as KortixError if not already
                if not isinstance(e, KortixError):
                    raise KortixError(
                        message=str(e),
                        error_type=context.error_type,
                        severity=context.severity,
                        details=context.details,
                        user_message=context.user_message,
                        recovery_action=context.recovery_action,
                        can_retry=context.can_retry
                    )
                raise
        
        return wrapper
    return decorator