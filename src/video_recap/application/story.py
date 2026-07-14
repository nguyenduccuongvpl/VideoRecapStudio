"""Application planning components for building story outlines, allocating importance budget, and mapping events to screenplay beats."""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field
from video_recap.application.event import Event, EventGraph, EventRelation

logger = logging.getLogger("StoryOutline")


class Beat(BaseModel):
    """A single storytelling beat mapping to screenplay structure."""

    beat_id: str = Field(..., description="Unique beat identifier.")
    beat_type: str = Field(
        ...,
        description="Beat type: hook, setup, inciting_event, development, escalation, turning_point, climax, resolution, outro"
    )
    event_ids: List[str] = Field(..., description="Associated Event IDs mapped to this beat.")
    title: str = Field(..., description="Beat title.")
    narrative_summary: str = Field(..., description="Summarized description of this plot segment.")
    duration_sec: float = Field(..., description="Allocated target duration in seconds.")


class StoryOutline(BaseModel):
    """The structured sequence of beats forming the overall video recap story outline."""

    beats: List[Beat] = Field(default_factory=list)
    target_duration_sec: float = Field(..., description="Target duration.")
    actual_duration_sec: float = Field(..., description="Actual summed duration of outline beats.")
    language: str = Field("vi", description="Target output language.")
    style: str = Field("neutral", description="Narrative style.")
    coverage_ratio: float = Field(0.0, description="Ratio of total event importance captured.")


class OmittedEventsReport(BaseModel):
    """Báo cáo các sự kiện bị lược bỏ do ngân sách thời gian."""

    omitted_event_ids: List[str] = Field(default_factory=list)
    reasons: Dict[str, str] = Field(default_factory=dict)


class ImportanceBudgeter:
    """Selects events based on importance and enforces causal ancestry coherence within duration limits."""

    def allocate_budget(
        self,
        events: List[Event],
        graph: EventGraph,
        target_duration: float,
    ) -> Tuple[List[Event], List[str], Dict[str, str]]:
        """Filter events to fit within the target duration while preserving causal ancestry.

        Returns:
            Tuple of (selected_events, omitted_event_ids, omission_reasons).
        """
        # Estimated event duration (e.g. 30 seconds per event as a budget weight)
        weight_per_event = 30.0
        max_events = max(1, int(target_duration // weight_per_event))

        # Sort by importance descending
        sorted_by_imp = sorted(events, key=lambda e: e.importance, reverse=True)
        selected_ids: Set[str] = set()

        # Build causal ancestors graph
        causal_ancestors: Dict[str, Set[str]] = {e.event_id: set() for e in events}
        for rel in graph.relations:
            if rel.relation_type in ["causes", "enables"]:
                causal_ancestors[rel.target_id].add(rel.source_id)

        def get_all_ancestors(evt_id: str, visited: Optional[Set[str]] = None) -> Set[str]:
            if visited is None:
                visited = set()
            anc = set()
            for p in causal_ancestors.get(evt_id, []):
                if p not in visited:
                    visited.add(p)
                    anc.add(p)
                    anc.update(get_all_ancestors(p, visited))
            return anc

        # Iterate and add events plus their causal ancestors
        for evt in sorted_by_imp:
            if len(selected_ids) >= max_events:
                break
            
            # Find what needs to be added (event + causal ancestors)
            needed = {evt.event_id}.union(get_all_ancestors(evt.event_id))
            if len(selected_ids) + len(needed.difference(selected_ids)) <= max_events:
                selected_ids.update(needed)
            else:
                # If adding all ancestors exceeds budget, skip this event for this iteration
                continue

        # If we selected nothing (because target_duration was too short or everything exceeded),
        # force include at least the single most important event
        if not selected_ids and events:
            selected_ids.add(sorted_by_imp[0].event_id)

        selected_events = sorted([e for e in events if e.event_id in selected_ids], key=lambda e: e.start_time)
        
        omitted = []
        reasons = {}
        for e in events:
            if e.event_id not in selected_ids:
                omitted.append(e.event_id)
                reasons[e.event_id] = "Omitted to fit within target duration budget constraints."

        return selected_events, omitted, reasons


class BeatSelectionPolicy:
    """Maps events to structured narrative beats according to chronology and drama profile."""

    def select_beats(self, events: List[Event], target_duration: float) -> List[Beat]:
        """Convert a sequence of chronologically sorted events into screenplay beats."""
        if not events:
            return []

        beats: List[Beat] = []
        n = len(events)
        duration_per_beat = target_duration / max(1, min(n, 7))

        # 1. Hook beat (Must be a real event!)
        hook_evt = events[0]
        beats.append(
            Beat(
                beat_id="beat_hook",
                beat_type="hook",
                event_ids=[hook_evt.event_id],
                title="Mở đầu",
                narrative_summary=hook_evt.factual_summary,
                duration_sec=duration_per_beat
            )
        )

        if n > 1:
            # 2. Climax event (Highest importance event in the second half)
            second_half = events[max(1, n // 2):]
            climax_evt = max(second_half, key=lambda e: e.importance)

            # Partition other events chronologically relative to climax
            events_before = [e for e in events if e.start_time < climax_evt.start_time]
            events_after = [e for e in events if e.start_time > climax_evt.start_time]

            # Exclude hook_evt from before-list to build setup & development
            before_ex_hook = [e for e in events_before if e.event_id != hook_evt.event_id]

            if before_ex_hook:
                split_idx = len(before_ex_hook) // 2
                setup_evts = before_ex_hook[:split_idx]
                dev_evts = before_ex_hook[split_idx:]

                if setup_evts:
                    beats.append(
                        Beat(
                            beat_id="beat_setup",
                            beat_type="setup",
                            event_ids=[e.event_id for e in setup_evts],
                            title="Bối cảnh",
                            narrative_summary=" ".join(e.factual_summary for e in setup_evts),
                            duration_sec=duration_per_beat
                        )
                    )
                if dev_evts:
                    beats.append(
                        Beat(
                            beat_id="beat_development",
                            beat_type="development",
                            event_ids=[e.event_id for e in dev_evts],
                            title="Diễn biến",
                            narrative_summary=" ".join(e.factual_summary for e in dev_evts),
                            duration_sec=duration_per_beat * 1.5
                        )
                    )

            # Add Climax
            beats.append(
                Beat(
                    beat_id="beat_climax",
                    beat_type="climax",
                    event_ids=[climax_evt.event_id],
                    title="Cao trào",
                    narrative_summary=climax_evt.factual_summary,
                    duration_sec=duration_per_beat * 1.5
                )
            )

            # Add Resolution (aftermath)
            if events_after:
                beats.append(
                    Beat(
                        beat_id="beat_resolution",
                        beat_type="resolution",
                        event_ids=[e.event_id for e in events_after],
                        title="Kết thúc",
                        narrative_summary=" ".join(e.factual_summary for e in events_after),
                        duration_sec=duration_per_beat
                    )
                )

        # Cleanup empty beat mappings
        beats = [b for b in beats if len(b.event_ids) > 0]
        return beats


class StoryPlanningService:
    """Orchestrates story outline planning, coverage scoring, and writing reports."""

    def __init__(self, budgeter: ImportanceBudgeter, policy: BeatSelectionPolicy) -> None:
        self.budgeter = budgeter
        self.policy = policy

    def plan_story(
        self,
        events: List[Event],
        graph: EventGraph,
        target_duration_sec: float,
        language: str = "vi",
        style: str = "neutral",
    ) -> Tuple[StoryOutline, OmittedEventsReport]:
        """Select events and build narrative beats into a StoryOutline."""
        if not events:
            return StoryOutline(target_duration_sec=target_duration_sec), OmittedEventsReport()

        # 1. Budget events
        selected, omitted, reasons = self.budgeter.allocate_budget(events, graph, target_duration_sec)

        # 2. Arrange into beats
        beats = self.policy.select_beats(selected, target_duration_sec)

        # 3. Calculate coverage metrics
        total_importance = sum(e.importance for e in events)
        captured_importance = sum(e.importance for e in selected)
        coverage_ratio = captured_importance / total_importance if total_importance > 0 else 0.0

        actual_duration = sum(b.duration_sec for b in beats)

        outline = StoryOutline(
            beats=beats,
            target_duration_sec=target_duration_sec,
            actual_duration_sec=actual_duration,
            language=language,
            style=style,
            coverage_ratio=coverage_ratio,
        )

        report = OmittedEventsReport(
            omitted_event_ids=omitted,
            reasons=reasons,
        )

        return outline, report

    def write_artifacts(
        self,
        outline: StoryOutline,
        report: OmittedEventsReport,
        output_dir: Path,
    ) -> None:
        """Write story_outline.json, omitted_events_report.json, and coverage metrics."""
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. story_outline.json
        with open(output_dir / "story_outline.json", "w", encoding="utf-8") as f:
            json.dump(outline.model_dump(), f, indent=2, ensure_ascii=False)

        # 2. omitted_events_report.json
        with open(output_dir / "omitted_events_report.json", "w", encoding="utf-8") as f:
            json.dump(report.model_dump(), f, indent=2, ensure_ascii=False)

        # 3. story_coverage_metrics.json
        metrics = {
            "target_duration_sec": outline.target_duration_sec,
            "actual_duration_sec": outline.actual_duration_sec,
            "coverage_ratio": outline.coverage_ratio,
            "total_beats": len(outline.beats),
            "omitted_count": len(report.omitted_event_ids),
        }
        with open(output_dir / "story_coverage_metrics.json", "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False)

        logger.info(f"Successfully wrote Story Outline artifacts to {output_dir}")
