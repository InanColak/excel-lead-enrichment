from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.health.routes import router as health_router

app = FastAPI(
    title="LeadEnrich API",
    version="1.0.0",
    description="Apollo-Powered Contact Enrichment Platform",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Will be restricted when dashboard integration happens
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health endpoint at root level (no /api/v1 prefix) for Docker healthcheck
app.include_router(health_router)

# Auth and admin routers will be added in Plan 02 under /api/v1/ prefix
