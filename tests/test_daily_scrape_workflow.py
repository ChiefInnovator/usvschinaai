#!/usr/bin/env python3
"""The daily scrape spends on AI research only on Sundays and manual runs.

Runs the workflow's own "Decide AI research budget" shell with a faked
`date`, and checks the billing and scraper steps consume its output."""
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "daily-scrape.yml"


def step(name):
    """Text of one step, from its `- name:` line up to the next step."""
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(rf"^( *)- name: {re.escape(name)}\n(.*?)(?=^\1- name:|\Z)", text, re.M | re.S)
    if not match:
        raise AssertionError(f"step {name!r} not found in {WORKFLOW.name}")
    return match.group(2)


def run_block(step_text):
    """The `run: |` body of a step, dedented."""
    lines = step_text.split("\n")
    start = next(i for i, l in enumerate(lines) if l.strip() == "run: |") + 1
    body = [l for l in lines[start:] if l.strip()]
    indent = min(len(l) - len(l.lstrip()) for l in body)
    return "\n".join(l[indent:] for l in body) + "\n"


class BudgetStepTests(unittest.TestCase):
    def budget(self, event, weekday):
        script = run_block(step("Decide AI research budget")).replace("${{ github.event_name }}", event)
        with tempfile.TemporaryDirectory() as tmp:
            fake_date = Path(tmp) / "date"
            fake_date.write_text(f"#!/bin/sh\necho {weekday}\n")
            fake_date.chmod(fake_date.stat().st_mode | stat.S_IEXEC)
            out = Path(tmp) / "out"
            env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(out)}
            subprocess.run(["bash", "-e", "-c", script], env=env, check=True)
            return out.read_text().strip()

    def test_sunday_schedule_researches(self):
        self.assertEqual(self.budget("schedule", 7), "max_calls=10")

    def test_weekday_schedule_is_cache_only(self):
        for day in range(1, 7):
            self.assertEqual(self.budget("schedule", day), "max_calls=0", f"weekday {day}")

    def test_manual_dispatch_researches_any_day(self):
        self.assertEqual(self.budget("workflow_dispatch", 3), "max_calls=10")

    def test_budget_step_runs_before_its_consumers(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        order = [text.index(f"- name: {n}") for n in
                 ("Decide AI research budget", "Check OpenAI billing", "Run scraper")]
        self.assertEqual(order, sorted(order))

    def test_billing_check_runs_every_night(self):
        # New models are researched nightly, so quota problems must surface nightly.
        self.assertNotIn("if:", step("Check OpenAI billing"))

    def test_scraper_receives_the_budget(self):
        self.assertIn('--gap-fill-max-calls "${{ steps.budget.outputs.max_calls }}"',
                      run_block(step("Run scraper")))


class SourceHealthStepTests(unittest.TestCase):
    def test_outage_alert_cannot_block_the_data_pull_request(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        order = [text.index(f"- name: {n}") for n in
                 ("Run scraper", "Summarize benchmark source health", "Open data feature pull request",
                  "Alert on sustained benchmark source outage")]
        self.assertEqual(order, sorted(order))
        summary = run_block(step("Summarize benchmark source health"))
        self.assertIn("--markdown", summary)
        self.assertIn("||", summary, "a summary failure must not block the pull request")
        alert = step("Alert on sustained benchmark source outage")
        self.assertNotIn("--markdown", alert)
        self.assertNotIn("continue-on-error", alert)

    def test_pull_request_body_carries_source_health(self):
        body = run_block(step("Open data feature pull request"))
        self.assertIn('cat "$RUNNER_TEMP/source-health.md"', body)
        self.assertIn('--body-file "$RUNNER_TEMP/pr-body.md"', body)

    def test_publishing_token_is_verified_before_the_scrape(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertLess(text.index("- name: Verify publishing token"), text.index("- name: Run scraper"))
        self.assertIn("exit 1", run_block(step("Verify publishing token")))
        # A valid but read-only token must fail here, not after the scrape and paid research.
        for workflow in (WORKFLOW, WORKFLOW.with_name("backfill-gap-fill.yml")):
            self.assertIn("info/refs?service=git-receive-pack", workflow.read_text(encoding="utf-8"))
        # The scraper itself never sees the write-capable token.
        self.assertNotIn("PAT_TOKEN", step("Run scraper"))


class CarryForwardStepTests(unittest.TestCase):
    """Runs the workflow's own carry-forward shell against a throwaway repository."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        self.origin, self.work = root / "origin.git", root / "work"
        self.git(root, "init", "--quiet", "--bare", "-b", "develop", str(self.origin))
        self.git(root, "clone", "--quiet", str(self.origin), str(self.work))
        self.git(self.work, "checkout", "--quiet", "-b", "develop")
        (self.work / "scripts").mkdir()
        self.commit({"models.json": "day 1\n", "scripts/code.py": "v1\n"}, "develop")
        self.git(self.work, "push", "--quiet", "origin", "develop")
        self.develop = self.head()

    def git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def head(self):
        return self.git(self.work, "rev-parse", "HEAD")

    def commit(self, files, message):
        for name, text in files.items():
            (self.work / name).write_text(text)
        self.git(self.work, "add", "-A")
        self.git(self.work, "commit", "--quiet", "-m", message)

    def pending(self, files, branch="feature/daily-scrape-1-1"):
        """Push a pending pull-request branch, then return the checkout to develop."""
        self.git(self.work, "checkout", "--quiet", "-b", branch)
        self.commit(files, "Daily scrape run")
        self.git(self.work, "push", "--quiet", "origin", branch)
        tip = self.head()
        self.git(self.work, "checkout", "--quiet", "develop")
        return branch, tip

    def run_step(self, open_branch="", verifies=True):
        text = step("Carry forward an unmerged daily scrape")
        generated = re.search(r"GENERATED: '([^']+)'", text).group(1)
        script = run_block(text).replace("${{ github.repository_owner }}", "owner")
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir(exist_ok=True)
        for name, body in (("gh", f"echo {open_branch}"), ("python", f"exit {0 if verifies else 1}")):
            tool = bin_dir / name
            tool.write_text(f"#!/bin/sh\n{body}\n")
            tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
        runner = Path(self.tmp.name) / "runner"
        runner.mkdir(exist_ok=True)
        out = Path(self.tmp.name) / "out"
        out.write_text("")
        env = {**self.env, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GENERATED": generated,
               "GITHUB_OUTPUT": str(out), "RUNNER_TEMP": str(runner), "GITHUB_REPOSITORY": "o/r"}
        done = subprocess.run(["bash", "-e", "-c", script], cwd=self.work, env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(out.read_text().strip(), f"develop_sha={self.develop}")
        self.assertEqual(self.git(self.work, "status", "--porcelain"), "")
        return done.stdout, (runner / "pending-note.md").exists()

    def test_no_open_pull_request_builds_on_develop(self):
        log, noted = self.run_step()
        self.assertEqual((self.head(), noted), (self.develop, False))
        self.assertIn("building on develop", log)

    def test_pending_data_is_built_upon(self):
        branch, tip = self.pending({"models.json": "day 1\nday 2\n"})
        log, noted = self.run_step(branch)
        self.assertEqual(self.head(), tip)
        self.assertTrue(noted)
        self.assertEqual((self.work / "models.json").read_text(), "day 1\nday 2\n")

    def test_pending_data_merges_onto_a_develop_that_gained_code(self):
        branch, tip = self.pending({"models.json": "day 1\nday 2\n"})
        self.commit({"scripts/code.py": "v2\n"}, "code change")
        self.git(self.work, "push", "--quiet", "origin", "develop")
        self.develop = self.head()
        self.run_step(branch)
        self.assertEqual(self.git(self.work, "rev-list", "--parents", "-n", "1", "HEAD").split()[1:], [self.develop, tip])
        self.assertEqual((self.work / "scripts/code.py").read_text(), "v2\n")

    def test_branch_touching_code_is_never_built_upon(self):
        branch, _ = self.pending({"models.json": "day 2\n", "scripts/code.py": "injected\n"})
        log, noted = self.run_step(branch)
        self.assertEqual((self.head(), noted), (self.develop, False))
        self.assertIn("does not generate", log)
        self.assertEqual((self.work / "scripts/code.py").read_text(), "v1\n")

    def test_unverifiable_or_conflicting_data_falls_back_to_develop(self):
        branch, _ = self.pending({"models.json": "day 2\n"})
        log, noted = self.run_step(branch, verifies=False)
        self.assertEqual((self.head(), noted), (self.develop, False))
        self.assertIn("does not verify", log)
        self.commit({"models.json": "republished\n"}, "algorithm change")
        self.git(self.work, "push", "--quiet", "origin", "develop")
        self.develop = self.head()
        log, noted = self.run_step(branch)
        self.assertEqual((self.head(), noted), (self.develop, False))
        self.assertIn("conflicts with develop", log)

    def test_publish_guard_compares_the_develop_commit_the_run_started_from(self):
        body = run_block(step("Open data feature pull request"))
        self.assertIn('"${{ steps.base.outputs.develop_sha }}" != "$(git rev-parse FETCH_HEAD)"', body)
        self.assertIn('cat "$RUNNER_TEMP/pending-note.md"', body)
        text = WORKFLOW.read_text(encoding="utf-8")
        order = [text.index(f"- name: {n}") for n in
                 ("Install dependencies", "Carry forward an unmerged daily scrape", "Run test suite", "Run scraper")]
        self.assertEqual(order, sorted(order))
        # The pending branch is read with the job's read-only token, never the publishing one.
        self.assertNotIn("PAT_TOKEN", step("Carry forward an unmerged daily scrape"))


if __name__ == "__main__":
    unittest.main()
