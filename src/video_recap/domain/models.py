"""Domain models and Pydantic v2 schemas for VideoRecapStudio."""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


# --- Enums ---


class JobState(str, Enum):
    """Execution states of a Job."""

    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    INGESTING = "INGESTING"
    TRANSCRIBING = "TRANSCRIBING"
    DETECTING_SHOTS = "DETECTING_SHOTS"
    OBSERVING = "OBSERVING"
    BUILDING_EVENTS = "BUILDING_EVENTS"
    PLANNING_STORY = "PLANNING_STORY"
    WRITING_NARRATION = "WRITING_NARRATION"
    PLANNING_TIMELINE = "PLANNING_TIMELINE"
    GENERATING_SPEECH = "GENERATING_SPEECH"
    RENDERING_PREVIEW = "RENDERING_PREVIEW"
    VALIDATING_PREVIEW = "VALIDATING_PREVIEW"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    RENDERING_FINAL = "RENDERING_FINAL"
    VALIDATING_FINAL = "VALIDATING_FINAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StageName(str, Enum):
    """Orchestration stages in the pipeline."""

    VALIDATING = "VALIDATING"
    INGESTING = "INGESTING"
    TRANSCRIBING = "TRANSCRIBING"
    DETECTING_SHOTS = "DETECTING_SHOTS"
    OBSERVING = "OBSERVING"
    BUILDING_EVENTS = "BUILDING_EVENTS"
    PLANNING_STORY = "PLANNING_STORY"
    WRITING_NARRATION = "WRITING_NARRATION"
    PLANNING_TIMELINE = "PLANNING_TIMELINE"
    GENERATING_SPEECH = "GENERATING_SPEECH"
    RENDERING_PREVIEW = "RENDERING_PREVIEW"
    VALIDATING_PREVIEW = "VALIDATING_PREVIEW"
    RENDERING_FINAL = "RENDERING_FINAL"
    VALIDATING_FINAL = "VALIDATING_FINAL"


# --- Base Artifact Class ---


class BaseArtifact(BaseModel):
    """Base class for all file-based versioned JSON artifacts."""

    schema_version: str = "1.0.0"
    producer_stage: str
    input_hashes: Dict[str, str] = Field(default_factory=dict)


# --- Core Models ---


class TimeRange(BaseModel):
    """Represents a time range with start and end times in seconds."""

    start: float = Field(..., ge=0.0)
    end: float = Field(..., ge=0.0)

    @model_validator(mode="after")
    def validate_range(self) -> "TimeRange":
        """Ensure start time is strictly less than end time."""
        if self.start >= self.end:
            raise ValueError(f"start time ({self.start}) must be strictly less than end time ({self.end})")
        return self

    def validate_with_context(self, media_duration: float) -> None:
        """Validate time range end is within media duration bounds."""
        if self.end > media_duration:
            raise ValueError(
                f"Time range end ({self.end}) exceeds media duration ({media_duration})"
            )


# --- Media Metadata Models ---


class MediaStreamInfo(BaseModel):
    """Metadata for a single stream within a media file."""

    index: int = 0
    stream_type: str  # "video", "audio", "subtitle", etc.
    codec: str
    codec_long_name: Optional[str] = None
    profile: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    display_aspect_ratio: Optional[str] = None
    pix_fmt: Optional[str] = None
    color_space: Optional[str] = None
    color_transfer: Optional[str] = None
    color_primaries: Optional[str] = None
    fps: Optional[float] = None
    avg_frame_rate: Optional[str] = None
    r_frame_rate: Optional[str] = None
    rotation: Optional[float] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    channel_layout: Optional[str] = None
    language: Optional[str] = None
    disposition: dict[str, int] = Field(default_factory=dict)
    duration: Optional[float] = Field(None, ge=0.0)
    bit_rate: Optional[int] = Field(None, ge=0)
    start_time: Optional[float] = None
    tags: dict[str, str] = Field(default_factory=dict)


class MediaInfo(BaseArtifact):
    """Technical details of the source video."""

    format_name: str = "unknown"
    duration: float = Field(..., gt=0.0)
    size_bytes: int = Field(..., ge=0)
    bit_rate: Optional[int] = Field(None, ge=0)
    streams: List[MediaStreamInfo]
    tags: dict[str, str] = Field(default_factory=dict)
    resolution: str
    fps: float = Field(..., gt=0.0)
    has_video: bool = False
    has_audio: bool = False
    vfr_detected: bool = False


class Shot(BaseModel):
    """A single detected camera shot/scene."""

    shot_id: int = Field(..., ge=0)
    time_range: TimeRange


class Keyframe(BaseModel):
    """A keyframe image extracted from a shot."""

    shot_id: int = Field(..., ge=0)
    timestamp: float = Field(..., ge=0.0)
    path: str
    confidence: float = Field(..., ge=0.0, le=1.0)


# --- Transcription Models ---


class SubtitleCue(BaseModel):
    """A single subtitle line with time bounds."""

    index: int = Field(..., ge=0)
    time_range: TimeRange
    text: str


class SubtitleTrack(BaseArtifact):
    """Phụ đề (SRT hoặc vtt) có cấu trúc."""

    language: str
    cues: List[SubtitleCue]


class TranscriptCue(BaseModel):
    """A single transcript segment."""

    text: str
    time_range: TimeRange
    speaker: Optional[str] = None


class SpeakerRef(BaseModel):
    """Reference to a speaking character in transcription."""

    speaker_id: str
    name: str


# --- Knowledge & Graph Models ---


class Entity(BaseModel):
    """An resolved entity (character, object, place) in the video."""

    id: str
    name: str
    category: str
    description: str


class EntityMention(BaseModel):
    """Occurrence of an entity at a specific point in the video."""

    entity_id: str
    timestamp: float = Field(..., ge=0.0)
    context: str


class Observation(BaseModel):
    """Factual visual or audio observation at a given timestamp."""

    id: str
    timestamp: float = Field(..., ge=0.0)
    description: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    visual_source: bool
    audio_source: bool


class EvidenceRef(BaseModel):
    """Links a claim to an observation or source time range."""

    observation_id: str
    timestamp: float = Field(..., ge=0.0)


class Event(BaseModel):
    """A logical event occurring in the narrative."""

    id: str
    title: str
    description: str
    time_range: TimeRange
    participant_ids: List[str]
    evidence_refs: List[str]


class EventRelation(BaseModel):
    """A causal or temporal connection between two events."""

    source_id: str
    target_id: str
    relation_type: str  # e.g., "causal", "temporal"


class EventGraph(BaseArtifact):
    """Network of entities, events, and relations."""

    events: List[Event]
    relations: List[EventRelation]

    @model_validator(mode="after")
    def validate_graph(self) -> "EventGraph":
        """Verify graph integrity and unique event IDs."""
        event_ids = {e.id for e in self.events}
        if len(event_ids) != len(self.events):
            raise ValueError("Event IDs must be unique in EventGraph")

        for rel in self.relations:
            if rel.source_id not in event_ids:
                raise ValueError(f"Relation source {rel.source_id} does not exist in events")
            if rel.target_id not in event_ids:
                raise ValueError(f"Relation target {rel.target_id} does not exist in events")
        return self


# --- Story Outline Models ---


class StoryBeat(BaseModel):
    """A narrative beat in the story outline."""

    id: str
    title: str
    description: str
    event_ids: List[str]
    duration_seconds: float = Field(..., gt=0.0)


class StoryOutline(BaseArtifact):
    """Logical narrative outline of the recap video."""

    title: str
    beats: List[StoryBeat]

    @model_validator(mode="after")
    def validate_beats(self) -> "StoryOutline":
        """Ensure beat IDs are unique."""
        beat_ids = [b.id for b in self.beats]
        if len(beat_ids) != len(set(beat_ids)):
            raise ValueError("StoryBeat IDs must be unique in StoryOutline")
        return self


# --- Narration Models ---


class NarrationClaim(BaseModel):
    """A factual claim stated in a narration segment."""

    statement: str
    evidence_refs: List[str]
    source_time_ranges: List[TimeRange]


class NarrationSegment(BaseModel):
    """A single segment of narration text with evidentiary grounding."""

    segment_id: int = Field(..., ge=0)
    text: str
    claims: List[NarrationClaim]
    event_ids: List[str] = Field(..., min_length=1)
    evidence_refs: List[str] = Field(..., min_length=1)


class Narration(BaseArtifact):
    """Completed narration script containing grounded segments."""

    segments: List[NarrationSegment]


# --- Timeline & Clipping Models ---


class ClipCandidate(BaseModel):
    """A candidate clip segment parsed from video source."""

    clip_id: str
    source_range: TimeRange
    score: float = Field(..., ge=0.0, le=1.0)
    tags: List[str]


class SourceClip(BaseModel):
    """A reference to a source video chunk."""

    filepath: str
    time_range: TimeRange


class TimelineSegment(BaseModel):
    """A timeline block matching a clip to narration audio."""

    segment_id: int = Field(..., ge=0)
    narration_text: str
    clip: SourceClip
    narration_audio_path: str
    narration_duration: float = Field(..., gt=0.0)
    target_start: float = Field(..., ge=0.0)

    @property
    def target_end(self) -> float:
        """Calculate target end timestamp on timeline."""
        return self.target_start + self.narration_duration


class Timeline(BaseArtifact):
    """The constructed render timeline."""

    segments: List[TimelineSegment]
    allow_overlaps: bool = False
    allow_gaps: bool = True

    @model_validator(mode="after")
    def validate_timeline(self) -> "Timeline":
        """Check for timeline uniqueness, overlaps, and gaps according to policy."""
        sorted_segs = sorted(self.segments, key=lambda s: s.target_start)

        seg_ids = [s.segment_id for s in sorted_segs]
        if len(seg_ids) != len(set(seg_ids)):
            raise ValueError("Timeline segment_ids must be unique")

        for i in range(len(sorted_segs) - 1):
            curr_seg = sorted_segs[i]
            next_seg = sorted_segs[i + 1]

            if curr_seg.target_end > next_seg.target_start:
                if not self.allow_overlaps:
                    raise ValueError(
                        f"Overlapping segments detected between segment {curr_seg.segment_id} "
                        f"and {next_seg.segment_id} (ends at {curr_seg.target_end}, "
                        f"starts at {next_seg.target_start})"
                    )

            if curr_seg.target_end < next_seg.target_start:
                if not self.allow_gaps:
                    raise ValueError(
                        f"Gap detected between segment {curr_seg.segment_id} "
                        f"and {next_seg.segment_id} (ends at {curr_seg.target_end}, "
                        f"starts at {next_seg.target_start})"
                    )
        return self

    def validate_with_context(self, media_duration: float) -> None:
        """Validate all source clip ranges against total media duration."""
        for seg in self.segments:
            seg.clip.time_range.validate_with_context(media_duration)


# --- Audio Assets & QA Models ---


class AudioAsset(BaseModel):
    """Metadata for an external audio asset."""

    filepath: str
    duration: float = Field(..., gt=0.0)
    volume: float = Field(1.0, ge=0.0)


class QAFinding(BaseModel):
    """A quality finding generated during QA checks."""

    finding_id: str
    metric: str
    severity: str  # "ERROR", "WARNING", "INFO"
    message: str
    timestamp: Optional[float] = Field(None, ge=0.0)


class QAReport(BaseArtifact):
    """QA analysis report containing all findings."""

    findings: List[QAFinding]
    overall_passed: bool


# --- Persistence & Cost Models ---


class CostRecord(BaseModel):
    """API usage cost log."""

    service_name: str
    cost_usd: float = Field(..., ge=0.0)
    request_count: int = Field(..., ge=0)
    input_tokens: int = Field(..., ge=0)
    output_tokens: int = Field(..., ge=0)


class StageResult(BaseModel):
    """Execution status logs of a single pipeline stage."""

    stage_name: str
    status: str  # "SUCCESS", "FAILED", "SKIPPED"
    started_at: str
    completed_at: str
    error_message: Optional[str] = None


class RunManifest(BaseArtifact):
    """Complete logs manifest of a pipeline execution run."""

    job_id: str
    started_at: str
    completed_at: Optional[str] = None
    stages: List[StageResult]
    costs: List[CostRecord]
    checksums: Dict[str, str]


class ProjectConfig(BaseModel):
    """General configuration data of a project."""

    project_id: str
    source_video_path: str
    output_directory: str
    preset_name: str
    target_recap_duration: float = Field(..., gt=0.0)
    voice_name: str
    api_keys: Dict[str, str]


class Job(BaseModel):
    """Represents a pipeline task execution job."""

    job_id: str
    project_id: str
    state: JobState
    current_stage: Optional[StageName] = None
    error_details: Optional[str] = None
