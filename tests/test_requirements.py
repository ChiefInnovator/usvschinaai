#!/usr/bin/env python3
"""Preflight checks on the pinned dependencies and the CI Python version.

Motivated by a real failure: Pillow 11.1.0 published no cp314 wheel, so
bumping CI to Python 3.14 made pip fall back to a source build, which died on
missing libjpeg headers. Nothing caught it until the daily scrape had already
run for several minutes and left production serving stale data.

The wheel check below reproduces that question offline-of-CI in about a
second: for the Python version the workflows actually pin, does every
requirement have a prebuilt Linux wheel?

Network-dependent tests skip (rather than fail) when PyPI is unreachable, so
the suite still runs offline.
"""
import json
from importlib.metadata import version as installed_version
import os
import re
import sys
import unittest
from unittest import mock
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = REPO_ROOT / "scripts" / "requirements.txt"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

PIN_RE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*==\s*([^\s#]+)\s*$")
PACKAGE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
PY_VERSION_RE = re.compile(r"python-version:\s*['\"]?(\d+)\.(\d+)['\"]?")


def parse_requirements():
    pins = {}
    for line in REQUIREMENTS.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = PIN_RE.match(line)
        if m:
            pins[m.group(1)] = m.group(2)
        elif PACKAGE_RE.fullmatch(line):
            pins[line] = None
    return pins


def workflow_python_versions():
    """{workflow filename: (major, minor)} for every workflow pinning Python."""
    out = {}
    for wf in sorted(WORKFLOW_DIR.glob("*.yml")):
        for m in PY_VERSION_RE.finditer(wf.read_text()):
            out.setdefault(wf.name, (int(m.group(1)), int(m.group(2))))
    return out


def pypi(package):
    url = f"https://pypi.org/pypi/{package}/json"
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


def skip_without_network(fn):
    def wrapper(self, *a, **k):
        try:
            return fn(self, *a, **k)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise unittest.SkipTest(f"PyPI unreachable: {exc}")
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def wheel_supports(filename, py):
    """Does this wheel install on CPython `py` = (major, minor), Linux x86_64?"""
    if not filename.endswith(".whl"):
        return False
    tag = f"cp{py[0]}{py[1]}"
    # Pure-Python wheels install anywhere.
    if "py3-none-any" in filename or "py2.py3-none-any" in filename:
        return True
    linux = "manylinux" in filename or "musllinux" in filename or "linux_x86_64" in filename
    if not linux or "x86_64" not in filename:
        return False
    # Version-specific, stable-ABI, or platform-only-but-Python-agnostic.
    return tag in filename or "abi3" in filename or "py3-none" in filename


class RequirementsFormatTests(unittest.TestCase):
    def test_requirements_file_exists_and_is_nonempty(self):
        self.assertTrue(REQUIREMENTS.exists(), f"missing {REQUIREMENTS}")
        self.assertTrue(parse_requirements(), "no requirements parsed")

    def test_requirements_use_supported_version_policy(self):
        """Playwright tracks latest; remaining dependencies use checked pins."""
        loose = []
        for line in REQUIREMENTS.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line != "playwright" and not PIN_RE.match(line):
                loose.append(line)
        self.assertEqual(loose, [], f"unsupported requirement specifications: {loose}")

    def test_playwright_tracks_latest_release(self):
        self.assertIn("playwright", parse_requirements())
        self.assertIsNone(parse_requirements()["playwright"])


class WorkflowPythonTests(unittest.TestCase):
    def test_at_least_one_workflow_pins_python(self):
        self.assertTrue(workflow_python_versions(), "no workflow pins python-version")

    def test_all_workflows_agree_on_python_version(self):
        """A split Python version means one workflow is tested and the other is not."""
        versions = workflow_python_versions()
        distinct = set(versions.values())
        self.assertEqual(
            len(distinct), 1,
            f"workflows disagree on Python version: {versions}",
        )


class WheelAvailabilityTests(unittest.TestCase):
    @skip_without_network
    def test_every_pin_has_a_linux_wheel_for_the_ci_python(self):
        """The exact check that would have caught the Pillow 11.1.0 failure.

        No wheel means pip compiles from source on the runner, which needs
        system headers the GitHub image does not necessarily carry.
        """
        py = sorted(set(workflow_python_versions().values()))[0]
        missing = []
        for package, version in parse_requirements().items():
            data = pypi(package)
            version = version or data["info"]["version"]
            files = data["releases"].get(version, [])
            self.assertTrue(files, f"{package}=={version} not published on PyPI")
            if not any(wheel_supports(f["filename"], py) for f in files):
                missing.append(f"{package}=={version}")
        self.assertEqual(
            missing, [],
            f"no prebuilt Linux wheel for Python {py[0]}.{py[1]}: {missing} "
            f"— pip will build from source in CI and may fail on missing headers",
        )

    @skip_without_network
    def test_pins_are_the_latest_released_version(self):
        """Project policy is to track latest; this surfaces drift immediately.

        Opt-in via CHECK_LATEST=1. The daily scrape runs this suite as a gate,
        and an upstream release is not a reason to stop publishing data — so
        drift is reported by the dedicated tests workflow, not by the pipeline.
        """
        if os.environ.get("CHECK_LATEST") != "1":
            self.skipTest("set CHECK_LATEST=1 to check for newer releases")
        stale = []
        for package, version in parse_requirements().items():
            latest = pypi(package)["info"]["version"]
            source = "pinned" if version else "installed"
            version = version or installed_version(package)
            if version != latest:
                stale.append(f"{package}: {source} {version}, latest {latest}")
        self.assertEqual(stale, [], "dependencies behind latest: " + "; ".join(stale))


class FloatingRequirementTests(unittest.TestCase):
    def test_latest_check_rejects_an_outdated_installed_playwright(self):
        with (mock.patch.dict(os.environ, {"CHECK_LATEST": "1"}),
              mock.patch(__name__ + ".parse_requirements", return_value={"playwright": None}),
              mock.patch(__name__ + ".pypi", return_value={"info": {"version": "1.65.0"}}),
              mock.patch(__name__ + ".installed_version", return_value="1.64.1")):
            check = WheelAvailabilityTests("test_pins_are_the_latest_released_version")
            with self.assertRaisesRegex(AssertionError, "playwright: installed 1.64.1, latest 1.65.0"):
                check.test_pins_are_the_latest_released_version()

    def test_wheel_check_includes_the_latest_playwright_release(self):
        with (mock.patch(__name__ + ".parse_requirements", return_value={"playwright": None}),
              mock.patch(__name__ + ".pypi", return_value={
                  "info": {"version": "1.65.0"}, "releases": {"1.65.0": []}})):
            check = WheelAvailabilityTests("test_every_pin_has_a_linux_wheel_for_the_ci_python")
            with self.assertRaisesRegex(AssertionError, "playwright==1.65.0 not published on PyPI"):
                check.test_every_pin_has_a_linux_wheel_for_the_ci_python()


class LocalInterpreterTests(unittest.TestCase):
    def test_local_python_matches_ci_python(self):
        """A local venv on a different minor version hides CI-only failures."""
        versions = workflow_python_versions()
        if not versions:
            self.skipTest("no workflow python pin found")
        expected = sorted(set(versions.values()))[0]
        actual = sys.version_info[:2]
        self.assertEqual(
            actual, expected,
            f"local Python {actual[0]}.{actual[1]} != CI "
            f"{expected[0]}.{expected[1]} — rebuild .venv to match",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
