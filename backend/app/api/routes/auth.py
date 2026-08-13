"""Auth routes. Endpoints land in T1.1 (register) and T1.2 (login)."""

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])
