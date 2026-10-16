from contextlib import asynccontextmanager


from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


from app.api import admin, assets, auth, clients, health, options, quotes, users, ws
from app.config import get_settings
from app.core.logging import setup_logging



@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    yield



settings = get_settings()
app = FastAPI(
    title="THLPro Backend",
    version=settings.app_version,
    description="API do sistema THLPro para análise profissional de opções.",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(assets.router)
app.include_router(options.router)
app.include_router(quotes.router)
app.include_router(clients.router)
app.include_router(admin.router)
app.include_router(ws.router)