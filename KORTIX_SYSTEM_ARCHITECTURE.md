# Kortix System Architecture - Complete Analysis & Tool Hanging Investigation

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture Components](#architecture-components)
3. [Complete Execution Flow](#complete-execution-flow)
4. [Tool Hanging Root Cause](#tool-hanging-root-cause)
5. [Critical Code Paths](#critical-code-paths)
6. [System Dependencies](#system-dependencies)
7. [Concurrency Model](#concurrency-model)
8. [Solution Implementation](#solution-implementation)

---

## System Overview

Kortix is a complex AI agent orchestration platform with the following core architecture:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Frontend  │────▶│   FastAPI   │────▶│    Redis    │
│  (Next.js)  │     │   Backend   │     │    Queue    │
└─────────────┘     └─────────────┘     └─────────────┘
                            │                    │
                            ▼                    ▼
                    ┌─────────────┐     ┌─────────────┐
                    │  Supabase   │     │  Dramatiq   │
                    │  Database   │     │   Workers   │
                    └─────────────┘     └─────────────┘
                                                │
                                                ▼
                                        ┌─────────────┐
                                        │AgentRunner  │
                                        └─────────────┘
                                                │
                                    ┌───────────┴──────────┐
                                    ▼                      ▼
                            ┌─────────────┐       ┌─────────────┐
                            │  LLM APIs   │       │   Daytona   │
                            │  (LiteLLM)  │       │   Sandbox   │
                            └─────────────┘       └─────────────┘
```

## Architecture Components

### 1. Frontend Layer (`/frontend`)
- **Technology**: Next.js 15 with React
- **Key Components**:
  - `/src/app/` - App router pages
  - `/src/components/thread/` - Chat interface
  - `/src/hooks/` - React Query hooks for data fetching
- **Communication**: REST API + Server-Sent Events (SSE) for streaming

### 2. API Layer (`/backend/api.py`)
- **Framework**: FastAPI with async support
- **Key Endpoints**:
  - `/api/agent/initiate` - Start agent execution
  - `/api/thread/{thread_id}/agent/start` - Start agent for thread
  - `/api/thread/{thread_id}/message` - Send message
- **Middleware**:
  - CORS configuration
  - Request logging
  - Error handling
  - JWT authentication (Supabase)

### 3. Queue System
- **Technology**: Redis + Dramatiq
- **Configuration**:
  - 4 worker processes (`--processes 4`)
  - 4 threads per process (`--threads 4`)
  - Redis backend for queue persistence
- **Key Files**:
  - `/backend/run_agent_background.py` - Worker entry point
  - `/backend/services/redis.py` - Redis connection management

### 4. Agent Execution Engine (`/backend/agent/`)
- **Core Class**: `AgentRunner` (`/backend/agent/run.py`)
- **Components**:
  - `ThreadManager` - Manages conversation state
  - `ToolRegistry` - Registers and manages tools
  - `ResponseProcessor` - Processes LLM responses and executes tools
  - `LLMService` - Handles LLM API calls via LiteLLM

### 5. Tool System (`/backend/agent/tools/`)
- **Base Classes**:
  - `Tool` - Base tool class
  - `SandboxToolsBase` - Base for sandbox-requiring tools
- **Tool Categories**:
  - **Sandbox Tools**: `web_search_tool`, `sb_shell_tool`, `sb_files_tool`
  - **Non-Sandbox Tools**: `message_tool`, `expand_message_tool`
  - **MCP Tools**: External integrations via Model Context Protocol

### 6. Sandbox System (`/backend/sandbox/`)
- **Provider**: Daytona SDK
- **Key Files**:
  - `sandbox.py` - Sandbox lifecycle management
  - `tool_base.py` - Base class for sandbox tools
- **Configuration**:
  - API URL: `https://app.daytona.io/api`
  - Timeouts: 10s (get), 30s (start), 60s (create)

## Complete Execution Flow

### Phase 1: Message Initiation
```python
# 1. User sends message via frontend
POST /api/thread/{thread_id}/message

# 2. API creates agent_run record
agent_run = await create_agent_run(thread_id, message)

# 3. Queue task in Redis via Dramatiq
await run_agent_background.send(
    agent_run_id=agent_run.id,
    thread_id=thread_id,
    account_id=user_id
)
```

### Phase 2: Worker Processing
```python
# 4. Dramatiq worker picks up task
@dramatiq.actor(max_retries=1, time_limit=3600000)
async def run_agent_background(agent_run_id, thread_id, account_id):
    
    # 5. Check for duplicate execution (Redis lock)
    if not await agent_api.can_start_agent_run(agent_run_id):
        return
    
    # 6. Initialize AgentRunner
    agent_runner = AgentRunner(config)
    
    # 7. Execute agent
    async for event in agent_runner.run():
        # Stream events back to client
        await publish_event(event)
```

### Phase 3: Agent Initialization
```python
# 8. AgentRunner.run() initialization
async def run(self):
    # Setup phase
    await self.setup()           # Database, auth, project setup
    await self.setup_tools()     # Register AgentPress tools
    await self.setup_mcp_tools() # Register MCP/external tools
    
    # 9. Create ThreadManager
    self.thread_manager = ThreadManager(
        thread_id=self.config.thread_id,
        db=self.db,
        trace=self.trace
    )
```

### Phase 4: Tool Registration
```python
# 10. Register sandbox tools
for tool_name in enabled_tools:
    if tool_name == "web_search_tool":
        tool = SandboxWebSearchTool(
            project_id=self.config.project_id,
            thread_manager=self.thread_manager
        )
        self.thread_manager.register_tool(tool)
```

### Phase 5: LLM Interaction
```python
# 11. Build conversation context
messages = await self.thread_manager.get_messages()

# 12. Call LLM with tool schemas
response = await litellm.acompletion(
    model=self.model,
    messages=messages,
    tools=tool_schemas,
    stream=True
)

# 13. Process streaming response
async for chunk in response:
    await self.response_processor.process_chunk(chunk)
```

### Phase 6: Tool Execution (WHERE IT HANGS!)
```python
# 14. ResponseProcessor detects tool call
if self._is_tool_call(chunk):
    tool_call = self._parse_tool_call(chunk)
    
    # 15. Execute tool - THIS HAS NO TIMEOUT!
    result = await self._execute_tool(tool_call)  # ← HANGS HERE
    
# Critical method without timeout:
async def _execute_tool(self, tool_call: Dict[str, Any]) -> ToolResult:
    tool_name = tool_call['name']
    arguments = tool_call['arguments']
    
    # Get tool from registry
    tool = self.tool_registry.get_tool(tool_name)
    
    # THIS CALL HAS NO TIMEOUT AND CAN HANG FOREVER
    result = await tool_fn(**arguments)  # Line 1246
    
    return result
```

### Phase 7: Sandbox Tool Execution
```python
# 16. SandboxToolsBase._ensure_sandbox() is called
async def _ensure_sandbox(self) -> AsyncSandbox:
    # Check if project has sandbox
    project = await client.table('projects').select('*').eq('project_id', self.project_id).execute()
    sandbox_info = project.data[0].get('sandbox') or {}
    
    if not sandbox_info.get('id'):
        # Create new sandbox - WITH TIMEOUT
        sandbox_obj = await create_sandbox(sandbox_pass, self.project_id)
        
        # Get preview links - NO TIMEOUT!
        vnc_link = await sandbox_obj.get_preview_link(6080)     # ← CAN HANG
        website_link = await sandbox_obj.get_preview_link(8080) # ← CAN HANG
```

## Tool Hanging Root Cause

### 🔴 PRIMARY ISSUE: Missing Timeout in Tool Execution

**Location**: `/backend/agentpress/response_processor.py:1246`
```python
# NO TIMEOUT WRAPPER HERE!
result = await tool_fn(**arguments)  # Can hang indefinitely
```

### 🟡 SECONDARY ISSUES:

1. **Sandbox Preview Links** - No timeout when getting preview URLs
2. **External API Calls** - Some tools don't handle service unavailability
3. **Database Operations** - Large queries without limits
4. **Async Task Coordination** - No cancellation mechanism

### Why Tools Hang:

1. **Worker receives task** ✓ Works
2. **Agent initializes** ✓ Works  
3. **LLM responds with tool call** ✓ Works
4. **Tool execution starts** ✓ Starts
5. **Tool makes external call** ⚠️ May hang
6. **No timeout catches hang** ❌ FAILS
7. **Worker thread blocked** ❌ Stuck
8. **Agent run stays "running"** ❌ Never completes

## Critical Code Paths

### 1. Tool Execution Path
```
ResponseProcessor._execute_tool() [Line 1219]
  ↓
Tool.__call__() method
  ↓
SandboxToolsBase._ensure_sandbox() [Line 26]
  ↓
Daytona API calls (sandbox.py)
  ↓
External service calls (Tavily, Firecrawl, etc.)
```

### 2. Sandbox Creation Path
```
SandboxToolsBase._ensure_sandbox()
  ↓
create_sandbox() [sandbox.py:86]
  ↓
daytona.create(params) [Line 125] - 60s timeout ✓
  ↓
sandbox.get_preview_link() [Line 54-55] - NO TIMEOUT ❌
```

### 3. Worker Lifecycle
```
Dramatiq worker process
  ↓
run_agent_background() actor [time_limit=3600000ms]
  ↓
AgentRunner.run() async generator
  ↓
ResponseProcessor event loop
  ↓
Tool execution (can block forever)
```

## System Dependencies

### External Services
1. **Daytona Sandbox Service**
   - URL: `https://app.daytona.io/api`
   - Critical for all sandbox tools
   - Can be slow or unavailable

2. **LLM Providers** (via LiteLLM)
   - Anthropic Claude
   - OpenAI GPT
   - Response times vary

3. **Third-Party APIs**
   - Tavily (web search)
   - Firecrawl (web scraping)
   - MCP servers (various)

### Internal Services
1. **Redis**
   - Queue management
   - Session state
   - Locks and pub/sub

2. **Supabase**
   - User authentication
   - Data persistence
   - Real-time subscriptions

3. **Dramatiq Workers**
   - 4 processes × 4 threads = 16 concurrent tasks
   - Redis-backed queue

## Concurrency Model

### Threading Architecture
```
Main Process (FastAPI)
    ├── Request Handler Threads
    └── Background Tasks

Dramatiq Processes (×4)
    ├── Main Thread (coordinator)
    └── Worker Threads (×4)
        └── Async Event Loops
            └── Tool Executions (await)
```

### Async Patterns
- **Sequential Execution**: Default for tool calls
- **Parallel Execution**: Optional via `parallel_tool_calls`
- **Streaming**: SSE for real-time updates
- **Pub/Sub**: Redis for control signals

### State Management
- **Redis**: Ephemeral state (locks, active runs)
- **Database**: Persistent state (messages, runs)
- **Memory**: Runtime state (thread manager)

## Solution Implementation

### Immediate Fix: Add Timeout to Tool Execution

**File**: `/backend/agentpress/response_processor.py`
```python
async def _execute_tool(self, tool_call: Dict[str, Any]) -> ToolResult:
    tool_name = tool_call['name']
    arguments = tool_call['arguments']
    
    # Get tool from registry
    tool = self.tool_registry.get_tool(tool_name)
    tool_fn = tool.get_function()
    
    # ADD TIMEOUT HERE
    try:
        # Different timeouts for different tool types
        timeout = 120  # Default 2 minutes
        if 'sandbox' in tool_name.lower():
            timeout = 180  # 3 minutes for sandbox tools
        elif 'web' in tool_name.lower():
            timeout = 60   # 1 minute for web tools
        
        result = await asyncio.wait_for(
            tool_fn(**arguments),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.error(f"Tool {tool_name} timed out after {timeout}s")
        return ToolResult(
            success=False,
            output=f"Tool execution timed out after {timeout} seconds"
        )
    except Exception as e:
        logger.error(f"Tool {tool_name} failed: {str(e)}")
        return ToolResult(
            success=False,
            output=f"Tool execution failed: {str(e)}"
        )
    
    return result
```

### Additional Improvements

1. **Add Preview Link Timeouts**
```python
# sandbox/tool_base.py line 54-55
vnc_link = await asyncio.wait_for(
    sandbox_obj.get_preview_link(6080),
    timeout=10.0
)
```

2. **Implement Circuit Breaker**
```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, timeout=60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
```

3. **Add Health Checks**
```python
async def check_sandbox_health():
    try:
        await asyncio.wait_for(
            daytona.list(),
            timeout=5.0
        )
        return True
    except:
        return False
```

4. **Graceful Degradation**
```python
if not await check_sandbox_health():
    # Use non-sandbox alternatives
    return self.use_fallback_tool()
```

## Summary

The tool hanging issue is caused by **missing timeouts in the core tool execution path** (`response_processor.py:1246`). When a tool makes an external call that hangs (Daytona API, web services, etc.), there's no timeout to catch it, causing:

1. Worker thread blocks indefinitely
2. Agent run stays in "running" status
3. Redis locks don't release
4. New executions can't start

The solution is to wrap all tool executions in `asyncio.wait_for()` with appropriate timeouts, and implement proper error handling and cleanup throughout the execution chain.

---

*Document generated: August 16, 2025*
*Issue Status: Root cause identified, solution proposed*
*Next Steps: Implement timeout wrapper in ResponseProcessor._execute_tool()*