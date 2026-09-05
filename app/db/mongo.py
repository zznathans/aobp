from fastapi import Request
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import Settings


def create_mongo_client(settings: Settings) -> AsyncIOMotorClient:
    return AsyncIOMotorClient(settings.mongodb_uri, maxPoolSize=settings.mongodb_max_pool_size)


def get_database(request: Request) -> AsyncIOMotorDatabase:
    client: AsyncIOMotorClient = request.app.state.mongo_client
    settings: Settings = request.app.state.settings
    return client[settings.mongodb_database]
