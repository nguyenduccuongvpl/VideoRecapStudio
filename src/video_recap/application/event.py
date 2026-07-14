"""Application services and models for event extraction, merging, relation building, and graph validation."""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field
from video_recap.domain.models import Observation

logger = logging.getLogger("EventGraph")


class Event(BaseModel):
    """A factual, parsed occurrence representing a coherent scene activity."""

    event_id: str = Field(..., description="Unique event identifier.")
    title: str = Field(..., description="Factual and neutral title.")
    start_time: float = Field(..., description="Start timestamp in seconds.")
    end_time: float = Field(..., description="End timestamp in seconds.")
    participants: List[str] = Field(default_factory=list, description="Resolved character IDs involved.")
    location: str = Field("unknown", description="Scene location.")
    factual_summary: str = Field(..., description="Un-embellished narrative detail.")
    observation_ids: List[str] = Field(..., description="List of source observation IDs.")
    evidence_refs: List[str] = Field(default_factory=list, description="Subtitle indices or transcript cues.")
    importance: float = Field(..., ge=0.0, le=1.0, description="Relative plot importance score.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in this extraction.")
    uncertainty: str = Field("none", description="Brief description of unknown aspects.")
    event_type: str = Field("action", description="Type (e.g. action, dialogue, travel, transition).")


class EventRelation(BaseModel):
    """A directed edge in the event graph connecting two events with semantic or temporal logic."""

    source_id: str = Field(..., description="Source Event ID.")
    target_id: str = Field(..., description="Target Event ID.")
    relation_type: str = Field(
        ...,
        description="Relation type: precedes, causes, enables, reveals, interrupts, resolves, parallel_to"
    )
    evidence: str = Field(..., description="Textual explanation supporting the connection.")


class EventGraph(BaseModel):
    """The complete directed story graph consisting of events and relation edges."""

    events: List[Event] = Field(default_factory=list)
    relations: List[EventRelation] = Field(default_factory=list)


class EventDeduplicator:
    """Combines similar events occurring in overlap regions or temporal proximity."""

    def merge_events(self, events: List[Event], time_tolerance: float = 5.0) -> List[Event]:
        """Merge events that occur at very close timestamps and share similar actions or participants."""
        if not events:
            return []

        sorted_events = sorted(events, key=lambda e: e.start_time)
        merged: List[Event] = []

        for current in sorted_events:
            if not merged:
                merged.append(current)
                continue

            # Look back to see if we can merge with the last added event
            last = merged[-1]
            time_gap = abs(current.start_time - last.end_time)
            
            # Condition for merging:
            # - High temporal proximity (time_gap within tolerance)
            # - Shared participants or high similarity in title/summary
            words_last = set(last.title.lower().split())
            words_current = set(current.title.lower().split())
            shared_words = words_last.intersection(words_current)

            has_shared_participants = bool(set(last.participants).intersection(set(current.participants)))
            is_similar = len(shared_words) >= 2 or (has_shared_participants and len(shared_words) >= 1)

            if time_gap <= time_tolerance and is_similar:
                # Perform Merge
                last.end_time = max(last.end_time, current.end_time)
                last.start_time = min(last.start_time, current.start_time)
                
                # Combine unique participants
                last.participants = sorted(list(set(last.participants + current.participants)))
                
                # Combine observations and evidence
                last.observation_ids = sorted(list(set(last.observation_ids + current.observation_ids)))
                last.evidence_refs = sorted(list(set(last.evidence_refs + current.evidence_refs)))
                
                # Take highest values for status attributes
                last.confidence = max(last.confidence, current.confidence)
                last.importance = max(last.importance, current.importance)
                
                # Concatenate summaries factually
                if last.factual_summary != current.factual_summary:
                    last.factual_summary = f"{last.factual_summary} Then, {current.factual_summary.lower()}"
                
                logger.info(f"Merged event '{current.event_id}' into '{last.event_id}' due to overlap/similarity.")
            else:
                merged.append(current)

        return merged


class EventRelationBuilder:
    """Analyzes events to establish causal, temporal, and logic relationships."""

    def build_relations(self, events: List[Event]) -> List[EventRelation]:
        """Automatically construct relation links among a sorted list of events."""
        relations: List[EventRelation] = []
        sorted_events = sorted(events, key=lambda e: e.start_time)

        for i in range(len(sorted_events)):
            evt_a = sorted_events[i]
            
            for j in range(i + 1, len(sorted_events)):
                evt_b = sorted_events[j]
                
                # 1. Parallel relationship check (overlap in duration)
                if evt_b.start_time < evt_a.end_time:
                    relations.append(
                        EventRelation(
                            source_id=evt_a.event_id,
                            target_id=evt_b.event_id,
                            relation_type="parallel_to",
                            evidence=f"Events overlap in time window ({evt_a.start_time}s - {evt_a.end_time}s vs {evt_b.start_time}s - {evt_b.end_time}s)"
                        )
                    )
                    continue

                # 2. Causal / Logical connection check
                # Check for causal trigger keywords in the target event's narrative summary
                summary_lower = evt_b.factual_summary.lower()
                causal_keywords = ["because", "due to", "resulting in", "consequently", "causes", "leads to", "triggered by"]
                
                has_causal_keyword = any(kw in summary_lower for kw in causal_keywords)
                shared_chars = set(evt_a.participants).intersection(set(evt_b.participants))

                if has_causal_keyword and shared_chars:
                    relations.append(
                        EventRelation(
                            source_id=evt_a.event_id,
                            target_id=evt_b.event_id,
                            relation_type="causes",
                            evidence=f"Causal transition phrase matched in summary with participant continuity {list(shared_chars)}"
                        )
                    )
                elif len(shared_chars) > 0 and (evt_b.start_time - evt_a.end_time) <= 30.0:
                    relations.append(
                        EventRelation(
                            source_id=evt_a.event_id,
                            target_id=evt_b.event_id,
                            relation_type="enables",
                            evidence=f"Enables subsequent action of {list(shared_chars)} within short timeframe"
                        )
                    )
                else:
                    # Default temporal predecessor relation
                    relations.append(
                        EventRelation(
                            source_id=evt_a.event_id,
                            target_id=evt_b.event_id,
                            relation_type="precedes",
                            evidence=f"Temporal ordering based on timestamp sequence"
                        )
                    )

        return relations


class EventGraphValidator:
    """Verifies graph integrity, checks for chronological consistency, and invalid causal loops."""

    def validate(self, graph: EventGraph) -> Tuple[bool, List[str]]:
        """Validate the event graph.

        Rules:
        - Every event must have at least one observation_id (evidence references).
        - No causal cycles (event A causes B, which causes A).
        - Chronology: preceding/causal source event must start at or before target event.
        """
        errors = []
        
        # Build lookup dict
        event_map = {e.event_id: e for e in graph.events}

        # 1. Check event evidence
        for evt in graph.events:
            if not evt.observation_ids:
                errors.append(f"Event {evt.event_id} has no source observation IDs (evidence missing).")

        # 2. Check Chronology and Reverse Causality
        for rel in graph.relations:
            src = event_map.get(rel.source_id)
            tgt = event_map.get(rel.target_id)
            
            if not src or not tgt:
                errors.append(f"Relation connects non-existent events: {rel.source_id} -> {rel.target_id}")
                continue

            if rel.relation_type in ["precedes", "causes", "enables"]:
                # Tolerance of 1.0s allowed for slightly overlapping actions
                if src.start_time > tgt.start_time + 1.0:
                    errors.append(
                        f"Chronology conflict: {rel.relation_type} relation has source starting after target "
                        f"({src.event_id} at {src.start_time}s vs {tgt.event_id} at {tgt.start_time}s)"
                    )

        # 3. Check for cycles in causal/enables relations (DAG checks)
        causal_adj: Dict[str, List[str]] = {e.event_id: [] for e in graph.events}
        for rel in graph.relations:
            if rel.relation_type in ["causes", "enables"]:
                causal_adj[rel.source_id].append(rel.target_id)

        # DFS path cycle detection
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def has_cycle(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            for neighbor in causal_adj.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.remove(node)
            return False

        for node in causal_adj:
            if node not in visited:
                if has_cycle(node):
                    errors.append("Invalid causal loop: Cyclic causal/enabling chain detected in graph.")
                    break

        return len(errors) == 0, errors


class EventExtractionService:
    """Orchestrates event extraction from observations, deduplication, relations, and exports reports."""

    def __init__(
        self,
        deduplicator: EventDeduplicator,
        relation_builder: EventRelationBuilder,
        validator: EventGraphValidator,
    ) -> None:
        self.deduplicator = deduplicator
        self.relation_builder = relation_builder
        self.validator = validator

    def extract_from_observations(self, observations: List[Observation]) -> EventGraph:
        """Create events based on observations, merge duplicates, build relationships, and validate."""
        events: List[Event] = []
        
        # 1. Transform raw observations into events
        for obs in observations:
            # Generate neutral title and ensure a factual summary is populated
            title = f"Activity at {obs.timestamp:.1f}s"
            # Split tags or descriptions to identify participants
            participants = []
            if "character_" in obs.description:
                # Simple extraction of character names/IDs mentioned in description
                words = obs.description.split()
                for w in words:
                    w_clean = w.strip(".,;:?!()\"'")
                    if "character_" in w_clean:
                        participants.append(w_clean)

            events.append(
                Event(
                    event_id=f"evt_{obs.id}",
                    title=title,
                    start_time=obs.timestamp,
                    end_time=obs.timestamp + 5.0,  # default event duration estimates
                    participants=sorted(list(set(participants))),
                    location="unknown",
                    factual_summary=obs.description,
                    observation_ids=[obs.id],
                    evidence_refs=[],
                    importance=0.5,
                    confidence=obs.confidence,
                )
            )

        # 2. Deduplicate close/overlapping events
        deduped_events = self.deduplicator.merge_events(events)

        # 3. Build relations
        relations = self.relation_builder.build_relations(deduped_events)

        graph = EventGraph(events=deduped_events, relations=relations)

        # 4. Validate
        is_valid, errors = self.validator.validate(graph)
        if not is_valid:
            logger.warning(f"Event graph validation warnings: {errors}")

        return graph

    def write_artifacts(self, graph: EventGraph, output_dir: Path) -> None:
        """Write events.json, event_graph.json, and event_graph_report.json."""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. events.json
        with open(output_dir / "events.json", "w", encoding="utf-8") as f:
            json.dump([e.model_dump() for e in graph.events], f, indent=2, ensure_ascii=False)

        # 2. event_graph.json
        with open(output_dir / "event_graph.json", "w", encoding="utf-8") as f:
            json.dump(graph.model_dump(), f, indent=2, ensure_ascii=False)

        # 3. event_graph_report.json (Validation results & summary)
        is_valid, errors = self.validator.validate(graph)
        report = {
            "is_valid": is_valid,
            "errors": errors,
            "events_count": len(graph.events),
            "relations_count": len(graph.relations),
            "timeline_summary": [
                {
                    "event_id": e.event_id,
                    "time": f"{e.start_time:.1f}s - {e.end_time:.1f}s",
                    "title": e.title,
                    "participants": e.participants,
                    "summary": e.factual_summary
                }
                for e in graph.events
            ]
        }
        with open(output_dir / "event_graph_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"Successfully wrote event graph artifacts to {output_dir}")
