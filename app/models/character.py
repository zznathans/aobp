from datetime import datetime

from pydantic import BaseModel


class CharacterDocument(BaseModel):
    character_id: int
    character_name: str
    owner_hash: str
    scopes: list[str]
    access_token: str
    refresh_token: str
    access_token_expires_at: datetime
    created_at: datetime
    updated_at: datetime
