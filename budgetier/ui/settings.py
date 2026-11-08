"""The window's own settings, in settings.json in the data folder: the look, motion, and
whether the tour has been seen. A setting that can't be read is worth no more than its
default."""
from __future__ import annotations

import json
from pathlib import Path

from ..storage import read_text, write_files

FILE = "settings.json"


def load(home: Path) -> dict:
    path = Path(home) / FILE
    try:
        saved = json.loads(read_text(path)) if path.exists() else {}
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def save(home: Path, **changes) -> None:
    """Change some settings and keep the rest."""
    settings = {**load(home), **changes}
    write_files({Path(home) / FILE: json.dumps(settings, indent=2, sort_keys=True) + "\n"})
