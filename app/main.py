from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import initialize_database
from app.errors import register_error_handlers
from app.offerings import router as offerings_router
from app.offerings import temples_router
from app.orders import router as orders_router
from app.schemas import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(lifespan=lifespan)
register_error_handlers(app)
app.include_router(offerings_router)
app.include_router(temples_router)
app.include_router(orders_router)


@app.get("/health")
def health_check() -> HealthResponse:
    return {"status": "ok"}