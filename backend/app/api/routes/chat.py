"""Chat routes. Session creation and the WebSocket stream land in Phase 3."""

from fastapi import APIRouter

router = APIRouter(prefix="/chat", tags=["chat"])
