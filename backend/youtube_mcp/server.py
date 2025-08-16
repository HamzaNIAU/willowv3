"""YouTube MCP Server - Provides YouTube tools via Model Context Protocol"""

import json
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime

try:
    from mcp.server import Server, NotificationOptions
    from mcp.server.models import InitializationOptions
    from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    Server = None
    NotificationOptions = None
    InitializationOptions = None
    Tool = None
    TextContent = None
    ImageContent = None
    EmbeddedResource = None

from services.supabase import DBConnection
from utils.logger import logger
from .oauth import YouTubeOAuthHandler
from .channels import YouTubeChannelService
from .upload import YouTubeUploadService


class YouTubeMCPServer:
    """MCP Server for YouTube integration"""
    
    def __init__(self, db: DBConnection):
        self.db = db
        self.server = Server("youtube-mcp")
        self.oauth_handler = YouTubeOAuthHandler(db)
        self.channel_service = YouTubeChannelService(db)
        self.upload_service = YouTubeUploadService(db)
        
        # Register handlers
        self._register_handlers()
    
    def _register_handlers(self):
        """Register MCP protocol handlers"""
        
        @self.server.list_tools()
        async def handle_list_tools() -> List[Tool]:
            """Return available YouTube tools"""
            return [
                Tool(
                    name="youtube_authenticate",
                    description="Start YouTube OAuth authentication flow",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "redirect_uri": {
                                "type": "string",
                                "description": "OAuth callback URL (optional)"
                            },
                            "state": {
                                "type": "string", 
                                "description": "CSRF protection token (optional)"
                            }
                        }
                    }
                ),
                Tool(
                    name="youtube_channels",
                    description="List connected YouTube channels",
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                ),
                Tool(
                    name="youtube_channels_enabled",
                    description="Check if user has connected YouTube channels",
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                ),
                Tool(
                    name="youtube_upload_video",
                    description="Upload a video to YouTube",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "channel_id": {
                                "type": "string",
                                "description": "YouTube channel ID"
                            },
                            "title": {
                                "type": "string",
                                "description": "Video title"
                            },
                            "description": {
                                "type": "string",
                                "description": "Video description"
                            },
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Video tags"
                            },
                            "category_id": {
                                "type": "string",
                                "description": "YouTube category ID (default: 22)",
                                "default": "22"
                            },
                            "privacy_status": {
                                "type": "string",
                                "enum": ["private", "unlisted", "public"],
                                "description": "Video privacy setting",
                                "default": "public"
                            },
                            "made_for_kids": {
                                "type": "boolean",
                                "description": "Whether video is made for kids",
                                "default": False
                            },
                            "scheduled_for": {
                                "type": "string",
                                "description": "Natural language scheduling (e.g., 'tomorrow at 3pm')"
                            },
                            "notify_subscribers": {
                                "type": "boolean",
                                "description": "Notify subscribers when video goes public",
                                "default": True
                            },
                            "video_reference_id": {
                                "type": "string",
                                "description": "Reference ID of uploaded video file"
                            },
                            "thumbnail_reference_id": {
                                "type": "string",
                                "description": "Reference ID of thumbnail image (optional)"
                            }
                        },
                        "required": ["channel_id", "title", "video_reference_id"]
                    }
                ),
                Tool(
                    name="youtube_remove_channel",
                    description="Remove a connected YouTube channel",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "channel_id": {
                                "type": "string",
                                "description": "YouTube channel ID to remove"
                            }
                        },
                        "required": ["channel_id"]
                    }
                )
            ]
        
        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: Optional[Dict[str, Any]] = None) -> List[TextContent | ImageContent | EmbeddedResource]:
            """Handle tool execution requests"""
            
            # Get user context (this would come from the MCP connection context)
            user_id = self._get_user_id_from_context()
            
            if not user_id:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "type": "error",
                        "message": "User authentication required"
                    })
                )]
            
            try:
                if name == "youtube_authenticate":
                    result = await self._handle_authenticate(user_id, arguments or {})
                elif name == "youtube_channels":
                    result = await self._handle_list_channels(user_id)
                elif name == "youtube_channels_enabled":
                    result = await self._handle_channels_enabled(user_id)
                elif name == "youtube_upload_video":
                    result = await self._handle_upload_video(user_id, arguments or {})
                elif name == "youtube_remove_channel":
                    result = await self._handle_remove_channel(user_id, arguments or {})
                else:
                    result = {
                        "type": "error",
                        "message": f"Unknown tool: {name}"
                    }
                
                return [TextContent(
                    type="text",
                    text=json.dumps(result)
                )]
                
            except Exception as e:
                logger.error(f"Tool execution failed: {e}")
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "type": "error",
                        "message": str(e)
                    })
                )]
    
    def _get_user_id_from_context(self) -> Optional[str]:
        """Get user ID from MCP connection context"""
        # This would be implemented based on how the MCP connection passes user context
        # For now, we'll use a placeholder that should be replaced with actual implementation
        import os
        return os.getenv("CURRENT_USER_ID")
    
    async def _handle_authenticate(self, user_id: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle YouTube authentication"""
        redirect_uri = arguments.get("redirect_uri")
        state = arguments.get("state")
        
        auth_url = self.oauth_handler.get_auth_url(state)
        
        return {
            "type": "youtube-auth",
            "auth_url": auth_url,
            "message": "Click the button below to connect your YouTube account",
            "instructions": [
                "1. Click the 'Connect YouTube' button",
                "2. Authorize the application in Google",
                "3. Your YouTube channel will be connected automatically"
            ]
        }
    
    async def _handle_list_channels(self, user_id: str) -> Dict[str, Any]:
        """Handle listing YouTube channels"""
        channels = await self.channel_service.get_user_channels(user_id)
        
        if not channels:
            return {
                "type": "youtube-channels",
                "channels": [],
                "message": "No YouTube channels connected. Use youtube_authenticate to connect a channel."
            }
        
        formatted_channels = []
        for channel in channels:
            formatted_channels.append({
                "id": channel["id"],
                "name": channel["name"],
                "username": channel.get("username"),
                "profile_picture": channel.get("profile_picture"),
                "statistics": {
                    "subscribers": self._format_count(channel.get("subscriber_count", 0)),
                    "views": self._format_count(channel.get("view_count", 0)),
                    "videos": str(channel.get("video_count", 0))
                },
                "capabilities": {
                    "upload": True,
                    "analytics": True,
                    "management": True
                }
            })
        
        return {
            "type": "youtube-channels",
            "channels": formatted_channels,
            "message": f"Found {len(channels)} connected YouTube channel(s)"
        }
    
    async def _handle_channels_enabled(self, user_id: str) -> Dict[str, Any]:
        """Check if user has YouTube channels connected"""
        channels = await self.channel_service.get_user_channels(user_id)
        
        return {
            "type": "youtube-channels-status",
            "enabled": len(channels) > 0,
            "channel_count": len(channels),
            "message": "YouTube channels are connected" if channels else "No YouTube channels connected"
        }
    
    async def _handle_upload_video(self, user_id: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle video upload to YouTube"""
        # Validate required arguments
        channel_id = arguments.get("channel_id")
        title = arguments.get("title")
        video_reference_id = arguments.get("video_reference_id")
        
        if not all([channel_id, title, video_reference_id]):
            return {
                "type": "error",
                "message": "Missing required parameters: channel_id, title, and video_reference_id are required"
            }
        
        # Prepare upload parameters
        upload_params = {
            "channel_id": channel_id,
            "title": title,
            "description": arguments.get("description", ""),
            "tags": arguments.get("tags", []),
            "category_id": arguments.get("category_id", "22"),
            "privacy_status": arguments.get("privacy_status", "public"),
            "made_for_kids": arguments.get("made_for_kids", False),
            "scheduled_for": arguments.get("scheduled_for"),
            "notify_subscribers": arguments.get("notify_subscribers", True),
            "video_reference_id": video_reference_id,
            "thumbnail_reference_id": arguments.get("thumbnail_reference_id")
        }
        
        try:
            # Start upload
            upload_result = await self.upload_service.upload_video(user_id, upload_params)
            
            return {
                "type": "youtube-upload",
                "upload_id": upload_result["upload_id"],
                "video_id": upload_result.get("video_id"),
                "title": title,
                "channel_name": upload_result.get("channel_name"),
                "message": f"Upload started for '{title}'",
                "status": upload_result.get("status", "uploading")
            }
            
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            return {
                "type": "youtube-upload-error",
                "message": f"Upload failed: {str(e)}"
            }
    
    async def _handle_remove_channel(self, user_id: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle removing a YouTube channel"""
        channel_id = arguments.get("channel_id")
        
        if not channel_id:
            return {
                "type": "error",
                "message": "channel_id is required"
            }
        
        success = await self.oauth_handler.remove_channel(user_id, channel_id)
        
        if success:
            return {
                "type": "youtube-channel-removed",
                "channel_id": channel_id,
                "message": f"YouTube channel {channel_id} has been disconnected"
            }
        else:
            return {
                "type": "error",
                "message": f"Failed to remove channel {channel_id}"
            }
    
    def _format_count(self, count: int) -> str:
        """Format large numbers with K/M/B suffixes"""
        if count >= 1_000_000_000:
            return f"{count / 1_000_000_000:.1f}B"
        elif count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}K"
        else:
            return str(count)
    
    async def run(self):
        """Run the MCP server"""
        async with self.server.run() as runner:
            options = InitializationOptions(
                server_name="youtube-mcp",
                server_version="1.0.0"
            )
            await runner.run(options)


# FastAPI integration for HTTP streaming
from fastapi import FastAPI, Request, Response, Depends
from fastapi.responses import StreamingResponse
import asyncio

app = FastAPI()

# Global MCP server instance
mcp_server = None


async def get_mcp_server():
    """Get or create MCP server instance"""
    global mcp_server
    if not mcp_server:
        db = DBConnection()
        mcp_server = YouTubeMCPServer(db)
    return mcp_server


@app.post("/mcp/stream")
async def mcp_stream(request: Request, server: YouTubeMCPServer = Depends(get_mcp_server)):
    """Handle MCP protocol over HTTP streaming"""
    
    async def stream_handler():
        """Generate SSE stream for MCP protocol"""
        # Read request body
        body = await request.body()
        
        # Process MCP request
        # This would integrate with the MCP server's message handling
        # For now, we'll implement a basic handler
        
        try:
            message = json.loads(body)
            
            # Handle different MCP message types
            if message.get("method") == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": message.get("id"),
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": True
                        },
                        "serverInfo": {
                            "name": "youtube-mcp",
                            "version": "1.0.0"
                        }
                    }
                }
                yield f"data: {json.dumps(response)}\n\n"
                
            elif message.get("method") == "tools/list":
                tools = await server.server.list_tools()
                response = {
                    "jsonrpc": "2.0",
                    "id": message.get("id"),
                    "result": {
                        "tools": [tool.model_dump() for tool in tools]
                    }
                }
                yield f"data: {json.dumps(response)}\n\n"
                
            elif message.get("method") == "tools/call":
                params = message.get("params", {})
                result = await server.server.call_tool(
                    params.get("name"),
                    params.get("arguments")
                )
                response = {
                    "jsonrpc": "2.0",
                    "id": message.get("id"),
                    "result": {
                        "content": [r.model_dump() for r in result]
                    }
                }
                yield f"data: {json.dumps(response)}\n\n"
                
        except Exception as e:
            logger.error(f"MCP stream error: {e}")
            error_response = {
                "jsonrpc": "2.0",
                "id": message.get("id") if "message" in locals() else None,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
            yield f"data: {json.dumps(error_response)}\n\n"
    
    return StreamingResponse(
        stream_handler(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )