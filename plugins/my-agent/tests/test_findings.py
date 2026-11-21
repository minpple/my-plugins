"""findings.py: per-severity Found, Fixed and Open counts and the open items of a task's judgment file (criterion 3)."""
import importlib.util
import os
import time
import tempfile
import unittest
from pathlib import Path

from helpers import L4, run_script

SCRIPT = L4 / 'scripts' / 'findings.py'
TABLE = '| Severity | Found | Fixed | Open |\n|---|---|---|---|\n'
STEP8 = '2026-11-20 10:00:00 step: n=8 name=Review-Deliver\n'


def table(rows):
    return TABLE + ''.join(f'| {sev} | {a} | {b} | {c} |\n' for sev, (a, b, c) in zip(('BLOCKER', 'SHOULD-FIX', 'NITPICK'), rows))


class FindingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.task = Path(self.tmp.name) / '261120-probe-task'
        self.task.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, text):
        path = self.task / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def run_f(self, file='review', task=None):
        return run_script(SCRIPT, '--task', str(task or self.task), '--file', file)

    def test_docstring(self):
        spec = importlib.util.spec_from_file_location('findings', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue((module.__doc__ or '').strip())

    def test_review_older_than_the_latest_reviewer_call_fails(self):
        self.put('review.md', 'BLOCKER 0\n\n## Findings\n')
        old = time.mktime(time.strptime('2026-11-20 09:00:00', '%Y-%m-%d %H:%M:%S'))
        os.utime(self.task / 'review.md', (old, old))
        self.put('run-log.md', STEP8 + '2026-11-20 10:00:05 start: agent=my-agent:plan-reviewer id=p1\n'
                               '2026-11-20 08:00:00 start: agent=my-agent:reviewer id=r1\n')
        self.assertEqual(self.run_f().returncode, 0)   # written after the latest reviewer call
        self.put('run-log.md', STEP8 + '2026-11-20 08:00:00 start: agent=my-agent:reviewer id=r1\n'
                               '2026-11-20 10:00:05 start: agent=my-agent:reviewer id=r2\n')
        r = self.run_f()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, f"findings: FAIL {self.task / 'review.md'} is older than the latest reviewer call "
                                   '(2026-11-20 10:00:05): the reviewer wrote no file\n')

    def test_review_one_round(self):
        self.put('review.md', 'BLOCKER 0\n\n## Findings\n- SHOULD-FIX a.py:1 first\n- SHOULD-FIX b.py:2 second → fix it\n'
                              '- NITPICK c.py:3 third\n- NITPICK d.py:4 fourth\n- NITPICK e.py:5 fifth\n\n'
                              '## Applied after review\n- a.py:1 done\n- c.py:3 done\n')
        r = self.run_f()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, 'findings: review.md (1 round)\n' + table([(0, 0, 0), (2, 1, 1), (3, 1, 2)]) +
                         'BLOCKER 0 · SHOULD-FIX 1 · NITPICK 2 (open)\n'
                         '- SHOULD-FIX b.py:2 second → fix it\n- NITPICK d.py:4 fourth\n- NITPICK e.py:5 fifth\n')

    def test_review_two_rounds_and_fix_line(self):
        self.put('archive/261120-101500-run1/review.md',
                 'BLOCKER 1\n\n## Findings\n- BLOCKER a.py:1 broken\n- SHOULD-FIX b.py:2 two\n- NITPICK c.py:3 three\n')
        self.put('review.md', 'BLOCKER 0\n\n## Findings\n- SHOULD-FIX b.py:2 two (carried)\n- NITPICK c.py:3 three (carried)\n'
                              '- NITPICK d.py:4 four (new)\n')
        self.put('run-log.md', STEP8 + '2026-11-20 10:05:00 fix: what="Review NITPICK c.py:3 three" files=c.py\n')
        r = self.run_f()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, 'findings: review.md (2 rounds)\n' + table([(1, 1, 0), (1, 0, 1), (2, 1, 1)]) +
                         'BLOCKER 0 · SHOULD-FIX 1 · NITPICK 1 (open)\n- SHOULD-FIX b.py:2 two\n- NITPICK d.py:4 four\n')

    def test_new_nitpick_in_second_round_is_open(self):
        self.put('archive/261120-101500-run1/review.md', 'BLOCKER 0\n\n## Findings\n- NITPICK a.py:1 one\n')
        self.put('review.md', 'BLOCKER 0\n\n## Findings\n- NITPICK a.py:1 one (carried)\n- NITPICK b.py:2 two (new)\n')
        r = self.run_f()
        self.assertIn('| NITPICK | 2 | 0 | 2 |\n', r.stdout)
        self.assertIn('- NITPICK b.py:2 two\n', r.stdout)

    def test_review_without_finding(self):
        self.put('review.md', 'BLOCKER 0\n\n## Findings\n')
        r = self.run_f()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, 'findings: review.md (1 round)\n' + table([(0, 0, 0)] * 3) +
                         'BLOCKER 0 · SHOULD-FIX 0 · NITPICK 0 (open)\n- none\n')

    def test_scope_and_plan_review(self):
        body = ('{v}\nRun: 1\n\n## Findings\n- SHOULD-FIX plan.md:10 one\n- SHOULD-FIX plan.md:20 two\n- NITPICK plan.md:30 three\n\n'
                '## Decisions\n- SHOULD-FIX plan.md:10 one → applied by L1\n- SHOULD-FIX plan.md:20 two → declined\n')
        self.put('scope-review.md', body.format(v='READY FOR CONFIRMATION'))
        r = self.run_f('scope-review')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, 'findings: scope-review.md\n' + table([(0, 0, 0), (2, 1, 1), (1, 0, 1)]) +
                         'BLOCKER 0 · SHOULD-FIX 1 · NITPICK 1 (open)\n- SHOULD-FIX plan.md:20 two\n- NITPICK plan.md:30 three\n')
        self.put('plan-review.md', body.format(v='READY FOR APPROVAL'))
        self.put('run-log.md', '2026-11-20 10:00:00 fix: what="Plan Review NITPICK plan.md:30 three" files=plan.md before=G1b\n')
        r = self.run_f('plan-review')
        self.assertEqual(r.stdout, 'findings: plan-review.md\n' + table([(0, 0, 0), (2, 1, 1), (1, 1, 0)]) +
                         'BLOCKER 0 · SHOULD-FIX 1 · NITPICK 0 (open)\n- SHOULD-FIX plan.md:20 two\n')
        self.assertIn('| NITPICK | 1 | 0 | 1 |', self.run_f('scope-review').stdout)   # the run-log fix is plan-review only

    def test_skipped_plan_review(self):
        self.put('plan-review.md', 'SKIPPED small task\n')
        r = self.run_f('plan-review')
        self.assertEqual((r.returncode, r.stdout), (0, 'findings: skipped (small task)\n'))

    def test_fail_causes(self):
        r = self.run_f()
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stdout.startswith('findings: FAIL ') and 'review.md' in r.stdout and r.stdout.count('\n') == 1, r.stdout)
        (self.task / 'review.md').mkdir()
        r = self.run_f()
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stdout.startswith('findings: FAIL ') and 'cannot be read' in r.stdout, r.stdout)
        (self.task / 'review.md').rmdir()
        self.put('review.md', 'LGTM\n\n## Findings\n')
        r = self.run_f()
        self.assertEqual(r.returncode, 1)
        self.assertIn('does not start with its blocker-count line (BLOCKER <n>)', r.stdout)
        self.put('plan-review.md', 'maybe\n\n## Findings\n')
        r = self.run_f('plan-review')
        self.assertEqual(r.returncode, 1)
        self.assertIn('no verdict line', r.stdout)

    def test_bad_arguments(self):
        self.assertEqual(run_script(SCRIPT, '--task', str(self.task), '--file', 'nope').returncode, 2)
        self.assertEqual(run_script(SCRIPT, '--file', 'review').returncode, 2)


if __name__ == '__main__':
    unittest.main()
