"""Tests for scripts/sync_skills.py (tarballs are built in memory, no network)."""

import importlib.util
import io
import tarfile
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "sync_skills.py"
SHA = "557253b5f2c1cee7e7ce4780d93cd4d000e05f5e"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sync_skills", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync_skills = _load()


def _tarball(files: dict[str, bytes], extra: list[tarfile.TarInfo] | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for info in extra or []:
            tar.addfile(info)
    return buf.getvalue()


def _link(name: str, kind: bytes, target: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = target
    return info


def test_extract_keeps_only_skills_subtree(tmp_path: Path) -> None:
    tarball = _tarball(
        {
            "top/README.md": b"readme",
            "top/skills/a/SKILL.md": b"skill",
            "top/scripts/x.py": b"print()",
        }
    )
    assert sync_skills.extract_skills(tarball, tmp_path) == ["a/SKILL.md"]
    assert (tmp_path / "a" / "SKILL.md").read_bytes() == b"skill"
    assert not (tmp_path / "README.md").exists()


def test_extract_ignores_links_outside_skills(tmp_path: Path) -> None:
    link = _link("top/CLAUDE.md", tarfile.SYMTYPE, "AGENTS.md")
    tarball = _tarball({"top/skills/a/SKILL.md": b"skill"}, [link])
    assert sync_skills.extract_skills(tarball, tmp_path) == ["a/SKILL.md"]


@pytest.mark.parametrize(
    "files,extra",
    [
        ({"top/skills/ok.md": b"ok", "top/skills/../evil": b"x"}, None),
        ({"top/skills/ok.md": b"ok", "/abs": b"x"}, None),
        ({"top/skills/ok.md": b"ok"}, [_link("top/skills/link", tarfile.SYMTYPE, "/etc/passwd")]),
        ({"top/skills/ok.md": b"ok"}, [_link("top/skills/hard", tarfile.LNKTYPE, "top/x")]),
    ],
    ids=["dotdot", "absolute", "symlink", "hardlink"],
)
def test_extract_rejects_unsafe_members(
    tmp_path: Path, files: dict[str, bytes], extra: list[tarfile.TarInfo] | None
) -> None:
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(ValueError):
        sync_skills.extract_skills(_tarball(files, extra), dest)
    assert list(dest.iterdir()) == []


def test_fetch_rejects_non_sha_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_network(*_a: object, **_k: object) -> None:
        raise AssertionError("network call attempted")

    monkeypatch.setattr(sync_skills.urllib.request, "urlopen", no_network)
    for bad in ("main", SHA.upper(), SHA[:-1], SHA + "0"):
        with pytest.raises(ValueError):
            sync_skills.fetch_tarball(bad)


@pytest.fixture
def vendored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tarball = _tarball({"top/skills/a/SKILL.md": b"one", "top/skills/b/SKILL.md": b"two"})
    dest = tmp_path / "skills"
    ref_file = tmp_path / "SKILLS_REF"
    monkeypatch.setattr(sync_skills, "DEST", dest)
    monkeypatch.setattr(sync_skills, "REF_FILE", ref_file)
    monkeypatch.setattr(sync_skills, "fetch_tarball", lambda ref: tarball)
    assert sync_skills.main(["--ref", SHA]) == 0
    return dest


def test_ref_vendors_and_records_ref(vendored: Path) -> None:
    assert (vendored / "a" / "SKILL.md").read_bytes() == b"one"
    assert sync_skills.REF_FILE.read_text() == SHA + "\n"
    assert sync_skills.main(["--check"]) == 0


def test_ref_replaces_stale_files(vendored: Path) -> None:
    (vendored / "stale.md").write_bytes(b"old")
    assert sync_skills.main(["--ref", SHA]) == 0
    assert not (vendored / "stale.md").exists()


def test_check_reports_drift(vendored: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (vendored / "a" / "SKILL.md").write_bytes(b"onE")
    (vendored / "extra.md").write_bytes(b"x")
    (vendored / "b" / "SKILL.md").unlink()
    assert sync_skills.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert "a/SKILL.md" in out
    assert "extra.md" in out
    assert "b/SKILL.md" in out


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


NEW_SHA = "a" * 40


def _fail_sync_and_check(vendored: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old_tree, old_ref = _tree(vendored), sync_skills.REF_FILE.read_bytes()
    new = _tarball({"top/skills/c/SKILL.md": b"three"})
    monkeypatch.setattr(sync_skills, "fetch_tarball", lambda ref: new)
    assert sync_skills.main(["--ref", NEW_SHA]) == 1
    assert _tree(vendored) == old_tree
    assert sync_skills.REF_FILE.read_bytes() == old_ref
    assert sorted(p.name for p in vendored.parent.iterdir()) == ["SKILLS_REF", "skills"]


def test_sync_restores_old_tree_when_tree_move_fails(
    vendored: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_rename = Path.rename

    def flaky(self: Path, target: Path) -> Path:
        if self.name.startswith(".skills-new-"):
            raise OSError("injected tree move failure")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky)
    _fail_sync_and_check(vendored, monkeypatch)


def test_sync_keeps_old_tree_when_backup_move_fails(
    vendored: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_rename = Path.rename

    def flaky(self: Path, target: Path) -> Path:
        if self == sync_skills.DEST:
            raise OSError("injected backup move failure")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky)
    _fail_sync_and_check(vendored, monkeypatch)


def test_sync_restores_old_tree_when_pin_write_fails(
    vendored: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise OSError("injected pin write failure")

    monkeypatch.setattr(sync_skills.os, "replace", boom)
    _fail_sync_and_check(vendored, monkeypatch)


def test_extract_rejects_oversized_member(tmp_path: Path) -> None:
    big = _tarball({"top/skills/big": bytes(sync_skills.MAX_FILE_BYTES + 1)})
    with pytest.raises(ValueError, match="too large"):
        sync_skills.extract_skills(big, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_extract_rejects_total_overflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync_skills, "MAX_FILE_BYTES", 100)
    monkeypatch.setattr(sync_skills, "MAX_TOTAL_BYTES", 250)
    files = {f"top/skills/f{i}": bytes(100) for i in range(3)}
    with pytest.raises(ValueError, match="expand"):
        sync_skills.extract_skills(_tarball(files), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_extract_rejects_too_many_members(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync_skills, "MAX_MEMBERS", 3)
    files = {f"top/other/f{i}": b"x" for i in range(4)}
    with pytest.raises(ValueError, match="members"):
        sync_skills.extract_skills(_tarball(files), tmp_path)
