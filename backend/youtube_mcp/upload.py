"""YouTube Upload Service - Handles video uploads to YouTube"""

import os
import uuid
from typing import Dict, Any, Optional
from datetime import datetime, timezone

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2.credentials import Credentials
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False
    build = None
    MediaFileUpload = None
    Credentials = None

from services.supabase import DBConnection
from utils.logger import logger
from .oauth import YouTubeOAuthHandler


class YouTubeUploadService:
    """Service for uploading videos to YouTube"""
    
    def __init__(self, db: DBConnection):
        self.db = db
        self.oauth_handler = YouTubeOAuthHandler(db)
    
    async def upload_video(self, user_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Upload a video to YouTube"""
        
        channel_id = params["channel_id"]
        
        # Get valid access token
        access_token = await self.oauth_handler.get_valid_token(user_id, channel_id)
        
        # Get channel info
        client = await self.db.client
        channel_result = await client.table("youtube_channels").select("name").eq(
            "user_id", user_id
        ).eq("id", channel_id).execute()
        
        if not channel_result.data:
            raise Exception(f"Channel {channel_id} not found")
        
        channel_name = channel_result.data[0]["name"]
        
        # Create upload record
        upload_id = str(uuid.uuid4())
        upload_data = {
            "id": upload_id,
            "user_id": user_id,
            "channel_id": channel_id,
            "title": params["title"],
            "description": params.get("description", ""),
            "tags": params.get("tags", []),
            "category_id": params.get("category_id", "22"),
            "privacy_status": params.get("privacy_status", "public"),
            "made_for_kids": params.get("made_for_kids", False),
            "file_name": "video.mp4",  # This would come from the file reference
            "file_size": 0,  # This would come from the file reference
            "upload_status": "pending",
            "video_reference_id": params.get("video_reference_id"),
            "thumbnail_reference_id": params.get("thumbnail_reference_id"),
            "scheduled_for": params.get("scheduled_for"),
            "notify_subscribers": params.get("notify_subscribers", True),
        }
        
        result = await client.table("youtube_uploads").insert(upload_data).execute()
        
        if not result.data:
            raise Exception("Failed to create upload record")
        
        # Note: Actual video upload implementation would go here
        # This would involve:
        # 1. Getting the file from video_file_references using video_reference_id
        # 2. Using YouTube API to upload the video
        # 3. Updating the upload record with progress
        # 4. Handling resumable uploads for large files
        
        # For now, return a placeholder response
        logger.info(f"Upload initiated for video '{params['title']}' to channel {channel_id}")
        
        return {
            "upload_id": upload_id,
            "channel_name": channel_name,
            "status": "pending",
            "message": f"Upload queued for '{params['title']}'"
        }
    
    async def get_upload_status(self, user_id: str, upload_id: str) -> Dict[str, Any]:
        """Get the status of an upload"""
        client = await self.db.client
        
        result = await client.table("youtube_uploads").select("*").eq(
            "user_id", user_id
        ).eq("id", upload_id).execute()
        
        if not result.data:
            raise Exception(f"Upload {upload_id} not found")
        
        upload = result.data[0]
        
        return {
            "upload_id": upload["id"],
            "title": upload["title"],
            "status": upload["upload_status"],
            "progress": upload.get("upload_progress", 0),
            "video_id": upload.get("video_id"),
            "message": upload.get("status_message", ""),
            "created_at": upload.get("created_at"),
            "completed_at": upload.get("completed_at"),
        }