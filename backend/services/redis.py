import redis.asyncio as redis
import os
from dotenv import load_dotenv
import asyncio
from utils.logger import logger
from typing import List, Any
from utils.retry import retry
from services.redis_circuit_breaker import (
    get_circuit_breaker, initialize_circuit_breaker, execute_with_circuit_breaker,
    OperationType, CircuitConfig
)

# Redis client and connection pool
client: redis.Redis | None = None
pool: redis.ConnectionPool | None = None
_initialized = False
_init_lock = asyncio.Lock()

# Constants
REDIS_KEY_TTL = 3600 * 24  # 24 hour TTL as safety mechanism


def initialize():
    """Initialize Redis connection pool and client using environment variables."""
    global client, pool

    # Load environment variables if not already loaded
    load_dotenv()

    # Get Redis configuration
    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = int(os.getenv("REDIS_PORT", 6379))
    redis_password = os.getenv("REDIS_PASSWORD", "")
    
    # Connection pool configuration - optimized for production
    max_connections = 128            # Reasonable limit for production
    socket_timeout = 15.0            # 15 seconds socket timeout
    connect_timeout = 10.0           # 10 seconds connection timeout
    retry_on_timeout = not (os.getenv("REDIS_RETRY_ON_TIMEOUT", "True").lower() != "true")

    logger.info(f"Initializing Redis connection pool to {redis_host}:{redis_port} with max {max_connections} connections")

    # Create connection pool with production-optimized settings
    pool = redis.ConnectionPool(
        host=redis_host,
        port=redis_port,
        password=redis_password,
        decode_responses=True,
        socket_timeout=socket_timeout,
        socket_connect_timeout=connect_timeout,
        socket_keepalive=True,
        retry_on_timeout=retry_on_timeout,
        health_check_interval=30,
        max_connections=max_connections,
    )

    # Create Redis client from connection pool
    client = redis.Redis(connection_pool=pool)

    return client


async def initialize_async():
    """Initialize Redis connection asynchronously."""
    global client, _initialized

    async with _init_lock:
        if not _initialized:
            logger.info("Initializing Redis connection")
            initialize()
            
            # Initialize circuit breaker
            circuit_config = CircuitConfig(
                read_failure_threshold=int(os.getenv("REDIS_READ_FAILURE_THRESHOLD", "5")),
                write_failure_threshold=int(os.getenv("REDIS_WRITE_FAILURE_THRESHOLD", "3")),
                pubsub_failure_threshold=int(os.getenv("REDIS_PUBSUB_FAILURE_THRESHOLD", "2")),
                recovery_timeout=float(os.getenv("REDIS_RECOVERY_TIMEOUT", "30.0")),
                fallback_cache_size=int(os.getenv("REDIS_FALLBACK_CACHE_SIZE", "1000")),
                auto_tune_enabled=os.getenv("REDIS_AUTO_TUNE", "true").lower() == "true"
            )
            initialize_circuit_breaker(circuit_config)

        try:
            # Test connection with timeout via circuit breaker
            await execute_with_circuit_breaker(
                lambda: asyncio.wait_for(client.ping(), timeout=5.0),
                OperationType.READ
            )
            logger.info("Successfully connected to Redis with circuit breaker")
            _initialized = True
        except asyncio.TimeoutError:
            logger.error("Redis connection timeout during initialization")
            client = None
            _initialized = False
            raise ConnectionError("Redis connection timeout")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            client = None
            _initialized = False
            raise

    return client


async def close():
    """Close Redis connection and connection pool."""
    global client, pool, _initialized
    if client:
        logger.info("Closing Redis connection")
        try:
            await asyncio.wait_for(client.aclose(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Redis close timeout, forcing close")
        except Exception as e:
            logger.warning(f"Error closing Redis client: {e}")
        finally:
            client = None
    
    if pool:
        logger.info("Closing Redis connection pool")
        try:
            await asyncio.wait_for(pool.aclose(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Redis pool close timeout, forcing close")
        except Exception as e:
            logger.warning(f"Error closing Redis pool: {e}")
        finally:
            pool = None
    
    _initialized = False
    logger.info("Redis connection and pool closed")


async def get_client():
    """Get the Redis client, initializing if necessary."""
    global client, _initialized
    if client is None or not _initialized:
        await retry(lambda: initialize_async())
    return client


# Basic Redis operations
async def set(key: str, value: str, ex: int = None, nx: bool = False):
    """Set a Redis key with circuit breaker protection."""
    redis_client = await get_client()
    return await execute_with_circuit_breaker(
        lambda: redis_client.set(key, value, ex=ex, nx=nx),
        OperationType.WRITE
    )


async def get(key: str, default: str = None):
    """Get a Redis key with circuit breaker protection and fallback caching."""
    redis_client = await get_client()
    
    try:
        result = await execute_with_circuit_breaker(
            lambda: redis_client.get(key),
            OperationType.READ,
            cache_key=f"get:{key}",
            cache_ttl=300
        )
        return result if result is not None else default
    except Exception as e:
        logger.warning(f"Redis GET failed for key {key}: {e}")
        return default


async def delete(key: str):
    """Delete a Redis key with circuit breaker protection."""
    redis_client = await get_client()
    return await execute_with_circuit_breaker(
        lambda: redis_client.delete(key),
        OperationType.WRITE
    )


async def publish(channel: str, message: str):
    """Publish a message to a Redis channel with circuit breaker protection."""
    redis_client = await get_client()
    return await execute_with_circuit_breaker(
        lambda: redis_client.publish(channel, message),
        OperationType.PUBSUB
    )


async def create_pubsub():
    """Create a Redis pubsub object."""
    redis_client = await get_client()
    return redis_client.pubsub()


# List operations
async def rpush(key: str, *values: Any):
    """Append one or more values to a list with circuit breaker protection."""
    redis_client = await get_client()
    return await execute_with_circuit_breaker(
        lambda: redis_client.rpush(key, *values),
        OperationType.WRITE
    )


async def lrange(key: str, start: int, end: int) -> List[str]:
    """Get a range of elements from a list with circuit breaker protection."""
    redis_client = await get_client()
    return await execute_with_circuit_breaker(
        lambda: redis_client.lrange(key, start, end),
        OperationType.READ,
        cache_key=f"lrange:{key}:{start}:{end}",
        cache_ttl=60  # Shorter TTL for lists as they change more frequently
    )


# Key management
async def keys(pattern: str) -> List[str]:
    """Get keys matching pattern with circuit breaker protection."""
    redis_client = await get_client()
    return await execute_with_circuit_breaker(
        lambda: redis_client.keys(pattern),
        OperationType.READ,
        cache_key=f"keys:{pattern}",
        cache_ttl=30  # Short TTL for key listings
    )


async def expire(key: str, seconds: int):
    """Set expiration on a key with circuit breaker protection."""
    redis_client = await get_client()
    return await execute_with_circuit_breaker(
        lambda: redis_client.expire(key, seconds),
        OperationType.WRITE
    )


# Circuit breaker health and monitoring
async def get_circuit_breaker_health():
    """Get circuit breaker health status."""
    circuit_breaker = get_circuit_breaker()
    return await circuit_breaker.get_health_status()


async def reset_circuit_breaker():
    """Reset circuit breaker to initial state."""
    circuit_breaker = get_circuit_breaker()
    await circuit_breaker.reset()
    logger.info("Redis circuit breaker reset")


async def auto_tune_circuit_breaker():
    """Trigger auto-tuning of circuit breaker thresholds."""
    circuit_breaker = get_circuit_breaker()
    await circuit_breaker.auto_tune_thresholds()
    logger.info("Redis circuit breaker auto-tuning completed")
