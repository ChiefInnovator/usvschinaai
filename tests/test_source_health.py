"""A sustained benchmark source outage fails the run; one bad night only warns."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import check_source_health as health


def report(**sources):
    return dict(retrievedAt='2026-11-10', accepted=3, sourceHealth=sources)


class SourceHealthTests(unittest.TestCase):
    def levels(self, **sources):
        return {row['source']: row['level'] for row in health.assess(report(**sources))}

    def test_levels(self):
        levels = self.levels(
            epoch=dict(status='ok', findings=12, since='2026-09-06', lastOk='2026-11-10'),
            blip=dict(status='failed', findings=0, since='2026-11-10', lastOk='2026-11-09', error='timed out'),
            vals=dict(status='failed', findings=0, since='2026-10-04', lastOk='2026-10-03', error='payload changed'),
            charxiv=dict(status='empty', findings=0, since='2026-09-06', lastOk=None),
            renamed=dict(status='empty', findings=0, since='2026-11-08', lastOk='2026-11-07'))
        self.assertEqual(levels, dict(epoch='ok', blip='warn', vals='alert', charxiv='info', renamed='alert'))

    def test_summary_names_every_unhealthy_source_and_its_outage_start(self):
        data = report(epoch=dict(status='ok', findings=12, since='2026-09-06', lastOk='2026-11-10'),
                      vals=dict(status='failed', findings=0, since='2026-10-04', lastOk='2026-10-03', error='payload changed'),
                      pages=dict(status='ok', findings=40, since='2026-09-06', lastOk='2026-11-10', pages=10, failedPages=4))
        text = health.render(data, health.assess(data))
        self.assertIn('2 of 3 sources returned results', text)
        self.assertIn('`vals`: failed since 2026-10-04 (38 days; last productive 2026-10-03): payload changed', text)
        self.assertNotIn('`epoch`', text)

    def run_main(self, data, *argv):
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / 'audit.json'
            audit.write_text(json.dumps(data))
            summary = Path(directory) / 'summary.md'
            with patch.object(health, 'AUDIT', audit), patch.object(sys, 'argv', ['check', *argv]), \
                 patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(summary)}), patch('builtins.print'):
                code = health.main()
            return code, summary.read_text() if summary.exists() else ''

    def test_exit_status_follows_sustained_outages_only(self):
        down = dict(status='failed', findings=0, since='2026-11-08', lastOk='2026-11-07', error='x')
        blip = dict(down, since='2026-11-10')
        self.assertEqual(self.run_main(report(vals=down))[0], 1)
        self.assertEqual(self.run_main(report(vals=blip))[0], 0)
        self.assertEqual(self.run_main(report(vals=down), '--markdown'), (0, ''))
        self.assertEqual(self.run_main(report(vals=down), '--grace-days', '5')[0], 0)
        self.assertIn('Benchmark source health', self.run_main(report(vals=down))[1])

    def test_audit_without_health_record_does_not_alert(self):
        for data in ({'retrievedAt': '2026-11-10'}, {}):
            self.assertEqual(self.run_main(data)[0], 0)


if __name__ == '__main__':
    unittest.main()
