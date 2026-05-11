import sys
import asyncio
import uvicorn
import os

if __name__ == "__main__":
    # Set the event loop policy to WindowsProactorEventLoopPolicy on Windows
    # This is required for Playwright to work with asyncio on Windows
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        print("Set WindowsProactorEventLoopPolicy for Playwright compatibility.")

    # Run Uvicorn
    # reload=False is safer for Windows + Playwright + asyncio policy
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
