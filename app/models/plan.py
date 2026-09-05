from datetime import datetime

from pydantic import BaseModel, Field


class PlanLine(BaseModel):
    line_id: str
    type_id: int
    runs: int
    material_efficiency: int
    source_item_id: int | None = None
    location_id: int | None = None


class PlanDocument(BaseModel):
    id: str = Field(alias="_id")
    character_id: int
    name: str
    lines: list[PlanLine]
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}
