"""Per-project profile auto-detection.

Reads profile JSON files from a profiles directory and returns the name of the
profile whose ``project_dir`` matches the current working directory (or is an
ancestor of it). Pure stdlib.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


def _norm(p: Path) -> str:
    """Return a normalized, comparable string form of ``p``.

    Uses ``Path.resolve(strict=False)`` to canonicalize the path even when it
    does not exist on disk, then applies ``os.path.normcase`` so comparisons
    are case-insensitive on Windows but case-sensitive on POSIX.
    """
    return os.path.normcase(str(p.resolve(strict=False)))


def _is_ancestor_or_equal(parent: Path, child: Path) -> bool:
    """True iff ``parent`` is equal to ``child`` or an ancestor directory."""
    pn = _norm(parent)
    cn = _norm(child)
    if pn == cn:
        return True
    # Ensure trailing separator on parent so e.g. /foo does not match /foobar.
    if not pn.endswith(os.sep):
        pn = pn + os.sep
    return cn.startswith(pn)


def find_matching_profile(cwd: Path, profiles_dir: Path) -> Optional[str]:
    """Return the name of the profile whose ``project_dir`` matches ``cwd``.

    Matching rules:
        * For each ``*.json`` file in ``profiles_dir``, read the JSON.
        * Skip if ``project_dir`` is missing, empty, or null.
        * A profile matches if its resolved absolute ``project_dir`` equals
          ``cwd`` or is an ancestor directory of ``cwd``.
        * If multiple profiles match, the LONGEST (most-specific) wins.
        * Ties are broken by profile name (lexicographic ascending).
        * Returns the profile's ``name`` field if present, otherwise the
          source filename stem.

    Robustness:
        * ``profiles_dir`` missing or not a directory → ``None``.
        * ``cwd`` missing/``None`` → ``None``.
        * Any individual profile that fails to read/parse is skipped silently.
    """
    if cwd is None:
        return None
    if profiles_dir is None:
        return None
    if not profiles_dir.exists() or not profiles_dir.is_dir():
        return None

    cwd_path = Path(cwd)

    # Each candidate is (project_dir_length, name, file_stem).
    candidates = []

    try:
        json_files = sorted(profiles_dir.glob("*.json"))
    except OSError:
        return None

    for json_path in json_files:
        try:
            with json_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError, UnicodeDecodeError):
            continue

        if not isinstance(data, dict):
            continue

        project_dir = data.get("project_dir")
        if not project_dir or not isinstance(project_dir, str):
            continue

        try:
            pdir = Path(project_dir)
        except (TypeError, ValueError):
            continue

        if not _is_ancestor_or_equal(pdir, cwd_path):
            continue

        # Use the normalized form length as the specificity measure.
        specificity = len(_norm(pdir))
        name = data.get("name")
        if not isinstance(name, str) or not name:
            name = json_path.stem
        candidates.append((specificity, name, json_path.stem))

    if not candidates:
        return None

    # Sort: longest project_dir first, then lexicographic name ascending.
    candidates.sort(key=lambda t: (-t[0], t[1]))
    return candidates[0][1]
