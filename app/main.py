import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import engine, Base, SessionLocal
from app.services.seed_service import seed_database
from app.services.price_simulator import run_price_simulator

# Import all models to ensure they register with Base
import app.models # noqa

# Import routers
from app.routers import (
    web_auth,
    web_dashboard,
    web_market,
    web_trading,
    web_profile,
    web_admin,
    api_oauth,
    api_v1,
    api_simulation,
    health,
    internal_api
)


simulator_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Startup: Create tables and seed initial data
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()

    # 2. Start background price simulator task
    sim_task = asyncio.create_task(run_price_simulator())
    yield
    # 3. Shutdown: Cancel simulator task
    sim_task.cancel()
    try:
        await sim_task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title=f"{settings.BROKER_NAME} API",
    description="Simulated Indian Discount Broker Platform & Kite-Connect-compatible Sandbox API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static Files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include Routers
app.include_router(health.router)
app.include_router(web_auth.router)
app.include_router(web_dashboard.router)
app.include_router(web_market.router)
app.include_router(web_trading.router)
app.include_router(web_profile.router)
app.include_router(web_admin.router)
app.include_router(api_oauth.router)
app.include_router(api_v1.router)
app.include_router(api_simulation.router)
app.include_router(internal_api.router)
