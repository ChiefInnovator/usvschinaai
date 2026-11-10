#!/usr/bin/env python3
"""Fail loudly when a benchmark source stays broken.

    python scripts/check_source_health.py             # exit 1 on a sustained outage
    python scripts/check_source_health.py --markdown  # summary only, always exit 0

Reads the sourceHealth record that refresh_benchmark_sources.py carries forward
in data/benchmark_source_refresh.json. One bad night is reported, not alerted.
A source that errors on consecutive refreshes, or stops matching models it used
to match, fails the run so the outage reaches the workflow-failure email
instead of sitting unread in an audit file.
"""
from preconditions import preconditions
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'data/benchmark_source_refresh.json'
# Days a source may stay unhealthy before the run fails; 1 tolerates a single bad night.
GRACE_DAYS = 1


@preconditions(report='mapping', grace_days='nonnegative_int')
def assess(report, grace_days=GRACE_DAYS):
    """One row per source: level is ok, info, warn or alert."""
    health = report.get('sourceHealth') or {}
    if not health:
        return []
    retrieved = date.fromisoformat(report['retrievedAt'])
    rows = []
    for name, record in sorted(health.items()):
        days = (retrieved - date.fromisoformat(record['since'])).days
        status = record['status']
        if status == 'ok':
            failed = record.get('failedPages', 0)
            level = 'ok'
            detail = f"{record['findings']} results" + (
                f"; {failed} of {record['pages']} pages unavailable" if failed else '')
        elif status == 'empty' and not record.get('lastOk'):
            level, detail = 'info', 'answers, but has never matched a tracked model'
        else:
            level = 'alert' if days >= grace_days else 'warn'
            reason = record.get('error') or 'answers, but no longer matches any tracked model'
            last = record.get('lastOk') or 'never'
            detail = f"{status} since {record['since']} ({days + 1} days; last productive {last}): {reason}"
        rows.append(dict(source=name, level=level, detail=detail))
    return rows


@preconditions(report='mapping', rows='sequence')
def render(report, rows):
    """Markdown for the job summary and the data pull request."""
    if not rows:
        return '### Benchmark source health\n\nNo source health record; the source refresh did not run.\n'
    healthy = sum(row['level'] == 'ok' for row in rows)
    lines = [f"### Benchmark source health ({report['retrievedAt']})", '',
             f"{healthy} of {len(rows)} sources returned results; "
             f"{report.get('accepted', 0)} new evidence records accepted."]
    marks = dict(alert='🔴', warn='🟡', info='⚪')
    lines += [''] + [f"- {marks[row['level']]} `{row['source']}`: {row['detail']}"
                     for row in rows if row['level'] != 'ok']
    return '\n'.join(lines).rstrip() + '\n'


@preconditions()
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--markdown', action='store_true', help='Print the summary and exit 0')
    parser.add_argument('--grace-days', type=int, default=GRACE_DAYS)
    args = parser.parse_args()
    report = json.loads(AUDIT.read_text())
    rows = assess(report, args.grace_days)
    summary = render(report, rows)
    print(summary, end='')
    if args.markdown:
        return 0
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as handle:
            handle.write(summary)
    for row in rows:
        if row['level'] in ('alert', 'warn'):
            kind = 'error' if row['level'] == 'alert' else 'warning'
            print(f"::{kind}::Benchmark source {row['source']} {row['detail']}")
    return 1 if any(row['level'] == 'alert' for row in rows) else 0


if __name__ == '__main__':
    sys.exit(main())
