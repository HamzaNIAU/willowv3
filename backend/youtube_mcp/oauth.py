"""YouTube OAuth handler for MCP integration"""

import os
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlencode

import aiohttp
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    GOOGLE_AUTH_AVAILABLE = False
    Request = None
    Credentials = None
    build = None
from cryptography.fernet import Fernet

from services.supabase import DBConnection
from utils.logger import logger


class YouTubeOAuthHandler:
    """Handles YouTube OAuth flow and token management"""
    
    OAUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
        "https://www.googleapis.com/auth/youtube.force-ssl",
    ]
    
    def __init__(self, db: DBConnection):
        self.db = db
        self.client_id = os.getenv("YOUTUBE_CLIENT_ID")
        self.client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
        self.redirect_uri = os.getenv("YOUTUBE_REDIRECT_URI", "http://localhost:8000/api/youtube/auth/callback")
        
        # Encryption key for tokens
        encryption_key = os.getenv("MCP_CREDENTIAL_ENCRYPTION_KEY")
        if encryption_key:
            self.fernet = Fernet(encryption_key.encode())
        else:
            # Generate a key if not provided (not recommended for production)
            logger.warning("No MCP_CREDENTIAL_ENCRYPTION_KEY found, generating temporary key")
            self.fernet = Fernet(Fernet.generate_key())
        
        if not self.client_id or not self.client_secret:
            raise ValueError("YouTube OAuth credentials not configured")
    
    def get_auth_url(self, state: Optional[str] = None) -> str:
        """Generate OAuth authorization URL"""
        if not state:
            state = secrets.token_urlsafe(32)
        
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        
        return f"{self.OAUTH_URL}?{urlencode(params)}"
    
    async def exchange_code_for_tokens(self, code: str) -> Tuple[str, str, datetime]:
        """Exchange authorization code for access and refresh tokens"""
        async with aiohttp.ClientSession() as session:
            data = {
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            }
            
            async with session.post(self.TOKEN_URL, data=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Token exchange failed: {error_text}")
                
                token_data = await response.json()
                
                access_token = token_data["access_token"]
                refresh_token = token_data.get("refresh_token")
                expires_in = token_data.get("expires_in", 3600)
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                
                return access_token, refresh_token, expires_at
    
    async def refresh_access_token(self, refresh_token: str) -> Tuple[str, datetime]:
        """Refresh an expired access token"""
        async with aiohttp.ClientSession() as session:
            data = {
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
            }
            
            async with session.post(self.TOKEN_URL, data=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Token refresh failed: {error_text}")
                
                token_data = await response.json()
                
                access_token = token_data["access_token"]
                expires_in = token_data.get("expires_in", 3600)
                expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                
                return access_token, expires_at
    
    async def get_channel_info(self, access_token: str) -> Dict[str, Any]:
        """Fetch YouTube channel information for authenticated user"""
        credentials = Credentials(token=access_token)
        youtube = build("youtube", "v3", credentials=credentials)
        
        try:
            # Get user's channel
            channels_response = youtube.channels().list(
                part="snippet,statistics,contentDetails",
                mine=True
            ).execute()
            
            if not channels_response.get("items"):
                raise Exception("No YouTube channel found for this account")
            
            channel = channels_response["items"][0]
            snippet = channel.get("snippet", {})
            statistics = channel.get("statistics", {})
            
            # Extract channel information
            thumbnails = snippet.get("thumbnails", {})
            
            # Try to get the best available thumbnail
            profile_picture = (
                thumbnails.get("high", {}).get("url") or
                thumbnails.get("medium", {}).get("url") or
                thumbnails.get("default", {}).get("url")
            )
            
            channel_info = {
                "id": channel["id"],
                "name": snippet.get("title", ""),
                "username": snippet.get("customUrl", "").replace("@", "") if snippet.get("customUrl") else None,
                "custom_url": snippet.get("customUrl"),
                "description": snippet.get("description", ""),
                "profile_picture": profile_picture,
                "profile_picture_medium": thumbnails.get("medium", {}).get("url") or profile_picture,
                "profile_picture_small": thumbnails.get("default", {}).get("url") or profile_picture,
                "subscriber_count": int(statistics.get("subscriberCount", 0)),
                "view_count": int(statistics.get("viewCount", 0)),
                "video_count": int(statistics.get("videoCount", 0)),
                "country": snippet.get("country"),
                "published_at": snippet.get("publishedAt"),
            }
            
            logger.info(f"Fetched channel info for {channel_info['name']}: profile_picture={profile_picture}")
            
            return channel_info
            
        except Exception as e:
            logger.error(f"Failed to fetch channel info: {e}")
            raise
    
    def encrypt_token(self, token: str) -> str:
        """Encrypt a token for storage"""
        return self.fernet.encrypt(token.encode()).decode()
    
    def decrypt_token(self, encrypted_token: str) -> str:
        """Decrypt a stored token"""
        return self.fernet.decrypt(encrypted_token.encode()).decode()
    
    async def save_channel(
        self,
        user_id: str,
        channel_info: Dict[str, Any],
        access_token: str,
        refresh_token: Optional[str],
        expires_at: datetime
    ) -> str:
        """Save YouTube channel to database"""
        client = await self.db.client
        
        # Encrypt tokens
        encrypted_access = self.encrypt_token(access_token)
        encrypted_refresh = self.encrypt_token(refresh_token) if refresh_token else None
        
        # Prepare channel data
        channel_data = {
            "id": channel_info["id"],
            "user_id": user_id,
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
            "country": channel_info.get("country"),
            "published_at": channel_info.get("published_at"),
            "access_token": encrypted_access,
            "refresh_token": encrypted_refresh,
            "token_expires_at": expires_at.isoformat(),
            "token_scopes": self.SCOPES,
            "is_active": True,
        }
        
        # Upsert channel (update if exists, insert if not)
        result = await client.table("youtube_channels").upsert(
            channel_data,
            on_conflict="id,user_id"
        ).execute()
        
        if result.data:
            logger.info(f"Saved YouTube channel {channel_info['id']} for user {user_id} with profile_picture: {channel_info.get('profile_picture')}")
            return channel_info["id"]
        else:
            raise Exception("Failed to save YouTube channel")
    
    async def get_valid_token(self, user_id: str, channel_id: str) -> str:
        """Get a valid access token, refreshing if necessary"""
        client = await self.db.client
        
        # Get channel from database
        result = await client.table("youtube_channels").select("*").eq(
            "user_id", user_id
        ).eq("id", channel_id).execute()
        
        if not result.data:
            raise Exception(f"YouTube channel {channel_id} not found")
        
        channel = result.data[0]
        
        # Decrypt tokens
        access_token = self.decrypt_token(channel["access_token"])
        refresh_token = self.decrypt_token(channel["refresh_token"]) if channel.get("refresh_token") else None
        
        # Check if token is expired (with 5-minute buffer)
        expires_at = datetime.fromisoformat(channel["token_expires_at"].replace("Z", "+00:00"))
        buffer_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        
        if expires_at > buffer_time:
            # Token is still valid
            return access_token
        
        # Token needs refresh
        if not refresh_token:
            raise Exception("Access token expired and no refresh token available")
        
        logger.info(f"Refreshing access token for channel {channel_id}")
        
        try:
            new_access_token, new_expires_at = await self.refresh_access_token(refresh_token)
            
            # Update token in database
            encrypted_access = self.encrypt_token(new_access_token)
            
            await client.table("youtube_channels").update({
                "access_token": encrypted_access,
                "token_expires_at": new_expires_at.isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", channel_id).eq("user_id", user_id).execute()
            
            return new_access_token
            
        except Exception as e:
            logger.error(f"Failed to refresh token: {e}")
            
            # Mark channel as inactive if refresh fails
            await client.table("youtube_channels").update({
                "is_active": False,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", channel_id).eq("user_id", user_id).execute()
            
            raise Exception(f"Failed to refresh access token: {e}")
    
    async def get_user_channels(self, user_id: str) -> list:
        """Get all YouTube channels for a user"""
        client = await self.db.client
        
        result = await client.table("youtube_channels").select("*").eq(
            "user_id", user_id
        ).eq("is_active", True).execute()
        
        channels = []
        for channel in result.data:
            channels.append({
                "id": channel["id"],
                "name": channel["name"],
                "username": channel.get("username"),
                "profile_picture": channel.get("profile_picture"),
                "subscriber_count": channel.get("subscriber_count", 0),
                "video_count": channel.get("video_count", 0),
                "view_count": channel.get("view_count", 0),
            })
        
        return channels
    
    async def remove_channel(self, user_id: str, channel_id: str) -> bool:
        """Remove a YouTube channel connection"""
        client = await self.db.client
        
        result = await client.table("youtube_channels").delete().eq(
            "user_id", user_id
        ).eq("id", channel_id).execute()
        
        if result.data:
            logger.info(f"Removed YouTube channel {channel_id} for user {user_id}")
            return True
        
        return False