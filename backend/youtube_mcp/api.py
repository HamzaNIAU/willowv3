"""YouTube MCP API Routes"""

from fastapi import APIRouter, HTTPException, Depends, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import json

from services.supabase import DBConnection
from utils.auth_utils import get_current_user_id_from_jwt
from utils.logger import logger
from .oauth import YouTubeOAuthHandler
from .channels import YouTubeChannelService
from .server import YouTubeMCPServer


router = APIRouter(prefix="/youtube", tags=["YouTube MCP"])

# Database connection
db: Optional[DBConnection] = None


def initialize(database: DBConnection):
    """Initialize YouTube MCP with database connection"""
    global db
    db = database


@router.post("/auth/initiate")
async def initiate_auth(
    user_id: str = Depends(get_current_user_id_from_jwt)
) -> Dict[str, Any]:
    """Start YouTube OAuth flow"""
    try:
        oauth_handler = YouTubeOAuthHandler(db)
        auth_url = oauth_handler.get_auth_url(state=user_id)
        
        return {
            "success": True,
            "auth_url": auth_url,
            "message": "Visit the auth_url to connect your YouTube account"
        }
    except Exception as e:
        logger.error(f"Failed to initiate YouTube auth: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/auth/callback")
async def auth_callback(
    code: str,
    state: Optional[str] = None,
    error: Optional[str] = None
):
    """Handle YouTube OAuth callback"""
    
    if error:
        return HTMLResponse(content=f"""
            <html>
                <body>
                    <script>
                        window.opener.postMessage({{
                            type: 'youtube-auth-error',
                            error: '{error}'
                        }}, '*');
                        window.close();
                    </script>
                </body>
            </html>
        """)
    
    try:
        oauth_handler = YouTubeOAuthHandler(db)
        
        # Exchange code for tokens
        access_token, refresh_token, expires_at = await oauth_handler.exchange_code_for_tokens(code)
        
        # Get channel info
        channel_info = await oauth_handler.get_channel_info(access_token)
        
        # Save channel to database
        user_id = state  # We passed user_id as state
        channel_id = await oauth_handler.save_channel(
            user_id=user_id,
            channel_info=channel_info,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at
        )
        
        # Return success HTML that closes the popup
        return HTMLResponse(content=f"""
            <html>
                <body>
                    <script>
                        window.opener.postMessage({{
                            type: 'youtube-auth-success',
                            channel: {json.dumps(channel_info)}
                        }}, '*');
                        window.close();
                    </script>
                </body>
            </html>
        """)
        
    except Exception as e:
        logger.error(f"YouTube OAuth callback failed: {e}")
        return HTMLResponse(content=f"""
            <html>
                <body>
                    <script>
                        window.opener.postMessage({{
                            type: 'youtube-auth-error',
                            error: '{str(e)}'
                        }}, '*');
                        window.close();
                    </script>
                </body>
            </html>
        """)


@router.get("/channels")
async def get_channels(
    user_id: str = Depends(get_current_user_id_from_jwt)
) -> Dict[str, Any]:
    """Get user's YouTube channels"""
    try:
        channel_service = YouTubeChannelService(db)
        channels = await channel_service.get_user_channels(user_id)
        
        return {
            "success": True,
            "channels": channels,
            "count": len(channels)
        }
    except Exception as e:
        logger.error(f"Failed to get YouTube channels: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/channels/{channel_id}")
async def get_channel(
    channel_id: str,
    user_id: str = Depends(get_current_user_id_from_jwt)
) -> Dict[str, Any]:
    """Get specific YouTube channel details"""
    try:
        channel_service = YouTubeChannelService(db)
        channel = await channel_service.get_channel(user_id, channel_id)
        
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")
        
        return {
            "success": True,
            "channel": channel
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get YouTube channel: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/channels/{channel_id}")
async def remove_channel(
    channel_id: str,
    user_id: str = Depends(get_current_user_id_from_jwt)
) -> Dict[str, Any]:
    """Remove a YouTube channel connection"""
    try:
        oauth_handler = YouTubeOAuthHandler(db)
        success = await oauth_handler.remove_channel(user_id, channel_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Channel not found")
        
        return {
            "success": True,
            "message": f"Channel {channel_id} removed successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove YouTube channel: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh-token/{channel_id}")
async def refresh_token(
    channel_id: str,
    user_id: str = Depends(get_current_user_id_from_jwt)
) -> Dict[str, Any]:
    """Refresh access token for a channel"""
    try:
        oauth_handler = YouTubeOAuthHandler(db)
        access_token = await oauth_handler.get_valid_token(user_id, channel_id)
        
        return {
            "success": True,
            "message": "Token refreshed successfully"
        }
    except Exception as e:
        logger.error(f"Failed to refresh token: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/channels/{channel_id}/refresh")
async def refresh_channel_info(
    channel_id: str,
    user_id: str = Depends(get_current_user_id_from_jwt)
) -> Dict[str, Any]:
    """Refresh channel information including profile pictures"""
    try:
        oauth_handler = YouTubeOAuthHandler(db)
        
        # Get valid access token
        access_token = await oauth_handler.get_valid_token(user_id, channel_id)
        
        # Fetch updated channel info from YouTube API
        channel_info = await oauth_handler.get_channel_info(access_token)
        
        # Update channel in database
        client = await db.client
        update_data = {
            "name": channel_info["name"],
            "username": channel_info.get("username"),
            "custom_url": channel_info.get("custom_url"),
            "profile_picture": channel_info.get("profile_picture"),
            "profile_picture_medium": channel_info.get("profile_picture_medium"),
            "profile_picture_small": channel_info.get("profile_picture_small"),
            "description": channel_info.get("description"),
            "subscriber_count": channel_info.get("subscriber_count", 0),
            "view_count": channel_info.get("view_count", 0),
            "video_count": channel_info.get("video_count", 0),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        result = await client.table("youtube_channels").update(update_data).eq(
            "user_id", user_id
        ).eq("id", channel_id).execute()
        
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to update channel")
        
        logger.info(f"Refreshed channel info for {channel_id}")
        
        # Return updated channel info
        channel_service = YouTubeChannelService(db)
        channel = await channel_service.get_channel(user_id, channel_id)
        
        return {
            "success": True,
            "channel": channel,
            "message": "Channel information refreshed successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to refresh channel info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/channels/debug")
async def debug_channels(
    user_id: str = Depends(get_current_user_id_from_jwt)
) -> Dict[str, Any]:
    """Debug endpoint to check channel data"""
    try:
        client = await db.client
        result = await client.table("youtube_channels").select("*").eq(
            "user_id", user_id
        ).eq("is_active", True).execute()
        
        channels_debug = []
        for channel in result.data:
            channels_debug.append({
                "id": channel["id"],
                "name": channel["name"],
                "username": channel.get("username"),
                "has_profile_picture": bool(channel.get("profile_picture")),
                "profile_picture_url": channel.get("profile_picture"),
                "profile_picture_medium_url": channel.get("profile_picture_medium"),
                "profile_picture_small_url": channel.get("profile_picture_small"),
            })
        
        return {
            "success": True,
            "channels": channels_debug
        }
    except Exception as e:
        logger.error(f"Debug channels error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mcp-url")
async def get_mcp_url() -> Dict[str, Any]:
    """Get the MCP URL for YouTube integration"""
    # This returns the URL that the MCP client should connect to
    import os
    base_url = os.getenv("BACKEND_URL", "http://localhost:8000")
    
    return {
        "success": True,
        "mcp_url": f"{base_url}/api/youtube/mcp/stream",
        "name": "YouTube MCP",
        "description": "YouTube integration via Model Context Protocol"
    }


# MCP streaming endpoint
@router.post("/mcp/stream")
async def mcp_stream(request: Request):
    """Handle MCP protocol streaming"""
    # This would be handled by the MCP server
    # For now, return a placeholder
    return JSONResponse(content={
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": "youtube-mcp",
                "version": "1.0.0"
            }
        }
    })