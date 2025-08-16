# Agent Not Responding - Complete Troubleshooting Guide

## Table of Contents
1. [Problem Description](#problem-description)
2. [How the Agent Execution Process Works](#how-the-agent-execution-process-works)
3. [Root Causes Identified](#root-causes-identified)
4. [Complete Solution Applied](#complete-solution-applied)
5. [Verification Steps](#verification-steps)
6. [Prevention Strategies](#prevention-strategies)
7. [Quick Diagnostic Commands](#quick-diagnostic-commands)
8. [Key Lessons Learned](#key-lessons-learned)

## Problem Description

After removing social media MCPs (Model Context Protocol integrations) from Composio and Pipedream, the agent became unresponsive, getting stuck at initialization messages like:
- "Initializing neural pathways..."  
- "Fine-tuning cognitive models..."
- "Engaging reasoning algorithms..."

The agent would never actually respond to user messages despite the frontend showing these loading states.

## How the Agent Execution Process Works

Understanding the complete flow helps identify where failures can occur:

### Architecture Overview
```
User Message → Frontend (Next.js) → Backend API (FastAPI)
                                          ↓
                                   Create Agent Run
                                          ↓
                                   Redis Queue Entry
                                          ↓
                                 Dramatiq Worker Picks Up
                                          ↓
                                    AgentRunner.run()
                                          ↓
                        ┌─────────────────┴─────────────────┐
                        ↓                                   ↓
                  Setup Tools                         Setup MCP Tools
                        ↓                                   ↓
                Register Sandbox Tools            Register External Tools
                        ↓                                   ↓
                  Tool Execution                     Tool Execution
                        ↓                                   ↓
                 _ensure_sandbox()                  Direct API Calls
                        ↓
                  Daytona API Call
                        ↓
                 Sandbox Creation/Get
                        ↓
                   Tool Operation
                        ↓
                 Response Streaming
                        ↓
                   Frontend Display
```

### Detailed Execution Flow

1. **User Interaction** (`/frontend/src/components/thread/`)
   - User sends message through chat interface
   - Frontend creates thread and initiates agent run

2. **API Layer** (`/backend/api.py`)
   - `/api/agent/initiate` or `/api/thread/{thread_id}/agent/start` endpoints
   - Creates agent_run record in database
   - Publishes task to Redis queue

3. **Queue Processing** (`/backend/run_agent_background.py`)
   - Dramatiq worker processes pick up tasks from Redis
   - Each worker can handle multiple threads concurrently
   - Worker calls `run_agent()` function

4. **Agent Initialization** (`/backend/agent/run.py`)
   ```python
   # Key initialization steps:
   await self.setup()           # Database, auth, project setup
   await self.setup_tools()     # Register AgentPress tools
   await self.setup_mcp_tools() # Register MCP/external tools
   ```

5. **Tool Registration**
   - **Sandbox Tools** (require Daytona sandbox):
     - `SandboxWebSearchTool`
     - `SandboxShellTool`
     - `SandboxFilesTool`
     - `SandboxVisionTool`
     - etc.
   
   - **Non-Sandbox Tools**:
     - `MessageTool`
     - `ExpandMessageTool`
     - MCP tools (external services)

6. **Critical Point: Sandbox Initialization** (`/backend/sandbox/tool_base.py`)
   ```python
   async def _ensure_sandbox(self) -> AsyncSandbox:
       # This is where the hang occurred!
       # Daytona API calls had no timeout
       sandbox = await daytona.get(sandbox_id)  # Could hang forever
   ```

7. **Tool Execution**
   - When user asks for web search, file operations, etc.
   - Tool's `_ensure_sandbox()` is called
   - If Daytona service is down/slow → HANG

8. **Response Streaming**
   - Agent generates response
   - Streams back through SSE (Server-Sent Events)
   - Frontend displays in real-time

### Failure Points in the System

| Component | Failure Mode | Symptoms | Impact |
|-----------|-------------|----------|---------|
| Dramatiq Workers | Zombie processes | Old workers hold locks | New requests fail |
| Redis | State corruption | Stale locks, bad flags | Agent can't start |
| Sandbox Service | No timeout on API calls | Hangs on tool use | Tools never execute |
| MCP Registration | Silent failures | No error messages | Unclear why failing |

## Root Causes Identified

### 1. **Zombie Worker Processes**
Old Dramatiq worker processes from previous sessions were still active and conflicting with new requests:
- Holding locks on resources
- Processing stale queue items  
- Preventing new workers from properly handling requests
- Some processes running since 4:01 AM (discovered via `ps aux`)

### 2. **Redis State Corruption**
Redis contained corrupted state from previous debugging:
- Stale agent run locks (`agent_run_lock:*`)
- Orphaned active run entries (`active_run:*`)
- Missing feature flags (cleared by accidental FLUSHDB)
- Old queue items in Dramatiq queues

### 3. **Sandbox Service Hanging on Tool Execution** ⚠️ **CRITICAL**
The most insidious issue - agent worked for simple text but hung on tools:
- `_ensure_sandbox()` in `tool_base.py` made Daytona API calls without timeouts
- When Daytona service was unavailable/slow, connection hung indefinitely
- No error messages - just infinite waiting
- Blocked ALL sandbox-based tools from executing
- User perspective: Agent stuck at "thinking" when trying to use tools

## Complete Solution Applied

### Step 1: Kill All Zombie Worker Processes
```bash
# Find all Dramatiq processes
ps aux | grep -E "dramatiq.*run_agent_background" | grep -v grep

# Kill all Dramatiq processes gracefully
pkill -f "dramatiq.*run_agent_background"

# If processes persist, force kill with specific PIDs
kill -9 45335 45336  # Use actual PIDs from ps aux
```

### Step 2: Clear Redis State Completely
```python
#!/usr/bin/env python3
import redis
import asyncio

async def clear_agent_locks():
    r = redis.Redis(host='localhost', port=6379, decode_responses=True)
    
    # Clear ALL agent-related Redis keys
    patterns = [
        'agent_run_lock:*',
        'active_run:*', 
        'agent_run:*:*',
        'dramatiq:run_agent_background',
        'dramatiq:run_agent_background.DLQ'
    ]
    
    for pattern in patterns:
        keys = list(r.scan_iter(match=pattern))
        if keys:
            r.delete(*keys)
            print(f'Cleared {len(keys)} keys matching {pattern}')
    
    print('Redis state cleared successfully')

asyncio.run(clear_agent_locks())
```

### Step 3: Restore Feature Flags
```python
#!/usr/bin/env python3
import asyncio
import sys
import os
sys.path.append('/Users/hamzam/willowv3/backend')
os.chdir('/Users/hamzam/willowv3/backend')

from dotenv import load_dotenv
load_dotenv()

from services import redis
from flags.flags import enable_flag

async def restore_flags():
    await redis.initialize_async()
    
    # Critical feature flags that must be enabled
    flags = [
        ("custom_agents", "Enable custom agent creation"),
        ("mcp_module", "Enable MCP module"),
        ("templates_api", "Enable templates API"),
        ("triggers_api", "Enable triggers API"),
        ("workflows_api", "Enable workflows API"),
        ("knowledge_base", "Enable knowledge base"),
        ("pipedream", "Enable Pipedream integration"),
        ("credentials_api", "Enable credentials API"),
        ("suna_default_agent", "Enable Suna default agent"),
        ("agent_marketplace", "Enable agent marketplace")
    ]
    
    for flag_name, description in flags:
        await enable_flag(flag_name, description)
        print(f"✓ Enabled: {flag_name}")
    
    print("\nAll feature flags restored!")

asyncio.run(restore_flags())
```

### Step 4: Fix Sandbox Timeouts (THE CRITICAL FIX) 🔧

**File: `/backend/sandbox/sandbox.py`**
```python
# Line 41 - Add timeout to get_or_start_sandbox
async def get_or_start_sandbox(sandbox_id: str) -> AsyncSandbox:
    try:
        # CRITICAL: Add 10-second timeout to prevent hanging
        sandbox = await asyncio.wait_for(daytona.get(sandbox_id), timeout=10.0)
        
        if sandbox.state == SandboxState.ARCHIVED or sandbox.state == SandboxState.STOPPED:
            # Also add timeout to start operation
            await asyncio.wait_for(daytona.start(sandbox), timeout=30.0)
            sandbox = await daytona.get(sandbox_id)
            
        return sandbox
        
    except asyncio.TimeoutError:
        logger.error(f"Timeout accessing sandbox {sandbox_id} - Daytona service may be unavailable")
        raise Exception(f"Cannot connect to sandbox service - operation timed out")

# Line 125 - Add timeout to create_sandbox
async def create_sandbox(password: str, project_id: str = None) -> AsyncSandbox:
    params = CreateSandboxFromSnapshotParams(...)
    
    try:
        # CRITICAL: Add 60-second timeout for creation
        sandbox = await asyncio.wait_for(daytona.create(params), timeout=60.0)
        logger.debug(f"Sandbox created with ID: {sandbox.id}")
        return sandbox
    except asyncio.TimeoutError:
        logger.error(f"Timeout creating sandbox after 60 seconds")
        raise Exception("Sandbox creation timed out - Daytona service may be unavailable")
```

**File: `/backend/sandbox/tool_base.py`**
```python
# Lines 95-103 - Graceful degradation when sandbox unavailable
async def _ensure_sandbox(self) -> AsyncSandbox:
    try:
        # ... existing sandbox initialization code ...
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error retrieving/creating sandbox: {error_msg}")
        
        # CRITICAL: Don't let sandbox issues crash the entire agent
        if "timed out" in error_msg.lower() or "daytona" in error_msg.lower():
            logger.warning(f"Sandbox service appears to be unavailable - tools may have limited functionality")
            return None  # Return None instead of crashing
        raise e
```

### Step 5: Add Debug Logging
**File: `/backend/agent/run.py`** (lines 465-471)
```python
async def run(self) -> AsyncGenerator[Dict[str, Any], None]:
    logger.info(f"[AGENT RUN] Starting agent run for thread {self.config.thread_id}")
    await self.setup()
    logger.info(f"[AGENT RUN] Setup completed")
    await self.setup_tools()
    logger.info(f"[AGENT RUN] Tools setup completed")
    mcp_wrapper_instance = await self.setup_mcp_tools()
    logger.info(f"[AGENT RUN] MCP tools setup completed, instance: {mcp_wrapper_instance is not None}")
    # Continue with execution...
```

### Step 6: Restart Services Cleanly
```bash
# 1. Restart Dramatiq workers with proper configuration
cd /Users/hamzam/willowv3/backend
uv run dramatiq --processes 4 --threads 4 run_agent_background

# 2. Backend auto-reloads with --reload flag
# If not using --reload, restart manually:
# uv run uvicorn api:app --reload --port 8000 --host 0.0.0.0

# 3. Verify services are running
ps aux | grep -E "(uvicorn|dramatiq)" | grep -v grep
```

## Verification Steps

### ✅ Confirmation the Fix Worked

1. **Simple Message Test** (Phase 1 verification)
   - Send: "Hello, how are you?"
   - Expected: Agent responds with text
   - Result: ✓ Working

2. **Tool Execution Test** (Phase 2 verification)
   - Send: "Search the web for high-quality zebra images"
   - Expected: Agent executes web search tool
   - Result: ✓ Working (as shown in screenshot)
   
3. **Evidence of Success**
   - Agent successfully executed `web_search` tool
   - Gathered 20 search results from Pixabay, Unsplash, etc.
   - Identified and filtered high-quality zebra images
   - No hanging or timeout issues
   - Complete execution flow working end-to-end

### How to Test After Applying Fix

```bash
# 1. Check worker processes are running
ps aux | grep dramatiq | grep -v grep
# Should show 4 worker processes

# 2. Check Redis is clean
redis-cli
> KEYS agent_run_lock:*
# Should return (empty array)

# 3. Test simple message
curl -X POST http://localhost:8000/api/thread/{thread_id}/message \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"content": "Hello"}'
# Should get response without hanging

# 4. Test tool execution
curl -X POST http://localhost:8000/api/thread/{thread_id}/message \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"content": "Search the web for Python tutorials"}'
# Should execute search and return results
```

## Prevention Strategies

### 1. **Graceful Shutdown Protocol**
```bash
#!/bin/bash
# graceful_shutdown.sh
echo "Stopping services gracefully..."

# Stop workers with SIGTERM (graceful)
pkill -TERM -f "dramatiq.*run_agent_background"
sleep 5

# Check if stopped
if pgrep -f "dramatiq.*run_agent_background" > /dev/null; then
    echo "Workers still running, force stopping..."
    pkill -9 -f "dramatiq.*run_agent_background"
fi

echo "Services stopped"
```

### 2. **Health Monitoring Script**
```python
#!/usr/bin/env python3
# health_check.py
import redis
import requests
import sys

def check_health():
    checks_passed = True
    
    # Check Redis
    try:
        r = redis.Redis()
        r.ping()
        print("✓ Redis is running")
    except:
        print("✗ Redis is down")
        checks_passed = False
    
    # Check API
    try:
        resp = requests.get("http://localhost:8000/api/health", timeout=5)
        if resp.status_code == 200:
            print("✓ API is healthy")
        else:
            print(f"✗ API returned {resp.status_code}")
            checks_passed = False
    except:
        print("✗ API is not responding")
        checks_passed = False
    
    # Check for zombie processes
    import subprocess
    result = subprocess.run(['pgrep', '-f', 'dramatiq'], capture_output=True)
    if result.returncode == 0:
        pids = result.stdout.decode().strip().split('\n')
        print(f"✓ {len(pids)} Dramatiq workers running")
    else:
        print("✗ No Dramatiq workers found")
        checks_passed = False
    
    return 0 if checks_passed else 1

if __name__ == "__main__":
    sys.exit(check_health())
```

### 3. **Automated Recovery Script**
```bash
#!/bin/bash
# auto_recovery.sh
# Run this if agent stops responding

echo "Starting automatic recovery..."

# Step 1: Stop everything
pkill -f dramatiq
sleep 2

# Step 2: Clear Redis state
redis-cli EVAL "
local keys = redis.call('keys', 'agent_run_lock:*')
for i=1,#keys do redis.call('del', keys[i]) end
keys = redis.call('keys', 'active_run:*')
for i=1,#keys do redis.call('del', keys[i]) end
redis.call('del', 'dramatiq:run_agent_background')
redis.call('del', 'dramatiq:run_agent_background.DLQ')
return 'Cleared'
" 0

# Step 3: Restart workers
cd /Users/hamzam/willowv3/backend
uv run dramatiq --processes 4 --threads 4 run_agent_background &

echo "Recovery complete"
```

## Quick Diagnostic Commands

```bash
# Show all relevant processes
ps aux | grep -E "(uvicorn|dramatiq|redis)" | grep -v grep

# Redis queue status
redis-cli LLEN dramatiq:run_agent_background

# Active agent runs
redis-cli --scan --pattern "active_run:*"

# Agent run locks
redis-cli --scan --pattern "agent_run_lock:*"

# Dead letter queue
redis-cli LLEN dramatiq:run_agent_background.DLQ

# Check feature flags
redis-cli HGETALL "flag:custom_agents"

# Monitor logs in real-time
tail -f /var/log/backend.log | grep -E "(ERROR|WARNING|AGENT RUN)"

# Test sandbox connectivity
curl -X GET http://localhost:8080/health  # Daytona health check
```

## Key Lessons Learned

1. **Always Add Timeouts to External Services**
   - Any API call to external services MUST have a timeout
   - Without timeouts, the entire system can hang indefinitely
   - Graceful degradation is better than hanging

2. **Worker Process Lifecycle Management**
   - Zombie processes are silent killers
   - Always use graceful shutdown (SIGTERM before SIGKILL)
   - Monitor worker health regularly

3. **Redis State is Critical**
   - Feature flags, locks, and queues all live in Redis
   - Never use FLUSHDB in production
   - Have scripts ready to restore critical state

4. **Debugging Requires Multiple Test Scenarios**
   - Test simple text responses (no tools)
   - Test tool execution separately
   - Different failure modes for different operations

5. **Silent Failures are the Worst Failures**
   - Always add logging at critical points
   - Timeout errors should be explicit
   - Users need to know what's happening

6. **Sandbox Services Need Special Handling**
   - Sandboxes can fail independently of the main agent
   - Tools should degrade gracefully without sandbox
   - Consider fallback options for critical tools

## Summary

The agent failure was a **perfect storm** of three issues:

1. **Immediate Issue**: Zombie worker processes preventing new requests
2. **State Issue**: Corrupted Redis state from debugging attempts  
3. **Hidden Issue**: Sandbox API calls hanging without timeouts

The fix required addressing all three:
- ✅ Killed zombie processes and cleaned Redis
- ✅ Restored feature flags and queue state
- ✅ **Most importantly**: Added timeouts to prevent future hangs

**Result**: Agent now handles both simple messages AND tool execution successfully, with graceful degradation when services are unavailable.

---
*Last Updated: August 15, 2025*  
*Issue Resolution Time: ~1 hour*  
*Status: RESOLVED ✅*