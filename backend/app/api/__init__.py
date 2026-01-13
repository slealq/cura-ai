"""API router combining all endpoints."""
from fastapi import APIRouter

from app.api.clusters import router as clusters_router
from app.api.images import router as images_router
from app.api.jobs import router as jobs_router
from app.api.search import router as search_router

api_router = APIRouter()

api_router.include_router(images_router)
api_router.include_router(clusters_router)
api_router.include_router(search_router)
api_router.include_router(jobs_router)
