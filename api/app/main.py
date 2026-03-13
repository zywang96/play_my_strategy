from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .gemini import GeminiPlanner
from .models import (
    BannerStatsRequest,
    BannerStatsResponse,
    NextMoveRequest,
    NextMoveResponse,
    NextSessionIdResponse,
    PlaygroundStepRequest,
    PlaygroundStepResponse,
    StatsResponse,
    SyncStateRequest,
    SyncStateResponse,
)
from .playground import build_playground_html, catalog, get_client_ip
from .store import FirestoreStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Gemini 2048 Navigator API", version="0.7.0")
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = FirestoreStore()
planner = GeminiPlanner()


GLOBAL_POST_ENDPOINTS = {
    "/playground/api/step",
    "/getNextMove",
    "/extractBannerStats",
}

GLOBAL_GET_ENDPOINTS = {
    "/healthz",
    "/playground",
    "/getStats",
    "/nextSessionId",
}

GLOBAL_QUOTAS = {
    "global_post": 50,
    "global_get": 120,
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def enforce_endpoint_limit(request: Request) -> int | None:
    path = request.url.path
    bucket_key = None
    max_calls = None
    if request.method == "POST" and path in GLOBAL_POST_ENDPOINTS:
        bucket_key = "global_post"
        max_calls = GLOBAL_QUOTAS[bucket_key]
    elif request.method == "GET" and path in GLOBAL_GET_ENDPOINTS:
        bucket_key = "global_get"
        max_calls = GLOBAL_QUOTAS[bucket_key]

    if bucket_key is None or max_calls is None:
        return None

    try:
        return store.reserve_rate_limited_call(
            namespace="api_rate_limits",
            bucket_key=bucket_key,
            max_calls=max_calls,
            window_unit="hour",
            metadata={
                "last_path": path,
                "last_method": request.method,
                "last_client_ip": get_client_ip(request),
            },
            logger = logger,
        )
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@app.get("/healthz")
def healthz():
    return {"ok": True, "time": utcnow_iso()}


@app.get("/playground", response_class=HTMLResponse)
def playground_page():
    return HTMLResponse(build_playground_html())




@app.post("/playground/api/step", response_model=PlaygroundStepResponse)
def playground_step(req: PlaygroundStepRequest, request: Request):
    remaining_calls = enforce_endpoint_limit(request)

    board_crop_b64, mime_type = catalog.load_board_as_b64(req.board_id)

    try:
        action = planner.plan_move(
            board_crop_b64=board_crop_b64,
            board_crop_mime_type=mime_type,
            strategy_text=req.strategy_text,
            logger=logger,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Planner failed: {exc}") from exc

    generated_at = utcnow_iso()
    return PlaygroundStepResponse(
        board_id=req.board_id,
        action=action,
        model=planner.model,
        generated_at=generated_at,
        remaining_calls_this_hour=remaining_calls if remaining_calls is not None else -1,
    )


@app.post("/syncState", response_model=SyncStateResponse)
def sync_state(req: SyncStateRequest, request: Request):
    remaining_calls = enforce_endpoint_limit(request)
    record = store.sync_local_state(
        session_id=req.session_id,
        strategy_text=req.strategy_text,
        board_crop_b64=req.board_crop_b64,
        board_crop_mime_type=req.board_crop_mime_type,
    )
    return SyncStateResponse(
        session_id=req.session_id,
        synced_at=record["latest_input"]["synced_at"],
        remaining_calls_this_hour=remaining_calls if remaining_calls is not None else -1,
    )


@app.post("/getNextMove", response_model=NextMoveResponse)
def get_next_move(req: NextMoveRequest, request: Request):
    remaining_calls = enforce_endpoint_limit(request)
    latest_input = store.get_latest_input(req.session_id)
    if not latest_input:
        raise HTTPException(status_code=404, detail="No board state found. Call /syncState first.")

    try:
        action = planner.plan_move(
            board_crop_b64=latest_input["board_crop_b64"],
            board_crop_mime_type=latest_input.get("board_crop_mime_type", "image/png"),
            strategy_text=latest_input["strategy_text"],
            logger=logger,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Planner failed: {exc}") from exc

    generated_at = utcnow_iso()
    store.record_move(
        session_id=req.session_id,
        move_payload={
            "move": action.move.value,
            "reasoning": action.reasoning,
            "board": action.board,
            "model": planner.model,
            "generated_at": generated_at,
        },
    )

    return NextMoveResponse(
        session_id=req.session_id,
        action=action,
        model=planner.model,
        generated_at=generated_at,
        remaining_calls_this_hour=remaining_calls if remaining_calls is not None else -1,
    )


@app.get("/getStats", response_model=StatsResponse)
def get_stats(session_id: str, request: Request):
    remaining_calls = enforce_endpoint_limit(request)
    stats = store.get_stats(session_id)
    return StatsResponse(
        session_id=session_id,
        remaining_calls_this_hour=remaining_calls if remaining_calls is not None else -1,
        **stats,
    )


@app.get("/nextSessionId", response_model=NextSessionIdResponse)
def next_session_id(device_id: str, request: Request):
    remaining_calls = enforce_endpoint_limit(request)
    sid = store.get_next_session_id(device_id)
    return NextSessionIdResponse(
        device_id=device_id,
        session_id=sid,
        remaining_calls_this_hour=remaining_calls if remaining_calls is not None else -1,
    )


@app.post("/extractBannerStats", response_model=BannerStatsResponse)
def extract_banner_stats(req: BannerStatsRequest, request: Request):
    remaining_calls = enforce_endpoint_limit(request)
    try:
        stats = planner.extract_banner_stats(
            banner_crop_b64=req.banner_crop_b64,
            banner_crop_mime_type=req.banner_crop_mime_type,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Banner stats extraction failed: {exc}") from exc
    return BannerStatsResponse(
        stats=stats,
        remaining_calls_this_hour=remaining_calls if remaining_calls is not None else -1,
    )
