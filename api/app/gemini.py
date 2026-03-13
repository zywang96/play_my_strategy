from __future__ import annotations

import base64
import json
import os
import re

from google import genai
from google.genai import types

from .models import ActionPlan, BannerStats

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


class GeminiPlanner:
    def __init__(self) -> None:
        self.model = DEFAULT_MODEL
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            self.client = genai.Client(api_key=api_key)
        else:
            self.client = genai.Client()

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        text = text.strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"^```\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return text.strip()

    def plan_move(self, board_crop_b64: str, board_crop_mime_type: str, strategy_text: str, logger) -> ActionPlan:
        board_crop_bytes = base64.b64decode(board_crop_b64)

        system_instruction = (
            "You are a 2048 move planner. Inspect a close-up image containing only the 4x4 2048 board. "
            "Read the board first, using 0 for empty cells and powers of two for non-empty cells. "
            "Then return exactly one next move: up, down, left, or right. "
            "Follow the provided user strategy. "
            "Return strict JSON only."
        )

        user_prompt = {
            "task": "Choose the best next move for the 2048 game from the cropped 4x4 board image.",
            "user_strategy": strategy_text,
            "required_json_schema": {
                "move": "one of up/down/left/right",
                "reasoning": "short explanation under 60 words",
                "board": "4x4 integer matrix if readable, otherwise null",
            },
        }

        contents = [
            types.Part.from_text(text=json.dumps(user_prompt)),
            types.Part.from_text(text="This image is the cropped 4x4 2048 board."),
            types.Part.from_bytes(data=board_crop_bytes, mime_type=board_crop_mime_type),
        ]

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.1,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=200),
                    #max_output_tokens=256,
                ),
            )
        except Exception as e:
            logger.exception("Gemini generate_content failed: %s", e)
            raise HTTPException(status_code=502, detail=f"Gemini call failed: {type(e).__name__}: {e}")

        raw_text = response.text or "{}"
        raw_text = self._strip_code_fences(raw_text)
        data = json.loads(raw_text)
        if "reasoning" not in data:
            data["reasoning"] = ""
        logger.info(data)
        return ActionPlan.model_validate(data)


    def extract_banner_stats(self, banner_crop_b64: str, banner_crop_mime_type: str) -> BannerStats:
        """Extract score, moves, and time from the top banner crop of the 2048 game."""
        banner_bytes = base64.b64decode(banner_crop_b64)

        system_instruction = (
            "You are an OCR and information extraction assistant for the 2048 game UI. "
            "Given a crop of the top banner, extract the numerical score, number of moves, and the elapsed time if visible. "
            "Return strict JSON only. If a field is unreadable, return null for that field."
        )

        user_prompt = {
            "task": "Extract score, moves, and time from the 2048 banner image.",
            "required_json_schema": {
                "score": "integer or null",
                "moves": "integer or null",
                "time": "string like 'MM:SS' or 'HH:MM:SS' or null",
            },
        }

        contents = [
            types.Part.from_text(text=json.dumps(user_prompt)),
            types.Part.from_text(text="This image is the cropped top banner of the 2048 game."),
            types.Part.from_bytes(data=banner_bytes, mime_type=banner_crop_mime_type),
        ]

        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )

        raw_text = response.text or "{}"
        raw_text = self._strip_code_fences(raw_text)
        data = json.loads(raw_text)
        return BannerStats.model_validate(data)
