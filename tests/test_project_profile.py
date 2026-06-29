"""Tests for project_profile.find_matching_profile."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure the repo root is importable when pytest is invoked from elsewhere.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from project_profile import find_matching_profile  # noqa: E402


def _write_profile(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_no_profiles_dir(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "does_not_exist"
    cwd = tmp_path / "project"
    cwd.mkdir()
    assert find_matching_profile(cwd, profiles_dir) is None


def test_empty_profiles_dir(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    cwd = tmp_path / "project"
    cwd.mkdir()
    assert find_matching_profile(cwd, profiles_dir) is None


def test_exact_match(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    project = tmp_path / "myproj"
    project.mkdir()
    _write_profile(
        profiles_dir / "p1.json",
        {"name": "MyProj", "project_dir": str(project)},
    )
    assert find_matching_profile(project, profiles_dir) == "MyProj"


def test_ancestor_match(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    parent = tmp_path / "parent"
    child = parent / "sub" / "deep"
    child.mkdir(parents=True)
    _write_profile(
        profiles_dir / "p1.json",
        {"name": "Parent", "project_dir": str(parent)},
    )
    assert find_matching_profile(child, profiles_dir) == "Parent"


def test_no_match(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    other = tmp_path / "elsewhere"
    other.mkdir()
    cwd = tmp_path / "here"
    cwd.mkdir()
    _write_profile(
        profiles_dir / "p1.json",
        {"name": "Other", "project_dir": str(other)},
    )
    assert find_matching_profile(cwd, profiles_dir) is None


def test_skips_empty_project_dir(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    cwd = tmp_path / "here"
    cwd.mkdir()
    _write_profile(
        profiles_dir / "p1.json",
        {"name": "Empty", "project_dir": ""},
    )
    assert find_matching_profile(cwd, profiles_dir) is None


def test_skips_missing_project_dir(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    cwd = tmp_path / "here"
    cwd.mkdir()
    _write_profile(
        profiles_dir / "p1.json",
        {"name": "NoDir"},
    )
    assert find_matching_profile(cwd, profiles_dir) is None


def test_skips_malformed_json(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    project = tmp_path / "good"
    project.mkdir()
    # Garbage file should not break the search.
    (profiles_dir / "broken.json").write_text("not { valid json", encoding="utf-8")
    _write_profile(
        profiles_dir / "ok.json",
        {"name": "Good", "project_dir": str(project)},
    )
    assert find_matching_profile(project, profiles_dir) == "Good"


def test_longest_wins(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    a = tmp_path / "a"
    ab = a / "b"
    abc = ab / "c"
    abc.mkdir(parents=True)
    _write_profile(
        profiles_dir / "outer.json",
        {"name": "Outer", "project_dir": str(a)},
    )
    _write_profile(
        profiles_dir / "inner.json",
        {"name": "Inner", "project_dir": str(ab)},
    )
    assert find_matching_profile(abc, profiles_dir) == "Inner"


def test_tiebreak_by_name(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    project = tmp_path / "shared"
    project.mkdir()
    _write_profile(
        profiles_dir / "zeta.json",
        {"name": "Zeta", "project_dir": str(project)},
    )
    _write_profile(
        profiles_dir / "alpha.json",
        {"name": "Alpha", "project_dir": str(project)},
    )
    assert find_matching_profile(project, profiles_dir) == "Alpha"


def test_falls_back_to_file_stem(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    project = tmp_path / "anon"
    project.mkdir()
    _write_profile(
        profiles_dir / "fallback_stem.json",
        {"project_dir": str(project)},
    )
    assert find_matching_profile(project, profiles_dir) == "fallback_stem"


def test_substring_not_false_match(tmp_path: Path) -> None:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    foo = tmp_path / "foo"
    foobar = tmp_path / "foobar"
    foo.mkdir()
    foobar.mkdir()
    _write_profile(
        profiles_dir / "p1.json",
        {"name": "Foo", "project_dir": str(foo)},
    )
    assert find_matching_profile(foobar, profiles_dir) is None
