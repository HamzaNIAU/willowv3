# KORTIX COMPLETE SYSTEM ARCHITECTURE
## Comprehensive Technical Documentation

Generated: 2025-08-16 | Lines of Code Analyzed: 6,924

---

## 1. SYSTEM OVERVIEW

Kortix (formerly Suna) is a distributed AI agent orchestration platform that enables users to create, manage, and execute AI agents with custom tools and integrations. The system consists of:

- **Backend**: Python/FastAPI service with Dramatiq workers for asynchronous agent execution
- **Frontend**: Next.js/React dashboard for user interaction
- **Database**: Supabase for persistent storage and real-time subscriptions
- **Cache**: Redis for state management, pub/sub messaging, and response caching
- **Sandbox**: Daytona SDK for isolated tool execution environments
- **LLM**: LiteLLM for unified access to multiple language model providers

---

## 2. REQUEST FLOW ARCHITECTURE

### 2.1 Complete Agent Execution Flow

```
User Message → Frontend → Backend API → Redis Queue → Dramatiq Worker → Agent Runner → LLM → Tool Execution → Response
```

#### Detailed Step-by-Step Flow:

1. **User Message Submission** (Frontend)
   - User sends message via chat interface
   - Frontend makes POST to `/api/thread/{thread_id}/agent/start`

2. **API Request Processing** (`api.py:307-537`)
   - Validates JWT authentication
   - Checks billing status and rate limits
   - Loads agent configuration from database
   - Creates agent run record in `agent_runs` table
   - Enqueues job to Dramatiq via Redis

3. **Background Worker Processing** (`run_agent_background.py:56-414`)
   - Dramatiq worker picks up job from Redis queue
   - Acquires distributed lock via Redis to prevent duplicates
   - Creates Redis pub/sub channels for control signals
   - Initializes agent runner with configuration

4. **Agent Initialization** (`agent/run.py:385-463`)
   - Sets up ThreadManager for conversation state
   - Registers all enabled tools
   - Initializes MCP (Model Context Protocol) tools if configured
   - Builds system prompt with agent instructions

5. **Main Execution Loop** (`agent/run.py:464-649`)
   - Checks billing status before each iteration
   - Builds message history from database
   - Makes LLM API call via ThreadManager
   - Processes streaming response
   - Executes tool calls as they arrive
   - Stores responses in Redis for streaming

6. **LLM Processing** (`agentpress/thread_manager.py:334-633`)
   - Constructs messages array with system + user + assistant history
   - Calls LLM service with retry logic
   - Handles both native and XML tool calling formats
   - Manages conversation context and state

7. **Tool Execution** (`agentpress/response_processor.py:1200-1400`)
   - Parses tool calls from LLM response
   - Validates tool availability and parameters
   - Executes tools (potentially in parallel)
   - For sandbox tools: ensures Daytona sandbox exists
   - Returns tool results to LLM for processing

8. **Response Streaming** (`agent/api.py:750-850`)
   - Client polls Redis for new responses via SSE
   - Responses streamed as they arrive from agent
   - Final status update when execution completes

---

## 3. CORE COMPONENTS

### 3.1 API Layer (`api.py`)
**Purpose**: Main FastAPI application entry point
**Key Responsibilities**:
- HTTP request routing and middleware
- CORS configuration for frontend access
- Database connection lifecycle management
- Redis connection pooling
- Request/response logging with correlation IDs

**Critical Functions**:
- `lifespan()`: Manages application startup/shutdown
- `log_requests_middleware()`: Structured logging for all requests

### 3.2 Agent API (`agent/api.py`)
**Purpose**: Agent-specific endpoints and orchestration
**Lines**: 2000+
**Key Endpoints**:
- `POST /thread/{thread_id}/agent/start`: Initiate agent execution
- `GET /agent-run/{agent_run_id}/stream`: Stream agent responses
- `POST /agents`: Create custom agents
- `GET /agents`: List available agents

**Agent Configuration Structure**:
```python
{
    "agent_id": str,
    "name": str,
    "system_prompt": str,
    "model": str,
    "configured_mcps": List[Dict],  # MCP server configurations
    "custom_mcps": List[Dict],      # Custom MCP integrations
    "agentpress_tools": Dict,       # Enabled sandbox tools
    "current_version_id": str       # Version tracking
}
```

### 3.3 Background Worker (`run_agent_background.py`)
**Purpose**: Asynchronous agent execution via Dramatiq
**Key Features**:
- Idempotency via Redis locks
- Graceful shutdown handling
- Real-time status updates
- Error recovery and retry logic

**Execution Phases**:
1. **Lock Acquisition** (lines 86-102): Prevents duplicate execution
2. **Redis Pub/Sub Setup** (lines 177-186): Control channel subscription
3. **Agent Execution** (lines 193-201): Runs agent generator
4. **Response Collection** (lines 209-240): Streams responses to Redis
5. **Cleanup** (lines 294-325): Releases locks, closes connections

### 3.4 Agent Runner (`agent/run.py`)
**Purpose**: Core agent orchestration logic
**Components**:
- `AgentConfig`: Configuration dataclass
- `ToolManager`: Tool registration and management
- `MCPManager`: MCP server integration
- `PromptManager`: System prompt construction
- `MessageManager`: Message history handling
- `AgentRunner`: Main execution orchestrator

**Execution Loop** (lines 494-649):
```python
while continue_execution and iteration_count < max_iterations:
    # 1. Check billing status
    # 2. Build temporary messages (browser state, images)
    # 3. Call LLM via ThreadManager
    # 4. Process streaming response
    # 5. Execute tools as needed
    # 6. Check for termination signals
```

---

## 4. AGENTPRESS FRAMEWORK

### 4.1 Thread Manager (`agentpress/thread_manager.py`)
**Purpose**: Manages conversation threads and tool orchestration
**Key Methods**:
- `run_thread()`: Main entry point for thread execution
- `add_tool()`: Registers tools with the thread
- `_get_messages()`: Retrieves conversation history
- `_stream_response()`: Handles LLM streaming

**Message Processing Pipeline**:
1. Load messages from database
2. Apply message transformations
3. Add temporary messages (browser state)
4. Include tool definitions
5. Make LLM call
6. Process response with ResponseProcessor

### 4.2 Response Processor (`agentpress/response_processor.py`)
**Purpose**: Processes LLM responses and executes tools
**Lines**: 1684
**Critical Function**: `execute_tool()` at line 1246

**Tool Execution Flow**:
```python
async def execute_tool(tool_name, arguments):
    # 1. Validate tool exists
    # 2. Check parameter types
    # 3. Execute tool function
    # 4. Handle success/failure
    # 5. Return formatted result
```

**Parallel Execution Support**:
- Detects multiple tool calls
- Executes in parallel when safe
- Aggregates results for LLM

### 4.3 Tool System (`agentpress/tool.py`)
**Purpose**: Base infrastructure for all tools
**Components**:
- `Tool`: Abstract base class
- `ToolSchema`: Schema container
- `ToolResult`: Standardized results
- Decorators: `@openapi_schema`, `@usage_example`

### 4.4 Tool Registry (`agentpress/tool_registry.py`)
**Purpose**: Central registry for tool management
**Features**:
- Dynamic tool registration
- Schema validation
- Function discovery
- OpenAPI spec generation

---

## 5. SANDBOX SYSTEM

### 5.1 Sandbox Manager (`sandbox/sandbox.py`)
**Purpose**: Daytona SDK integration for isolated execution
**Key Functions**:
- `create_sandbox()`: Creates new Daytona instance
- `get_or_start_sandbox()`: Retrieves or starts existing
- `delete_sandbox()`: Cleanup sandbox resources

**Configuration** (lines 97-121):
```python
CreateSandboxFromSnapshotParams(
    snapshot=SANDBOX_SNAPSHOT_NAME,
    resources=Resources(cpu=4, memory=8, disk=10),
    auto_stop_interval=15,
    auto_archive_interval=120
)
```

### 5.2 Sandbox Tool Base (`sandbox/tool_base.py`)
**Purpose**: Base class for sandbox-requiring tools
**Key Method**: `_ensure_sandbox()` (lines 26-105)

**Lazy Sandbox Creation**:
1. Check if project has sandbox metadata
2. If not, create sandbox on first tool use
3. Store sandbox info in project record
4. Reuse sandbox for subsequent calls

### 5.3 Shell Tool (`agent/tools/sb_shell_tool.py`)
**Purpose**: Execute shell commands in sandbox
**Features**:
- tmux session management
- Blocking/non-blocking execution
- Output streaming
- Session persistence

---

## 6. SERVICES LAYER

### 6.1 Database Service (`services/supabase.py`)
**Purpose**: Centralized Supabase connection management
**Pattern**: Thread-safe singleton
**Features**:
- Automatic reconnection
- Service role key support
- Connection pooling

### 6.2 Redis Service (`services/redis.py`)
**Purpose**: Redis connection and operations
**Configuration**:
- Max connections: 128
- Socket timeout: 15 seconds
- Health check interval: 30 seconds
- Key TTL: 24 hours

**Key Operations**:
```python
# Agent run locks
f"agent_run_lock:{agent_run_id}"

# Response storage
f"agent_run:{agent_run_id}:responses"

# Control channels
f"agent_run:{agent_run_id}:control"

# Active runs
f"active_run:{instance_id}:{agent_run_id}"
```

### 6.3 LLM Service (`services/llm.py`)
**Purpose**: Unified LLM provider interface via LiteLLM
**Supported Providers**:
- Anthropic (Claude)
- OpenAI (GPT)
- Google (Gemini)
- xAI (Grok)
- AWS Bedrock
- OpenRouter (fallback)

**Key Features**:
- Retry logic with exponential backoff
- Provider-specific parameter handling
- Streaming support
- Tool calling normalization
- Anthropic prompt caching

---

## 7. MCP (MODEL CONTEXT PROTOCOL) INTEGRATION

### 7.1 MCP Tool Wrapper (`agent/tools/mcp_tool_wrapper.py`)
**Purpose**: Dynamic tool generation from MCP servers
**Features**:
- Redis caching of MCP schemas (1 hour TTL)
- Parallel server initialization
- Custom MCP handler support
- Dynamic method generation

**Initialization Flow** (lines 134-210):
1. Check Redis cache for schemas
2. Initialize uncached servers in parallel
3. Create dynamic tool methods
4. Register with tool registry
5. Cache successful schemas

### 7.2 MCP Connection Types:
1. **Standard MCP**: External MCP servers
2. **Custom MCP**: User-defined integrations
   - Pipedream workflows
   - Composio actions
   - SSE endpoints

---

## 8. TOOL EXECUTION FLOW

### 8.1 Tool Discovery
```
1. Agent configuration specifies enabled tools
2. ToolManager registers tools based on config
3. Tools added to ThreadManager registry
4. OpenAPI schemas sent to LLM
```

### 8.2 Tool Invocation
```
1. LLM generates tool call in response
2. ResponseProcessor parses tool call
3. Validates tool exists and parameters
4. Executes tool function (line 1246)
5. Returns result to LLM
```

### 8.3 Sandbox Tool Execution
```
1. Tool inherits from SandboxToolsBase
2. Calls _ensure_sandbox() before execution
3. Creates sandbox if not exists
4. Executes command in sandbox
5. Returns formatted result
```

---

## 9. ERROR HANDLING AND RECOVERY

### 9.1 Retry Mechanisms
- **LLM Calls**: 2 retries with exponential backoff
- **Database Operations**: 3 retries with delay
- **Redis Operations**: Retry wrapper with timeout
- **Sandbox Creation**: 60 second timeout

### 9.2 Failure Points and Recovery

#### Dramatiq Worker Failure:
- Redis lock prevents duplicate execution
- Status updated to "failed" in database
- Error message stored for debugging

#### Sandbox Unavailable:
- Tools return None when sandbox times out
- Agent continues without sandbox tools
- Error logged but execution continues

#### LLM Rate Limiting:
- 30 second delay before retry
- Falls back to OpenRouter if available
- Returns error after max retries

### 9.3 Cleanup Operations
```python
# Run lock cleanup
await redis.delete(f"agent_run_lock:{agent_run_id}")

# Response list TTL
await redis.expire(response_list_key, 86400)

# Instance key removal
await redis.delete(f"active_run:{instance_id}:{agent_run_id}")
```

---

## 10. PERFORMANCE OPTIMIZATIONS

### 10.1 Redis Caching
- MCP schemas cached for 1 hour
- Feature flags cached indefinitely
- Response lists expire after 24 hours

### 10.2 Parallel Execution
- Tool calls executed in parallel when safe
- MCP servers initialized concurrently
- Database checks batched together

### 10.3 Connection Pooling
- Redis: 128 max connections
- Database: Supabase client pooling
- Keep-alive enabled for persistent connections

---

## 11. CRITICAL ISSUES AND SOLUTIONS

### 11.1 Tool Hanging Issue
**Problem**: Tools hang when Daytona service unavailable
**Solution**: Added timeouts to sandbox operations (10s get, 60s create)

### 11.2 Zombie Worker Processes
**Problem**: Old Dramatiq workers blocking queue
**Solution**: Kill zombies with `pkill -f "dramatiq.*run_agent_background"`

### 11.3 Missing Feature Flags
**Problem**: Redis FLUSHDB deletes feature flags
**Solution**: Restore script in `/tmp/restore_flags.py`

### 11.4 Stuck Agent Runs
**Problem**: Runs marked as "running" but not processing
**Solution**: Clear Redis locks and update database status

---

## 12. MONITORING AND DEBUGGING

### 12.1 Key Log Locations
```python
# Agent run start
logger.info(f"[AGENT RUN] Starting agent run for thread {thread_id}")

# Tool execution
logger.debug(f"Executing tool: {tool_name} with args: {arguments}")

# Sandbox creation
logger.info(f"Creating sandbox for project {project_id}")

# Worker processing
logger.info(f"Starting background agent run: {agent_run_id}")
```

### 12.2 Redis Keys for Debugging
```bash
# Check active runs
redis-cli keys "active_run:*"

# Check locks
redis-cli keys "agent_run_lock:*"

# View responses
redis-cli lrange "agent_run:{id}:responses" 0 -1
```

### 12.3 Database Queries
```sql
-- Check stuck runs
SELECT * FROM agent_runs 
WHERE status = 'running' 
AND started_at < NOW() - INTERVAL '1 hour';

-- Check agent configurations
SELECT * FROM agents 
WHERE account_id = '{user_id}' 
AND is_default = true;
```

---

## 13. CONFIGURATION

### 13.1 Environment Variables
```bash
# Core Services
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
REDIS_HOST=
REDIS_PORT=

# Daytona Sandbox
DAYTONA_API_KEY=
DAYTONA_SERVER_URL=
DAYTONA_TARGET=

# LLM Providers
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
OPENROUTER_API_KEY=

# Monitoring
LANGFUSE_PUBLIC_KEY=
SENTRY_DSN=
```

### 13.2 Key Configuration Values
- Max parallel agent runs: 3 (production)
- Redis TTL: 24 hours
- Sandbox auto-stop: 15 minutes
- Sandbox auto-archive: 2 hours
- Worker processes: 4
- Worker threads: 4

---

## 14. SYSTEM BOUNDARIES

### 14.1 Rate Limits
- Parallel agent runs: Configurable (default 3)
- API requests: Based on subscription tier
- LLM tokens: Provider-specific limits

### 14.2 Resource Limits
- Sandbox CPU: 4 cores
- Sandbox Memory: 8 GB
- Sandbox Disk: 10 GB
- Redis connections: 128 max

### 14.3 Timeout Values
- LLM response: 120 seconds
- Sandbox creation: 60 seconds
- Sandbox get: 10 seconds
- Redis operations: 5 seconds

---

## 15. SECURITY CONSIDERATIONS

### 15.1 Authentication
- JWT tokens for API access
- Service role keys for backend operations
- API key authentication for external access

### 15.2 Isolation
- Sandboxed execution via Daytona
- Row-level security in Supabase
- Encrypted credentials at rest

### 15.3 Rate Limiting
- Per-account agent run limits
- Billing-based tier restrictions
- Model access control

---

## APPENDIX A: FILE STRUCTURE

```
backend/
├── api.py                    # Main FastAPI app (242 lines)
├── run_agent_background.py   # Dramatiq worker (415 lines)
├── agent/
│   ├── api.py               # Agent endpoints (2000+ lines)
│   ├── run.py               # Agent runner (695 lines)
│   └── tools/               # Tool implementations
├── agentpress/
│   ├── thread_manager.py    # Thread management (634 lines)
│   ├── response_processor.py # Response processing (1684 lines)
│   ├── tool.py              # Tool base (142 lines)
│   └── tool_registry.py    # Registry (130 lines)
├── sandbox/
│   ├── sandbox.py           # Daytona integration (153 lines)
│   └── tool_base.py         # Sandbox base (125 lines)
└── services/
    ├── supabase.py          # Database (91 lines)
    ├── redis.py             # Cache (180 lines)
    └── llm.py               # LLM service (367 lines)
```

---

## APPENDIX B: COMMON COMMANDS

```bash
# Start backend
uv run uvicorn api:app --reload --port 8000

# Start workers
uv run dramatiq --processes 4 --threads 4 run_agent_background

# Monitor Redis
redis-cli monitor

# Check Dramatiq workers
ps aux | grep -E "dramatiq.*run_agent" | grep -v grep

# Clear stuck runs
redis-cli del "agent_run_lock:*"

# View logs
tail -f logs/api.log
```

---

END OF DOCUMENT
Total Lines Analyzed: 6,924
Generated: 2025-08-16