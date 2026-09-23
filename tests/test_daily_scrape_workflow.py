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


if __name__ == "__main__":
    unittest.main()
