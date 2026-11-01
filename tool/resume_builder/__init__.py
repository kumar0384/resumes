"""Hybrid resume builder: core-skills block up top, reverse-chronological history below."""

from importlib import resources

from .model import Resume, check  # noqa: F401

__version__ = "0.1.0"


def skeleton() -> Resume:
    """A fresh hybrid resume filled with [placeholder] guidance."""
    path = resources.files(__package__) / "templates" / "hybrid_skeleton.json"
    import json
    return Resume.from_dict(json.loads(path.read_text(encoding="utf-8")))
