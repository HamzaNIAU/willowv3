"""
Health Check API Endpoints

This module provides comprehensive health check endpoints for monitoring
the system's various components including Daytona, Redis, LLM, and database.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import asyncio
from datetime import datetime

from utils.logger import logger
from sandbox.daytona_health import get_daytona_health_checker
from sandbox.daytona_circuit_breaker import get_daytona_circuit_breaker
from services.redis_circuit_breaker import get_circuit_breaker as get_redis_circuit_breaker
from services.llm_retry_manager import get_retry_manager as get_llm_retry_manager
import services.redis as redis_service
from services.supabase import DBConnection

router = APIRouter(tags=["health"])


@router.get("/status")
async def health_check() -> Dict[str, Any]:
    """Basic health check endpoint."""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "kortix-backend"
    }


@router.get("/detailed")
async def detailed_health_check() -> Dict[str, Any]:
    """
    Comprehensive health check for all system components.
    
    Returns detailed status of:
    - Daytona sandbox service
    - Redis cache and pub/sub
    - LLM service providers
    - Database connectivity
    - Circuit breakers state
    """
    health_status = {
        "overall": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "components": {},
        "metrics": {}
    }
    
    # Check Daytona service (with timeout to prevent blocking)
    try:
        daytona_checker = get_daytona_health_checker()
        daytona_report = await asyncio.wait_for(
            daytona_checker.check_health(detailed=True),
            timeout=2.0  # Short timeout to prevent blocking
        )
        
        health_status["components"]["daytona"] = {
            "status": daytona_report.status.value,
            "response_time_ms": daytona_report.response_time_ms,
            "is_healthy": daytona_report.is_healthy(),
            "error": daytona_report.error_message,
            "consecutive_failures": daytona_report.consecutive_failures
        }
        
        # Get Daytona circuit breaker status
        daytona_cb = get_daytona_circuit_breaker()
        health_status["components"]["daytona"]["circuit_breaker"] = daytona_cb.get_metrics()
        
        if not daytona_report.is_healthy():
            health_status["overall"] = "degraded"
    
    except asyncio.TimeoutError:
        logger.warning("Daytona health check timed out")
        health_status["components"]["daytona"] = {
            "status": "timeout",
            "error": "Health check timed out"
        }
        # Don't mark overall as unhealthy for Daytona timeout
    except Exception as e:
        logger.error(f"Failed to check Daytona health: {e}")
        health_status["components"]["daytona"] = {
            "status": "error",
            "error": str(e)
        }
        health_status["overall"] = "unhealthy"
    
    # Check Redis
    try:
        # Ping Redis to check connectivity
        redis_healthy = False
        try:
            await redis_service.get_client()
            await redis_service.client.ping()
            redis_healthy = True
        except:
            redis_healthy = False
        
        redis_cb = get_redis_circuit_breaker()
        redis_cb_status = await redis_cb.get_health_status()
        
        health_status["components"]["redis"] = {
            "status": "healthy" if redis_healthy else "unhealthy",
            "circuit_breaker": redis_cb_status
        }
        
        if not redis_healthy:
            health_status["overall"] = "degraded"
            
    except Exception as e:
        logger.error(f"Failed to check Redis health: {e}")
        health_status["components"]["redis"] = {
            "status": "error",
            "error": str(e)
        }
        health_status["overall"] = "unhealthy"
    
    # Check LLM service
    try:
        llm_manager = get_llm_retry_manager()
        llm_metrics = await llm_manager.get_metrics()
        
        health_status["components"]["llm"] = {
            "status": "healthy",
            "metrics": llm_metrics
        }
        
    except Exception as e:
        logger.error(f"Failed to check LLM health: {e}")
        health_status["components"]["llm"] = {
            "status": "error",
            "error": str(e)
        }
    
    # Check Database
    try:
        db = DBConnection()
        # Simple query to check connectivity
        client = await db.client
        result = await asyncio.wait_for(
            client.table('agents').select('id').limit(1).execute(),
            timeout=5.0
        )
        
        health_status["components"]["database"] = {
            "status": "healthy",
            "connected": True
        }
        
    except Exception as e:
        logger.error(f"Failed to check database health: {e}")
        health_status["components"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["overall"] = "unhealthy"
    
    # Set appropriate HTTP status code
    if health_status["overall"] == "unhealthy":
        raise HTTPException(status_code=503, detail=health_status)
    elif health_status["overall"] == "degraded":
        # Return 200 but indicate degraded status
        health_status["warning"] = "Some services are degraded but system is operational"
    
    return health_status


@router.get("/daytona")
async def daytona_health() -> Dict[str, Any]:
    """Check Daytona sandbox service health."""
    try:
        checker = get_daytona_health_checker()
        # Use a short timeout to prevent blocking
        report = await asyncio.wait_for(
            checker.check_health(force_refresh=True, detailed=True),
            timeout=3.0
        )
        
        circuit_breaker = get_daytona_circuit_breaker()
        cb_metrics = circuit_breaker.get_metrics()
        
        return {
            "status": report.status.value,
            "healthy": report.is_healthy(),
            "response_time_ms": report.response_time_ms,
            "api_version": report.api_version,
            "error": report.error_message,
            "consecutive_failures": report.consecutive_failures,
            "circuit_breaker": cb_metrics,
            "metrics": checker.get_metrics()
        }
    except Exception as e:
        logger.error(f"Daytona health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "status": "error",
                "error": str(e)
            }
        )


@router.get("/redis")
async def redis_health() -> Dict[str, Any]:
    """Check Redis service health."""
    try:
        # Ping Redis to check connectivity
        is_healthy = False
        try:
            await redis_service.get_client()
            await redis_service.client.ping()
            is_healthy = True
        except:
            is_healthy = False
        
        circuit_breaker = get_redis_circuit_breaker()
        cb_status = await circuit_breaker.get_health_status()
        
        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "connected": is_healthy,
            "circuit_breaker": cb_status
        }
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "status": "error",
                "error": str(e)
            }
        )


@router.get("/llm")
async def llm_health() -> Dict[str, Any]:
    """Check LLM service health and metrics."""
    try:
        retry_manager = get_llm_retry_manager()
        metrics = await retry_manager.get_metrics()
        
        # Determine health based on metrics
        status = "healthy"
        if metrics["total_requests"] > 0:
            avg_cost = metrics["average_cost_per_request"]
            if avg_cost > 1.0:  # More than $1 per request average
                status = "expensive"
            
            # Check model health
            for model_name, model_metrics in metrics["models"].items():
                if model_metrics["success_rate"] < 50:
                    status = "degraded"
                    break
        
        return {
            "status": status,
            "metrics": metrics
        }
    except Exception as e:
        logger.error(f"LLM health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "status": "error",
                "error": str(e)
            }
        )


@router.post("/reset-circuit-breakers")
async def reset_circuit_breakers() -> Dict[str, str]:
    """Manually reset all circuit breakers."""
    try:
        # Reset Daytona circuit breaker
        daytona_cb = get_daytona_circuit_breaker()
        await daytona_cb.reset()
        
        # Reset Redis circuit breaker
        redis_cb = get_redis_circuit_breaker()
        await redis_cb.reset()
        
        # Reset LLM retry manager metrics
        llm_manager = get_llm_retry_manager()
        await llm_manager.reset_metrics()
        
        return {
            "status": "success",
            "message": "All circuit breakers have been reset"
        }
    except Exception as e:
        logger.error(f"Failed to reset circuit breakers: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": str(e)
            }
        )