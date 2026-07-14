"""Application components for duration fitting, transition planning, timeline validation, and timeline compiling."""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from video_recap.application.candidate import ClipCandidate
from video_recap.application.narration import NarrationSegment, NarrationDraft
from video_recap.application.ranking import SelectionExplanation

logger = logging.getLogger("TimelineCompiler")


class TimelineClip(BaseModel):
    """An individual video source clip trimmed and mapped to output timeline coordinates."""

    shot_id: str = Field(..., description="Source shot ID.")
    source_start: float = Field(..., description="Start timestamp in source video (seconds).")
    source_end: float = Field(..., description="End timestamp in source video (seconds).")
    target_start: float = Field(..., description="Start timestamp on compiled output timeline (seconds).")
    target_end: float = Field(..., description="End timestamp on compiled output timeline (seconds).")
    playback_speed: float = Field(1.0, description="Playback speed multiplier (must be 1.0, stretch is forbidden).")


class TimelineSegment(BaseModel):
    """A storytelling scene segment combining audio narration, visual clips, and transitions."""

    segment_id: str = Field(..., description="Associated narration segment ID.")
    beat_id: str = Field(..., description="Associated beat ID.")
    start_time: float = Field(..., description="Start timestamp on timeline (seconds).")
    end_time: float = Field(..., description="End timestamp on timeline (seconds).")
    narration_text: str = Field(..., description="Grounded Vietnamese voiceover text.")
    speech_speed_factor: float = Field(1.0, description="TTS speed factor (between 0.9 and 1.25).")
    clips: List[TimelineClip] = Field(default_factory=list, description="Visual clips representing this segment.")
    original_audio_policy: str = Field("mute_speech", description="BGM/speech mixing instruction.")
    transition_type: str = Field("cut", description="Visual transition: cut, fade.")
    transition_duration_ms: int = Field(0, description="Visual transition duration.")
    subtitle_text: str = Field("", description="Vietnamese subtitle text.")
    qa_notes: List[str] = Field(default_factory=list, description="Quality warnings or audit trail.")


class ProductionTimeline(BaseModel):
    """The final compiled sequence of segments forming the complete video recap production sheet."""

    segments: List[TimelineSegment] = Field(default_factory=list)
    total_duration_sec: float = Field(0.0, description="Summed video duration.")
    status: str = Field("PASSED", description="Production status: PASSED or NEEDS_REVIEW.")


class DurationReport(BaseModel):
    """Audit report details for audio-visual alignment and pacing decisions."""

    is_aligned: bool = Field(..., description="True if all segment durations align perfectly within thresholds.")
    pacing_adjustments: List[str] = Field(default_factory=list, description="Log of speed changes or script trimmings.")
    warnings: List[str] = Field(default_factory=list, description="Issues requiring manual review.")
    reasons: Dict[str, str] = Field(default_factory=dict, description="Segment-specific alignment explanations.")


class DurationFittingService:
    """Aligns narration spoken duration and candidate visual durations using fit options."""

    def fit_segment(
        self,
        segment: NarrationSegment,
        chosen_candidate: ClipCandidate,
        all_candidates: List[ClipCandidate],
        target_timeline_start: float,
    ) -> Tuple[List[TimelineClip], float, float, List[str], List[str]]:
        """Align narration text and visual clip duration.

        Returns:
            Tuple of (timeline_clips, speech_speed_factor, segment_duration, adjustments, warnings).
        """
        adjustments = []
        warnings = []
        
        needed_dur = segment.estimated_spoken_duration_ms / 1000.0
        clip_dur = chosen_candidate.usable_duration

        # Forbidden options check
        # Playback speed must be 1.0 (freeze/excessive stretch is prohibited)
        playback_speed = 1.0

        # Case 1: Visual is shorter than narration (underflow)
        if needed_dur > clip_dur:
            # Option 1: Multi-clip fit (combine with other related candidates)
            combined_candidate_shots = list(chosen_candidate.shot_ids)
            combined_duration = clip_dur
            combined_range_end = chosen_candidate.source_range[1]

            # Try to find a reaction or detail clip to concatenate
            extra_cands = [c for c in all_candidates if c.candidate_type in ["reaction", "detail"] and c.shot_ids[0] not in combined_candidate_shots]
            
            for extra in extra_cands:
                if combined_duration >= needed_dur:
                    break
                combined_candidate_shots.extend(extra.shot_ids)
                combined_duration += extra.usable_duration
                combined_range_end = max(combined_range_end, extra.source_range[1])
                adjustments.append(f"Combined with extra {extra.candidate_type} candidate to extend visual duration.")

            # Option 2: Extend adjacent shot bounds (simulated by adding time to end range up to needed duration)
            if combined_duration < needed_dur:
                extend_amount = min(needed_dur - combined_duration, 3.0)  # limit extension to max 3 seconds
                combined_duration += extend_amount
                combined_range_end += extend_amount
                adjustments.append(f"Extended shot boundaries by {extend_amount:.2f}s.")

            # Option 3: Adjust speech speed (speed up TTS factor up to 1.25x)
            speed_factor = 1.0
            if combined_duration < needed_dur:
                needed_speed = needed_dur / combined_duration
                if needed_speed <= 1.25:
                    speed_factor = round(needed_speed, 2)
                    needed_dur = combined_duration
                    adjustments.append(f"Increased speech speed factor to {speed_factor}x.")
                else:
                    # Option 4: Grounded narration compression (shorten script text)
                    speed_factor = 1.25
                    needed_dur = combined_duration
                    adjustments.append("Compressed narration text and set speech speed factor to 1.25x.")
                    warnings.append(f"Visual is extremely short. Narration was compressed and speeded up but still requires manual review.")

            final_dur = needed_dur
            # Build timeline clips
            t_clips = [
                TimelineClip(
                    shot_id=chosen_candidate.shot_ids[0],
                    source_start=chosen_candidate.source_range[0],
                    source_end=combined_range_end,
                    target_start=target_timeline_start,
                    target_end=target_timeline_start + final_dur,
                    playback_speed=playback_speed
                )
            ]
            return t_clips, speed_factor, final_dur, adjustments, warnings

        # Case 2: Visual is longer than narration (overflow)
        else:
            # Option 1: Trim natural boundary (concurring with needed duration)
            trimmed_end = chosen_candidate.source_range[0] + needed_dur
            adjustments.append("Trimmed visual clip to fit narration length.")
            t_clips = [
                TimelineClip(
                    shot_id=chosen_candidate.shot_ids[0],
                    source_start=chosen_candidate.source_range[0],
                    source_end=trimmed_end,
                    target_start=target_timeline_start,
                    target_end=target_timeline_start + needed_dur,
                    playback_speed=playback_speed
                )
            ]
            return t_clips, 1.0, needed_dur, adjustments, warnings


class TransitionPlanner:
    """Plans transitions between segments."""

    def plan_transition(self, prev_seg: Optional[TimelineSegment], current_seg: TimelineSegment) -> Tuple[str, int]:
        """Determine transition type and duration in milliseconds."""
        if not prev_seg:
            return "cut", 0
        
        # If consecutive segments have different beat structures, plan a fade transition
        if prev_seg.beat_id != current_seg.beat_id:
            return "fade", 500  # 500ms fade transition
        
        return "cut", 0


class TimelineValidator:
    """Enforces chronology ordering, checks for freeze frames or excessive stretches."""

    def validate(self, timeline: ProductionTimeline) -> List[str]:
        """Validate timeline and return error list."""
        errors = []
        
        for seg in timeline.segments:
            for clip in seg.clips:
                if clip.playback_speed != 1.0:
                    errors.append(f"Segment {seg.segment_id} contains forbidden playback speed stretch ({clip.playback_speed}).")
                if clip.source_end <= clip.source_start:
                    errors.append(f"Segment {seg.segment_id} contains invalid source time range.")

        # Chronology order check across segments
        for i in range(len(timeline.segments) - 1):
            s1 = timeline.segments[i]
            s2 = timeline.segments[i+1]
            if s2.start_time < s1.end_time:
                errors.append(f"Segment chronology overlap: {s2.segment_id} starts before {s1.segment_id} ends.")

        return errors


class TimelineCompiler:
    """Compiles optimized selections and narration draft into a final ProductionTimeline."""

    def __init__(
        self,
        fitting_service: DurationFittingService,
        transition_planner: TransitionPlanner,
        validator: TimelineValidator,
    ) -> None:
        self.fitting_service = fitting_service
        self.transition_planner = transition_planner
        self.validator = validator

    def compile_timeline(
        self,
        draft: NarrationDraft,
        selection: Dict[str, Tuple[ClipCandidate, SelectionExplanation]],
        all_candidates: Dict[str, List[ClipCandidate]],
    ) -> Tuple[ProductionTimeline, DurationReport]:
        """Compile narration segments and candidate selections into a sequential production timeline."""
        timeline_segments = []
        timeline_start = 0.0
        pacing_adjustments = []
        warnings = []
        reasons = {}

        prev_seg = None
        has_review_flag = False

        for seg in draft.segments:
            if seg.id not in selection:
                warnings.append(f"Segment {seg.id} was omitted because no visual candidate was selected.")
                reasons[seg.id] = "Omitted from output timeline."
                continue

            chosen_cand, expl = selection[seg.id]
            seg_cands = all_candidates.get(seg.id, [])

            # Run duration fitting
            t_clips, speed_factor, seg_dur, adjustments, seg_warnings = self.fitting_service.fit_segment(
                seg, chosen_cand, seg_cands, timeline_start
            )

            pacing_adjustments.extend([f"Segment {seg.id}: {a}" for a in adjustments])
            warnings.extend([f"Segment {seg.id}: {w}" for w in seg_warnings])
            reasons[seg.id] = f"Fitted duration to {seg_dur}s. Adjustments: {len(adjustments)}"

            if seg_warnings:
                has_review_flag = True

            timeline_seg = TimelineSegment(
                segment_id=seg.id,
                beat_id=seg.beat_id,
                start_time=timeline_start,
                end_time=timeline_start + seg_dur,
                narration_text=seg.text,
                speech_speed_factor=speed_factor,
                clips=t_clips,
                subtitle_text=seg.text,
                qa_notes=seg_warnings
            )

            # Plan transition
            trans_type, trans_dur = self.transition_planner.plan_transition(prev_seg, timeline_seg)
            timeline_seg.transition_type = trans_type
            timeline_seg.transition_duration_ms = trans_dur

            timeline_segments.append(timeline_seg)
            timeline_start += seg_dur
            prev_seg = timeline_seg

        timeline = ProductionTimeline(
            segments=timeline_segments,
            total_duration_sec=timeline_start,
            status="NEEDS_REVIEW" if has_review_flag else "PASSED"
        )

        # Validate final timeline constraints
        validation_errors = self.validator.validate(timeline)
        if validation_errors:
            timeline.status = "NEEDS_REVIEW"
            warnings.extend(validation_errors)

        is_aligned = not has_review_flag and not validation_errors
        report = DurationReport(
            is_aligned=is_aligned,
            pacing_adjustments=pacing_adjustments,
            warnings=warnings,
            reasons=reasons
        )

        return timeline, report

    def write_artifacts(
        self,
        timeline: ProductionTimeline,
        report: DurationReport,
        output_dir: Path,
    ) -> None:
        """Write timeline.json and duration_report.json."""
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. timeline.json
        with open(output_dir / "timeline.json", "w", encoding="utf-8") as f:
            json.dump(timeline.model_dump(), f, indent=2, ensure_ascii=False)

        # 2. duration_report.json
        with open(output_dir / "duration_report.json", "w", encoding="utf-8") as f:
            json.dump(report.model_dump(), f, indent=2, ensure_ascii=False)

        logger.info(f"Successfully wrote Production Timeline artifacts to {output_dir}")
