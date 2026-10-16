"""Catalog of the bundled BunkerWeb skills, served as MCP resources."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

SKILLS_DIR = Path(__file__).with_name("data") / "skills"
SKILL_URI_PREFIX = "skill://bunkerweb"

MAX_FILES = 512
MAX_BYTES = 16 * 1024 * 1024
_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)^---[ \t]*\r?$", re.DOTALL | re.MULTILINE)


@dataclass(frozen=True, slots=True)
class SkillFile:
    """One file of a skill, served verbatim."""

    uri: str
    text: str
    digest: str
    size: int
    mime_type: str


@dataclass(frozen=True, slots=True)
class SkillEntry:
    """A skill directory with its parsed ``SKILL.md`` frontmatter."""

    name: str
    uri: str
    frontmatter: dict[str, Any]
    files: tuple[SkillFile, ...]


def _frontmatter(skill: str, text: str) -> dict[str, Any]:
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise ValueError(f"{skill}: SKILL.md has no frontmatter at byte 0")
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ValueError(f"{skill}: invalid frontmatter YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{skill}: frontmatter is not a mapping")
    try:
        json.dumps(data)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{skill}: frontmatter is not JSON-serialisable: {exc}") from exc

    name = data.get("name")
    if not isinstance(name, str) or len(name) > 64 or not _NAME_RE.match(name) or name != skill:
        raise ValueError(f"{skill}: frontmatter name {name!r} is invalid or differs from the dir")
    description = data.get("description")
    if not isinstance(description, str) or not 1 <= len(description) <= 1024:
        raise ValueError(f"{skill}: description must be 1 to 1024 characters")
    return data


def _read_files(skill: str, skill_dir: Path) -> tuple[SkillFile, ...]:
    files: list[SkillFile] = []
    total = 0
    for path in sorted(skill_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"{skill}: {path.relative_to(skill_dir)} is a symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"{skill}: {path.relative_to(skill_dir)} is not a regular file")
        if len(files) >= MAX_FILES:
            raise ValueError(f"{skill}: more than {MAX_FILES} files")
        rel = path.relative_to(skill_dir).as_posix()
        raw = path.read_bytes()
        total += len(raw)
        if total > MAX_BYTES:
            raise ValueError(f"{skill}: more than {MAX_BYTES} bytes in total")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{skill}: {rel} is not valid UTF-8") from exc
        # ponytail: UTF-8 text only; add blob resources when a skill ships a binary file
        mime = (
            "text/markdown" if rel.endswith(".md") else mimetypes.guess_type(rel)[0] or "text/plain"
        )
        files.append(
            SkillFile(
                uri=f"{SKILL_URI_PREFIX}/{skill}/{rel}",
                text=text,
                digest="sha256:" + hashlib.sha256(raw).hexdigest(),
                size=len(raw),
                mime_type=mime,
            )
        )
    return tuple(sorted(files, key=lambda f: f.uri))


def load_skills(root: Path = SKILLS_DIR) -> tuple[SkillEntry, ...]:
    """Load every skill under ``root``; raise ``ValueError`` naming the offending skill dir."""

    entries: list[SkillEntry] = []
    for skill_dir in sorted(p for p in root.iterdir() if p.is_dir() or p.is_symlink()):
        skill = skill_dir.name
        if skill_dir.is_symlink():
            raise ValueError(f"{skill}: skill dir is a symlink")
        files = _read_files(skill, skill_dir)
        root_uri = f"{SKILL_URI_PREFIX}/{skill}/SKILL.md"
        skill_md = next((f for f in files if f.uri == root_uri), None)
        if skill_md is None:
            raise ValueError(f"{skill}: no SKILL.md")
        entries.append(
            SkillEntry(
                name=skill,
                uri=skill_md.uri,
                frontmatter=_frontmatter(skill, skill_md.text),
                files=files,
            )
        )
    return tuple(entries)
