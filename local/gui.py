from __future__ import annotations

import gradio as gr

import core


def launch_ui() -> None:
    runner = core.ControllerRunner()

    # ------------------------------------------------------------
    # Frontend JS helpers
    # ------------------------------------------------------------
    scroll_js = """
    (enabled) => {
        if (!enabled) return;
        const el = document.getElementById('log-container');
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }
    """

    recorder_init_js = """
    () => {
        if (window.__strategyRecorderInit) return;
        window.__strategyRecorderInit = true;

        const state = {
            mediaRecorder: null,
            chunks: [],
            stream: null,
            recognition: null,
            transcript: "",
            timer: null,
            startedAt: null,
            isRecording: false,
            audioUrl: "",
        };
        window.__strategyRecorderState = state;

        const $ = (id) => document.getElementById(id);
        const setStatus = (msg) => {
            const el = $("voice_status_text");
            if (el) el.textContent = msg;
        };
        const setTimer = (msg) => {
            const el = $("voice_timer_text");
            if (el) el.textContent = msg;
        };
        const setPreview = (msg) => {
            const el = $("voice_preview_box");
            if (el) el.textContent = msg || "";
        };
        const setAudio = (url) => {
            const holder = $("voice_audio_holder");
            if (!holder) return;
            if (state.audioUrl && state.audioUrl !== url) {
                try { URL.revokeObjectURL(state.audioUrl); } catch (e) {}
            }
            state.audioUrl = url || "";
            if (!url) {
                return;
            }
            holder.innerHTML = `<audio controls src="${url}" style="width:100%;"></audio>`;
        };
        const syncPreviewToTextbox = () => {
            const textbox = document.querySelector('#voice_preview textarea');
            if (!textbox) return;
            textbox.value = state.transcript || "";
            textbox.dispatchEvent(new Event('input', { bubbles: true }));
        };
        const stopActiveRecording = () => {
            state.isRecording = false;
            if (state.timer) {
                clearInterval(state.timer);
                state.timer = null;
            }
            if (state.mediaRecorder && state.mediaRecorder.state !== 'inactive') {
                try { state.mediaRecorder.onstop = null; } catch (e) {}
                try { state.mediaRecorder.stop(); } catch (e) {}
            }
            if (state.recognition) {
                try { state.recognition.stop(); } catch (e) {}
                state.recognition = null;
            }
            if (state.stream) {
                try { state.stream.getTracks().forEach(t => t.stop()); } catch (e) {}
                state.stream = null;
            }
            state.mediaRecorder = null;
            state.chunks = [];
            state.startedAt = null;
        };
        const clearRecordingState = () => {
            stopActiveRecording();
            state.transcript = "";
            setAudio(null);
            setPreview("");
            setTimer('00:00');
            syncPreviewToTextbox();
        };

        window.__strategyRecorderHelpers = { setStatus, setTimer, setPreview, setAudio, syncPreviewToTextbox, stopActiveRecording, clearRecordingState };
        setAudio(null);
        setStatus('Ready to record.');
        setTimer('00:00');
    }
    """

    start_record_js = """
    async () => {
        const state = window.__strategyRecorderState;
        const helpers = window.__strategyRecorderHelpers;
        if (!state || !helpers) return [];
        if (state.isRecording) return [];

        state.transcript = "";
        helpers.setPreview("");
        helpers.setAudio(null);
        helpers.syncPreviewToTextbox();

        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            state.stream = stream;
            state.chunks = [];
            state.mediaRecorder = new MediaRecorder(stream);
            state.mediaRecorder.ondataavailable = (e) => {
                if (e.data && e.data.size > 0) state.chunks.push(e.data);
            };
            state.mediaRecorder.onstop = () => {
                try {
                    const blob = new Blob(state.chunks, { type: state.mediaRecorder?.mimeType || 'audio/webm' });
                    const url = URL.createObjectURL(blob);
                    helpers.setAudio(url);
                } catch (e) {
                    helpers.setStatus(`Recorded, but could not render audio player: ${e}`);
                }
            };
            state.mediaRecorder.start();

            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (SpeechRecognition) {
                state.recognition = new SpeechRecognition();
                state.recognition.lang = 'en-US';
                state.recognition.continuous = true;
                state.recognition.interimResults = true;
                state.recognition.onresult = (event) => {
                    let finalText = '';
                    let interimText = '';
                    for (let i = 0; i < event.results.length; i++) {
                        const txt = (event.results[i][0]?.transcript || '').trim();
                        if (!txt) continue;
                        if (event.results[i].isFinal) finalText += txt + ' ';
                        else interimText += txt + ' ';
                    }
                    const merged = `${finalText}${interimText}`.trim();
                    if (merged) {
                        state.transcript = merged;
                        helpers.setPreview(merged);
                        helpers.syncPreviewToTextbox();
                    }
                };
                state.recognition.onerror = (event) => {
                    const err = event?.error || 'unknown_error';
                    if (err === 'not-allowed') helpers.setStatus('Microphone permission was denied.');
                    else if (err !== 'aborted') helpers.setStatus(`Recording is fine, but speech recognition failed: ${err}`);
                };
                try { state.recognition.start(); } catch (e) {}
            }

            state.startedAt = Date.now();
            state.isRecording = true;
            helpers.setStatus('Recording... speak your strategy, then press Stop.');
            helpers.setTimer('00:00');
            state.timer = setInterval(() => {
                const sec = Math.max(0, Math.floor((Date.now() - state.startedAt) / 1000));
                const mm = String(Math.floor(sec / 60)).padStart(2, '0');
                const ss = String(sec % 60).padStart(2, '0');
                helpers.setTimer(`${mm}:${ss}`);
            }, 200);
        } catch (err) {
            helpers.setStatus(`Could not start recording: ${err}`);
        }
        return [];
    }
    """

    stop_record_js = """
    () => {
        const state = window.__strategyRecorderState;
        const helpers = window.__strategyRecorderHelpers;
        if (!state || !helpers) return [];
        if (!state.isRecording) {
            helpers.setStatus('No active recording.');
            return [];
        }

        helpers.stopActiveRecording();
        helpers.setStatus(state.transcript ? 'Stopped. Review the transcript, then click Use as Strategy if you want it.' : 'Stopped. No transcript captured.');
        helpers.syncPreviewToTextbox();
        return [];
    }
    """

    use_recording_js = """
    () => {
        const state = window.__strategyRecorderState;
        const helpers = window.__strategyRecorderHelpers;
        const text = (state && state.transcript ? state.transcript : "").toString().trim();
        if (helpers) helpers.setStatus(text ? "Transcript copied into Strategy." : "Nothing captured yet.");
        return [text];
    }
    """

    discard_recording_js = """
    () => {
        const state = window.__strategyRecorderState;
        const helpers = window.__strategyRecorderHelpers;
        if (!state || !helpers) return [];
        helpers.clearRecordingState();
        helpers.setStatus("Discarded.");
        return [];
    }
    """

    def on_start(strategy_text: str):
        runner.strategy_text = strategy_text or ""
        runner.start()
        return core.get_log_html()

    def on_pause():
        runner.pause()
        return core.get_log_html()

    def on_step(strategy_text: str):
        runner.strategy_text = strategy_text or ""
        runner.step_once()
        return core.get_log_html()

    def on_refresh_log():
        return core.get_log_html()

    def show_voice_panel():
        return gr.update(visible=False), gr.update(visible=True)

    def show_strategy_panel():
        return gr.update(visible=True), gr.update(visible=False)

    def use_transcript(text: str):
        """Accept transcript text, return updated strategy + panel visibility in one step."""
        return text, gr.update(visible=True), gr.update(visible=False)

    core.append_log_line("[UI] Ready. Waiting for Start / Pause / Step commands.")

    theme=gr.themes.Soft()
    css="""
        /* Strategy header (label + audio button) */
        .strategy-header {
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:10px;
            margin-bottom:6px;
        }
        .strategy-header .label {
            font-size: 20px;
            font-weight: 800;
            color: #0F172A;
            line-height: 20px;
        }

        /* Voice panel shell */
        .voice-shell {
            background: none !important;     /* remove gray shade */
            border: none !important;
            border-radius: 16px;
            padding: 0;
            margin: 0;
        }
        .voice-header-label {
            font-size: 20px;
            font-weight: 800;
            color: #0F172A;
            line-height: 20px;
        }
        
        /* Rounded-rectangle style for voice panel buttons */
        .voice-shell button,
        .voice-actions button {
            border-radius: 14px !important;
        }

        /* Compact 2x2 voice action buttons */
        .voice-actions button {
            font-size: 14px;
            padding: 7px 10px;
            white-space: nowrap;
            width: 100%;
        }

        /* Icon-only Go Back button */
        #go_back_icon button {
            min-width: 44px !important;
            width: 44px !important;
            padding: 6px 8px !important;
            border-radius: 12px !important;  /* rounded rectangle */
            font-size: 16px !important;
            line-height: 1 !important;

            color: #111 !important;          /* black arrow */
            background: #fff !important;     /* white background */
            border: 1px solid #cbd5e1 !important;
            box-shadow: none !important;
        }
        /* Add this inside your existing CSS string */

        #mic_btn {
            height: 44px !important;
            width: 44px !important;
            padding: 0 !important; /* Remove padding to let icon fill space */
            display: flex;
            align-items: center;
            justify-content: center;
        }

        #mic_btn img {
            height: 40% !important;
            width: 40% !important;
            object-fit: contain; /* Ensures the icon isn't distorted */
        }

        /* Make left column feel like one block and avoid page scrolling */
        #left_col_wrap {
            max-height: calc(100vh - 140px);
        }

        #strategy_box textarea {
            font-size: 18px !important;
        }
    """
    with gr.Blocks(title="Play My Strategy") as demo:
        gr.Markdown(
            "<div style='text-align:center'>"
            "<h1 style='margin-bottom:0.2em'>Play My Strategy</h1>"
            "<p style='margin-top:0.2em'>Edit the strategy, then <b>Start Game</b> for continuous play, <b>Pause Game</b> to stop, or <b>Single Step</b> for one move.</p>"
            "</div>"
        )

        with gr.Row(equal_height=True):
            with gr.Column(scale=5, elem_id="left_col_wrap"):
                # Strategy panel (default visible)
                with gr.Column(visible=True) as strategy_panel:
                    with gr.Row(equal_height=True):
                        gr.HTML('<div class="strategy-header"><div class="label">Strategy</div></div>')
                        # https://www.flaticon.com/free-icons/mic Mic icons created by Dave Gandy - Flaticon
                        audio_btn = gr.Button(value="", icon="./icon/microphone.png", scale=0, min_width=44, elem_id="mic_btn")


                    strategy = gr.Textbox(
                        label=None,
                        show_label=False,
                        value=core.DEFAULT_STRATEGY,
                        lines=12, #9,
                        max_lines=24,
                        placeholder="Type your strategy here...",
                        #elem_id="strategy_box",
                    )

                    with gr.Row():
                        start_btn = gr.Button("Start Game", variant="primary", scale=0, min_width=150)
                        pause_btn = gr.Button("Pause Game", scale=0, min_width=150)
                        step_btn = gr.Button("Single Step", scale=0, min_width=150)


                # Voice panel (hidden until audio button is clicked)
                with gr.Column(visible=False) as voice_panel:
                    with gr.Column(elem_classes=["voice-shell"]):
                        with gr.Row(equal_height=True):
                            gr.HTML('<div class="voice-header-label">Voice Option</div>')
                            go_back_btn = gr.Button("\N{LEFTWARDS ARROW WITH HOOK}", scale=0, min_width=44, elem_id="go_back_icon")

                        gr.HTML("""
                        <div style="background:#0F172A; border:1px solid #1E293B; border-radius:14px; padding:14px; margin-top:0;">
                            <div style="display:flex; justify-content:space-between; align-items:center; gap:16px; margin-bottom:10px;">
                                <div id="voice_status_text" style="color:#BFDBFE; font-weight:600;">Ready to record.</div>
                                <div id="voice_timer_text" style="color:#FDE68A; font-family:Consolas, monospace; font-size:18px;">00:00</div>
                            </div>
                            <div id="voice_audio_holder" style="margin-bottom:10px;"></div>
                            <div style="color:#94A3B8; font-size:13px; margin-bottom:6px;">Transcript preview:</div>
                            <div id="voice_preview_box" style="min-height:72px; white-space:pre-wrap; background:#111827; color:#E5E7EB; border:1px solid #334155; border-radius:10px; padding:10px; font-size:13px;"></div>
                        </div>
                        """)

                        # 2x2 action buttons below the dark-blue box so everything fits on screen
                        with gr.Column(elem_classes=["voice-actions"], scale=1):
                            with gr.Row():
                                start_record_btn = gr.Button("Start Recording")
                                stop_record_btn = gr.Button("Stop Recording")
                            with gr.Row():
                                use_recording_btn = gr.Button("Use as Strategy", variant="primary")
                                discard_recording_btn = gr.Button("Discard")

                # Hidden textbox used for the JS -> textbox sync
                voice_preview = gr.Textbox(visible=False, elem_id="voice_preview")


            with gr.Column(scale=7):
                # Match the left-column Strategy label styling for visual balance.
                with gr.Row(equal_height=True):
                    gr.HTML('<div class="strategy-header"><div class="label">Terminal Log</div></div>')
                    refresh_btn = gr.Button("Refresh", scale=0, min_width=110)
                    autoscroll_cb = gr.Checkbox(label="Autoscroll Logs", value=True, interactive=True, min_width=150)

                log_box = gr.HTML(
                    value=core.get_log_html(),
                    label="Controller Logs",
                )

       
        if hasattr(gr, "Timer"):
            timer = gr.Timer(1.0)
            timer.tick(fn=on_refresh_log, inputs=[], outputs=[log_box]).then(
                fn=None,
                inputs=[autoscroll_cb],
                js=scroll_js,
            )

        demo.load(fn=None, inputs=[], outputs=[], js=recorder_init_js)

        # Toggle to voice panel
        audio_btn.click(fn=show_voice_panel, inputs=[], outputs=[strategy_panel, voice_panel])
        go_back_btn.click(fn=show_strategy_panel, inputs=[], outputs=[strategy_panel, voice_panel], js="""
        () => {
            const helpers = window.__strategyRecorderHelpers;
            if (helpers) {
                helpers.clearRecordingState();
                helpers.setStatus('Ready to record.');
            }
            return [];
        }
        """)

        # Voice recording buttons
        start_record_btn.click(fn=None, inputs=[], outputs=[], js=start_record_js)
        stop_record_btn.click(fn=None, inputs=[], outputs=[], js=stop_record_js)

        # Use transcript -> strategy textbox, then return to strategy panel
        use_recording_btn.click(
            fn=use_transcript,
            inputs=[voice_preview],
            outputs=[strategy, strategy_panel, voice_panel],
            js=use_recording_js,
        ).then(
            lambda: core.get_log_html(),
            inputs=[],
            outputs=[log_box],
        ).then(
            fn=None,
            inputs=[autoscroll_cb],
            js=scroll_js,
        )

        # Discard stays on voice panel
        discard_recording_btn.click(fn=None, inputs=[], outputs=[], js=discard_recording_js)

        # Game control buttons
        start_btn.click(fn=on_start, inputs=[strategy], outputs=[log_box]).then(
            fn=None, inputs=[autoscroll_cb], js=scroll_js
        )
        pause_btn.click(fn=on_pause, inputs=[], outputs=[log_box]).then(
            fn=None, inputs=[autoscroll_cb], js=scroll_js
        )
        step_btn.click(fn=on_step, inputs=[strategy], outputs=[log_box]).then(
            fn=None, inputs=[autoscroll_cb], js=scroll_js
        )

        refresh_btn.click(fn=on_refresh_log, inputs=[], outputs=[log_box]).then(
            fn=None, inputs=[autoscroll_cb], js=scroll_js
        )

    demo.queue().launch(theme=theme, css=css)