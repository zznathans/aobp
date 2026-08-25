from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings, get_settings
from app.db.mongo import get_database
from app.deps import get_current_character
from app.models.character import CharacterDocument
from app.services import eve_sso

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
def login(request: Request, settings: Settings = Depends(get_settings)) -> RedirectResponse:
    pkce_pair = eve_sso.generate_pkce_pair()
    state = eve_sso.generate_state()
    request.session["pkce_verifier"] = pkce_pair.code_verifier
    request.session["pkce_state"] = state

    authorize_url = eve_sso.build_authorize_url(
        settings, code_challenge=pkce_pair.code_challenge, state=state
    )
    return RedirectResponse(authorize_url)


@router.get("/callback")
async def callback(
    request: Request,
    code: str,
    state: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    expected_state = request.session.get("pkce_state")
    code_verifier = request.session.get("pkce_verifier")
    if not expected_state or not code_verifier or state != expected_state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or missing OAuth state")

    token = await eve_sso.exchange_code_for_token(settings, code=code, code_verifier=code_verifier)
    claims = await eve_sso.validate_access_token(settings, token.access_token)

    now = datetime.now(UTC).replace(tzinfo=None)
    document = CharacterDocument(
        character_id=claims.character_id,
        character_name=claims.character_name,
        owner_hash=claims.owner_hash,
        scopes=claims.scopes,
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        access_token_expires_at=now + timedelta(seconds=token.expires_in),
        created_at=now,
        updated_at=now,
    )
    await db.characters.update_one(
        {"_id": claims.character_id},
        {
            "$set": document.model_dump(exclude={"created_at"}),
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )

    del request.session["pkce_verifier"]
    del request.session["pkce_state"]
    request.session["character_id"] = claims.character_id

    return RedirectResponse("/")


@router.get("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/")


@router.get("/me")
async def me(character: CharacterDocument = Depends(get_current_character)) -> dict[str, object]:
    return {
        "character_id": character.character_id,
        "character_name": character.character_name,
        "scopes": character.scopes,
    }
