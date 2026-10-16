#!/usr/bin/env python3
"""Vendor the bunkerweb-skills `skills/` tree at the commit pinned in SKILLS_REF.

    python scripts/sync_skills.py --ref <sha>   # fetch, replace the vendored tree, rewrite SKILLS_REF
    python scripts/sync_skills.py --check       # fail if the vendored tree differs from SKILLS_REF

Stdlib only. The tarball is untrusted: members are validated before anything is written.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "src" / "bunkerweb_mcp" / "data" / "skills"
REF_FILE = ROOT / "SKILLS_REF"
TARBALL_URL = "https://codeload.github.com/bunkerity/bunkerweb-skills/tar.gz/{ref}"
SHA_RE = re.compile(r"[0-9a-f]{40}")
MAX_TARBALL_BYTES = 64 * 1024 * 1024
MAX_MEMBERS = 4096
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024


def fetch_tarball(ref: str) -> bytes:
    """Download the gzipped tarball of `ref`, which must be a full lowercase commit sha."""
    if not SHA_RE.fullmatch(ref):
        raise ValueError(f"ref must be 40 lowercase hex characters, got {ref!r}")
    with urllib.request.urlopen(TARBALL_URL.format(ref=ref), timeout=60) as resp:  # noqa: S310
        data: bytes = resp.read(MAX_TARBALL_BYTES + 1)
    if len(data) > MAX_TARBALL_BYTES:
        raise ValueError("tarball exceeds size limit")
    return data


def extract_skills(tarball: bytes, dest: Path) -> list[str]:
    """Write the files under `<top>/skills/` into `dest` and return their sorted relative paths.

    The archive is streamed and bounded (member count, per-file and total size). Nothing is written
    until every member passed, so a rejected tarball leaves `dest` untouched.
    """
    files: dict[str, bytes] = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r|gz") as tar:
        for count, member in enumerate(tar, start=1):
            if count > MAX_MEMBERS:
                raise ValueError(f"archive has more than {MAX_MEMBERS} members")
            parts = PurePosixPath(member.name).parts
            if member.name.startswith("/") or ".." in parts:
                raise ValueError(f"unsafe member path: {member.name!r}")
            if len(parts) < 2 or parts[1] != "skills":
                continue  # outside skills/: data never read, links there (CLAUDE.md) are harmless
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"unsupported member type: {member.name!r}")
            if not member.isfile() or len(parts) < 3:
                continue
            if member.size > MAX_FILE_BYTES:
                raise ValueError(f"member too large: {member.name!r} ({member.size} bytes)")
            total += member.size
            if total > MAX_TOTAL_BYTES:
                raise ValueError(f"skills/ would expand past {MAX_TOTAL_BYTES} bytes")
            src = tar.extractfile(member)
            assert src is not None  # regular file, checked above
            buf = bytearray()
            while chunk := src.read(CHUNK_BYTES):
                buf += chunk
                if len(buf) > member.size:
                    break
            if len(buf) != member.size:
                raise ValueError(f"member size mismatch: {member.name!r}")
            files["/".join(parts[2:])] = bytes(buf)
    for rel, content in files.items():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return sorted(files)


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _read_ref() -> str:
    return REF_FILE.read_text().strip()


def _write_ref(content: bytes) -> None:
    tmp = REF_FILE.with_name(REF_FILE.name + ".tmp")
    try:
        tmp.write_bytes(content)
        os.replace(tmp, REF_FILE)
    finally:
        tmp.unlink(missing_ok=True)


def _sync(ref: str) -> int:
    tarball = fetch_tarball(ref)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".skills-new-", dir=DEST.parent))
    old = DEST.parent / ".skills-old"
    old_ref = REF_FILE.read_bytes() if REF_FILE.exists() else None
    try:
        if not extract_skills(tarball, tmp):
            print("tarball holds no skills/ files", file=sys.stderr)
            return 1
        if old.exists():  # leftover of a killed run: it is the good tree if DEST is gone
            if DEST.exists():
                shutil.rmtree(old)
            else:
                old.rename(DEST)
        backed_up = installed = pinned = False
        try:
            if DEST.exists():
                DEST.rename(old)
                backed_up = True
            tmp.rename(DEST)
            installed = True
            # set before the write: a half-done replace is undone by rewriting old_ref
            pinned = True
            _write_ref((ref + "\n").encode())
        except BaseException:
            if installed:
                shutil.rmtree(DEST, ignore_errors=True)
            if backed_up:
                old.rename(DEST)
            if pinned:
                if old_ref is None:
                    REF_FILE.unlink(missing_ok=True)
                elif not REF_FILE.exists() or REF_FILE.read_bytes() != old_ref:
                    _write_ref(old_ref)
            raise
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"vendored {len(_tree(DEST))} files at {ref}")
    return 0


def _check() -> int:
    ref = _read_ref()
    with tempfile.TemporaryDirectory() as tmp:
        extract_skills(fetch_tarball(ref), Path(tmp))
        want, have = _tree(Path(tmp)), _tree(DEST) if DEST.is_dir() else {}
    diff = sorted(p for p in want.keys() | have.keys() if want.get(p) != have.get(p))
    for path in diff:
        print(f"differs: {path}")
    if diff:
        print(f"vendored skills drift from {ref}; run: python scripts/sync_skills.py --ref {ref}")
        return 1
    print(f"vendored skills match {ref} ({len(have)} files)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ref", help="40-hex commit sha to vendor")
    group.add_argument("--check", action="store_true", help="compare vendored tree to SKILLS_REF")
    args = parser.parse_args(argv)
    try:
        return _check() if args.check else _sync(args.ref)
    except (ValueError, OSError, tarfile.TarError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
