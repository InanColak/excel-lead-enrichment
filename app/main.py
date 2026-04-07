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

# Admin routes
from app.admin.routes import router as admin_router

app.include_router(admin_router, prefix="/api/v1/admin", tags=["admin"])

# Jobs routes
from app.jobs.routes import router as jobs_router

app.include_router(jobs_router, prefix="/api/v1/jobs", tags=["jobs"])

# Webhook routes (no JWT auth — uses shared secret per D-42/D-45)
from app.enrichment.routes import router as webhook_router

app.include_router(webhook_router, prefix="/api/v1", tags=["webhooks"])
