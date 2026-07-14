"""Application components for resolving character mentions, nicknames, and visual descriptions into global entities."""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

logger = logging.getLogger("EntityResolution")


class Entity(BaseModel):
    """A stable, globally recognized entity/character in the film."""

    entity_id: str = Field(..., description="Stable unique identifier (e.g. character_001, john_doe).")
    canonical_name: str = Field(..., description="Best known name for the entity.")
    aliases: List[str] = Field(default_factory=list, description="Alternative names or abbreviations.")
    description: Optional[str] = Field(None, description="Physical description or character role.")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in this entity's resolution.")


class EntityMention(BaseModel):
    """An individual occurrence of a character mention in the timeline."""

    mention_id: str = Field(..., description="Unique ID for the mention.")
    provisional_name: str = Field(..., description="The name or description as observed (e.g. 'John', 'he', 'man in red').")
    timestamp: float = Field(..., description="Timestamp in seconds.")
    context_text: str = Field(..., description="Surrounding text or action context.")
    mention_type: str = Field(..., description="Modality source: 'subtitle', 'dialogue', 'visual', or 'ocr'.")
    chunk_id: str = Field(..., description="Chunk ID where the mention occurred.")
    inferred_gender: Optional[str] = Field(None, description="'male', 'female', or 'unknown'.")


class CharacterContinuityReport(BaseModel):
    """Continuity tracking across chunks for all resolved characters."""

    reconciled_entities: List[Entity] = Field(default_factory=list)
    mentions_count: Dict[str, int] = Field(default_factory=dict, description="Entity ID to count of mentions.")
    chunk_presence: Dict[str, List[str]] = Field(default_factory=dict, description="Entity ID to list of chunk IDs.")
    linkage_notes: List[str] = Field(default_factory=list, description="Audit log of decisions and linkages.")


class AliasNormalizer:
    """Standardizes names, variations, and handles contraction matching."""

    def normalize(self, name: str) -> str:
        """Strip spaces, lowercase, and clean minor punctuations."""
        return " ".join(name.lower().replace(".", "").replace(",", "").split())

    def are_compatible(self, name1: str, name2: str) -> bool:
        """Verify if two names represent compatible aliases without direct conflicts."""
        norm1 = self.normalize(name1)
        norm2 = self.normalize(name2)
        
        if not norm1 or not norm2:
            return False

        # Exact match
        if norm1 == norm2:
            return True

        # Initial/Abbreviation check: e.g. "john smith" vs "john s"
        parts1 = norm1.split()
        parts2 = norm2.split()
        
        # If one is a single name and the other is multi-name: e.g. "john" vs "john smith"
        if len(parts1) == 1 and len(parts2) > 1:
            return parts1[0] == parts2[0]
        if len(parts2) == 1 and len(parts1) > 1:
            return parts2[0] == parts1[0]

        # First name matches and last name starts with initial: e.g., "john smith" vs "john s"
        if len(parts1) > 1 and len(parts2) > 1:
            if parts1[0] == parts2[0]:
                last1, last2 = parts1[-1], parts2[-1]
                if last1.startswith(last2) or last2.startswith(last1):
                    return True

        return False


class MentionLinker:
    """Links individual mentions to globally tracked entities using timeline context and pronoun heuristics."""

    def __init__(self, normalizer: AliasNormalizer, time_window_sec: float = 15.0) -> None:
        self.normalizer = normalizer
        self.time_window_sec = time_window_sec

    def link_mention(
        self,
        mention: EntityMention,
        existing_entities: List[Entity],
        recent_mentions: List[Tuple[str, float]],  # List of (entity_id, timestamp)
    ) -> Tuple[Optional[str], float, str]:
        """Link mention to an existing entity or determine if it is a new entity.

        Returns:
            Tuple of (linked_entity_id, confidence, reason_string).
        """
        prov_norm = self.normalizer.normalize(mention.provisional_name)

        # 1. Exact or Alias match
        for ent in existing_entities:
            # Check canonical name compatibility
            if self.normalizer.are_compatible(mention.provisional_name, ent.canonical_name):
                return ent.entity_id, 1.0, f"Alias match with canonical name: {ent.canonical_name}"
            # Check all aliases
            for alias in ent.aliases:
                if self.normalizer.are_compatible(mention.provisional_name, alias):
                    return ent.entity_id, 0.95, f"Alias match with registered alias: {alias}"

        # 2. Pronoun resolution ("he", "she", "they", "it")
        if prov_norm in ["he", "him", "his", "she", "her", "hers"]:
            target_gender = "male" if prov_norm in ["he", "him", "his"] else "female"
            
            # Find eligible entities mentioned recently in the time window
            eligible_entities = []
            for ent_id, ts in sorted(recent_mentions, key=lambda x: x[1], reverse=True):
                if abs(mention.timestamp - ts) <= self.time_window_sec:
                    # Find corresponding Entity model
                    ent = next((e for e in existing_entities if e.entity_id == ent_id), None)
                    if ent:
                        # Infer entity gender from description or ID
                        desc_lower = (ent.description or "").lower()
                        if "female" in desc_lower:
                            ent_gender = "female"
                        elif "male" in desc_lower:
                            ent_gender = "male"
                        else:
                            ent_gender = "unknown"

                        if ent_gender == target_gender:
                            eligible_entities.append(ent)

            if len(eligible_entities) == 1:
                return eligible_entities[0].entity_id, 0.7, f"Resolved pronoun '{mention.provisional_name}' to {eligible_entities[0].canonical_name}"
            elif len(eligible_entities) > 1:
                # Ambiguity: multiple candidates in window
                return eligible_entities[0].entity_id, 0.4, f"Ambiguous pronoun resolution. Linked to most recent: {eligible_entities[0].canonical_name}"

        # 3. Visual description (e.g. "man in red shirt")
        # Do not merge based solely on shirts/generic descriptions unless there's direct evidence
        if mention.mention_type == "visual" and len(prov_norm.split()) > 1:
            for ent in existing_entities:
                if ent.description and self.normalizer.normalize(mention.provisional_name) in self.normalizer.normalize(ent.description):
                    return ent.entity_id, 0.8, f"Visual description matched entity profile description"

        return None, 0.0, "No compatible entity found"


class EntityResolutionService:
    """Manages the full lifecycle of entity discovery, mention linking, and continuity reporting."""

    def __init__(self, normalizer: AliasNormalizer, linker: MentionLinker) -> None:
        self.normalizer = normalizer
        self.linker = linker

    def resolve_entities(self, mentions: List[EntityMention]) -> Tuple[List[Entity], CharacterContinuityReport]:
        """Resolve a collection of mentions into stable entities and build a continuity report."""
        sorted_mentions = sorted(mentions, key=lambda m: m.timestamp)
        
        reconciled_entities: List[Entity] = []
        recent_mentions: List[Tuple[str, float]] = []  # Track (entity_id, timestamp)
        
        # Track statistics
        mentions_count: Dict[str, int] = {}
        chunk_presence: Dict[str, Set[str]] = {}
        linkage_notes: List[str] = []
        anon_counter = 1

        for mention in sorted_mentions:
            # Skip empty mentions
            if not mention.provisional_name.strip():
                continue

            linked_id, confidence, reason = self.linker.link_mention(
                mention,
                reconciled_entities,
                recent_mentions,
            )

            if linked_id:
                # Update existing entity
                ent = next(e for e in reconciled_entities if e.entity_id == linked_id)
                # If provisional name is more detailed, add to aliases
                if mention.provisional_name not in ent.aliases and mention.provisional_name != ent.canonical_name:
                    if mention.mention_type in ["subtitle", "dialogue", "ocr"]:
                        # Standardize name variation
                        ent.aliases.append(mention.provisional_name)
                
                # Boost confidence slightly with more observations
                ent.confidence = min(1.0, max(ent.confidence, confidence))
                
                linkage_notes.append(
                    f"[{mention.timestamp:.2f}s] Linked mention '{mention.provisional_name}' "
                    f"to global entity '{ent.canonical_name}' (ID: {ent.entity_id}) | Confidence: {confidence:.2f} | Reason: {reason}"
                )
            else:
                # Create a new entity
                # Check if the provisional name is a pronoun or generic visual description (create anonymous ID)
                is_generic = self.normalizer.normalize(mention.provisional_name) in [
                    "he", "him", "his", "she", "her", "hers", "they", "them", "it", "man", "woman", "person"
                ] or mention.mention_type == "visual"

                if is_generic:
                    entity_id = f"character_{anon_counter:03d}"
                    canonical_name = f"Anonymous Character {anon_counter}"
                    anon_counter += 1
                    description = mention.provisional_name if mention.mention_type == "visual" else None
                else:
                    entity_id = self.normalizer.normalize(mention.provisional_name).replace(" ", "_")
                    canonical_name = mention.provisional_name
                    description = None

                # Infer gender
                inferred_gender = mention.inferred_gender or "unknown"
                if mention.provisional_name.lower() in ["he", "him", "his"]:
                    inferred_gender = "male"
                elif mention.provisional_name.lower() in ["she", "her", "hers"]:
                    inferred_gender = "female"
                
                if inferred_gender != "unknown":
                    description = f"{inferred_gender} character" if not description else f"{inferred_gender} - {description}"

                ent = Entity(
                    entity_id=entity_id,
                    canonical_name=canonical_name,
                    aliases=[mention.provisional_name] if not is_generic else [],
                    description=description,
                    confidence=0.9 if not is_generic else 0.5,
                )
                reconciled_entities.append(ent)
                linked_id = entity_id

                linkage_notes.append(
                    f"[{mention.timestamp:.2f}s] Spawned new global entity '{ent.canonical_name}' "
                    f"(ID: {ent.entity_id}) from mention '{mention.provisional_name}'"
                )

            # Record stats
            mentions_count[linked_id] = mentions_count.get(linked_id, 0) + 1
            chunk_presence.setdefault(linked_id, set()).add(mention.chunk_id)
            
            # Keep trace of recent mentions
            recent_mentions.append((linked_id, mention.timestamp))

        # Convert set to sorted list for pydantic serialization
        serializable_chunk_presence = {k: sorted(list(v)) for k, v in chunk_presence.items()}

        report = CharacterContinuityReport(
            reconciled_entities=reconciled_entities,
            mentions_count=mentions_count,
            chunk_presence=serializable_chunk_presence,
            linkage_notes=linkage_notes,
        )

        return reconciled_entities, report

    def write_artifacts(
        self,
        entities: List[Entity],
        mentions: List[EntityMention],
        report: CharacterContinuityReport,
        output_dir: Path,
    ) -> None:
        """Write resolution outputs: entities.json, entity_mentions.json, and entity_resolution_report.json."""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. entities.json
        with open(output_dir / "entities.json", "w", encoding="utf-8") as f:
            json.dump([e.model_dump() for e in entities], f, indent=2, ensure_ascii=False)

        # 2. entity_mentions.json
        with open(output_dir / "entity_mentions.json", "w", encoding="utf-8") as f:
            json.dump([m.model_dump() for m in mentions], f, indent=2, ensure_ascii=False)

        # 3. entity_resolution_report.json
        with open(output_dir / "entity_resolution_report.json", "w", encoding="utf-8") as f:
            json.dump(report.model_dump(), f, indent=2, ensure_ascii=False)
        
        logger.info(f"Successfully wrote entity resolution artifacts to {output_dir}")
