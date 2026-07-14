"""Application components for critic analysis, automated repair of narration text, and validation reporting."""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field
from video_recap.application.event import Event, EventGraph
from video_recap.application.narration import NarrationDraft, NarrationSegment

logger = logging.getLogger("CriticPipeline")


class CriticFinding(BaseModel):
    """An individual warning or critical error identified in the narration script."""

    code: str = Field(..., description="Classification code (e.g. UNSUPPORTED_CLAIM, WRONG_CHARACTER).")
    severity: str = Field(..., description="Severity level: 'critical' or 'warning'.")
    segment_id: str = Field(..., description="ID of the segment where the issue was found.")
    claim: Optional[str] = Field(None, description="The specific ungrounded claim or text portion.")
    evidence: Optional[str] = Field(None, description="Associated source event summary or details.")
    explanation: str = Field(..., description="Explanation of why this issue was raised.")
    suggested_action: str = Field(..., description="How to repair the issue.")
    auto_fixable: bool = Field(False, description="True if the pipeline can automatically fix this.")


class CriticReport(BaseModel):
    """Overall validation report produced by the CriticPipeline."""

    status: str = Field(..., description="Outcome status: 'PASSED' or 'NEEDS_REVIEW'.")
    findings: List[CriticFinding] = Field(default_factory=list)
    iterations_run: int = Field(1, description="Number of auto-repair cycles run.")


class GroundingCritic:
    """Verifies that all claims are grounded in source observations (no external knowledge)."""

    def check(self, segment: NarrationSegment, associated_events: List[Event]) -> List[CriticFinding]:
        findings = []
        event_summaries = " ".join(e.factual_summary.lower() for e in associated_events)

        for claim in segment.claims:
            claim_words = [w.strip(".,;:?!") for w in claim.lower().split() if len(w) > 4]
            if claim_words:
                matched = sum(1 for w in claim_words if w in event_summaries)
                ratio = matched / len(claim_words)
                if ratio < 0.5:
                    findings.append(
                        CriticFinding(
                            code="UNSUPPORTED_CLAIM",
                            severity="critical",
                            segment_id=segment.id,
                            claim=claim,
                            evidence=event_summaries,
                            explanation=f"Claim '{claim}' is not supported by event summaries.",
                            suggested_action="Remove or rewrite the ungrounded claim.",
                            auto_fixable=True
                        )
                    )
        return findings


class ContinuityCritic:
    """Checks chronology, causal, and information-revealing sequence logic."""

    def check(self, segments: List[NarrationSegment], events: List[Event], graph: EventGraph) -> List[CriticFinding]:
        findings = []
        # Build event order map from narration sequence
        evt_order = {}
        for idx, seg in enumerate(segments):
            for eid in seg.event_ids:
                if eid not in evt_order:
                    evt_order[eid] = idx

        # Check causal relations sequence
        for rel in graph.relations:
            if rel.relation_type in ["causes", "enables"]:
                src_order = evt_order.get(rel.source_id)
                tgt_order = evt_order.get(rel.target_id)
                
                # If target is narrated BEFORE source -> Causal chronology violation!
                if src_order is not None and tgt_order is not None and tgt_order < src_order:
                    findings.append(
                        CriticFinding(
                            code="CHRONOLOGY_VIOLATION",
                            severity="critical",
                            segment_id=segments[tgt_order].id,
                            claim=f"Event {rel.target_id} narrated before its cause {rel.source_id}",
                            explanation="Target event is presented before the cause/enabler event.",
                            suggested_action="Reorder beats to present the cause first.",
                            auto_fixable=False
                        )
                    )
        return findings


class EntityConsistencyCritic:
    """Validates character names and detects misidentifications or naming conflicts."""

    def check(self, segment: NarrationSegment, associated_events: List[Event]) -> List[CriticFinding]:
        findings = []
        # Union of all participants resolved in associated events
        valid_participants = set()
        for evt in associated_events:
            valid_participants.update(evt.participants)

        # Simple check: if narration mentions a name not in valid participants
        # To make it testable, if the text mentions character IDs, check if they are in valid_participants
        text_words = [w.strip(".,;:?!") for w in segment.text.split()]
        for w in text_words:
            if "nhân_vật_" in w or "character_" in w:
                char_id = w.replace("nhân_vật_", "character_")
                if char_id not in valid_participants:
                    findings.append(
                        CriticFinding(
                            code="WRONG_CHARACTER",
                            severity="critical",
                            segment_id=segment.id,
                            claim=char_id,
                            explanation=f"Character '{char_id}' mentioned in text but not present in events.",
                            suggested_action=f"Replace '{char_id}' with a correct participant: {list(valid_participants)}",
                            auto_fixable=True
                        )
                    )
        return findings


class StyleCritic:
    """Checks for sensationalist tone, repetitive filler words, and creator imitation."""

    def check(self, segment: NarrationSegment) -> List[CriticFinding]:
        findings = []
        clichés = ["không ngờ rằng", "chưa dừng lại ở đó", "hóa ra", "ai mà tin được"]
        text_lower = segment.text.lower()
        
        for cliché in clichés:
            if cliché in text_lower:
                findings.append(
                    CriticFinding(
                        code="CLICHE_DETECTED",
                        severity="warning",
                        segment_id=segment.id,
                        claim=cliché,
                        explanation=f"Text contains banned sensationalist phrase: '{cliché}'",
                        suggested_action="Remove cliché filler phrase.",
                        auto_fixable=True
                    )
                )
        return findings


class RepetitionCritic:
    """Finds repeated n-grams or consecutive words."""

    def check(self, segment: NarrationSegment) -> List[CriticFinding]:
        findings = []
        words = segment.text.split()
        
        # Check for consecutive duplicate words
        for i in range(len(words) - 1):
            if words[i].lower() == words[i+1].lower() and len(words[i]) >= 2:
                findings.append(
                    CriticFinding(
                        code="REPETITION_DETECTED",
                        severity="warning",
                        segment_id=segment.id,
                        claim=words[i],
                        explanation=f"Duplicate consecutive word detected: '{words[i]}'",
                        suggested_action="Remove duplicate word.",
                        auto_fixable=True
                    )
                )
                break
        return findings


class DurationBudgetCritic:
    """Ensures estimated narration speech time fits within segment limits."""

    def check(self, segment: NarrationSegment) -> List[CriticFinding]:
        findings = []
        # Allow 1000ms overflow tolerance
        if segment.estimated_spoken_duration_ms > segment.target_duration_ms + 1000:
            findings.append(
                CriticFinding(
                    code="DURATION_OVERFLOW",
                    severity="critical",
                    segment_id=segment.id,
                    claim=segment.text,
                    explanation=f"Spoken duration ({segment.estimated_spoken_duration_ms}ms) exceeds budget ({segment.target_duration_ms}ms).",
                    suggested_action="Shorten script segment text.",
                    auto_fixable=True
                )
            )
        return findings


class CriticPipeline:
    """Orchestrates validation checking, automated bounded repairs, and re-validating."""

    def __init__(
        self,
        grounding_critic: GroundingCritic,
        continuity_critic: ContinuityCritic,
        entity_critic: EntityConsistencyCritic,
        style_critic: StyleCritic,
        repetition_critic: RepetitionCritic,
        duration_critic: DurationBudgetCritic,
        max_repair_attempts: int = 3,
    ) -> None:
        self.grounding_critic = grounding_critic
        self.continuity_critic = continuity_critic
        self.entity_critic = entity_critic
        self.style_critic = style_critic
        self.repetition_critic = repetition_critic
        self.duration_critic = duration_critic
        self.max_repair_attempts = max_repair_attempts

    def run_validation(
        self,
        draft: NarrationDraft,
        events: List[Event],
        graph: EventGraph,
    ) -> Tuple[NarrationDraft, CriticReport]:
        """Run critics check and auto-repair iterations up to max_repair_attempts."""
        repaired_draft = draft.model_copy(deep=True)
        event_map = {e.event_id: e for e in events}
        
        iteration = 0
        findings = []

        while iteration < self.max_repair_attempts:
            iteration += 1
            findings = []

            # 1. Run all segment-level critics
            for seg in repaired_draft.segments:
                associated = [event_map[eid] for eid in seg.event_ids if eid in event_map]
                findings.extend(self.grounding_critic.check(seg, associated))
                findings.extend(self.entity_critic.check(seg, associated))
                findings.extend(self.style_critic.check(seg))
                findings.extend(self.repetition_critic.check(seg))
                findings.extend(self.duration_critic.check(seg))

            # 2. Run draft-level critics
            findings.extend(self.continuity_critic.check(repaired_draft.segments, events, graph))

            # Check if there are any fixable findings
            fixable_findings = [f for f in findings if f.auto_fixable]
            if not fixable_findings:
                break  # nothing left to auto-repair, exit early

            # 3. Apply repairs
            self._apply_repairs(repaired_draft, fixable_findings, event_map)

        # Final validation status
        has_critical = any(f.severity == "critical" for f in findings)
        status = "NEEDS_REVIEW" if has_critical else "PASSED"
        
        report = CriticReport(
            status=status,
            findings=findings,
            iterations_run=iteration,
        )

        return repaired_draft, report

    def _apply_repairs(
        self,
        draft: NarrationDraft,
        findings: List[CriticFinding],
        event_map: Dict[str, Event],
    ) -> None:
        """Apply text adjustments to fix auto_fixable findings."""
        for finding in findings:
            seg = next((s for s in draft.segments if s.id == finding.segment_id), None)
            if not seg:
                continue

            if finding.code == "CLICHE_DETECTED":
                # Remove cliché phrase
                phrase = finding.claim or ""
                seg.text = seg.text.replace(phrase, "")
                # Clean up spaces
                seg.text = " ".join(seg.text.split())
                logger.info(f"Auto-repaired cliché '{phrase}' in segment {seg.id}")

            elif finding.code == "WRONG_CHARACTER":
                # Replace wrong character with first valid participant name
                wrong_char = finding.claim or ""
                associated = [event_map[eid] for eid in seg.event_ids if eid in event_map]
                valid_chars = []
                for e in associated:
                    valid_chars.extend(e.participants)
                
                correct_char = valid_chars[0] if valid_chars else "nhân_vật_001"
                seg.text = seg.text.replace(wrong_char, correct_char)
                logger.info(f"Auto-repaired wrong character '{wrong_char}' to '{correct_char}' in segment {seg.id}")

            elif finding.code == "REPETITION_DETECTED":
                # Remove duplicate consecutive words
                words = seg.text.split()
                repaired_words = []
                for w in words:
                    if not repaired_words or w.lower() != repaired_words[-1].lower():
                        repaired_words.append(w)
                seg.text = " ".join(repaired_words)
                logger.info(f"Auto-repaired repetition in segment {seg.id}")

            elif finding.code == "DURATION_OVERFLOW":
                # Shorten segment text (truncate to half of words)
                words = seg.text.split()
                if len(words) > 3:
                    seg.text = " ".join(words[:len(words) // 2]) + "."
                seg.estimated_spoken_duration_ms = int(seg.estimated_spoken_duration_ms * 0.5)
                logger.info(f"Auto-repaired duration overflow by truncating segment {seg.id}")

            elif finding.code == "UNSUPPORTED_CLAIM":
                # Remove claim from text if it matches sentences
                unsupported_claim = finding.claim or ""
                seg.text = seg.text.replace(unsupported_claim, "")
                seg.text = " ".join(seg.text.split())
                # Truncate empty punctuation
                if seg.text.endswith(","):
                    seg.text = seg.text[:-1] + "."
                # Clean claims list
                seg.claims = [c for c in seg.claims if c != unsupported_claim]
                logger.info(f"Auto-repaired unsupported claim in segment {seg.id}")

    def write_artifacts(
        self,
        draft: NarrationDraft,
        report: CriticReport,
        output_dir: Path,
    ) -> None:
        """Write critic_report.json and narration_final.json."""
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. critic_report.json
        with open(output_dir / "critic_report.json", "w", encoding="utf-8") as f:
            json.dump(report.model_dump(), f, indent=2, ensure_ascii=False)

        # 2. narration_final.json
        with open(output_dir / "narration_final.json", "w", encoding="utf-8") as f:
            json.dump(draft.model_dump(), f, indent=2, ensure_ascii=False)

        logger.info(f"Successfully wrote Critic Pipeline artifacts to {output_dir}")
