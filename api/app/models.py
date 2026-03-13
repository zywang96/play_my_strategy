from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MoveDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"


class SyncStateRequest(BaseModel):
    session_id: str
    strategy_text: str = Field(..., description="Preferred 2048 playing strategy from the laptop")
    board_crop_b64: str = Field(..., description="Base64 encoded PNG/JPEG crop containing only the 4x4 2048 board")
    board_crop_mime_type: str = Field(default="image/png")


class SyncStateResponse(BaseModel):
    ok: bool = True
    session_id: str
    synced_at: str
    remaining_calls_this_hour: int = -1


class NextMoveRequest(BaseModel):
    session_id: str


class ActionPlan(BaseModel):
    move: MoveDirection
    reasoning: Optional[str] = None
    board: Optional[list[list[int]]] = None


class NextMoveResponse(BaseModel):
    ok: bool = True
    session_id: str
    action: ActionPlan
    model: str
    generated_at: str
    remaining_calls_this_hour: int = -1


class StatsResponse(BaseModel):
    ok: bool = True
    session_id: str
    total_requests: int = 0
    last_move: Optional[str] = None
    updated_at: Optional[str] = None
    remaining_calls_this_hour: int = -1


class BannerStatsRequest(BaseModel):
    banner_crop_b64: str = Field(..., description="Base64 encoded PNG/JPEG crop containing only the top banner")
    banner_crop_mime_type: str = Field(default="image/png")


class BannerStats(BaseModel):
    score: Optional[int] = None
    moves: Optional[int] = None
    time: Optional[str] = None


class BannerStatsResponse(BaseModel):
    ok: bool = True
    stats: BannerStats
    remaining_calls_this_hour: int = -1


class NextSessionIdResponse(BaseModel):
    ok: bool = True
    device_id: str
    session_id: str
    remaining_calls_this_hour: int = -1


class PlaygroundAsset(BaseModel):
    board_id: str
    label: str
    thumbnail_url: str
    board_image_url: str


class PlaygroundAssetsResponse(BaseModel):
    ok: bool = True
    assets: list[PlaygroundAsset]


class PlaygroundStepRequest(BaseModel):
    board_id: str
    strategy_text: str = Field(default="", description="Strategy text entered in the playground UI")


class PlaygroundStepResponse(BaseModel):
    ok: bool = True
    board_id: str
    action: ActionPlan
    model: str
    generated_at: str
    remaining_calls_this_hour: int
