import asyncio
from daytona_sdk import AsyncDaytona, DaytonaConfig, CreateSandboxFromSnapshotParams, Resources
from utils.config import config
import uuid

async def test_kortix_sandbox():
    print(f"Testing with snapshot: {config.SANDBOX_SNAPSHOT_NAME}")
    print(f"API Key: {config.DAYTONA_API_KEY[:10]}...")
    print(f"Server URL: {config.DAYTONA_SERVER_URL}")
    print("-" * 50)
    
    daytona_config = DaytonaConfig(
        api_key=config.DAYTONA_API_KEY,
        api_url=config.DAYTONA_SERVER_URL,
        target=config.DAYTONA_TARGET,
    )
    
    daytona = AsyncDaytona(daytona_config)
    
    try:
        # List existing sandboxes
        print("Checking existing sandboxes...")
        sandboxes = await daytona.list()
        print(f"Found {len(sandboxes)} existing sandboxes")
        
        # Create a test sandbox
        print(f"\nCreating sandbox with {config.SANDBOX_SNAPSHOT_NAME}...")
        params = CreateSandboxFromSnapshotParams(
            snapshot=config.SANDBOX_SNAPSHOT_NAME,
            public=True,
            labels={'test': 'kortix-test', 'project_id': str(uuid.uuid4())},
            env_vars={
                "VNC_PASSWORD": str(uuid.uuid4()),
                "RESOLUTION": "1024x768x24",
                "CHROME_PERSISTENT_SESSION": "true",
            },
            resources=Resources(cpu=4, memory=8, disk=10),
            auto_stop_interval=15,
            auto_archive_interval=120,
        )
        
        sandbox = await daytona.create(params)
        print(f"✅ Sandbox created: {sandbox.id}")
        print(f"   State: {sandbox.state}")
        
        # Test supervisord
        from sandbox.sandbox import start_supervisord_session
        print("\nTesting supervisord startup...")
        try:
            await start_supervisord_session(sandbox)
            print("✅ Supervisord started successfully")
        except Exception as e:
            print(f"❌ Supervisord failed: {e}")
        
        # Get preview links
        vnc_link = await sandbox.get_preview_link(6080)
        print(f"\nVNC Preview: {vnc_link.url if hasattr(vnc_link, 'url') else 'N/A'}")
        
        # Clean up
        print("\nCleaning up...")
        await daytona.delete(sandbox)
        print("Sandbox deleted")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_kortix_sandbox())