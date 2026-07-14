"""Unit tests for entity resolver, alias standardizer, and pronoun linkage algorithms."""

import json
import pytest
from pathlib import Path
from video_recap.application.entity import (
    AliasNormalizer,
    MentionLinker,
    EntityResolutionService,
    EntityMention,
    Entity,
)


def test_alias_normalizer_matching() -> None:
    """Verify name variations and abbreviation checks match compatible characters."""
    norm = AliasNormalizer()

    # Simple normalization
    assert norm.normalize("John S.") == "john s"

    # Variations
    assert norm.are_compatible("John Smith", "john s") is True
    assert norm.are_compatible("John", "John Doe") is True
    assert norm.are_compatible("John Doe", "Jane Doe") is False
    assert norm.are_compatible("Alice", "Bob") is False


def test_mention_linker_pronouns() -> None:
    """Verify pronouns he/she resolve to the correct entity based on temporal proximity and gender."""
    norm = AliasNormalizer()
    linker = MentionLinker(norm, time_window_sec=15.0)

    # Pre-existing entities
    entities = [
        Entity(entity_id="john_doe", canonical_name="John Doe", description="male character", confidence=1.0),
        Entity(entity_id="jane_doe", canonical_name="Jane Doe", description="female character", confidence=1.0),
    ]

    # Mention "he" at 10s. Recent mentions: john_doe at 5s.
    mention = EntityMention(
        mention_id="m1",
        provisional_name="he",
        timestamp=10.0,
        context_text="he walks in",
        mention_type="dialogue",
        chunk_id="chunk_01",
    )
    recent = [("john_doe", 5.0), ("jane_doe", 2.0)]

    ent_id, conf, reason = linker.link_mention(mention, entities, recent)
    assert ent_id == "john_doe"
    assert conf == pytest.approx(0.7)


def test_mention_linker_pronoun_ambiguity() -> None:
    """Verify ambiguous pronouns select the most recent candidate with lower confidence."""
    norm = AliasNormalizer()
    linker = MentionLinker(norm, time_window_sec=15.0)

    entities = [
        Entity(entity_id="john_doe", canonical_name="John Doe", description="male character", confidence=1.0),
        Entity(entity_id="bob_smith", canonical_name="Bob Smith", description="male character", confidence=1.0),
    ]

    # Mention "he" at 10s. Bob mentioned at 8s, John mentioned at 7s (both in window).
    mention = EntityMention(
        mention_id="m2",
        provisional_name="he",
        timestamp=10.0,
        context_text="he laughs",
        mention_type="dialogue",
        chunk_id="chunk_01",
    )
    recent = [("john_doe", 7.0), ("bob_smith", 8.0)]

    ent_id, conf, reason = linker.link_mention(mention, entities, recent)
    # Linked to most recent (Bob) with lower confidence (0.4)
    assert ent_id == "bob_smith"
    assert conf == pytest.approx(0.4)
    assert "Ambiguous" in reason


def test_entity_resolution_service_spawns_and_merges(tmp_path: Path) -> None:
    """Verify service spawns new entities, links mentions, tracks continuity, and writes files."""
    norm = AliasNormalizer()
    linker = MentionLinker(norm, time_window_sec=15.0)
    service = EntityResolutionService(norm, linker)

    mentions = [
        # Spawn John Smith in chunk 1
        EntityMention(
            mention_id="m1", provisional_name="John Smith", timestamp=1.0,
            context_text="John Smith enters", mention_type="subtitle", chunk_id="chunk_01"
        ),
        # Link John in chunk 1
        EntityMention(
            mention_id="m2", provisional_name="John", timestamp=10.0,
            context_text="John speaks", mention_type="dialogue", chunk_id="chunk_01"
        ),
        # Spawn anonymous character in chunk 2
        EntityMention(
            mention_id="m3", provisional_name="man in blue", timestamp=25.0,
            context_text="a man in blue arrives", mention_type="visual", chunk_id="chunk_02"
        ),
        # Link John S in chunk 2 (cross-chunk continuity check)
        EntityMention(
            mention_id="m4", provisional_name="John S", timestamp=40.0,
            context_text="John S waves", mention_type="ocr", chunk_id="chunk_02"
        ),
    ]

    entities, report = service.resolve_entities(mentions)

    # Expecting 2 entities: john_smith and character_001
    assert len(entities) == 2
    
    john = next(e for e in entities if e.entity_id == "john_smith")
    assert john.canonical_name == "John Smith"
    # provisional name John and John S are added to aliases
    assert "John" in john.aliases
    assert "John S" in john.aliases

    anon = next(e for e in entities if e.entity_id == "character_001")
    assert anon.canonical_name == "Anonymous Character 1"
    assert anon.description == "man in blue"

    # Check report statistics
    assert report.mentions_count["john_smith"] == 3
    assert report.mentions_count["character_001"] == 1
    assert report.chunk_presence["john_smith"] == ["chunk_01", "chunk_02"]
    assert report.chunk_presence["character_001"] == ["chunk_02"]

    # Write files check
    service.write_artifacts(entities, mentions, report, tmp_path)
    
    assert (tmp_path / "entities.json").exists()
    assert (tmp_path / "entity_mentions.json").exists()
    assert (tmp_path / "entity_resolution_report.json").exists()

    with open(tmp_path / "entities.json", "r", encoding="utf-8") as f:
        ents_loaded = json.load(f)
    assert len(ents_loaded) == 2
    assert ents_loaded[0]["entity_id"] == "john_smith"
