from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Dict

from fastapi import HTTPException, Request

from .models import PlaygroundAsset, PlaygroundAssetsResponse

STATIC_ROOT = Path(__file__).parent / "static" / "playground"


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = request.client.host if request.client else ""
    return client or "unknown"


class PlaygroundCatalog:
    def __init__(self) -> None:
        self._assets = self._build_assets()

    def _build_assets(self) -> Dict[str, PlaygroundAsset]:
        board_ids = ["board-a", "board-b", "board-c"]
        assets: Dict[str, PlaygroundAsset] = {}
        for idx, board_id in enumerate(board_ids, start=1):
            assets[board_id] = PlaygroundAsset(
                board_id=board_id,
                label=f"Board {idx}",
                thumbnail_url=f"/static/playground/boards/{board_id}.png",
                board_image_url=f"/static/playground/boards/{board_id}.png",
            )
        return assets

    def list_assets(self) -> PlaygroundAssetsResponse:
        return PlaygroundAssetsResponse(assets=list(self._assets.values()))

    def get_asset(self, board_id: str) -> PlaygroundAsset:
        asset = self._assets.get(board_id)
        if not asset:
            raise HTTPException(status_code=404, detail=f"Unknown board id: {board_id}")
        return asset

    def load_board_as_b64(self, board_id: str) -> tuple[str, str]:
        asset = self.get_asset(board_id)
        image_path = STATIC_ROOT / "boards" / f"{asset.board_id}.png"
        raw = image_path.read_bytes()
        return base64.b64encode(raw).decode("utf-8"), "image/png"


catalog = PlaygroundCatalog()


def build_playground_html() -> str:
    assets_json = json.dumps(catalog.list_assets().model_dump()["assets"])
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Playground</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7fb;
      --panel: #ffffff;
      --border: #d8deea;
      --text: #1f2937;
      --muted: #667085;
      --accent: #1d4ed8;
      --accent-soft: #dbeafe;
      --shadow: 0 14px 40px rgba(15, 23, 42, 0.08);
      --radius: 18px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    .page {
      max-width: 1480px;
      margin: 0 auto;
      padding: 28px;
    }
    .hero {
      background: linear-gradient(135deg, #eff6ff 0%, #ffffff 65%);
      border: 1px solid var(--border);
      border-radius: 24px;
      padding: 24px 28px;
      box-shadow: var(--shadow);
      margin: 0 auto 22px auto;
      display: flex;
      flex-direction: column;
      align-items: center;
      text-align: center;
    }
    .hero h1 { margin: 0 0 8px 0; font-size: 30px; }
    .hero p {
      margin: 0;
      color: var(--muted);
      font-size: 15px;
      max-width: 1000px;
      width: 100%;
      text-align: justify;
      text-justify: inter-word;
      text-align-last: left;
    }
    .grid {
      display: grid;
      grid-template-columns: 1.05fr 1.0fr 1.35fr;
      gap: 20px;
      align-items: start;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 18px;
    }
    .panel h2 {
      margin: 0 0 12px 0;
      font-size: 18px;
    }
    label {
      display: block;
      font-weight: 600;
      margin-bottom: 8px;
    }
    textarea, select {
      width: 100%;
      border: 1px solid #cfd8e3;
      border-radius: 14px;
      padding: 12px 14px;
      font: inherit;
      background: white;
      color: var(--text);
    }
    textarea {
      min-height: 265px;
      resize: vertical;
      line-height: 1.5;
    }
    .preset-row { margin-top: 14px; }
    .button-row {
      margin-top: 16px;
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }
    button {
      appearance: none;
      border: none;
      border-radius: 999px;
      padding: 12px 22px;
      background: var(--accent);
      color: white;
      font-weight: 700;
      cursor: pointer;
      font-size: 14px;
    }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
    .quota {
      font-size: 13px;
      color: var(--muted);
    }
    .thumb-strip {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }
    .thumb {
      border: 2px solid transparent;
      border-radius: 16px;
      overflow: hidden;
      padding: 4px;
      background: #f8fafc;
      cursor: pointer;
    }
    .thumb.active {
      border-color: var(--accent);
      background: var(--accent-soft);
    }
    .thumb img {
      width: 100%;
      display: block;
      border-radius: 12px;
    }
    .large-board {
      border: 1px solid #dbe2ef;
      border-radius: 20px;
      overflow: hidden;
      background: #f8fafc;
    }
    .large-board img {
      width: 100%;
      display: block;
      aspect-ratio: 1 / 1;
      object-fit: cover;
    }
    .subtle {
      color: var(--muted);
      font-size: 13px;
      margin-top: 8px;
    }
    .log-box {
      background: #0f172a;
      color: #dbeafe;
      border-radius: 16px;
      padding: 14px;
      height: 305px;
      overflow: auto;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      line-height: 1.45;
      white-space: pre-wrap;
    }
    .meta {
      margin: 14px 0 0 0;
      display: grid;
      gap: 8px;
      font-size: 14px;
    }
    .meta-card {
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 14px;
      padding: 10px 12px;
    }
    .meta-title {
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 3px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }
    @media (max-width: 1200px) {
      .grid { grid-template-columns: 1fr; }
      textarea { min-height: 220px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <div class="hero">
      <h1>Play My Strategy -- Playground</h1>
      <p>This page provides a simple playground that demonstrates how we use Gemini to play 2048 with a user-provided strategy. We include several sample boards, and when you press the “Step” button, the page calls the APIs and shows the returned information in the Log area. This playground runs independently of the phone, so there is no need to connect a device or use ADB. API usage is rate-limited to ensure fair access and prevent overuse. You will receive warnings if requests exceed the allowed limit, and the quota is refreshed on an hourly basis.</p>
    </div>

    <div class="grid">
      <section class="panel">
        <h2>Strategy</h2>
        <label for="strategyBox">Enter strategy</label>
        <textarea id="strategyBox" placeholder="Describe the 2048 strategy you want Gemini to follow.">Keep the largest tile in the top-right corner, and avoid breaking the monotonic gradient unless doing so creates a clear merge.</textarea>
        <div class="preset-row">
          <label for="strategyPreset">Or choose a preset</label>
          <select id="strategyPreset">
            <option value="">Choose a sample strategy</option>
            <option value="Prefer moves that keep the largest tile anchored in the bottom-left corner, and use the opposite direction only when no safe merge is available.">Corner control</option>
            <option value="Prioritize moves that preserve monotonic rows, create empty space, and avoid scattering larger tiles.">Monotonic board</option>
            <option value="Choose moves randomly without following any fixed strategy.">Random Swipes</option>
          </select>
        </div>
        <div class="button-row">
          <button id="stepBtn">Step</button>
        </div>
      </section>

      <section class="panel">
        <h2>Selected board</h2>
        <div id="thumbStrip" class="thumb-strip"></div>
        <div class="large-board">
          <img id="selectedBoardImg" alt="Selected board image" />
        </div>
        <div class="subtle" id="selectedBoardLabel">No board selected.</div>
      </section>

      <section class="panel">
        <h2>Log</h2>
        <div id="logBox" class="log-box"></div>
        <div class="meta">
          <div class="meta-card">
            <div class="meta-title">Returned swipe</div>
            <div id="moveValue">—</div>
          </div>
          <div class="meta-card">
            <div class="meta-title">Model</div>
            <div id="modelValue">—</div>
          </div>
        </div>
      </section>
    </div>
  </div>

  <script id="playgroundAssets" type="application/json">__PLAYGROUND_ASSETS__</script>
  <script>
    const state = {
      assets: [],
      selectedBoardId: null,
    };

    const logBox = document.getElementById('logBox');
    const thumbStrip = document.getElementById('thumbStrip');
    const selectedBoardImg = document.getElementById('selectedBoardImg');
    const selectedBoardLabel = document.getElementById('selectedBoardLabel');
    const moveValue = document.getElementById('moveValue');
    const modelValue = document.getElementById('modelValue');
    const strategyBox = document.getElementById('strategyBox');
    const strategyPreset = document.getElementById('strategyPreset');
    const stepBtn = document.getElementById('stepBtn');

    function appendLog(line, color = null) {
      const stamp = new Date().toLocaleTimeString();
      const row = document.createElement('div');
      row.textContent = `[${stamp}] ${line}`;
      if (color) row.style.color = color;
      logBox.appendChild(row);
      logBox.scrollTop = logBox.scrollHeight;
    }

    function appendBlueLog(line) {
      appendLog(line, '#60a5fa');
    }

    function appendOrangeLog(line) {
      appendLog(line, '#ffa500');
    }

    function clearLog() {
      logBox.innerHTML = '';
    }

    function appendParsedGrid(board) {
      if (!Array.isArray(board)) return;
      board.forEach((row, idx) => {
        const rowText = Array.isArray(row)
          ? row.map((value) => {
              const n = Number(value);
              return Number.isFinite(n) ? String(Math.trunc(n)).padStart(4, ' ') : String(value);
            }).join(', ')
          : String(row);
        appendLog(`Gemini parse row ${idx + 1}: [${rowText}]`);
      });
    }

    function renderBoardSelection(boardId) {
      state.selectedBoardId = boardId;
      const asset = state.assets.find((x) => x.board_id === boardId);
      if (!asset) return;
      selectedBoardImg.src = asset.board_image_url;
      selectedBoardLabel.textContent = `${asset.label} selected.`;
      moveValue.textContent = '—';
      modelValue.textContent = '—';
      [...thumbStrip.children].forEach((node) => {
        node.classList.toggle('active', node.dataset.boardId === boardId);
      });
    }

    async function loadAssets() {
      state.assets = JSON.parse(document.getElementById('playgroundAssets').textContent || '[]');
      thumbStrip.innerHTML = '';
      state.assets.forEach((asset) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'thumb';
        btn.dataset.boardId = asset.board_id;
        btn.innerHTML = `<img src="${asset.thumbnail_url}" alt="${asset.label}" />`;
        btn.addEventListener('click', () => renderBoardSelection(asset.board_id));
        thumbStrip.appendChild(btn);
      });
      clearLog();
      if (state.assets.length) {
        appendLog('[UI] Board catalog loaded.');
        renderBoardSelection(state.assets[0].board_id);
      } else {
        appendLog('[UI] No boards found.');
      }
    }

    strategyPreset.addEventListener('change', (event) => {
      if (event.target.value) strategyBox.value = event.target.value;
    });

    stepBtn.addEventListener('click', async () => {
      if (!state.selectedBoardId) {
        appendLog('Select a board first.');
        return;
      }
      stepBtn.disabled = true;
      appendLog('Calling API ...');
      try {
        const res = await fetch('/playground/api/step', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            board_id: state.selectedBoardId,
            strategy_text: strategyBox.value || '',
          }),
        });
        const data = await res.json();
        if (!res.ok) {
          appendOrangeLog(`Request failed (${res.status}): ${data.detail || 'unknown error'}`);
          return;
        }
        if (data.action.board) appendParsedGrid(data.action.board);
        if (data.action.reasoning) appendLog(`Reasoning: ${data.action.reasoning}`);
        appendBlueLog(`Move=${data.action.move}; remaining quota=${data.remaining_calls_this_hour}`);
        moveValue.textContent = data.action.move;
        modelValue.textContent = data.model;
      } catch (err) {
        appendOrangeLog(`Network error: ${err}`);
      } finally {
        stepBtn.disabled = false;
      }
    });

    loadAssets();
  </script>
</body>
</html>
""".replace("__PLAYGROUND_ASSETS__", assets_json)