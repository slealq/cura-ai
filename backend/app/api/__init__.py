"""API router combining all endpoints."""
from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.clusters import router as clusters_router
from app.api.edit import router as edit_router
from app.api.folders import router as folders_router
from app.api.generation import router as generation_router
from app.api.images import router as images_router
from app.api.jobs import router as jobs_router
from app.api.logs import router as logs_router
from app.api.search import router as search_router
from app.api.settings import router as settings_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(images_router)
api_router.include_router(folders_router)
api_router.include_router(clusters_router)
api_router.include_router(search_router)
api_router.include_router(jobs_router)
api_router.include_router(logs_router)
api_router.include_router(settings_router)
api_router.include_router(generation_router)
api_router.include_router(edit_router)
