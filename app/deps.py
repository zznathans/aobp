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

    updates: dict[str, object] = {}

    if document.access_token_expires_at <= _utcnow_naive():
        token = await eve_sso.refresh_access_token(settings, refresh_token=document.refresh_token)
        document.access_token = token.access_token
        document.refresh_token = token.refresh_token
        document.access_token_expires_at = _expires_at(token.expires_in)
        updates["access_token"] = document.access_token
        updates["refresh_token"] = document.refresh_token
        updates["access_token_expires_at"] = document.access_token_expires_at

    if (
        document.corp_refresh_token is not None
        and document.corp_access_token_expires_at is not None
        and document.corp_access_token_expires_at <= _utcnow_naive()
    ):
        corp_token = await eve_sso.refresh_access_token(
            settings, refresh_token=document.corp_refresh_token
        )
        document.corp_access_token = corp_token.access_token
        document.corp_refresh_token = corp_token.refresh_token
        document.corp_access_token_expires_at = _expires_at(corp_token.expires_in)
        updates["corp_access_token"] = document.corp_access_token
        updates["corp_refresh_token"] = document.corp_refresh_token
        updates["corp_access_token_expires_at"] = document.corp_access_token_expires_at

    if updates:
        document.updated_at = _utcnow_naive()
        updates["updated_at"] = document.updated_at
        await db.characters.update_one({"_id": character_id}, {"$set": updates})

    return document


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _expires_at(expires_in: int) -> datetime:
    return _utcnow_naive() + timedelta(seconds=expires_in)
