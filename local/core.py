from __future__ import annotations

import base64
import html
import random
import re
import subprocess
import time
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Any

import cv2
import requests
import numpy as np

# ============================================================
# Logging
# ============================================================
LOG_LOCK = threading.Lock()
LOG_BUFFER = deque(maxlen=500)


def append_log_line(line: str) -> None:
    with LOG_LOCK:
        LOG_BUFFER.append(line)


def get_log_text() -> str:
    with LOG_LOCK:
        return "\n".join(LOG_BUFFER)


def _style_log_line(line: str) -> str:
    """
    Render one log line as colored HTML without using red.
    """
    safe = html.escape(line)

    color = "#E5E7EB"
    weight = "400"

    if "[GAME OVER]" in line:
        color = "#FBBF24"
        weight = "700"
    elif "[NO CHANGE AFTER MOVE]" in line:
        color = "#F59E0B"
        weight = "700"
    elif "Loop error" in line or "failed" in line.lower():
        color = "#C084FC"
        weight = "700"
    elif "Gemini decision:" in line:
        color = "#60A5FA"
        weight = "700"
    elif "Executing" in line:
        color = "#60A5FA"
        weight = "700"
    elif "Gemini parse row" in line:
        color = "#34D399"
        weight = "600"
    elif "UI action:" in line:
        color = "#A78BFA"
        weight = "700"
    elif "--- loop tick ---" in line:
        color = "#93C5FD"
        weight = "700"
    elif "State synced" in line or "Syncing state" in line or "Requesting next move" in line:
        color = "#67E8F9"
    elif "New session started" in line or "initial SESSION_ID" in line:
        color = "#FDE68A"
        weight = "700"
    elif "Not on game screen" in line or "No phone detected" in line:
        color = "#D8B4FE"
    elif "Reasoning:" in line:
        color = "#FDE68A"
        weight = "500"
    elif "[UI] Ready" in line:
        color = "#86EFAC"
        weight = "700"
    elif "Pause/stop requested" in line:
        color = "#FDBA74"
        weight = "700"

    return f'<span style="color:{color}; font-weight:{weight};">{safe}</span>'


def get_log_html() -> str:
    with LOG_LOCK:
        lines = list(LOG_BUFFER)

    rendered = "<br>".join(_style_log_line(line) for line in lines)
    return f"""
    <div id="log-container" style="
        background:#0F172A;
        color:#E5E7EB;
        padding:12px 14px;
        border-radius:12px;
        font-family:Consolas, Menlo, Monaco, 'Courier New', monospace;
        font-size:13px;
        line-height:1.5;
        white-space:pre-wrap;
        overflow-y:auto;
        height:320px;
        border:1px solid #1E293B;
    ">{rendered}</div>
    """


def log(msg: str) -> None:
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    try:
        sid = SESSION_ID
    except Exception:
        sid = 'N/A'
    line = f'[{ts}] [{sid}] {msg}'
    print(line, flush=True)
    append_log_line(line)


# ============================================================
# CONFIG
# ============================================================

DEVICE_ID = "phone-01"
SESSION_ID = f"{DEVICE_ID}-0001"

END_PIXEL_X = 957
END_PIXEL_Y = 2272
END_PIXEL_BGR = (129, 147, 164)

BANNER_Y1, BANNER_Y2 = 63, 363
BANNER_X1, BANNER_X2 = 79, 1043

RESTART_TAP_X = 416
RESTART_TAP_Y = 2208

OUT_DIR = Path("./demo")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SCREEN_PNG = OUT_DIR / "screen.png"
SCREEN_PNG_POST = OUT_DIR / "screen_post.png"
BOARD_CROP_PNG = OUT_DIR / "board_crop.png"
BOARD_CROP_PNG_POST = OUT_DIR / "board_crop_post.png"
BANNER_CROP_PNG = OUT_DIR / "banner_crop.png"

CROP_Y1, CROP_Y2 = 564, 1453
CROP_X1, CROP_X2 = 94, 985

GAME_SCREEN_BGR = (239, 248, 250)

LOOP_SLEEP_SEC = 2.0

ADB = None
API_BASE = None
SWIPE_CMDS = {}

LOG_RATE_LIMIT_REMAINING = False

#You can edit this to create default strategy
DEFAULT_STRATEGY = (''
)

def configure_runtime(adb_path: str, api_base: str) -> None:
    global ADB, API_BASE, SWIPE_CMDS

    ADB = adb_path
    API_BASE = api_base.rstrip("/")

    SWIPE_CMDS = {
        "up": [ADB, "shell", "input", "swipe", "500", "1600", "500", "700", "100"],
        "down": [ADB, "shell", "input", "swipe", "500", "700", "500", "1600", "100"],
        "left": [ADB, "shell", "input", "swipe", "900", "1150", "150", "1150", "100"],
        "right": [ADB, "shell", "input", "swipe", "150", "1150", "900", "1150", "100"],
    }

# ============================================================
# BASIC HELPERS (ADB)
# ============================================================
def encode_bytes_b64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def adb_command(args, capture_output=False, text=True, check=True):
    return subprocess.run(
        [ADB] + args,
        capture_output=capture_output,
        text=text,
        check=check,
    )


def adb_tap(x: int, y: int) -> None:
    subprocess.check_call([ADB, "shell", "input", "tap", str(x), str(y)])


def is_phone_connected() -> bool:
    try:
        result = adb_command(["devices"], capture_output=True)
        lines = (result.stdout or "").strip().splitlines()[1:]
        for line in lines:
            if "\tdevice" in line:
                return True
        return False
    except Exception as e:
        log(f"ADB check failed: {e}")
        return False


def take_phone_screenshot(output_path: Path) -> bool:
    try:
        result = subprocess.run(
            [ADB, "exec-out", "screencap", "-p"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        output_path.write_bytes(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        log("Failed to take screenshot.")
        try:
            log(e.stderr.decode(errors="ignore"))
        except Exception:
            pass
        return False


# ============================================================
# IMAGE / CROPS
# ============================================================
def is_game_screen(image) -> bool:
    if image is None or image.size == 0:
        return False
    b, g, r = image[-1, -1]
    return (int(b), int(g), int(r)) == GAME_SCREEN_BGR


def is_game_over(image) -> bool:
    if image is None or image.size == 0:
        return False
    h, w = image.shape[:2]
    if not (0 <= END_PIXEL_X < w and 0 <= END_PIXEL_Y < h):
        return False
    b, g, r = image[END_PIXEL_Y, END_PIXEL_X]
    return (int(b), int(g), int(r)) == END_PIXEL_BGR


def crop_banner_from_image(image, banner_crop_path: Path) -> bool:
    cropped = image[BANNER_Y1:BANNER_Y2, BANNER_X1:BANNER_X2]
    if cropped is None or cropped.size == 0:
        log("Banner crop failed.")
        return False
    cv2.imwrite(str(banner_crop_path), cropped)
    return True


def crop_board_from_image(image, board_crop_path: Path) -> bool:
    cropped = image[CROP_Y1:CROP_Y2, CROP_X1:CROP_X2]
    if cropped is None or cropped.size == 0:
        log("Board crop failed.")
        return False
    cv2.imwrite(str(board_crop_path), cv2.resize(cropped, (450, 450)))
    return True


def load_board_crop_b64() -> str:
    return base64.b64encode(BOARD_CROP_PNG.read_bytes()).decode("utf-8")


def load_banner_crop_b64() -> str:
    return base64.b64encode(BANNER_CROP_PNG.read_bytes()).decode("utf-8")


def compdiff(path1, path2) -> bool:
    img1 = cv2.imread(str(path1))
    img2 = cv2.imread(str(path2))
    if img1 is None or img2 is None:
        return False
    if img1.shape != img2.shape:
        return False
    return np.mean(np.abs(img1.astype(np.float32) - img2.astype(np.float32))) < 0.05


# ============================================================
# CLOUD API
# ============================================================
def maybe_log_remaining_quota(endpoint_label: str, data: Any) -> None:
    if not LOG_RATE_LIMIT_REMAINING:
        return
    if not isinstance(data, dict):
        return
    remaining = data.get("remaining_calls_this_hour")
    if remaining is None:
        return
    log(f"quota remaining ({endpoint_label})={remaining}")


def sync_state(session_id: str, strategy_text: str) -> dict:
    payload = {
        "session_id": session_id,
        "strategy_text": (strategy_text or "").strip(),
        "board_crop_b64": load_board_crop_b64(),
        "board_crop_mime_type": "image/png",
    }
    resp = requests.post(f"{API_BASE}/syncState", json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json() if resp.content else {}
    maybe_log_remaining_quota("syncState", data)
    return data


def get_next_move(session_id: str) -> Tuple[str, Optional[list], Any, str]:
    resp = requests.post(f"{API_BASE}/getNextMove", json={"session_id": session_id}, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    maybe_log_remaining_quota("getNextMove", data)

    action = data.get("action") if isinstance(data, dict) else None
    if not isinstance(action, dict):
        action = {}

    move = action.get("move") or (data.get("move") if isinstance(data, dict) else None)
    board = action.get("board")
    reason = action.get("reasoning") or ""

    if not isinstance(move, str) or move not in SWIPE_CMDS:
        move = "down"

    return move, board, data, reason


def extract_banner_stats() -> dict:
    payload = {
        "banner_crop_b64": load_banner_crop_b64(),
        "banner_crop_mime_type": "image/png",
    }
    resp = requests.post(f"{API_BASE}/extractBannerStats", json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json() if resp.content else {}
    maybe_log_remaining_quota("extractBannerStats", data)
    return (data or {}).get("stats", {})


def execute_move(move: str) -> None:
    subprocess.check_call(SWIPE_CMDS[move])


# ============================================================
# SESSION / STATS
# ============================================================
@dataclass
class EpisodeStats:
    start_ts: float
    moves_sent: int = 0
    last_banner: Optional[dict] = None


def bump_session_id(session_id: str) -> str:
    m = re.match(r"^(.*)-(\d{4})$", session_id)
    if m:
        base, n = m.group(1), int(m.group(2))
        return f"{base}-{n + 1:04d}"
    return f"{session_id}-0001"


def new_episode_stats() -> EpisodeStats:
    return EpisodeStats(start_ts=time.time())


def get_initial_session_id(device_id: str) -> str:
    try:
        resp = requests.get(f"{API_BASE}/nextSessionId", params={"device_id": device_id}, timeout=120)
        resp.raise_for_status()
        data = resp.json() or {}
        maybe_log_remaining_quota("nextSessionId", data)
        sid = data.get("session_id")
        if isinstance(sid, str) and sid:
            return sid
    except Exception as e:
        log(f"Failed to fetch next session id from API; using local default. err={e}")
    return f"{device_id}-0001"


# ============================================================
# GRID LOGGING
# ============================================================
def log_gemini_grid(board: list) -> None:
    for idx, row in enumerate(board, start=1):
        try:
            row_text = ", ".join(f"{int(v):4d}" for v in row)
        except Exception:
            row_text = ", ".join(str(v) for v in row)
        log(f"Gemini parse row {idx}: [{row_text}]")


# ============================================================
# UI RENDER HELPERS
# ============================================================
def render_status(text: str) -> str:
    return f"""
    <div style="
        display:inline-block;
        padding:10px 16px;
        border-radius:14px;
        background:linear-gradient(135deg, #1E293B, #0F172A);
        border:1px solid #334155;
        color:#E2E8F0;
        font-family:Inter, Arial, sans-serif;
        font-size:14px;
        font-weight:600;
        box-shadow:0 4px 14px rgba(0,0,0,0.18);
    ">
        {html.escape(text)}
    </div>
    """


def render_voice_status(text: str) -> str:
    return f"""
    <div style="
        display:inline-block;
        padding:8px 14px;
        border-radius:12px;
        background:linear-gradient(135deg, #0F172A, #111827);
        border:1px solid #334155;
        color:#BFDBFE;
        font-family:Inter, Arial, sans-serif;
        font-size:13px;
        font-weight:600;
    ">
        {html.escape(text)}
    </div>
    """


# ============================================================
# CORE: one loop step
# ============================================================
def run_one_step(
    strategy_text: str,
    stats: EpisodeStats,
    runner: Optional["ControllerRunner"] = None,
    allow_paused_run: bool = False,
    step_pause_gen: int = 0,
) -> EpisodeStats:
    global SESSION_ID, LOOP_SLEEP_SEC

    def should_abort() -> bool:
        if runner is None:
            return False
        return runner.should_abort_current_step(
            allow_paused_run=allow_paused_run,
            step_pause_gen=step_pause_gen,
        )

    loop_t0 = time.time()
    log('--- loop tick ---')

    if not is_phone_connected():
        log("No phone detected by ADB. Please connect your device and enable USB debugging.")
        time.sleep(1.0)
        return stats

    log(f'Capturing screenshot to {SCREEN_PNG} ...')
    if not take_phone_screenshot(SCREEN_PNG):
        log('Screenshot failed; retrying later')
        time.sleep(LOOP_SLEEP_SEC)
        return stats

    image = cv2.imread(str(SCREEN_PNG))
    if image is None:
        log('Failed to decode screenshot image')
        time.sleep(LOOP_SLEEP_SEC)
        return stats

    if not is_game_screen(image):
        log('Not on game screen; waiting...')
        time.sleep(LOOP_SLEEP_SEC)
        return stats

    if is_game_over(image):
        if crop_banner_from_image(image, BANNER_CROP_PNG):
            try:
                banner = extract_banner_stats()
                stats.last_banner = banner
                log(f"[GAME OVER] banner_stats={banner}")
            except Exception as e:
                log(f"[GAME OVER] banner extraction failed: {e}")

        try:
            log("Restarting a new game.")
            adb_tap(RESTART_TAP_X, RESTART_TAP_Y)
        except Exception as e:
            log(f"Restart tap failed: {e}")

        SESSION_ID = bump_session_id(SESSION_ID)
        stats = new_episode_stats()
        log(f"New session started: SESSION_ID={SESSION_ID}")
        time.sleep(1.5)
        return stats

    log('Cropping board region...')
    if not crop_board_from_image(image, BOARD_CROP_PNG):
        time.sleep(LOOP_SLEEP_SEC)
        return stats

    if should_abort():
        log("Pause/stop requested; aborting current step before cloud sync.")
        return stats

    try:
        log('Syncing state to cloud...')
        sync_state(SESSION_ID, strategy_text=strategy_text)

        if should_abort():
            log("Pause/stop requested; synced state but skipping Gemini request.")
            return stats

        log('State synced. Requesting next move...')
        move, board, raw, reason = get_next_move(SESSION_ID)

        if board is not None and isinstance(board, list) and len(board) == 4:
            try:
                zero_count = sum(1 for row in board for v in row if int(v) == 0)
                LOOP_SLEEP_SEC = 2.0 if zero_count < 4 else 0.5
            except Exception:
                pass

        if board is not None and isinstance(board, list) and len(board) == 4:
            try:
                log_gemini_grid(board)
            except Exception:
                log("Gemini returned a board grid, but pretty-print failed.")
        else:
            try:
                keys = list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__
            except Exception:
                keys = 'unknown'
            log(f"Gemini did not return a usable board grid (keys={keys}).")

        log(f'Gemini decision: swipe {move!r}')
        if reason:
            log(f'Reasoning: {reason}')

        if should_abort():
            log(f"Pause/stop requested; skipping Gemini swipe {move!r}.")
            return stats

        log(f'Executing {move!r} swipe')
        time.sleep(0.30)

        if should_abort():
            log(f"Pause/stop requested during pre-swipe delay; cancelled {move!r}.")
            return stats

        execute_move(move)
        stats.moves_sent += 1

        time.sleep(0.30)

        if should_abort():
            log("Pause/stop requested; skipping post-move random override check.")
            log(f"Move done. moves_sent={stats.moves_sent} loop_dt={time.time()-loop_t0:.3f}s")
            return stats

        if take_phone_screenshot(SCREEN_PNG_POST):
            post_img = cv2.imread(str(SCREEN_PNG_POST))
            if post_img is not None and is_game_screen(post_img):
                if crop_board_from_image(post_img, BOARD_CROP_PNG_POST):
                    if compdiff(BOARD_CROP_PNG, BOARD_CROP_PNG_POST):
                        choices = [m for m in SWIPE_CMDS.keys() if m != move] or list(SWIPE_CMDS.keys())
                        override = random.choice(list(choices))

                        if should_abort():
                            log(f"Pause/stop requested; skipping random override {override!r}.")
                            log(f"Move done. moves_sent={stats.moves_sent} loop_dt={time.time()-loop_t0:.3f}s")
                            return stats

                        log(f"[NO CHANGE AFTER MOVE] applying random override {override!r} (different from gemini {move!r})")
                        execute_move(override)
                        stats.moves_sent += 1
        else:
            log('Post screenshot failed')

        log(f"Move done. moves_sent={stats.moves_sent} loop_dt={time.time()-loop_t0:.3f}s")
    except Exception as e:
        log(f"Loop error: {e}")
    time.sleep(LOOP_SLEEP_SEC)
    return stats


# ============================================================
# UI Runner
# ============================================================
class ControllerRunner:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None

        self._stop = False
        self._paused = True
        self._step = False

        # increments every time Pause is pressed; lets in-flight steps detect cancellation
        self._pause_gen = 0

        self.strategy_text: str = DEFAULT_STRATEGY
        self.stats: EpisodeStats = new_episode_stats()

        global SESSION_ID
        SESSION_ID = get_initial_session_id(DEVICE_ID)

    def should_abort_current_step(self, allow_paused_run: bool, step_pause_gen: int) -> bool:
        if self._stop:
            return True

        if self._pause_gen != step_pause_gen:
            return True

        if self._paused and not allow_paused_run:
            return True

        return False

    def ensure_started(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def start(self) -> str:
        self.ensure_started()
        self._paused = False
        log("UI action: Start pressed.")
        return render_status("Status: running.")

    def pause(self) -> str:
        self._paused = True
        self._pause_gen += 1
        log("UI action: Pause pressed.")
        return render_status("Status: paused.")

    def step_once(self) -> str:
        self.ensure_started()
        self._paused = True
        self._step = True
        log("UI action: Step pressed.")
        return render_status("Status: stepping one move.")

    def _loop(self) -> None:
        self.stats = new_episode_stats()
        log(f"Controller loop started; DEVICE_ID={DEVICE_ID}; initial SESSION_ID={SESSION_ID}")

        while not self._stop:
            if self._paused and not self._step:
                time.sleep(0.05)
                continue

            do_one = self._step
            step_pause_gen = self._pause_gen

            if do_one:
                self._step = False

            self.stats = run_one_step(
                strategy_text=self.strategy_text,
                stats=self.stats,
                runner=self,
                allow_paused_run=do_one,
                step_pause_gen=step_pause_gen,
            )

            if do_one:
                self._paused = True


