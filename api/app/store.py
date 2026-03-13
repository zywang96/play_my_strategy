from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Dict, Optional

import re

from google.cloud import firestore



def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_to_doc_id(iso_ts: str) -> str:
    try:
        if iso_ts.endswith("Z"):
            iso_ts = iso_ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
    except Exception:
        dt = datetime.now(timezone.utc)

    return dt.strftime("%Y-%m-%dT%H-%M-%S_") + f"{dt.microsecond:06d}Z"



def serialize_board(board: Optional[list[list[int]]]) -> Optional[Dict[str, Any]]:
    if board is None:
        return None
    rows = len(board)
    cols = len(board[0]) if rows else 0
    return {"rows": rows, "cols": cols, "cells": [cell for row in board for cell in row]}


class FirestoreStore:
    def __init__(self) -> None:
        self.db = firestore.Client()
        self.sessions = self.db.collection("sessions")

    def _session_ref(self, session_id: str):
        return self.sessions.document(session_id)

    def sync_local_state(
        self,
        session_id: str,
        strategy_text: str,
        board_crop_b64: str,
        board_crop_mime_type: str,
    ) -> Dict[str, Any]:
        now = utcnow_iso()
        latest_input = {
            "board_crop_b64": board_crop_b64,
            "board_crop_mime_type": board_crop_mime_type,
            "synced_at": now,
        }
        payload = {
            "strategy_text": strategy_text,
            "latest_input": latest_input,
            "updated_at": now,
        }
        self._session_ref(session_id).set(payload, merge=True)
        return {"strategy_text": strategy_text, "latest_input": latest_input}

    def get_latest_input(self, session_id: str) -> Optional[Dict[str, Any]]:
        snap = self._session_ref(session_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        latest_input = data.get("latest_input")
        if not latest_input:
            return None
        latest_input["strategy_text"] = data.get("strategy_text", "")
        return latest_input

    def record_move(self, session_id: str, move_payload: Dict[str, Any]) -> None:
        session_ref = self._session_ref(session_id)
        move = move_payload.get("move")
        board = move_payload.get("board")
        generated_at = move_payload.get("generated_at", utcnow_iso())
        doc_id = iso_to_doc_id(str(generated_at))
        session_ref.collection("moves").document(doc_id).set(
            {
                "move": move,
                "reasoning": move_payload.get("reasoning"),
                "board": serialize_board(board),
                "model": move_payload.get("model"),
                "generated_at": generated_at,
            }
        )
        session_ref.set(
            {
                "total_requests": firestore.Increment(1),
                "last_move": move,
                "updated_at": generated_at,
            },
            merge=True,
        )

    def get_stats(self, session_id: str) -> Dict[str, Any]:
        snap = self._session_ref(session_id).get()
        if not snap.exists:
            return {"total_requests": 0, "last_move": None, "updated_at": None}
        data = snap.to_dict() or {}
        return {
            "total_requests": int(data.get("total_requests", 0)),
            "last_move": data.get("last_move"),
            "updated_at": data.get("updated_at"),
        }

    def get_next_session_id(self, device_id: str) -> str:
        """Return the next available session id for a device.

        Session ids follow the format: "{device_id}-NNNN" (4 digits).
        We scan existing session document ids and pick max(NNNN)+1.
        """
        pat = re.compile(rf"^{re.escape(device_id)}-(\d{{4}})$")

        max_n = 0
        found = False
        for snap in self.sessions.stream():
            m = pat.match(snap.id)
            if not m:
                continue
            found = True
            try:
                max_n = max(max_n, int(m.group(1)))
            except Exception:
                continue

        if not found:
            return f"{device_id}-0001"
        return f"{device_id}-{max_n + 1:04d}"

    def reserve_rate_limited_call(
        self,
        *,
        namespace: str,
        bucket_key: str,
        max_calls: int,
        window_unit: str = "hour",
        metadata: Optional[Dict[str, Any]] = None,
        logger
    ) -> int:
        """Reserve one API call in a shared global bucket.

        Returns remaining calls after reservation.
        Raises ValueError when the bucket is exhausted.
        """
        now = datetime.now(timezone.utc)
        if window_unit == "minute":
            bucket = now.strftime("%Y%m%d%H%M")
            window_label = "minute"
        elif window_unit == "day":
            bucket = now.strftime("%Y%m%d")
            window_label = "day"
        else:
            bucket = now.strftime("%Y%m%d%H")
            window_label = "hour"
        bucket_hash = sha1(bucket_key.encode("utf-8")).hexdigest()[:16]
        doc_ref = self.db.collection(namespace).document(f"{bucket}-{bucket_hash}")
        @firestore.transactional
        def txn(transaction):
            snap = doc_ref.get(transaction=transaction)
            current = 0
            if snap.exists:
                data = snap.to_dict() or {}
                current = int(data.get("count", 0))
            if current >= max_calls:
                raise ValueError("Rate limit exceeded. Please try again later.")
            new_count = current + 1
            payload = {
                "bucket_key": bucket_key,
                "bucket_hash": bucket_hash,
                "bucket": bucket,
                "window_unit": window_label,
                "count": new_count,
                "updated_at": utcnow_iso(),
            }
            if metadata:
                payload.update(metadata)
            transaction.set(doc_ref, payload, merge=True)
            return max_calls - new_count
        transaction = self.db.transaction()
        return txn(transaction)
