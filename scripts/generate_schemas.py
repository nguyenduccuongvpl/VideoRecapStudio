#!/usr/bin/env python3
"""Script to automatically generate JSON Schema files for VideoRecapStudio artifacts."""

import json
import sys
from pathlib import Path

# Add src folder to python path to import video_recap package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from video_recap.domain import (  # noqa: E402
    EventGraph,
    MediaInfo,
    Narration,
    ProjectConfig,
    QAReport,
    RunManifest,
    StoryOutline,
    SubtitleTrack,
    Timeline,
)


def main() -> None:
    """Generate JSON schemas for all major domain artifacts."""
    schemas_dir = Path(__file__).parent.parent / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)

    models_to_generate = {
        "project_config": ProjectConfig,
        "media_info": MediaInfo,
        "subtitle_track": SubtitleTrack,
        "event_graph": EventGraph,
        "story_outline": StoryOutline,
        "narration": Narration,
        "timeline": Timeline,
        "qa_report": QAReport,
        "run_manifest": RunManifest,
    }

    for name, model_cls in models_to_generate.items():
        schema_data = model_cls.model_json_schema()
        schema_path = schemas_dir / f"{name}.json"
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(schema_data, f, indent=2)
        print(f"Generated JSON Schema for {name} -> {schema_path.name}")


if __name__ == "__main__":
    main()
