"""Inputvalidering for API'et."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

ItemType = Literal["speech", "video", "other"]
Placement = Literal["bottom", "top", "after_live"]


class _Text(BaseModel):
    @field_validator("title", "description", "technical_notes", mode="before", check_fields=False)
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class ItemCreate(_Text):
    title: str = Field(min_length=1, max_length=200)
    item_type: ItemType = "speech"
    description: str = Field(default="", max_length=5000)
    technical_notes: str = Field(default="", max_length=5000)
    duration_seconds: int = Field(default=0, ge=0, le=24 * 3600)
    optional: bool = False
    # Placering ved oprettelse (standard: sidst)
    after_id: Optional[int] = None
    place: Optional[Placement] = None


class ItemUpdate(_Text):
    expected_version: int = Field(ge=1)
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    item_type: Optional[ItemType] = None
    description: Optional[str] = Field(default=None, max_length=5000)
    technical_notes: Optional[str] = Field(default=None, max_length=5000)
    duration_seconds: Optional[int] = Field(default=None, ge=0, le=24 * 3600)
    optional: Optional[bool] = None


class ActionRequest(BaseModel):
    # Den status klienten så, da brugeren trykkede. Bruges til at afvise
    # handlinger baseret på forældet tilstand.
    expected_status: Optional[str] = None


class MoveRequest(BaseModel):
    direction: Literal["up", "down"]


class PlaceRequest(BaseModel):
    """Flyt et punkt: før/efter et andet punkt, eller øverst/sidst/efter det, der afvikles."""

    before_id: Optional[int] = None
    after_id: Optional[int] = None
    where: Optional[Placement] = None
