"""Lock-drift tests: the hash-pinned lock files must match pyproject.toml."""

import re
import tomllib
from importlib import metadata
from pathlib import Path

from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
RUNTIME_IN = ROOT / "requirements.in"
RUNTIME_LOCK = ROOT / "requirements.txt"
DEV_IN = ROOT / "requirements-dev.in"
DEV_LOCK = ROOT / "requirements-dev.txt"
BUILD_IN = ROOT / "requirements-build.in"
BUILD_LOCK = ROOT / "requirements-build.txt"

_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)\s*(?:;\s*([^\\]+?))?\s*\\?$")


def _parse_lock(path: Path) -> dict[str, list[str]]:
    """Return {name: [versions]} for the lock entries that apply to this interpreter."""
    entries: dict[str, list[str]] = {}
    for line in path.read_text().splitlines():
        match = _PIN.match(line)
        if not match:
            continue
        name, version, marker = match.groups()
        if marker and not Marker(marker).evaluate():
            continue
        entries.setdefault(canonicalize_name(name), []).append(version)
    return entries


def _check_requirements(requirements: list[str], lock: dict[str, list[str]]) -> None:
    assert requirements, "no pyproject requirements to check"
    assert lock, "lock has no applicable entries"
    for text in requirements:
        req = Requirement(text)
        if req.marker and not req.marker.evaluate():
            continue
        wanted = [req]
        # The lock is flat, so the dependencies an extra pulls in need an entry too.
        for extra in req.extras:
            for dep_text in metadata.requires(req.name) or []:
                dep = Requirement(dep_text)
                # Only deps gated on this extra: true with it, false without it.
                if (
                    dep.marker
                    and dep.marker.evaluate({"extra": extra})
                    and not dep.marker.evaluate({"extra": ""})
                ):
                    wanted.append(dep)
        for item in wanted:
            versions = lock.get(canonicalize_name(item.name), [])
            assert len(versions) == 1, f"{item.name}: expected one lock entry, got {versions}"
            if item is req:
                assert req.specifier.contains(Version(versions[0]), prereleases=True), (
                    f"{req.name}=={versions[0]} violates {req.specifier}"
                )


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text())["project"]


def test_runtime_lock_satisfies_pyproject() -> None:
    _check_requirements(_pyproject()["dependencies"], _parse_lock(RUNTIME_LOCK))


def test_dev_lock_satisfies_dev_extra() -> None:
    _check_requirements(_pyproject()["optional-dependencies"]["dev"], _parse_lock(DEV_LOCK))


def test_dev_lock_pins_match_runtime() -> None:
    runtime = _parse_lock(RUNTIME_LOCK)
    assert runtime, "runtime lock has no applicable entries"
    dev = _parse_lock(DEV_LOCK)
    for name, versions in runtime.items():
        assert dev.get(name) == versions, f"{name}: runtime {versions} vs dev {dev.get(name)}"


def _parse_in(path: Path, follow: bool = True) -> list[Requirement]:
    """Return the requirements of a .in file, following `-r` lines unless told not to."""
    reqs: list[Requirement] = []
    for raw in path.read_text().splitlines():
        line = raw.split("#")[0].strip()
        if line.startswith(("-r ", "-c ")):
            if follow:
                reqs += _parse_in(path.parent / line[3:].strip())
        elif line:
            reqs.append(Requirement(line))
    return reqs


def test_in_pins_match_locks() -> None:
    for source, lock_path in (
        (RUNTIME_IN, RUNTIME_LOCK),
        (DEV_IN, DEV_LOCK),
        (BUILD_IN, BUILD_LOCK),
    ):
        lock = _parse_lock(lock_path)
        pins = _parse_in(source)
        assert pins, source
        for req in pins:
            versions = [spec.version for spec in req.specifier if spec.operator == "=="]
            assert len(versions) == 1, f"{source.name}: {req} is not an exact pin"
            assert lock.get(canonicalize_name(req.name)) == versions, f"{source.name}: {req}"


def _check_in_pins(requirements: list[str], source: Path) -> None:
    assert requirements, "no pyproject requirements to check"
    pins = _parse_in(source, follow=False)
    for text in requirements:
        req = Requirement(text)
        matches = [p for p in pins if canonicalize_name(p.name) == canonicalize_name(req.name)]
        assert len(matches) == 1, f"{source.name}: expected one pin for {req.name}, got {matches}"
        pin = matches[0]
        assert pin.extras == req.extras, f"{source.name}: extras of {req.name} differ"
        version = next(spec.version for spec in pin.specifier if spec.operator == "==")
        assert req.specifier.contains(Version(version), prereleases=True), (
            f"{req.name}=={version} violates {req.specifier}"
        )


def test_in_pins_satisfy_pyproject() -> None:
    _check_in_pins(_pyproject()["dependencies"], RUNTIME_IN)
    _check_in_pins(_pyproject()["optional-dependencies"]["dev"], DEV_IN)
