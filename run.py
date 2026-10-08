"""
NiftyTrade Server Launcher with reload restricted to the app/ directory.
Prevents watchfiles / uvicorn from endlessly restarting on SQLite .db updates.
"""
import uvicorn

if __name__ == "__main__":
    print("Starting NiftyTrade on http://127.0.0.1:8000 (reload restricted to 'app' directory)...")
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=["app"]
    )
