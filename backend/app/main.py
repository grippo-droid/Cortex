"""Cortex API entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, chat, documents
from app.config import settings, verify_jwt_secret
from app.database import init_db
from app.observability import RequestLoggingMiddleware, configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    verify_jwt_secret()
    init_db()
    yield


app = FastAPI(title="Cortex API", version="0.1.0", lifespan=lifespan)

# Added last, so it wraps CORS and therefore sees every response, including the
# ones CORS short-circuits.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(chat.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
