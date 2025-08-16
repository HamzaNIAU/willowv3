from typing import Optional
import uuid
import asyncio
import time

from agentpress.thread_manager import ThreadManager
from agentpress.tool import Tool
from daytona_sdk import AsyncSandbox
from sandbox.sandbox import get_or_start_sandbox, create_sandbox, delete_sandbox
from sandbox.daytona_health import daytona_pre_flight_check, get_daytona_health_checker
from utils.logger import logger
from utils.files_utils import clean_path
from utils.error_handler import SandboxError, TransientError

class SandboxToolsBase(Tool):
    """Base class for all sandbox tools that provides project-based sandbox access."""
    
    # Class variable to track if sandbox URLs have been printed
    _urls_printed = False
    
    def __init__(self, project_id: str, thread_manager: Optional[ThreadManager] = None):
        super().__init__()
        self.project_id = project_id
        self.thread_manager = thread_manager
        self.workspace_path = "/workspace"
        self._sandbox = None
        self._sandbox_id = None
        self._sandbox_pass = None

    async def _ensure_sandbox(self) -> AsyncSandbox:
        """Ensure we have a valid sandbox instance, retrieving it from the project if needed.

        If the project does not yet have a sandbox, create it lazily and persist
        the metadata to the `projects` table so subsequent calls can reuse it.
        """
        if self._sandbox is None:
            # Pre-flight check for Daytona service
            is_healthy, error_msg = await daytona_pre_flight_check()
            if not is_healthy:
                logger.error(f"Daytona service is not healthy: {error_msg}")
                raise SandboxError(f"Cannot create sandbox: {error_msg}")
            
            try:
                # Get database client
                client = await self.thread_manager.db.client

                # Get project data
                project = await client.table('projects').select('*').eq('project_id', self.project_id).execute()
                if not project.data or len(project.data) == 0:
                    raise ValueError(f"Project {self.project_id} not found")

                project_data = project.data[0]
                sandbox_info = project_data.get('sandbox') or {}

                # If there is no sandbox recorded for this project, create one lazily
                if not sandbox_info.get('id'):
                    logger.info(f"No sandbox recorded for project {self.project_id}; creating lazily")
                    sandbox_pass = str(uuid.uuid4())
                    
                    # Retry sandbox creation with exponential backoff
                    max_retries = 3
                    retry_delay = 2.0
                    sandbox_obj = None
                    
                    for attempt in range(max_retries):
                        try:
                            logger.info(f"Creating sandbox (attempt {attempt + 1}/{max_retries})")
                            sandbox_obj = await asyncio.wait_for(
                                create_sandbox(sandbox_pass, self.project_id),
                                timeout=15.0  # 15 second timeout for creation
                            )
                            sandbox_id = sandbox_obj.id
                            logger.info(f"Successfully created sandbox {sandbox_id}")
                            break
                        except asyncio.TimeoutError:
                            if attempt < max_retries - 1:
                                logger.warning(f"Sandbox creation timed out, retrying in {retry_delay}s...")
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 2  # Exponential backoff
                            else:
                                raise TransientError("Sandbox creation timed out after multiple attempts")
                        except Exception as e:
                            if attempt < max_retries - 1:
                                logger.warning(f"Sandbox creation failed: {e}, retrying in {retry_delay}s...")
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 2
                            else:
                                raise
                    
                    if not sandbox_obj:
                        raise SandboxError("Failed to create sandbox after all retries")

                    # Gather preview links and token (best-effort parsing)
                    try:
                        vnc_link = await sandbox_obj.get_preview_link(6080)
                        website_link = await sandbox_obj.get_preview_link(8080)
                        vnc_url = vnc_link.url if hasattr(vnc_link, 'url') else str(vnc_link).split("url='")[1].split("'")[0]
                        website_url = website_link.url if hasattr(website_link, 'url') else str(website_link).split("url='")[1].split("'")[0]
                        token = vnc_link.token if hasattr(vnc_link, 'token') else (str(vnc_link).split("token='")[1].split("'")[0] if "token='" in str(vnc_link) else None)
                    except Exception:
                        # If preview link extraction fails, still proceed but leave fields None
                        logger.warning(f"Failed to extract preview links for sandbox {sandbox_id}", exc_info=True)
                        vnc_url = None
                        website_url = None
                        token = None

                    # Persist sandbox metadata to project record
                    update_result = await client.table('projects').update({
                        'sandbox': {
                            'id': sandbox_id,
                            'pass': sandbox_pass,
                            'vnc_preview': vnc_url,
                            'sandbox_url': website_url,
                            'token': token
                        }
                    }).eq('project_id', self.project_id).execute()

                    if not update_result.data:
                        # Cleanup created sandbox if DB update failed
                        try:
                            await delete_sandbox(sandbox_id)
                        except Exception:
                            logger.error(f"Failed to delete sandbox {sandbox_id} after DB update failure", exc_info=True)
                        raise Exception("Database update failed when storing sandbox metadata")

                    # Store local metadata and ensure sandbox is ready
                    self._sandbox_id = sandbox_id
                    self._sandbox_pass = sandbox_pass
                    self._sandbox = await get_or_start_sandbox(self._sandbox_id)
                else:
                    # Use existing sandbox metadata
                    self._sandbox_id = sandbox_info['id']
                    self._sandbox_pass = sandbox_info.get('pass')
                    
                    # Retry getting existing sandbox with timeout
                    max_retries = 3
                    retry_delay = 1.0
                    
                    for attempt in range(max_retries):
                        try:
                            logger.info(f"Getting sandbox {self._sandbox_id} (attempt {attempt + 1}/{max_retries})")
                            self._sandbox = await asyncio.wait_for(
                                get_or_start_sandbox(self._sandbox_id),
                                timeout=10.0  # 10 second timeout for getting existing sandbox
                            )
                            logger.info(f"Successfully connected to sandbox {self._sandbox_id}")
                            break
                        except asyncio.TimeoutError:
                            if attempt < max_retries - 1:
                                logger.warning(f"Getting sandbox timed out, retrying in {retry_delay}s...")
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 2
                            else:
                                raise TransientError(f"Failed to connect to sandbox {self._sandbox_id} after multiple attempts")
                        except Exception as e:
                            if attempt < max_retries - 1:
                                logger.warning(f"Failed to get sandbox: {e}, retrying in {retry_delay}s...")
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 2
                            else:
                                raise

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error retrieving/creating sandbox for project {self.project_id}: {error_msg}", exc_info=True)
                
                # If sandbox service is unavailable, return None to allow tools to handle it
                if "timed out" in error_msg.lower() or "daytona" in error_msg.lower():
                    logger.warning(f"Sandbox service appears to be unavailable - tools may have limited functionality")
                    return None
                raise e

        return self._sandbox

    @property
    def sandbox(self) -> AsyncSandbox:
        """Get the sandbox instance, ensuring it exists."""
        if self._sandbox is None:
            raise RuntimeError("Sandbox not initialized. Call _ensure_sandbox() first.")
        return self._sandbox

    @property
    def sandbox_id(self) -> str:
        """Get the sandbox ID, ensuring it exists."""
        if self._sandbox_id is None:
            raise RuntimeError("Sandbox ID not initialized. Call _ensure_sandbox() first.")
        return self._sandbox_id

    def clean_path(self, path: str) -> str:
        """Clean and normalize a path to be relative to /workspace."""
        cleaned_path = clean_path(path, self.workspace_path)
        logger.debug(f"Cleaned path: {path} -> {cleaned_path}")
        return cleaned_path