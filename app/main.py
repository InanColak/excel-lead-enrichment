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

# Auth routes
from app.auth.routes import router as auth_router

app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
