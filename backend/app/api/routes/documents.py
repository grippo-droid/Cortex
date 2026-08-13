"""Document routes. Endpoints land in Phase 2 (T2.1 upload, T2.5 list)."""

from fastapi import APIRouter

router = APIRouter(prefix="/documents", tags=["documents"])
