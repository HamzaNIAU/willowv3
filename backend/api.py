from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, HTTPException, Response, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from services import redis
import sentry
from contextlib import asynccontextmanager
from agentpress.thread_manager import ThreadManager
from services.supabase import DBConnection
from datetime import datetime, timezone
from utils.config import config, EnvMode
import asyncio
from utils.logger import logger, structlog
import time
from collections import OrderedDict

from pydantic import BaseModel
import uuid

from agent import api as agent_api

from sandbox import api as sandbox_api
from services import billing as billing_api
from flags import api as feature_flags_api
from services import transcription as transcription_api
import sys
from services import email_api
from triggers import api as triggers_api
from services import api_keys_api
from api_health import router as health_router


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Initialize managers
db = DBConnection()
instance_id = "single"

# Rate limiter state
ip_tracker = OrderedDict()
MAX_CONCURRENT_IPS = 25

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting up FastAPI application with instance ID: {instance_id} in {config.ENV_MODE.value} mode")
    try:
        await db.initialize()
        
        agent_api.initialize(
            db,
            instance_id
        )
        
        
        sandbox_api.initialize(db)
        
        # Initialize Redis connection
        from services import redis
        try:
            await redis.initialize_async()
            logger.info("Redis connection initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Redis connection: {e}")
            # Continue without Redis - the application will handle Redis failures gracefully
        
        # Start background tasks
        # asyncio.create_task(agent_api.restore_running_agent_runs())
        
        triggers_api.initialize(db)
        pipedream_api.initialize(db)
        credentials_api.initialize(db)
        template_api.initialize(db)
        composio_api.initialize(db)
        
        yield
        
        # Clean up agent resources
        logger.info("Cleaning up agent resources")
        await agent_api.cleanup()
        
        # Clean up Redis connection
        try:
            logger.info("Closing Redis connection")
            await redis.close()
            logger.info("Redis connection closed successfully")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")
        
        # Clean up database connection
        logger.info("Disconnecting from database")
        await db.disconnect()
    except Exception as e:
        logger.error(f"Error during application startup: {e}")
        raise

app = FastAPI(lifespan=lifespan)

@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    structlog.contextvars.clear_contextvars()

    request_id = str(uuid.uuid4())
    start_time = time.time()
    client_ip = request.client.host if request.client else "unknown"
    method = request.method
    path = request.url.path
    query_params = str(request.query_params)

    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        client_ip=client_ip,
        method=method,
        path=path,
        query_params=query_params
    )

    # Log the incoming request
    logger.info(f"Request started: {method} {path} from {client_ip} | Query: {query_params}")
    
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        logger.debug(f"Request completed: {method} {path} | Status: {response.status_code} | Time: {process_time:.2f}s")
        return response
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(f"Request failed: {method} {path} | Error: {str(e)} | Time: {process_time:.2f}s")
        raise

# Define allowed origins based on environment
allowed_origins = ["https://www.suna.so", "https://suna.so"]
allow_origin_regex = None

# Add staging-specific origins
if config.ENV_MODE == EnvMode.LOCAL:
    allowed_origins.append("http://localhost:3000")

# Add staging-specific origins
if config.ENV_MODE == EnvMode.STAGING:
    allowed_origins.append("https://staging.suna.so")
    allowed_origins.append("http://localhost:3000")
    allow_origin_regex = r"https://suna-.*-prjcts\.vercel\.app"

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Project-Id", "X-MCP-URL", "X-MCP-Type", "X-MCP-Headers", "X-Refresh-Token", "X-API-Key"],
)

# Create a main API router
api_router = APIRouter()

# Include all API routers without individual prefixes
api_router.include_router(agent_api.router)
api_router.include_router(sandbox_api.router)
api_router.include_router(billing_api.router)
api_router.include_router(feature_flags_api.router)
api_router.include_router(api_keys_api.router)

from mcp_module import api as mcp_api
from credentials import api as credentials_api
from templates import api as template_api

api_router.include_router(mcp_api.router)
api_router.include_router(credentials_api.router, prefix="/secure-mcp")
api_router.include_router(template_api.router, prefix="/templates")

api_router.include_router(transcription_api.router)
api_router.include_router(email_api.router)

from knowledge_base import api as knowledge_base_api
api_router.include_router(knowledge_base_api.router)

api_router.include_router(triggers_api.router)

from pipedream import api as pipedream_api
api_router.include_router(pipedream_api.router)

# MFA functionality moved to frontend



from admin import api as admin_api
api_router.include_router(admin_api.router)

from composio_integration import api as composio_api
api_router.include_router(composio_api.router)

# Include comprehensive health check endpoints
api_router.include_router(health_router, prefix="/health")

@api_router.get("/health")
async def health_check():
    logger.info("Health check endpoint called")
    return {
        "status": "ok", 
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "instance_id": instance_id
    }

@api_router.get("/health-docker")
async def health_check():
    logger.info("Health docker check endpoint called")
    try:
        client = await redis.get_client()
        await client.ping()
        db = DBConnection()
        await db.initialize()
        db_client = await db.client
        await db_client.table("threads").select("thread_id").limit(1).execute()
        logger.info("Health docker check complete")
        return {
            "status": "ok", 
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "instance_id": instance_id
        }
    except Exception as e:
        logger.error(f"Failed health docker check: {e}")
        raise HTTPException(status_code=500, detail="Health check failed")


@api_router.get("/health/redis")
async def redis_health():
    """Redis health check with circuit breaker status."""
    logger.info("Redis health check endpoint called")
    try:
        # Get circuit breaker health
        circuit_health = await redis.get_circuit_breaker_health()
        
        # Test basic Redis connection
        redis_client = await redis.get_client()
        await redis_client.ping()
        
        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "instance_id": instance_id,
            "circuit_breaker": circuit_health
        }
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        try:
            circuit_health = await redis.get_circuit_breaker_health()
        except:
            circuit_health = None
        
        return {
            "status": "unhealthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "instance_id": instance_id,
            "error": str(e),
            "circuit_breaker": circuit_health
        }


@api_router.post("/health/redis/reset")
async def reset_redis_circuit_breaker():
    """Reset Redis circuit breaker."""
    logger.info("Redis circuit breaker reset endpoint called")
    try:
        await redis.reset_circuit_breaker()
        return {
            "status": "success",
            "message": "Circuit breaker reset successfully",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "instance_id": instance_id
        }
    except Exception as e:
        logger.error(f"Failed to reset Redis circuit breaker: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/health/redis/auto-tune")
async def auto_tune_redis_circuit_breaker():
    """Trigger auto-tuning of Redis circuit breaker."""
    logger.info("Redis circuit breaker auto-tune endpoint called")
    try:
        await redis.auto_tune_circuit_breaker()
        health = await redis.get_circuit_breaker_health()
        return {
            "status": "success",
            "message": "Circuit breaker auto-tuning completed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "instance_id": instance_id,
            "health": health
        }
    except Exception as e:
        logger.error(f"Failed to auto-tune Redis circuit breaker: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/health/llm")
async def llm_health():
    """LLM service health check with retry manager metrics."""
    logger.info("LLM health check endpoint called")
    try:
        from services.llm_retry_manager import get_retry_manager
        
        # Get retry manager metrics
        retry_manager = get_retry_manager()
        metrics = await retry_manager.get_metrics()
        
        # Test a simple LLM call
        from services.llm import make_llm_api_call
        test_response = await make_llm_api_call(
            messages=[{"role": "user", "content": "Hello"}],
            model_name="openai/gpt-3.5-turbo",
            max_tokens=5,
            use_smart_retry=False  # Don't use retry for health check
        )
        
        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "instance_id": instance_id,
            "test_call": "success",
            "retry_manager": metrics
        }
    except Exception as e:
        logger.error(f"LLM health check failed: {e}")
        try:
            from services.llm_retry_manager import get_retry_manager
            retry_manager = get_retry_manager()
            metrics = await retry_manager.get_metrics()
        except:
            metrics = None
        
        return {
            "status": "unhealthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "instance_id": instance_id,
            "error": str(e),
            "retry_manager": metrics
        }


@api_router.post("/health/llm/reset")
async def reset_llm_retry_manager():
    """Reset LLM retry manager metrics."""
    logger.info("LLM retry manager reset endpoint called")
    try:
        from services.llm_retry_manager import get_retry_manager
        
        retry_manager = get_retry_manager()
        await retry_manager.reset_metrics()
        
        return {
            "status": "success",
            "message": "LLM retry manager metrics reset successfully",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "instance_id": instance_id
        }
    except Exception as e:
        logger.error(f"Failed to reset LLM retry manager: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/health/llm/metrics")
async def get_llm_metrics():
    """Get detailed LLM retry manager metrics."""
    logger.info("LLM metrics endpoint called")
    try:
        from services.llm_retry_manager import get_retry_manager
        
        retry_manager = get_retry_manager()
        metrics = await retry_manager.get_metrics()
        
        return {
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "instance_id": instance_id,
            "metrics": metrics
        }
    except Exception as e:
        logger.error(f"Failed to get LLM metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


app.include_router(api_router, prefix="/api")


if __name__ == "__main__":
    import uvicorn
    
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    workers = 4
    
    logger.info(f"Starting server on 0.0.0.0:8000 with {workers} workers")
    uvicorn.run(
        "api:app", 
        host="0.0.0.0", 
        port=8000,
        workers=workers,
        loop="asyncio"
    )