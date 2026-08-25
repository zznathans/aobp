from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings, get_settings
from app.db.mongo import get_database
from app.models.character import CharacterDocument
from app.services import eve_sso


async def get_current_character(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> CharacterDocument:
    character = await get_current_character_optional(request, db, settings)
    if character is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return character


async def get_current_character_optional(
    request: Request,
    db: AsyncIOMotorDatabase = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> CharacterDocument | None:
    character_id = request.session.get("character_id")
    if character_id is None:
        return None

    raw_doc = await db.characters.find_one({"_id": character_id})
    if raw_doc is None:
        return None

    document = CharacterDocument.model_validate(raw_doc)

    if document.access_token_expires_at <= _utcnow_naive():
        token = await eve_sso.refresh_access_token(settings, refresh_token=document.refresh_token)
        document.access_token = token.access_token
        document.refresh_token = token.refresh_token
        document.access_token_expires_at = _expires_at(token.expires_in)
        document.updated_at = _utcnow_naive()
        await db.characters.update_one(
            {"_id": character_id},
            {
                "$set": {
                    "access_token": document.access_token,
                    "refresh_token": document.refresh_token,
                    "access_token_expires_at": document.access_token_expires_at,
                    "updated_at": document.updated_at,
                }
            },
        )

    return document


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _expires_at(expires_in: int) -> datetime:
    return _utcnow_naive() + timedelta(seconds=expires_in)
