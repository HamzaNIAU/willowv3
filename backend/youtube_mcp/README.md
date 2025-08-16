# YouTube MCP Integration

## Overview
YouTube is integrated as a native social media MCP (Model Context Protocol) in Suna, providing direct OAuth authentication and YouTube Data API access without relying on third-party services like Composio.

## Architecture

### Frontend Flow
1. User connects YouTube account via OAuth on the Social Media page
2. YouTube channels are stored in the `youtube_channels` table
3. When toggling YouTube in chat, channels are added to agent's `custom_mcps` with:
   - `customType: 'social-media'`
   - `platform: 'youtube'`
   - `qualifiedName: 'social.youtube.{channel_id}'`

### Backend Flow
1. **AgentRunner** (`agent/run.py`):
   - Detects YouTube MCPs in `custom_mcps`
   - Adds `user_id` to the config for authentication
   - Passes configuration to MCPToolWrapper

2. **MCPToolWrapper** (`agent/tools/mcp_tool_wrapper.py`):
   - Initializes all MCP configurations
   - Delegates to CustomMCPHandler for custom types

3. **CustomMCPHandler** (`agent/tools/utils/custom_mcp_handler.py`):
   - Recognizes `customType: 'social-media'`
   - Calls `_initialize_social_media_mcp()` for YouTube
   - Registers YouTube tools: authenticate, channels, upload, stats

4. **MCPToolExecutor** (`agent/tools/utils/mcp_tool_executor.py`):
   - Handles tool execution for `social-media` type
   - Creates YouTubeTool instance with user_id and channel_ids
   - Maps tool calls to YouTubeTool methods

5. **YouTubeTool** (`agent/tools/youtube_tool.py`):
   - Implements actual YouTube API calls
   - Uses backend API endpoints for OAuth and data operations

## Available Tools

### youtube_authenticate
Initiates OAuth flow for connecting YouTube accounts.

### youtube_channels
Lists all connected YouTube channels with metadata.

### youtube_upload_video
Uploads videos to specified YouTube channels.

### youtube_channel_stats
Retrieves statistics for YouTube channels.

## Configuration Example

```json
{
  "custom_mcps": [
    {
      "name": "YouTube - Channel Name",
      "qualifiedName": "social.youtube.UC_x5XG1OV2P6uZZ5FSM9Ttw",
      "customType": "social-media",
      "platform": "youtube",
      "config": {
        "user_id": "auto-populated-by-backend"
      },
      "enabledTools": []
    }
  ]
}
```

## Key Differences from Composio

1. **Native Integration**: Direct OAuth and API integration, no third-party dependencies
2. **Better Security**: Tokens encrypted and stored in our database
3. **Custom Features**: Ability to add YouTube-specific features not available in Composio
4. **Unified Experience**: Consistent UI/UX with other Suna features

## Database Schema

### youtube_channels
- `id`: Channel ID from YouTube
- `user_id`: Suna user ID
- `name`: Channel name
- `username`: Channel handle
- `profile_picture`: Channel avatar URL
- `encrypted_tokens`: OAuth tokens (encrypted)

### youtube_uploads
- Tracks video uploads
- Links to channels and file references

## Security

- OAuth tokens encrypted using Fernet encryption
- Row Level Security (RLS) policies ensure users only access their own data
- Tokens never exposed to frontend
- API calls authenticated with JWT