"""Presentation review tools: exporters for JSON, CSV, and dynamic HTML review dashboards."""

import csv
import json
from pathlib import Path
from typing import List
from video_recap.application.review import (
    ObservationReviewRecord,
    calculate_accuracy_metrics,
)
from video_recap.domain.models import Observation


def export_review_json(records: List[ObservationReviewRecord], output_path: Path) -> None:
    """Export review records to a JSON file."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump([r.model_dump() for r in records], f, indent=2, ensure_ascii=False)


def export_review_csv(records: List[ObservationReviewRecord], output_path: Path) -> None:
    """Export review records to a CSV file."""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "observation_id", "timestamp", "description", "confidence",
            "visual_source", "audio_source", "label", "notes"
        ])
        for r in records:
            writer.writerow([
                r.observation_id, r.timestamp, r.description, r.confidence,
                int(r.visual_source), int(r.audio_source), r.label, r.notes or ""
            ])


def generate_review_html(
    observations: List[Observation],
    video_filepath: str,
    output_path: Path,
) -> None:
    """Generate a highly premium, interactive HTML dashboard for human verification of observations."""
    obs_json_data = []
    for obs in observations:
        # Pre-generate ffplay command for easy copying
        ffplay_cmd = f"ffplay -ss {max(0.0, obs.timestamp - 2.0):.2f} -t 6.0 -autoexit -i \"{video_filepath}\""
        obs_json_data.append({
            "id": obs.id,
            "timestamp": obs.timestamp,
            "description": obs.description,
            "confidence": obs.confidence,
            "visual_source": obs.visual_source,
            "audio_source": obs.audio_source,
            "ffplay_command": ffplay_cmd,
            "label": "unverifiable",  # Default status
            "notes": ""
        })

    obs_json_str = json.dumps(obs_json_data, ensure_ascii=False)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Observation Factual Accuracy Review Tool</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=Plus+Jakarta+Sans:wght@300;400;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-base: #0B0F19;
            --bg-surface: rgba(20, 28, 47, 0.6);
            --border-color: rgba(255, 255, 255, 0.08);
            --primary: #4F46E5;
            --primary-glow: rgba(79, 70, 229, 0.4);
            --text-main: #F3F4F6;
            --text-muted: #9CA3AF;
            --correct: #10B981;
            --partial: #F59E0B;
            --wrong: #EF4444;
            --unverifiable: #6B7280;
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            background-color: var(--bg-base);
            color: var(--text-main);
            font-family: 'Plus Jakarta Sans', sans-serif;
            height: 100vh;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }}

        h1, h2, h3, .brand {{
            font-family: 'Outfit', sans-serif;
        }}

        /* Header styling */
        header {{
            background: linear-gradient(180deg, rgba(11, 15, 25, 0.9) 0%, rgba(11, 15, 25, 0) 100%);
            border-bottom: 1px solid var(--border-color);
            padding: 1.25rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            backdrop-filter: blur(12px);
            z-index: 10;
        }}

        .brand-section {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }}

        .brand-logo {{
            width: 2rem;
            height: 2rem;
            background: linear-gradient(135deg, #818CF8 0%, #4F46E5 100%);
            border-radius: 0.5rem;
            box-shadow: 0 0 15px var(--primary-glow);
        }}

        .brand-title {{
            font-size: 1.25rem;
            font-weight: 800;
            letter-spacing: -0.5px;
            background: linear-gradient(135deg, #FFF 0%, #A5B4FC 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        /* Realtime metrics dashboard */
        .metrics-bar {{
            display: flex;
            gap: 1.5rem;
            background: var(--bg-surface);
            padding: 0.5rem 1.25rem;
            border-radius: 2rem;
            border: 1px solid var(--border-color);
        }}

        .metric-item {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.875rem;
        }}

        .metric-value {{
            font-weight: 700;
            color: #FFF;
        }}

        /* Workspace split */
        .workspace {{
            display: flex;
            flex: 1;
            height: calc(100vh - 70px);
            overflow: hidden;
        }}

        /* Left side: List of observations */
        .sidebar {{
            width: 380px;
            border-right: 1px solid var(--border-color);
            background: rgba(15, 23, 42, 0.4);
            display: flex;
            flex-direction: column;
        }}

        .sidebar-header {{
            padding: 1rem 1.5rem;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .sidebar-title {{
            font-size: 1rem;
            font-weight: 600;
            color: var(--text-muted);
        }}

        .obs-list {{
            flex: 1;
            overflow-y: auto;
            padding: 0.75rem;
        }}

        .obs-item {{
            padding: 1rem;
            border-radius: 0.75rem;
            border: 1px solid transparent;
            background: rgba(255, 255, 255, 0.02);
            margin-bottom: 0.5rem;
            cursor: pointer;
            transition: all 0.2s ease;
        }}

        .obs-item:hover {{
            background: rgba(255, 255, 255, 0.04);
            border-color: rgba(255, 255, 255, 0.05);
        }}

        .obs-item.active {{
            background: rgba(79, 70, 229, 0.15);
            border-color: var(--primary);
            box-shadow: 0 0 15px rgba(79, 70, 229, 0.1);
        }}

        .obs-meta-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
        }}

        .obs-timestamp {{
            font-size: 0.75rem;
            font-weight: 700;
            color: #818CF8;
            background: rgba(129, 140, 248, 0.1);
            padding: 0.15rem 0.5rem;
            border-radius: 0.25rem;
        }}

        .obs-badge {{
            font-size: 0.7rem;
            text-transform: uppercase;
            font-weight: 700;
            padding: 0.15rem 0.4rem;
            border-radius: 0.25rem;
        }}

        .badge-correct {{ background: rgba(16, 185, 129, 0.1); color: var(--correct); }}
        .badge-partial {{ background: rgba(245, 158, 11, 0.1); color: var(--partial); }}
        .badge-wrong {{ background: rgba(239, 68, 68, 0.1); color: var(--wrong); }}
        .badge-unverifiable {{ background: rgba(107, 114, 128, 0.1); color: var(--unverifiable); }}

        .obs-desc-preview {{
            font-size: 0.875rem;
            line-height: 1.4;
            color: var(--text-main);
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }}

        /* Right side: Editor board */
        .editor-pane {{
            flex: 1;
            padding: 2.5rem;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 2rem;
        }}

        .card {{
            background: var(--bg-surface);
            border-radius: 1rem;
            border: 1px solid var(--border-color);
            padding: 2rem;
            backdrop-filter: blur(20px);
        }}

        .section-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 1.5rem;
        }}

        .editor-title {{
            font-size: 1.5rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }}

        .editor-meta-group {{
            display: flex;
            gap: 1rem;
        }}

        .meta-pill {{
            font-size: 0.8rem;
            background: rgba(255, 255, 255, 0.05);
            padding: 0.35rem 0.75rem;
            border-radius: 0.5rem;
            color: var(--text-muted);
        }}

        .meta-pill strong {{
            color: #FFF;
        }}

        .observation-description {{
            font-size: 1.25rem;
            line-height: 1.5;
            color: #FFF;
            margin-bottom: 1.5rem;
        }}

        /* Ffplay copy command section */
        .play-tool {{
            background: rgba(0, 0, 0, 0.3);
            border-radius: 0.75rem;
            padding: 1rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }}

        .cmd-text {{
            font-family: monospace;
            font-size: 0.85rem;
            color: #A5B4FC;
            overflow-x: auto;
            white-space: nowrap;
            flex: 1;
        }}

        .btn-copy {{
            background: var(--primary);
            color: #FFF;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 0.5rem;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }}

        .btn-copy:hover {{
            background: #4338CA;
        }}

        /* Review labels selector */
        .label-selector {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 1rem;
            margin-top: 1rem;
        }}

        .label-option {{
            position: relative;
            cursor: pointer;
        }}

        .label-option input {{
            position: absolute;
            opacity: 0;
            width: 0;
            height: 0;
        }}

        .label-card {{
            border: 1px solid var(--border-color);
            background: rgba(255, 255, 255, 0.02);
            padding: 1rem;
            border-radius: 0.75rem;
            text-align: center;
            font-weight: 700;
            font-size: 0.9rem;
            transition: all 0.2s ease;
        }}

        .label-option input:checked + .label-card.card-correct {{
            background: rgba(16, 185, 129, 0.2);
            border-color: var(--correct);
            color: var(--correct);
            box-shadow: 0 0 15px rgba(16, 185, 129, 0.15);
        }}

        .label-option input:checked + .label-card.card-partial {{
            background: rgba(245, 158, 11, 0.2);
            border-color: var(--partial);
            color: var(--partial);
            box-shadow: 0 0 15px rgba(245, 158, 11, 0.15);
        }}

        .label-option input:checked + .label-card.card-wrong {{
            background: rgba(239, 68, 68, 0.2);
            border-color: var(--wrong);
            color: var(--wrong);
            box-shadow: 0 0 15px rgba(239, 68, 68, 0.15);
        }}

        .label-option input:checked + .label-card.card-unverifiable {{
            background: rgba(107, 114, 128, 0.2);
            border-color: var(--unverifiable);
            color: var(--unverifiable);
            box-shadow: 0 0 15px rgba(107, 114, 128, 0.15);
        }}

        /* Notes section */
        .notes-field {{
            margin-top: 1.5rem;
        }}

        .notes-label {{
            font-size: 0.875rem;
            font-weight: 600;
            color: var(--text-muted);
            margin-bottom: 0.5rem;
            display: block;
        }}

        textarea {{
            width: 100%;
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--border-color);
            border-radius: 0.75rem;
            padding: 1rem;
            color: #FFF;
            font-family: inherit;
            resize: none;
            height: 100px;
            transition: border-color 0.2s;
        }}

        textarea:focus {{
            outline: none;
            border-color: var(--primary);
        }}

        /* Footer buttons */
        .footer-action {{
            display: flex;
            justify-content: flex-end;
        }}

        .btn-download {{
            background: linear-gradient(135deg, #818CF8 0%, #4F46E5 100%);
            color: #FFF;
            border: none;
            padding: 0.75rem 2rem;
            border-radius: 0.75rem;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            box-shadow: 0 4px 15px var(--primary-glow);
            transition: all 0.2s;
        }}

        .btn-download:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(79, 70, 229, 0.5);
        }}
    </style>
</head>
<body>

    <header>
        <div class="brand-section">
            <div class="brand-logo"></div>
            <div class="brand-title">VideoRecapStudio Review Dashboard</div>
        </div>

        <div class="metrics-bar">
            <div class="metric-item">
                <span>Accuracy:</span>
                <span class="metric-value" id="stat-accuracy">0%</span>
            </div>
            <div class="metric-item">
                <span>Correct:</span>
                <span class="metric-value" id="stat-correct">0</span>
            </div>
            <div class="metric-item">
                <span>Partial:</span>
                <span class="metric-value" id="stat-partial">0</span>
            </div>
            <div class="metric-item">
                <span>Wrong:</span>
                <span class="metric-value" id="stat-wrong">0</span>
            </div>
            <div class="metric-item">
                <span>Total:</span>
                <span class="metric-value" id="stat-total">0/0</span>
            </div>
        </div>
    </header>

    <div class="workspace">
        <!-- Sidebar list -->
        <div class="sidebar">
            <div class="sidebar-header">
                <div class="sidebar-title">Observations</div>
            </div>
            <div class="obs-list" id="obs-list-container">
                <!-- Javascript populated -->
            </div>
        </div>

        <!-- Editor panel -->
        <div class="editor-pane">
            <div class="card" id="editor-card">
                <div class="section-header">
                    <div>
                        <h2 class="editor-title" id="editor-obs-id">Observation Detail</h2>
                        <div class="editor-meta-group">
                            <span class="meta-pill">Time: <strong id="editor-time">0.0s</strong></span>
                            <span class="meta-pill">Confidence: <strong id="editor-confidence">0.0</strong></span>
                            <span class="meta-pill">Modalities: <strong id="editor-modalities">None</strong></span>
                        </div>
                    </div>
                </div>

                <div class="observation-description" id="editor-desc">
                    Select an observation from the sidebar to begin review.
                </div>

                <div class="play-tool">
                    <span class="cmd-text" id="editor-cmd">ffplay command...</span>
                    <button class="btn-copy" onclick="copyCommand()">Copy Command</button>
                </div>

                <div style="margin-top: 2rem;">
                    <span class="notes-label">Review Label</span>
                    <div class="label-selector">
                        <label class="label-option">
                            <input type="radio" name="review-label" value="correct" onclick="setLabel('correct')">
                            <div class="label-card card-correct">Correct</div>
                        </label>
                        <label class="label-option">
                            <input type="radio" name="review-label" value="partial" onclick="setLabel('partial')">
                            <div class="label-card card-partial">Partial</div>
                        </label>
                        <label class="label-option">
                            <input type="radio" name="review-label" value="wrong" onclick="setLabel('wrong')">
                            <div class="label-card card-wrong">Wrong</div>
                        </label>
                        <label class="label-option">
                            <input type="radio" name="review-label" value="unverifiable" onclick="setLabel('unverifiable')">
                            <div class="label-card card-unverifiable">Unverifiable</div>
                        </label>
                    </div>
                </div>

                <div class="notes-field">
                    <label class="notes-label" for="editor-notes">Reviewer Notes</label>
                    <textarea id="editor-notes" placeholder="Enter notes or discrepancies found..." oninput="updateNotes()"></textarea>
                </div>
            </div>

            <div class="footer-action">
                <button class="btn-download" onclick="downloadResults()">Download Completed Review (JSON)</button>
            </div>
        </div>
    </div>

    <script>
        const observations = {obs_json_str};
        let activeIndex = 0;

        function renderList() {{
            const container = document.getElementById("obs-list-container");
            container.innerHTML = "";

            observations.forEach((obs, idx) => {{
                const item = document.createElement("div");
                item.className = `obs-item ${{idx === activeIndex ? 'active' : ''}}`;
                item.onclick = () => selectObservation(idx);

                const metaRow = document.createElement("div");
                metaRow.className = "obs-meta-row";

                const ts = document.createElement("span");
                ts.className = "obs-timestamp";
                ts.innerText = obs.timestamp.toFixed(2) + "s";

                const badge = document.createElement("span");
                badge.className = "obs-badge badge-" + obs.label;
                badge.innerText = obs.label;

                metaRow.appendChild(ts);
                metaRow.appendChild(badge);

                const desc = document.createElement("div");
                desc.className = "obs-desc-preview";
                desc.innerText = obs.description;

                item.appendChild(metaRow);
                item.appendChild(desc);
                container.appendChild(item);
            }});

            calculateMetrics();
        }}

        function selectObservation(idx) {{
            activeIndex = idx;
            renderList();

            const obs = observations[idx];
            document.getElementById("editor-obs-id").innerText = "Reviewing " + obs.id;
            document.getElementById("editor-desc").innerText = obs.description;
            document.getElementById("editor-time").innerText = obs.timestamp.toFixed(2) + "s";
            document.getElementById("editor-confidence").innerText = obs.confidence.toFixed(2);
            document.getElementById("editor-cmd").innerText = obs.ffplay_command;

            // Modalities display
            let mods = [];
            if (obs.visual_source) mods.push("Visual");
            if (obs.audio_source) mods.push("Audio");
            document.getElementById("editor-modalities").innerText = mods.join(" + ");

            // Set radio button check
            const radios = document.getElementsByName("review-label");
            radios.forEach(r => {{
                r.checked = r.value === obs.label;
            }});

            // Notes
            document.getElementById("editor-notes").value = obs.notes || "";
        }}

        function setLabel(label) {{
            observations[activeIndex].label = label;
            renderList();
        }}

        function updateNotes() {{
            observations[activeIndex].notes = document.getElementById("editor-notes").value;
        }}

        function copyCommand() {{
            const cmd = document.getElementById("editor-cmd").innerText;
            navigator.clipboard.writeText(cmd).then(() => {{
                alert("ffplay command copied to clipboard!");
            }});
        }}

        function calculateMetrics() {{
            let correct = 0;
            let partial = 0;
            let wrong = 0;
            let unverifiable = 0;

            observations.forEach(obs => {{
                if (obs.label === "correct") correct++;
                else if (obs.label === "partial") partial++;
                else if (obs.label === "wrong") wrong++;
                else if (obs.label === "unverifiable") unverifiable++;
            }});

            const ratedCount = correct + partial + wrong;
            const accuracy = ratedCount > 0 ? ((correct + 0.5 * partial) / ratedCount) * 100 : 0;

            document.getElementById("stat-accuracy").innerText = accuracy.toFixed(1) + "%";
            document.getElementById("stat-correct").innerText = correct;
            document.getElementById("stat-partial").innerText = partial;
            document.getElementById("stat-wrong").innerText = wrong;
            document.getElementById("stat-total").innerText = (correct + partial + wrong + unverifiable) + "/" + observations.length;
        }}

        function downloadResults() {{
            const records = observations.map(obs => ({{
                observation_id: obs.id,
                timestamp: obs.timestamp,
                description: obs.description,
                confidence: obs.confidence,
                visual_source: obs.visual_source,
                audio_source: obs.audio_source,
                label: obs.label,
                notes: obs.notes
            }}));

            const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(json.stringify(records, null, 2));
            const dlAnchorElem = document.createElement('a');
            dlAnchorElem.setAttribute("href", dataStr);
            dlAnchorElem.setAttribute("download", "observation_review_records.json");
            dlAnchorElem.click();
        }}

        // Initial load
        if (observations.length > 0) {{
            selectObservation(0);
        }} else {{
            document.getElementById("editor-card").style.display = "none";
        }}
    </script>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
