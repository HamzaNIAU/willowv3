# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kortix (formerly Suna) is an open-source platform for building, managing, and training AI agents. The platform consists of:
- **Backend**: Python/FastAPI service for agent orchestration, LLM integration, and API endpoints
- **Frontend**: Next.js/React dashboard for agent management and user interaction
- **Database**: Supabase for authentication, data storage, and real-time subscriptions
- **Agent Runtime**: Docker-based isolated execution environments with MCP (Model Context Protocol) support

## Development Commands

### Backend (Python/FastAPI)
```bash
# Install dependencies
cd backend
uv sync

# Run development server
uv run uvicorn api:app --reload --port 8000 --host 0.0.0.0

# Run background worker
uv run dramatiq --skip-logging --processes 4 --threads 4 run_agent_background

# Run tests
uv run pytest
uv run pytest path/to/test.py::TestClass::test_method  # Run specific test

# Format code (install separately if needed)
uv run black .
uv run ruff check --fix .
```

### Frontend (Next.js/React)
```bash
# Install dependencies
cd frontend
npm install

# Run development server (with Turbopack)
npm run dev

# Build for production
npm run build

# Run linting
npm run lint

# Format code
npm run format

# Check formatting
npm run format:check
```

### Docker Development
```bash
# Start all services (API, worker, Redis)
cd backend
docker-compose up

# Start specific service
docker-compose up backend
docker-compose up worker
docker-compose up redis

# Rebuild containers
docker-compose build

# View logs
docker-compose logs -f api
docker-compose logs -f worker
```

### Database Migrations
```bash
# Run Supabase migrations
cd backend/supabase
supabase migration up

# Create new migration
supabase migration new <migration_name>

# Reset database (development only)
supabase db reset
```

## Architecture Overview

### Backend Structure (`/backend`)

**Core Components:**
- `api.py`: Main FastAPI application with middleware and routing
- `agent/`: Agent execution, builder prompts, and tool management
- `agentpress/`: Custom framework for thread management and tool orchestration
- `services/`: External service integrations (Redis, Supabase, LLM providers)
- `composio_integration/`: Composio platform integration for external tools
- `credentials/`: Secure credential and profile management
- `triggers/`: Scheduled and event-based trigger system
- `sandbox/`: Docker-based sandboxed execution environment
- `mcp_module/`: Model Context Protocol server integrations

**Key Services:**
- **LLM Integration**: Via LiteLLM supporting Anthropic, OpenAI, and other providers
- **Redis**: Session management and caching
- **Dramatiq**: Background task processing for agent runs
- **MCP**: Model Context Protocol for tool integration

### Frontend Structure (`/frontend`)

**Core Components:**
- `src/app/`: Next.js 15 app router pages and API routes
- `src/components/`: React components organized by feature
  - `agents/`: Agent configuration, builder, and management
  - `thread/`: Chat interface and message handling
  - `workflows/`: Visual workflow builder
  - `billing/`: Subscription and usage management
- `src/hooks/`: Custom React hooks and React Query hooks
- `src/lib/`: Utility functions and API clients

**Key Features:**
- Real-time agent chat with streaming responses
- Visual agent builder with drag-and-drop workflow configuration
- MCP server configuration and tool management
- File upload and attachment handling
- Team collaboration with Basejump integration

### Database Schema (Supabase)

**Core Tables:**
- `agents`: Agent configurations and metadata
- `agent_versions`: Version control for agent configurations
- `threads`: Conversation threads
- `messages`: Chat messages with tool calls
- `agent_runs`: Agent execution tracking
- `workflows`: Agent workflow definitions
- `triggers`: Scheduled and event triggers
- `knowledge_base`: Agent knowledge documents
- `credential_profiles`: Secure credential storage

## Key Patterns and Conventions

### API Patterns
- All API routes prefixed with `/api/`
- Authentication via Supabase JWT tokens (without signature verification)
- Rate limiting based on subscription tier
- Streaming responses for agent interactions

### Frontend Patterns
- Server Components for initial page loads
- Client Components for interactive features
- React Query for data fetching and caching
- Zustand for client-side state management
- Tailwind CSS with shadcn/ui components
- React Hook Form with Zod validation

### Agent Development
- Tools defined in `backend/agent/tools/`
- Custom tools extend `AgentBuilderBaseTool` or `Tool` base classes
- MCP servers configured via `mcp_module/`
- Workflows defined as JSON structures
- Tool schemas use dual decorators (OpenAPI + XML)

### Security Considerations
- All credentials encrypted at rest using Fernet
- Sandboxed execution for untrusted code
- Row-level security (RLS) in Supabase
- API key authentication for external access

## Environment Variables

### Backend (.env)
```bash
# Supabase
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# LLM Providers
LITELLM_ANTHROPIC_API_KEY=
LITELLM_OPENAI_API_KEY=
LITELLM_OPENROUTER_API_KEY=

# Observability
LANGFUSE_SECRET_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_HOST=
SENTRY_DSN=

# Billing
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
```

### Frontend (.env.local)
```bash
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_POSTHOG_KEY=
NEXT_PUBLIC_POSTHOG_HOST=
```

## Testing Strategy

### Backend Testing
- Unit tests for individual tools and services
- Integration tests for API endpoints
- Mock external services in tests
- Use pytest fixtures for test data
- Run with `uv run pytest`
- Test file example: `test_kortix_sandbox.py`

### Frontend Testing
- Component testing with React Testing Library
- E2E tests for critical user flows
- Visual regression testing for UI components
- Test file example: `src/components/workflows/utils/workflow-structure-utils.test.ts`

## Deployment

### Production Deployment
- Backend: Docker container with Uvicorn/Gunicorn
- Frontend: Vercel or self-hosted Next.js
- Database: Supabase cloud or self-hosted
- Redis: Managed Redis or self-hosted
- Workers: Dramatiq with Redis backend

### Monitoring
- Sentry for error tracking
- Langfuse for LLM observability
- PostHog for product analytics
- Structured logging with correlation IDs
- Health checks at `/api/health`

## Important Implementation Details

### Tool Development
When creating new tools:
1. Extend appropriate base class (`AgentBuilderBaseTool` or `Tool`)
2. Use `@openapi_schema` decorator for function schemas
3. Return `ToolResult` objects using `success_response()` or `fail_response()`
4. Implement proper error handling and logging

Example:
```python
class ExampleTool(AgentBuilderBaseTool):
    @openapi_schema({
        "type": "function",
        "function": {
            "name": "example_action",
            "description": "Clear description",
            "parameters": {
                "type": "object",
                "properties": {
                    "param1": {"type": "string", "description": "Description"}
                },
                "required": ["param1"]
            }
        }
    })
    async def example_action(self, param1: str) -> ToolResult:
        try:
            result = await self.perform_action(param1)
            return self.success_response(result=result)
        except Exception as e:
            return self.fail_response(str(e))
```

### Database Migrations
- Always use idempotent SQL patterns
- Include proper indexing for foreign keys
- Enable RLS for user-accessible tables
- Use `gen_random_uuid()` for UUID primary keys
- Create update triggers for `updated_at` columns

Example migration pattern:
```sql
BEGIN;
CREATE TABLE IF NOT EXISTS example_table (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_example_table_user_id ON example_table(user_id);
ALTER TABLE example_table ENABLE ROW LEVEL SECURITY;
COMMIT;
```

### Frontend Development
- Use shadcn/ui components as default
- Follow Next.js App Router patterns
- Implement proper loading and error states
- Use TypeScript strictly (avoid `any`)
- Batch API calls when possible

### Backend API Development
- Use async/await for all I/O operations
- Implement proper Pydantic models for validation
- Use dependency injection for services
- Handle JWT validation properly
- Structure logging with context

## Quick Reference

### Common File Locations
- API routes: `backend/api.py`
- Agent tools: `backend/agent/tools/`
- Frontend pages: `frontend/src/app/`
- UI components: `frontend/src/components/`
- Database migrations: `backend/supabase/migrations/`
- Docker config: `backend/docker-compose.yml`

### Debugging Tips
- Backend logs: Check console output or `logs/` directory
- Frontend errors: Browser DevTools console
- Database issues: Supabase dashboard
- Worker issues: `docker-compose logs worker`
- Redis issues: `docker-compose logs redis`

### Performance Optimization
- Use Redis caching for frequently accessed data
- Implement pagination for large datasets
- Use database indexes for query optimization
- Enable Turbopack in Next.js development
- Use connection pooling for external APIs