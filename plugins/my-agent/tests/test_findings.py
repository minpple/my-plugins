"""findings.py: per-severity Found, Fixed and Open counts and the open items of a task's judgment file."""
import os
import time
import tempfile
import unittest
from pathlib import Path

from helpers import L4, run_script

SCRIPT = L4 / 'scripts' / 'findings.py'
TABLE = '| Severity | Found | Fixed | Open |\n|---|---|---|---|\n'
V = {'scope-review.md': 'READY FOR CONFIRMATION', 'plan-review.md': 'READY FOR APPROVAL'}
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

    def test_review_criterion_tag_shows_as_marker(self):
        self.put('review.md', 'BLOCKER 0\n\n## Findings\n- SHOULD-FIX a.py:3 text → fix [criterion 2, 5]\n'
                              '- SHOULD-FIX b.py:4 other [criterion none]\n- NITPICK c.py:5 small (new)\n')
        r = self.run_f()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, 'findings: review.md (1 round)\n' + table([(0, 0, 0), (2, 0, 2), (1, 0, 1)]) +
                         'BLOCKER 0 · SHOULD-FIX 2 · NITPICK 1 (open)\n'
                         '- SHOULD-FIX a.py:3 text → fix · criterion 2, 5\n- SHOULD-FIX b.py:4 other\n- NITPICK c.py:5 small\n')
        self.assertNotIn('[criterion', r.stdout)

    def test_review_range_finding_counts_as_fixed(self):
        self.put('review.md', 'BLOCKER 0\n\n## Findings\n- SHOULD-FIX work/final.md:28-30 three lines\n'
                              '- NITPICK tests/fixtures/x/ folder\n- NITPICK general remark\n\n'
                              '## Applied after review\n- fixed (work/final.md:29)\n- fixed (tests/fixtures/x/a.json)\n')
        r = self.run_f()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, 'findings: review.md (1 round)\n' + table([(0, 0, 0), (1, 1, 0), (2, 1, 1)]) +
                         'BLOCKER 0 · SHOULD-FIX 0 · NITPICK 1 (open)\n- NITPICK general remark\n')

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
        self.assertEqual(r.stdout, 'findings: scope-review.md (1 round)\n' + table([(0, 0, 0), (2, 1, 1), (1, 0, 1)]) +
                         'BLOCKER 0 · SHOULD-FIX 1 · NITPICK 1 (open)\n- SHOULD-FIX plan.md:20 two\n- NITPICK plan.md:30 three\n')
        self.put('plan-review.md', body.format(v='READY FOR APPROVAL'))
        self.put('run-log.md', '2026-11-20 10:00:00 fix: what="Plan Review NITPICK plan.md:30 three" files=plan.md before=G1b\n')
        r = self.run_f('plan-review')
        self.assertEqual(r.stdout, 'findings: plan-review.md (1 round)\n' + table([(0, 0, 0), (2, 1, 1), (1, 1, 0)]) +
                         'BLOCKER 0 · SHOULD-FIX 1 · NITPICK 0 (open)\n- SHOULD-FIX plan.md:20 two\n')
        self.assertIn('| NITPICK | 1 | 0 | 1 |', self.run_f('scope-review').stdout)   # the run-log fix is plan-review only

    def judged(self, name, finding, decision, mark=''):
        self.put(name, f'{V[name]}\nRun: 1\n\n## Findings\n- SHOULD-FIX {finding} text{mark}\n\n## Decisions\n- SHOULD-FIX {decision} text → applied by L1\n')
        return self.run_f(name[:-3]).stdout

    def test_decision_short_path_fixes_the_finding(self):
        for name in ('scope-review.md', 'plan-review.md'):
            for dec in ('scope.md:14', 'rules/scope.md:14', '/a/rules/scope.md:14'):
                self.assertIn('| SHOULD-FIX | 1 | 1 | 0 |', self.judged(name, '/a/rules/scope.md:14', dec), (name, dec))
        for dec in ('ope.md:14', 'scope.md:15', 'plan.md:14', 'other/scope.md:14'):
            self.assertIn('| SHOULD-FIX | 1 | 0 | 1 |', self.judged('scope-review.md', '/a/rules/scope.md:14', dec), dec)

    def test_decision_exact_text_without_line_still_fixes(self):
        self.assertIn('| SHOULD-FIX | 1 | 1 | 0 |', self.judged('scope-review.md', 'general', 'general'))
        self.assertIn('| SHOULD-FIX | 1 | 0 | 1 |', self.judged('scope-review.md', '/a/scope.md', 'scope.md'))

    def test_one_short_decision_fixes_two_files(self):
        self.put('scope-review.md', 'READY FOR CONFIRMATION\nRun: 1\n\n## Findings\n- SHOULD-FIX /a/x/scope.md:14 one\n- SHOULD-FIX /a/y/scope.md:14 two\n\n'
                                    '## Decisions\n- SHOULD-FIX scope.md:14 both → applied by L1\n')
        self.assertIn('| SHOULD-FIX | 2 | 2 | 0 |', self.run_f('scope-review').stdout)

    def test_ask_person_mark_is_found_and_fixed(self):
        out = self.judged('scope-review.md', '/a/scope.md:14', 'scope.md:14', ' → ask [ask person]')
        self.assertIn('| SHOULD-FIX | 1 | 1 | 0 |', out)

    def test_old_judgment_file_with_exact_decisions_is_unchanged(self):
        self.put('plan-review.md', 'READY FOR APPROVAL\nRun: 1\n\n## Findings\n- BLOCKER plan.md:5 a\n- SHOULD-FIX plan.md:Work-units b\n'
                                   '- NITPICK plan.md:9 c\n\n## Decisions\n- BLOCKER plan.md:5 a → applied by L1\n'
                                   '- SHOULD-FIX plan.md:Work-units b → applied by L1\n- NITPICK plan.md:9 c → declined\n')
        self.assertEqual(self.run_f('plan-review').stdout, 'findings: plan-review.md (1 round)\n' + table([(1, 1, 0), (1, 1, 0), (1, 0, 1)]) +
                         'BLOCKER 0 · SHOULD-FIX 0 · NITPICK 1 (open)\n- NITPICK plan.md:9 c\n')

    def test_plan_review_rounds(self):
        """A second round counts the first: its findings are found and fixed; open is what the latest round leaves."""
        self.put('archive/261120-100000-rev0-draft/plan-review.md',
                 'REVISE\nRun: 1\n\n## Findings\n- BLOCKER plan.md:41 no unit\n- SHOULD-FIX plan.md:50 vague\n\n## Decisions\n')
        self.put('archive/261120-100500-rev0-draft/plan-review.md',   # the same run archived again: counted once
                 'REVISE\nRun: 1\n\n## Findings\n- BLOCKER plan.md:41 no unit\n- SHOULD-FIX plan.md:50 vague\n\n## Decisions\n'
                 '- BLOCKER plan.md:41 no unit → applied by architect\n')
        self.put('plan-review.md', 'READY FOR APPROVAL\nRun: 2\n\n## Findings\n- SHOULD-FIX plan.md:50 vague\n'
                                   '- NITPICK plan.md:41 wording\n- NITPICK plan.md:60 typo\n\n## Decisions\n')
        fix = '2026-11-20 10:0{m}:00 fix: what="Plan Review NITPICK plan.md:{line} x" files=plan.md before=G1b\n'
        start = '2026-11-20 10:05:00 start: agent=my-agent:plan-reviewer id=p{n}\n'
        # the fix line of round 1 names plan.md:41, where round 2 has another finding: it does not fix that one
        self.put('run-log.md', start.format(n=1) + fix.format(m=1, line=41) + start.format(n=2) + fix.format(m=7, line=60))
        r = self.run_f('plan-review')
        self.assertEqual(r.stdout, 'findings: plan-review.md (2 rounds)\n' + table([(1, 1, 0), (1, 0, 1), (2, 1, 1)]) +
                         'BLOCKER 0 · SHOULD-FIX 1 · NITPICK 1 (open)\n- SHOULD-FIX plan.md:50 vague\n- NITPICK plan.md:41 wording\n')

    def test_scope_review_rounds_and_revision_cut(self):
        self.put('archive/261120-090000-scope-run1/scope-review.md', 'REVISE\nRun: 1\n\n## Findings\n- BLOCKER scope.md:5 old revision\n')
        self.put('archive/261120-093000-rev1/scope-review.md', 'READY FOR CONFIRMATION\nRun: 2\n\n## Findings\n- NITPICK scope.md:9 old\n')
        self.put('archive/261120-100000-scope-run1/scope-review.md',
                 'REVISE\nRun: 1\n\n## Findings\n- BLOCKER scope.md:12 no measure\n- BLOCKER scope.md:14 no user\n')
        self.put('scope-review.md', 'READY FOR CONFIRMATION\nRun: 2\n\n## Findings\n- NITPICK scope.md:20 term\n\n'
                                    '## Decisions\n- NITPICK scope.md:20 term → applied by L1\n')
        r = self.run_f('scope-review')   # the rounds before the `-rev1` archive belong to the revision before
        self.assertEqual(r.stdout, 'findings: scope-review.md (2 rounds)\n' + table([(2, 2, 0), (0, 0, 0), (1, 1, 0)]) +
                         'BLOCKER 0 · SHOULD-FIX 0 · NITPICK 0 (open)\n- none\n')

    def test_review_fix_line_before_the_latest_reviewer_call(self):
        """A Review `fix` line written before the latest reviewer call fixed the round before, not a finding of this one."""
        self.put('archive/261120-101500-run1/review.md', 'BLOCKER 1\n\n## Findings\n- BLOCKER a.py:3 null\n')
        self.put('review.md', 'BLOCKER 0\n\n## Findings\n- NITPICK a.py:9 name (new)\n')
        self.put('run-log.md', STEP8 + '2026-11-20 10:10:00 fix: what="null check a.py" files=a.py\n'
                               '2026-11-20 10:20:00 start: agent=my-agent:reviewer id=r2\n')
        now = time.time() + 5
        os.utime(self.task / 'review.md', (now, now))
        r = self.run_f()
        self.assertEqual(r.stdout, 'findings: review.md (2 rounds)\n' + table([(1, 1, 0), (0, 0, 0), (1, 0, 1)]) +
                         'BLOCKER 0 · SHOULD-FIX 0 · NITPICK 1 (open)\n- NITPICK a.py:9 name\n')

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
