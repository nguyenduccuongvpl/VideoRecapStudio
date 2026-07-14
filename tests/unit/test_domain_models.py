"""Unit tests for domain models, validation, and storage operations."""

import json
from pathlib import Path
from unittest.mock import patch
import pytest
from pydantic import ValidationError
from video_recap.domain import (
    ClipCandidate,
    CostRecord,
    Event,
    EventGraph,
    EventRelation,
    Job,
    JobState,
    Keyframe,
    MediaInfo,
    MediaStreamInfo,
    Narration,
    NarrationClaim,
    NarrationSegment,
    Observation,
    ProjectConfig,
    QAFinding,
    QAReport,
    RunManifest,
    Shot,
    SourceClip,
    StageName,
    StageResult,
    StoryBeat,
    StoryOutline,
    SubtitleCue,
    SubtitleTrack,
    TimeRange,
    Timeline,
    TimelineSegment,
    TranscriptCue,
    SpeakerRef,
    Entity,
    EntityMention,
    AudioAsset,
)
from video_recap.domain.storage import load_artifact, register_migrator, save_artifact_atomic


def test_time_range_validation() -> None:
    """Test start and end validation in TimeRange."""
    # Happy path
    tr = TimeRange(start=10.0, end=15.5)
    assert tr.start == 10.0
    assert tr.end == 15.5

    # Fails when start >= end
    with pytest.raises(ValidationError):
        TimeRange(start=10.0, end=10.0)

    with pytest.raises(ValidationError):
        TimeRange(start=10.0, end=5.0)

    # Fails when non-negative constraint is broken
    with pytest.raises(ValidationError):
        TimeRange(start=-1.0, end=5.0)


def test_time_range_contextual_validation() -> None:
    """Test TimeRange validation against media duration context."""
    tr = TimeRange(start=5.0, end=10.0)

    # Within duration
    tr.validate_with_context(10.0)
    tr.validate_with_context(12.5)

    # Exceeds duration
    with pytest.raises(ValueError, match="exceeds media duration"):
        tr.validate_with_context(9.9)


def test_keyframe_confidence_validation() -> None:
    """Test confidence boundaries [0, 1] in Keyframe."""
    # Happy path
    kf = Keyframe(shot_id=1, timestamp=2.0, path="kf.jpg", confidence=0.75)
    assert kf.confidence == 0.75

    # Out of bounds
    with pytest.raises(ValidationError):
        Keyframe(shot_id=1, timestamp=2.0, path="kf.jpg", confidence=-0.1)

    with pytest.raises(ValidationError):
        Keyframe(shot_id=1, timestamp=2.0, path="kf.jpg", confidence=1.01)


def test_observation_validation() -> None:
    """Test Observation model constraints."""
    # Happy path
    obs = Observation(
        id="obs_01",
        timestamp=5.0,
        description="Character John walks in",
        confidence=0.9,
        visual_source=True,
        audio_source=False,
    )
    assert obs.id == "obs_01"

    # Invalid confidence
    with pytest.raises(ValidationError):
        Observation(
            id="obs_01",
            timestamp=5.0,
            description="Character John walks in",
            confidence=1.1,
            visual_source=True,
            audio_source=False,
        )


def test_event_graph_integrity() -> None:
    """Test EventGraph unique IDs and relation validity."""
    e1 = Event(
        id="ev_01",
        title="Event 1",
        description="John enters",
        time_range=TimeRange(start=0.0, end=5.0),
        participant_ids=["john"],
        evidence_refs=["obs_01"],
    )
    e2 = Event(
        id="ev_02",
        title="Event 2",
        description="John talks",
        time_range=TimeRange(start=5.0, end=10.0),
        participant_ids=["john"],
        evidence_refs=["obs_02"],
    )

    # Happy path
    graph = EventGraph(
        producer_stage="BUILDING_EVENTS",
        events=[e1, e2],
        relations=[EventRelation(source_id="ev_01", target_id="ev_02", relation_type="causal")],
    )
    assert len(graph.events) == 2

    # Fails when event IDs are duplicate
    with pytest.raises(ValidationError, match="Event IDs must be unique"):
        EventGraph(producer_stage="BUILDING_EVENTS", events=[e1, e1], relations=[])

    # Fails when relation points to non-existent source
    with pytest.raises(ValidationError, match="does not exist in events"):
        EventGraph(
            producer_stage="BUILDING_EVENTS",
            events=[e1, e2],
            relations=[
                EventRelation(source_id="ev_missing", target_id="ev_02", relation_type="causal")
            ],
        )

    # Fails when relation points to non-existent target
    with pytest.raises(ValidationError, match="does not exist in events"):
        EventGraph(
            producer_stage="BUILDING_EVENTS",
            events=[e1, e2],
            relations=[
                EventRelation(source_id="ev_01", target_id="ev_missing", relation_type="causal")
            ],
        )


def test_story_outline_beats() -> None:
    """Test StoryOutline unique StoryBeats constraint."""
    b1 = StoryBeat(id="b_01", title="Beat 1", description="", event_ids=["ev_1"], duration_seconds=10.0)
    b2 = StoryBeat(id="b_02", title="Beat 2", description="", event_ids=["ev_2"], duration_seconds=5.0)

    # Happy path
    outline = StoryOutline(producer_stage="PLANNING_STORY", title="Outline", beats=[b1, b2])
    assert len(outline.beats) == 2

    # Duplicate Beat IDs
    with pytest.raises(ValidationError, match="StoryBeat IDs must be unique"):
        StoryOutline(producer_stage="PLANNING_STORY", title="Outline", beats=[b1, b1])


def test_narration_segment_evidence_required() -> None:
    """Test that NarrationSegment requires non-empty event_ids and evidence_refs."""
    claim = NarrationClaim(
        statement="John is here",
        evidence_refs=["obs_01"],
        source_time_ranges=[TimeRange(start=0.0, end=5.0)],
    )

    # Happy path
    seg = NarrationSegment(
        segment_id=1,
        text="John walks into the room.",
        claims=[claim],
        event_ids=["ev_01"],
        evidence_refs=["obs_01"],
    )
    assert seg.segment_id == 1

    # Empty event_ids
    with pytest.raises(ValidationError):
        NarrationSegment(
            segment_id=1,
            text="John walks into the room.",
            claims=[claim],
            event_ids=[],
            evidence_refs=["obs_01"],
        )

    # Empty evidence_refs
    with pytest.raises(ValidationError):
        NarrationSegment(
            segment_id=1,
            text="John walks into the room.",
            claims=[claim],
            event_ids=["ev_01"],
            evidence_refs=[],
        )


def test_timeline_overlaps_and_gaps() -> None:
    """Test Timeline segment overlap and gap policies."""
    clip1 = SourceClip(filepath="src.mp4", time_range=TimeRange(start=0.0, end=5.0))
    clip2 = SourceClip(filepath="src.mp4", time_range=TimeRange(start=5.0, end=10.0))

    seg1 = TimelineSegment(
        segment_id=1,
        narration_text="Seg 1",
        clip=clip1,
        narration_audio_path="audio1.wav",
        narration_duration=5.0,
        target_start=0.0,
    )
    # Seg 2 overlaps (starts at 4.0, while Seg 1 ends at 5.0)
    seg2_overlap = TimelineSegment(
        segment_id=2,
        narration_text="Seg 2",
        clip=clip2,
        narration_audio_path="audio2.wav",
        narration_duration=5.0,
        target_start=4.0,
    )
    # Seg 2 with gap (starts at 6.0, while Seg 1 ends at 5.0)
    seg2_gap = TimelineSegment(
        segment_id=2,
        narration_text="Seg 2",
        clip=clip2,
        narration_audio_path="audio2.wav",
        narration_duration=5.0,
        target_start=6.0,
    )

    # Seg 2 perfect (starts at 5.0)
    seg2_perfect = TimelineSegment(
        segment_id=2,
        narration_text="Seg 2",
        clip=clip2,
        narration_audio_path="audio2.wav",
        narration_duration=5.0,
        target_start=5.0,
    )

    # 1. Perfect Timeline (no gaps, no overlaps)
    t_perfect = Timeline(
        producer_stage="PLANNING_TIMELINE",
        segments=[seg1, seg2_perfect],
        allow_overlaps=False,
        allow_gaps=False,
    )
    assert len(t_perfect.segments) == 2

    # 2. Overlap Timeline - Rejected by default (allow_overlaps=False)
    with pytest.raises(ValidationError, match="Overlapping segments detected"):
        Timeline(
            producer_stage="PLANNING_TIMELINE",
            segments=[seg1, seg2_overlap],
            allow_overlaps=False,
        )

    # Overlap Timeline - Allowed explicitly
    t_overlap_ok = Timeline(
        producer_stage="PLANNING_TIMELINE",
        segments=[seg1, seg2_overlap],
        allow_overlaps=True,
    )
    assert t_overlap_ok.allow_overlaps

    # 3. Gap Timeline - Rejected when allow_gaps=False
    with pytest.raises(ValidationError, match="Gap detected"):
        Timeline(
            producer_stage="PLANNING_TIMELINE",
            segments=[seg1, seg2_gap],
            allow_gaps=False,
        )

    # Gap Timeline - Allowed by default (allow_gaps=True)
    t_gap_ok = Timeline(
        producer_stage="PLANNING_TIMELINE",
        segments=[seg1, seg2_gap],
        allow_gaps=True,
    )
    assert t_gap_ok.allow_gaps


def test_timeline_contextual_validation() -> None:
    """Test Timeline contextual validation against media duration."""
    clip_too_long = SourceClip(filepath="src.mp4", time_range=TimeRange(start=0.0, end=15.0))
    seg = TimelineSegment(
        segment_id=1,
        narration_text="Seg",
        clip=clip_too_long,
        narration_audio_path="audio.wav",
        narration_duration=5.0,
        target_start=0.0,
    )
    timeline = Timeline(producer_stage="PLANNING_TIMELINE", segments=[seg])

    # Valid if media duration is 20.0
    timeline.validate_with_context(20.0)

    # Invalid if media duration is 10.0
    with pytest.raises(ValueError, match="exceeds media duration"):
        timeline.validate_with_context(10.0)


def test_atomic_save_and_load(tmp_path: Path) -> None:
    """Test save_artifact_atomic and load_artifact utility functions."""
    info = MediaInfo(
        producer_stage="INGESTING",
        resolution="1920x1080",
        fps=30.0,
        duration=120.0,
        size_bytes=102400,
        streams=[MediaStreamInfo(codec="h264", stream_type="video")],
    )

    file_path = tmp_path / "media_info.json"

    # Save atomically
    save_artifact_atomic(file_path, info)
    assert file_path.exists()

    # Load and validate
    loaded = load_artifact(file_path, MediaInfo)
    assert loaded.resolution == "1920x1080"
    assert loaded.fps == 30.0
    assert loaded.producer_stage == "INGESTING"


def test_artifact_migration_strategy(tmp_path: Path) -> None:
    """Test schema version checking and migration strategy."""
    # Write a version 1.0.0 schema dictionary manually
    legacy_data = {
        "schema_version": "1.0.0",
        "producer_stage": "INGESTING",
        "resolution": "1280x725",  # We want to migrate this to "1280x720"
        "fps": 24.0,
        "duration": 60.0,
        "size_bytes": 50000,
        "streams": [{"codec": "h264", "stream_type": "video"}],
    }

    file_path = tmp_path / "legacy_info.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(legacy_data, f)

    # Define a migrator function for MediaInfo from 1.0.0 to 1.1.0
    def migrate_1_0_0_to_1_1_0(data: dict) -> dict:
        data["schema_version"] = "1.1.0"
        if data.get("resolution") == "1280x725":
            data["resolution"] = "1280x720"
        return data

    register_migrator(MediaInfo, "1.0.0", migrate_1_0_0_to_1_1_0)

    # Temporarily override schema_version default in MediaInfo to "1.1.0" to simulate upgrade
    with patch.object(MediaInfo.model_fields["schema_version"], "default", "1.1.0"):
        loaded = load_artifact(file_path, MediaInfo)
        assert loaded.schema_version == "1.1.0"
        assert loaded.resolution == "1280x720"  # Successfully migrated!


def test_remaining_domain_models_instantiation() -> None:
    """Test remaining domain models instantiation for full test coverage."""
    # Shot
    s = Shot(shot_id=1, time_range=TimeRange(start=0.0, end=4.0))
    assert s.shot_id == 1

    # SubtitleCue & SubtitleTrack
    cue = SubtitleCue(index=1, time_range=TimeRange(start=0.0, end=4.0), text="Hello")
    track = SubtitleTrack(producer_stage="TRANSCRIBING", language="vi", cues=[cue])
    assert track.language == "vi"

    # TranscriptCue
    tc = TranscriptCue(text="Hello speaker", time_range=TimeRange(start=0.0, end=2.0))
    assert tc.text == "Hello speaker"

    # SpeakerRef
    sp = SpeakerRef(speaker_id="spk_01", name="Alice")
    assert sp.name == "Alice"

    # EntityMention & Entity
    entity = Entity(id="ent_01", name="Car", category="Object", description="A red car")
    mention = EntityMention(entity_id="ent_01", timestamp=10.0, context="Car is moving")
    assert entity.id == mention.entity_id

    # ClipCandidate
    cc = ClipCandidate(clip_id="c_1", source_range=TimeRange(start=1.0, end=3.0), score=0.9, tags=["act"])
    assert cc.score == 0.9

    # Narration
    narr = Narration(producer_stage="WRITING_NARRATION", segments=[])
    assert len(narr.segments) == 0

    # QAReport
    qa = QAReport(
        producer_stage="VALIDATING_PREVIEW",
        findings=[
            QAFinding(finding_id="f1", metric="Q-FRZE", severity="ERROR", message="No freeze frame")
        ],
        overall_passed=False,
    )
    assert not qa.overall_passed

    # CostRecord, StageResult, RunManifest
    costs = [CostRecord(service_name="Gemini API", cost_usd=0.01, request_count=2, input_tokens=100, output_tokens=50)]
    stages = [StageResult(stage_name="INGESTING", status="SUCCESS", started_at="2026-07-14", completed_at="2026-07-14")]
    manifest = RunManifest(
        producer_stage="COMPLETED",
        job_id="job_01",
        started_at="2026-07-14",
        stages=stages,
        costs=costs,
        checksums={"project.json": "abcdef"},
    )
    assert manifest.job_id == "job_01"

    # ProjectConfig
    cfg = ProjectConfig(
        project_id="proj_01",
        source_video_path="input.mp4",
        output_directory="out",
        preset_name="default",
        target_recap_duration=300.0,
        voice_name="HoaiMy",
        api_keys={"openai": "sk-..."},
    )
    assert cfg.preset_name == "default"

    # Job
    job = Job(job_id="j_1", project_id="proj_01", state=JobState.CREATED, current_stage=StageName.VALIDATING)
    assert job.state == JobState.CREATED


def test_timeline_duplicate_segment_ids() -> None:
    """Test that Timeline segments must have unique segment_ids."""
    clip = SourceClip(filepath="src.mp4", time_range=TimeRange(start=0.0, end=5.0))
    seg1 = TimelineSegment(
        segment_id=1,
        narration_text="Seg 1",
        clip=clip,
        narration_audio_path="audio1.wav",
        narration_duration=5.0,
        target_start=0.0,
    )
    seg2_dup = TimelineSegment(
        segment_id=1,  # Duplicate ID
        narration_text="Seg 2",
        clip=clip,
        narration_audio_path="audio2.wav",
        narration_duration=5.0,
        target_start=5.0,
    )

    with pytest.raises(ValidationError, match="Timeline segment_ids must be unique"):
        Timeline(producer_stage="PLANNING_TIMELINE", segments=[seg1, seg2_dup])


def test_atomic_save_exception_handling(tmp_path: Path) -> None:
    """Test exception propagation and temp file cleanup in save_artifact_atomic."""
    info = MediaInfo(
        producer_stage="INGESTING",
        resolution="1920x1080",
        fps=30.0,
        duration=120.0,
        size_bytes=102400,
        streams=[],
    )

    # Patch os.replace to raise an exception to trigger the error handling block
    with patch("os.replace", side_effect=IOError("Mock Disk Full")):
        with pytest.raises(IOError, match="Mock Disk Full"):
            save_artifact_atomic(tmp_path / "fail.json", info)


def test_circular_migration_path(tmp_path: Path) -> None:
    """Test that circular migration paths are detected and raise an error."""
    legacy_data = {
        "schema_version": "1.0.0",
        "producer_stage": "INGESTING",
        "resolution": "1920x1080",
        "fps": 30.0,
        "duration": 120.0,
        "size_bytes": 102400,
        "streams": [],
    }

    file_path = tmp_path / "circular_info.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(legacy_data, f)

    # Register circular migrator: 1.0.0 -> 1.0.0 (or a cycle 1.0.0 -> 2.0.0 -> 1.0.0)
    register_migrator(MediaInfo, "1.0.0", lambda data: data)  # Doesn't change version

    with patch.object(MediaInfo.model_fields["schema_version"], "default", "1.1.0"):
        with pytest.raises(RuntimeError, match="Circular migration path detected"):
            load_artifact(file_path, MediaInfo)

