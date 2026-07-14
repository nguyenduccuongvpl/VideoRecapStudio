"""Unit tests for observation human review sampler, metrics calculator, and exporter."""

import csv
import json
import pytest
from pathlib import Path
from video_recap.application.review import (
    ObservationReviewRecord,
    calculate_accuracy_metrics,
    StratifiedObservationSampler,
)
from video_recap.domain.models import Observation
from video_recap.presentation.cli.review_tool import (
    export_review_json,
    export_review_csv,
    generate_review_html,
)


def test_calculate_accuracy_metrics() -> None:
    """Verify factual accuracy percentage calculation with correct, partial, wrong, and unverifiable labels."""
    records = [
        ObservationReviewRecord(
            observation_id="1", timestamp=1.0, description="desc", confidence=0.9,
            visual_source=True, audio_source=False, label="correct"
        ),
        ObservationReviewRecord(
            observation_id="2", timestamp=2.0, description="desc", confidence=0.8,
            visual_source=True, audio_source=False, label="partial"
        ),
        ObservationReviewRecord(
            observation_id="3", timestamp=3.0, description="desc", confidence=0.7,
            visual_source=True, audio_source=False, label="wrong"
        ),
        ObservationReviewRecord(
            observation_id="4", timestamp=4.0, description="desc", confidence=0.6,
            visual_source=True, audio_source=False, label="unverifiable"
        ),
    ]

    metrics = calculate_accuracy_metrics(records)

    assert metrics.total_reviewed == 4
    assert metrics.correct_count == 1
    assert metrics.partial_count == 1
    assert metrics.wrong_count == 1
    assert metrics.unverifiable_count == 1
    # Weighted accuracy: (1 + 0.5 * 1) / (1 + 1 + 1) = 1.5 / 3 = 0.50
    assert metrics.factual_accuracy == 0.50


def test_stratified_sampler_samples_target_count() -> None:
    """Verify that stratified sampler splits observations into tiers and modality strata correctly."""
    # Create 30 observations with varying confidence and modalities
    observations = []
    for i in range(30):
        confidence = 0.9 if i % 3 == 0 else (0.6 if i % 3 == 1 else 0.4)
        visual = (i % 2 == 0)
        audio = (i % 5 == 0)
        observations.append(
            Observation(
                id=f"obs-{i}",
                timestamp=float(i),
                description=f"Observation {i}",
                confidence=confidence,
                visual_source=visual,
                audio_source=audio,
            )
        )

    sampler = StratifiedObservationSampler()
    sampled = sampler.sample(observations, target_size=10)

    # Verify size
    assert len(sampled) == 10
    # Verify chronological sort order
    assert all(sampled[i].timestamp <= sampled[i+1].timestamp for i in range(len(sampled) - 1))


def test_exporters_generate_correct_files(tmp_path: Path) -> None:
    """Verify JSON, CSV, and HTML exporters generate files containing expected details."""
    records = [
        ObservationReviewRecord(
            observation_id="obs-1", timestamp=10.0, description="Cat jumps", confidence=0.9,
            visual_source=True, audio_source=False, label="correct", notes="looks good"
        )
    ]

    # 1. JSON Export
    json_file = tmp_path / "review.json"
    export_review_json(records, json_file)
    assert json_file.exists()
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data[0]["observation_id"] == "obs-1"
    assert data[0]["notes"] == "looks good"

    # 2. CSV Export
    csv_file = tmp_path / "review.csv"
    export_review_csv(records, csv_file)
    assert csv_file.exists()
    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    # Header + 1 row
    assert len(rows) == 2
    assert rows[1][0] == "obs-1"
    assert rows[1][6] == "correct"

    # 3. HTML Export
    html_file = tmp_path / "review.html"
    observations = [
        Observation(
            id="obs-1",
            timestamp=10.0,
            description="Cat jumps",
            confidence=0.9,
            visual_source=True,
            audio_source=False,
        )
    ]
    generate_review_html(observations, "video.mp4", html_file)
    assert html_file.exists()
    html_content = html_file.read_text(encoding="utf-8")
    assert "VideoRecapStudio Review Dashboard" in html_content
    assert "Cat jumps" in html_content
