"""Per-computer app settings (not part of any resume file).

Stored as JSON in ~/.resume_builder.json, e.g. which local folder is your
site repo. Set RESUME_BUILDER_SETTINGS to use a different file (tests do).
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def path() -> Path:
    return Path(os.environ.get("RESUME_BUILDER_SETTINGS") or Path.home() / ".resume_builder.json")


def load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get(key: str, default=None):
    return load().get(key, default)


def set(key: str, value) -> None:  # noqa: A001 - module-level API mirrors dict naming
    data = load()
    data[key] = value
    try:
        path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass                        # settings are a convenience; never block the app
