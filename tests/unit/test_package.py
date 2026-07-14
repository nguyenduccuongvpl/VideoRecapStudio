"""Package import test."""

import video_recap


def test_package_import() -> None:
    """Test that package can be imported and version is present."""
    assert hasattr(video_recap, "__version__")
    assert video_recap.__version__ == "0.1.0"
