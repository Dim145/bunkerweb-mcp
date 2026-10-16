"""Tests for the bundled skill catalog loader (fixture trees live under tmp_path)."""

import hashlib
import os
from pathlib import Path

import pytest

from bunkerweb_mcp.skill_catalog import SKILL_URI_PREFIX, load_skills


def _skill(root: Path, name: str, front: str | None = None, body: str = "# Body\n") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    if front is None:
        front = f"name: {name}\ndescription: Use when testing {name}."
    (skill_dir / "SKILL.md").write_text(f"---\n{front}\n---\n{body}", encoding="utf-8")
    return skill_dir


def test_load_valid_skill(tmp_path: Path) -> None:
    skill_dir = _skill(tmp_path, "demo")
    (skill_dir / "references").mkdir()
    (skill_dir / "references" / "mapping.md").write_bytes(b"# Mapping\n")
    (entry,) = load_skills(tmp_path)

    assert entry.name == "demo"
    assert entry.uri == f"{SKILL_URI_PREFIX}/demo/SKILL.md"
    assert entry.frontmatter == {"name": "demo", "description": "Use when testing demo."}
    assert [f.uri for f in entry.files] == [
        f"{SKILL_URI_PREFIX}/demo/SKILL.md",
        f"{SKILL_URI_PREFIX}/demo/references/mapping.md",
    ]
    raw = (skill_dir / "references" / "mapping.md").read_bytes()
    ref = entry.files[1]
    assert ref.digest == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert ref.size == len(raw)
    assert ref.mime_type == "text/markdown"


def test_skills_sorted(tmp_path: Path) -> None:
    _skill(tmp_path, "zeta")
    _skill(tmp_path, "alpha")
    assert [e.name for e in load_skills(tmp_path)] == ["alpha", "zeta"]


def test_nested_skill_md_is_not_the_root(tmp_path: Path) -> None:
    skill_dir = tmp_path / "demo"
    (skill_dir / "references" / "demo").mkdir(parents=True)
    (skill_dir / "references" / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Nested.\n---\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match=r"demo.*no SKILL\.md"):
        load_skills(tmp_path)


def test_root_skill_md_wins_over_nested(tmp_path: Path) -> None:
    skill_dir = _skill(tmp_path, "demo")
    # "A" sorts before "SKILL.md", so a suffix match would pick this file first
    (skill_dir / "A" / "demo").mkdir(parents=True)
    (skill_dir / "A" / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Nested.\n---\n", encoding="utf-8"
    )
    (entry,) = load_skills(tmp_path)
    assert entry.uri == f"{SKILL_URI_PREFIX}/demo/SKILL.md"
    assert entry.frontmatter["description"] == "Use when testing demo."


def test_crlf_and_bom_served_verbatim(tmp_path: Path) -> None:
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    skill_raw = b"---\r\nname: demo\r\ndescription: Use when testing.\r\n---\r\n# Body\r\n"
    ref_raw = b"\xef\xbb\xbf# Reference\r\n"
    (skill_dir / "SKILL.md").write_bytes(skill_raw)
    (skill_dir / "ref.md").write_bytes(ref_raw)
    (entry,) = load_skills(tmp_path)

    # sorted by uri: "SKILL.md" < "ref.md"
    for file, raw in zip(entry.files, (skill_raw, ref_raw), strict=True):
        assert file.text.encode("utf-8") == raw
        assert file.digest == "sha256:" + hashlib.sha256(raw).hexdigest()
        assert file.size == len(raw)
    assert entry.frontmatter["name"] == "demo"


def _bad_name_mismatch(root: Path) -> None:
    _skill(root, "demo", "name: other\ndescription: Use when testing.")


def _bad_name_pattern(root: Path) -> None:
    _skill(root, "Demo", "name: Demo\ndescription: Use when testing.")


def _bad_name_length(root: Path) -> None:
    long = "a" * 65
    _skill(root, long, f"name: {long}\ndescription: Use when testing.")


def _bad_missing_skill_md(root: Path) -> None:
    (root / "demo").mkdir()
    (root / "demo" / "other.md").write_text("x")


def _bad_no_frontmatter(root: Path) -> None:
    skill_dir = root / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# no frontmatter\n")


def _bad_not_a_dict(root: Path) -> None:
    _skill(root, "demo", "- a\n- b")


def _bad_empty_description(root: Path) -> None:
    _skill(root, "demo", 'name: demo\ndescription: ""')


def _bad_missing_description(root: Path) -> None:
    _skill(root, "demo", "name: demo")


def _bad_long_description(root: Path) -> None:
    _skill(root, "demo", f"name: demo\ndescription: {'x' * 1025}")


def _bad_non_utf8(root: Path) -> None:
    skill_dir = _skill(root, "demo")
    (skill_dir / "ref.md").write_bytes(b"\xff\xfe\x00bad")


def _bad_symlink(root: Path) -> None:
    skill_dir = _skill(root, "demo")
    target = root / "outside.md"
    target.write_text("secret")
    os.symlink(target, skill_dir / "link.md")


def _bad_date_frontmatter(root: Path) -> None:
    _skill(root, "demo", "name: demo\ndescription: Use when testing.\nupdated: 2026-10-16")


def _bad_too_many_files(root: Path) -> None:
    skill_dir = _skill(root, "demo")
    for i in range(512):
        (skill_dir / f"f{i}.md").write_text("x")


def _bad_too_large(root: Path) -> None:
    skill_dir = _skill(root, "demo")
    (skill_dir / "big.md").write_bytes(b"x" * (16 * 1024 * 1024))


@pytest.mark.parametrize(
    "build",
    [
        _bad_name_mismatch,
        _bad_name_pattern,
        _bad_name_length,
        _bad_missing_skill_md,
        _bad_no_frontmatter,
        _bad_not_a_dict,
        _bad_empty_description,
        _bad_missing_description,
        _bad_long_description,
        _bad_non_utf8,
        _bad_symlink,
        _bad_date_frontmatter,
        _bad_too_many_files,
        _bad_too_large,
    ],
)
def test_rejects(tmp_path: Path, build: "object") -> None:
    root = tmp_path / "skills"
    root.mkdir()
    build(root)  # type: ignore[operator]
    with pytest.raises(ValueError, match="demo|Demo|aaaa"):
        load_skills(root)


def test_bundled_skills_load() -> None:
    entries = load_skills()
    assert len(entries) == 13
    names = {e.name for e in entries}
    assert {"bunkerweb", "bunkerweb-troubleshooting", "bunkerweb-modsecurity-crs-tuning"} <= names
    assert sum(len(e.files) for e in entries) == 59
