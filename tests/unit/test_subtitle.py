"""Unit tests for subtitle discovery, parsing (SRT, VTT, ASS), formatting cleanup, overlap correction, and selection ranking."""

import pytest
from pathlib import Path
from video_recap.application.subtitle import SubtitleCandidate
from video_recap.domain.models import MediaInfo, MediaStreamInfo, StageName, TimeRange, TranscriptCue
from video_recap.infrastructure.media.subtitle import (
    SubtitleDiscoveryServiceImpl,
    SubtitleSelectionPolicyImpl,
    SubtitleParserImpl,
    SubtitleNormalizerImpl,
)


@pytest.fixture
def dummy_srt(tmp_path: Path) -> Path:
    f = tmp_path / "video.srt"
    content = (
        "1\n"
        "00:00:01,000 --> 00:00:04,500\n"
        "Hello <b>World</b>!\n\n"
        "2\n"
        "00:00:04,200 --> 00:00:07,000\n"
        "<i>This is a subtitle.</i>\n"
    )
    f.write_text(content, encoding="utf-8")
    return f


@pytest.fixture
def dummy_vtt(tmp_path: Path) -> Path:
    f = tmp_path / "video.vtt"
    content = (
        "WEBVTT\n\n"
        "NOTE This is a comment\n\n"
        "00:01.000 --> 00:04.500\n"
        "First cue text\n\n"
        "00:00:04.200 --> 00:00:07.000\n"
        "Second cue text\n"
    )
    f.write_text(content, encoding="utf-8")
    return f


@pytest.fixture
def dummy_ass(tmp_path: Path) -> Path:
    f = tmp_path / "video.ass"
    content = (
        "[Script Info]\n"
        "Title: Default ASS file\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.20,0:00:03.50,Default,,0,0,0,,{\\pos(400,570)}Hello ASS subtitle!\n"
        "Dialogue: 0,0:00:03.00,0:00:05.10,Default,,0,0,0,,Second ASS cue\n"
    )
    f.write_text(content, encoding="utf-8")
    return f


def test_subtitle_discovery(tmp_path: Path) -> None:
    """Verify scanning matches sidecars (same basename) and registers embedded streams."""
    video_path = tmp_path / "movie.mp4"
    video_path.write_text("dummy")

    # Write matching sidecar files
    (tmp_path / "movie.srt").write_text("srt")
    (tmp_path / "movie.en.vtt").write_text("vtt")
    (tmp_path / "other.srt").write_text("other srt")  # non-matching name

    media_info = MediaInfo(
        schema_version="1.0.0",
        producer_stage=StageName.INGESTING,
        input_hashes={},
        format_name="mp4",
        duration=10.0,
        size_bytes=100,
        resolution="1920x1080",
        fps=30.0,
        streams=[
            MediaStreamInfo(index=0, codec="h264", stream_type="video"),
            MediaStreamInfo(index=1, codec="srt", stream_type="subtitle", language="vi", disposition={"default": 1}),
        ],
    )

    discovery = SubtitleDiscoveryServiceImpl()
    candidates = discovery.discover_subtitles(video_path, media_info, user_selected_path=str(tmp_path / "other.srt"))

    # Should discover:
    # 1. user_selected (other.srt)
    # 2. sidecar (movie.srt)
    # 3. sidecar (movie.en.vtt)
    # 4. embedded (stream index 1)
    assert len(candidates) == 4
    
    types = [c.source_type for c in candidates]
    assert "user_selected" in types
    assert "sidecar" in types
    assert "embedded" in types

    embedded_candidates = [c for c in candidates if c.source_type == "embedded"]
    assert len(embedded_candidates) == 1
    assert embedded_candidates[0].language == "vi"
    assert embedded_candidates[0].is_default is True


def test_subtitle_selection_policy() -> None:
    """Verify selection policy ranks candidates correctly."""
    policy = SubtitleSelectionPolicyImpl()

    candidates = [
        SubtitleCandidate(source_type="embedded", stream_index=1, language="vi"),
        SubtitleCandidate(source_type="embedded", stream_index=2, language="en", is_default=True),
        SubtitleCandidate(source_type="sidecar", path="video.srt"),
        SubtitleCandidate(source_type="user_selected", path="user.srt"),
    ]

    # 1. User selected has highest priority
    best = policy.select_best(candidates)
    assert best.source_type == "user_selected"

    # 2. Sidecar has priority if user selected is missing
    candidates_no_user = candidates[0:3]
    best_no_user = policy.select_best(candidates_no_user)
    assert best_no_user.source_type == "sidecar"

    # 3. Embedded default preferred over other embedded
    candidates_only_embedded = candidates[0:2]
    best_embedded = policy.select_best(candidates_only_embedded)
    assert best_embedded.stream_index == 2  # default stream

    # 4. Preferred language matches
    best_lang = policy.select_best(candidates_only_embedded, preferred_language="vi")
    assert best_lang.stream_index == 1  # VI matches preferred


def test_srt_parser_success(dummy_srt: Path) -> None:
    """Verify SRT parser correctly converts timecodes and extracts clean text."""
    parser = SubtitleParserImpl()
    cues = parser.parse(dummy_srt)

    assert len(cues) == 2
    assert cues[0].text == "Hello <b>World</b>!"
    assert cues[0].time_range.start == 1.0
    assert cues[0].time_range.end == 4.5
    assert cues[1].time_range.start == 4.2
    assert cues[1].time_range.end == 7.0


def test_vtt_parser_success(dummy_vtt: Path) -> None:
    """Verify VTT parser reads notes, timecodes missing hour, and dots."""
    parser = SubtitleParserImpl()
    cues = parser.parse(dummy_vtt)

    assert len(cues) == 2
    assert cues[0].text == "First cue text"
    assert cues[0].time_range.start == 1.0  # 00:01.000 = 1s
    assert cues[0].time_range.end == 4.5
    assert cues[1].text == "Second cue text"
    assert cues[1].time_range.start == 4.2
    assert cues[1].time_range.end == 7.0


def test_ass_parser_success(dummy_ass: Path) -> None:
    """Verify ASS parser extracts dialogue texts and handles centisecond timestamps."""
    parser = SubtitleParserImpl()
    cues = parser.parse(dummy_ass)

    assert len(cues) == 2
    assert cues[0].text == "{\\pos(400,570)}Hello ASS subtitle!"
    assert cues[0].time_range.start == 1.20
    assert cues[0].time_range.end == 3.50
    assert cues[1].text == "Second ASS cue"


def test_parser_encoding_autodetect(tmp_path: Path) -> None:
    """Verify parser auto-detects non-UTF-8 encodings (like UTF-16)."""
    f = tmp_path / "utf16.srt"
    content = "1\n00:00:01,000 --> 00:00:02,000\nText in UTF-16\n"
    f.write_text(content, encoding="utf-16")

    parser = SubtitleParserImpl()
    cues = parser.parse(f)
    assert len(cues) == 1
    assert cues[0].text == "Text in UTF-16"


def test_subtitle_normalizer() -> None:
    """Verify HTML/ASS formatting stripping, chronological sorting, and overlap/duplicate fixes."""
    cues = [
        TranscriptCue(text="Dialogue 1 <i>italic</i>", time_range=TimeRange(start=2.0, end=4.0)),
        # Bilingual duplicate at same timeline
        TranscriptCue(text="Dialogue 1 Vietnamese", time_range=TimeRange(start=2.0, end=4.0)),
        # Overlapping cue
        TranscriptCue(text="{\\i1}Dialogue 2{\\r}", time_range=TimeRange(start=3.5, end=6.0)),
    ]

    normalizer = SubtitleNormalizerImpl()
    normalized = normalizer.normalize_cues(cues)

    # Should:
    # 1. Clean HTML tags: "Dialogue 1 italic"
    # 2. Merge bilingual duplicates at same timestamps: "Dialogue 1 italic | Dialogue 1 Vietnamese"
    # 3. Clip overlapping timestamps: Dialogue 1 end clips to 3.5 (Dialogue 2 start)
    # 4. Strip ASS tags: "Dialogue 2"
    assert len(normalized) == 2
    
    assert normalized[0].text == "Dialogue 1 italic | Dialogue 1 Vietnamese"
    assert normalized[0].time_range.start == 2.0
    assert normalized[0].time_range.end == 3.5  # clipped from 4.0 to 3.5 due to Dialogue 2 overlap

    assert normalized[1].text == "Dialogue 2"
    assert normalized[1].time_range.start == 3.5
    assert normalized[1].time_range.end == 6.0
