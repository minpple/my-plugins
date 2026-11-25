"""pre-gate.py: the gate's recording and report calls in one script (cost, ask, report text, findings, pointer)."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import L4, log_lines, make_task, run_script

SCRIPT = L4 / 'scripts' / 'pre-gate.py'
REPORT = '### Overview\n\n| Item | Value |\n|---|---|\n| Task | probe |\n\n### Takeaway\n\n- Scope: one\n'
REVIEW = 'BLOCKER 0\n\n## Findings\n- SHOULD-FIX a.py:1 first\n'
JUDGED = 'READY FOR APPROVAL\n\n## Findings\n- NITPICK a.py:1 small\n'


class PreGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.task = make_task(self.root, session='s-test')
        self.status = self.root / 'statusline'
        self.status.mkdir()
        self.data = self.root / 'data'
        self.data.mkdir()
        self.env = {'MA_TASKS_DIR': str(self.root / 'none'), 'CLAUDE_CODE_SESSION_ID': 's-test',
                    'MA_CLAUDE_PROJECTS': str(self.root / 'projects'), 'MA_STATUSLINE_DIR': str(self.status)}
        self.report = self.root / 'report.md'
        self.report.write_text(REPORT, encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, text):
        (self.task / name).write_text(text, encoding='utf-8')

    def pre(self, gate='G3', *extra, report=True):
        args = ['--gate', gate, '--task', str(self.task), 'q=Final acceptance?', 'rec=Accept',
                '--data-dir', str(self.data), '--task-dir', '.my-agent']
        if report:
            args += ['--report-text', str(self.report)]
        return run_script(SCRIPT, *args, *extra, cwd=str(self.root), env=self.env)

    def statusline(self):
        (self.status / 's-test.json').write_text(json.dumps({'cost_usd': 1.5}), encoding='utf-8')

    def test_g3_cost_ask_report_findings_pointer(self):
        self.statusline()
        self.put('review.md', REVIEW)
        r = self.pre()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = log_lines(self.task)
        self.assertEqual([l.split(' ', 2)[2].split(':')[0] for l in log], ['ask', 'cost'])   # ask first: a failing ask leaves no cost line
        self.assertIn('gate=G3', log[0])
        out = r.stdout
        self.assertLess(out.index('cost:'), out.index('ask:'))
        self.assertLess(out.index('ask:'), out.index('### Overview'))
        self.assertLess(out.index('### Takeaway'), out.index('### Review findings'))
        self.assertLess(out.index('### Review findings'), out.index('| Severity | Found | Fixed | Open |'))
        self.assertLess(out.index('| Severity |'), out.index('Report: '))
        self.assertIn(REPORT, out)   # the report text as written

    def test_failing_ask_leaves_no_cost_line(self):
        spec = importlib.util.spec_from_file_location('pre_gate_mod', SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        calls = []

        def fake(script, *args):
            calls.append(args[0])
            return (1, '', 'run-log: ask failed') if args[0] == 'ask' else (0, 'cost: x', '')

        argv = ['--gate', 'G3', '--task', str(self.task), 'q=Q?', 'rec=R', '--data-dir', str(self.data),
                '--task-dir', '.my-agent']
        out = io.StringIO()
        with mock.patch.object(mod, 'run', fake), mock.patch.object(mod.ma_active, 'find_active', return_value=object()), \
                contextlib.redirect_stdout(out):
            code = mod.main(argv)
        self.assertEqual(code, 1)
        self.assertNotIn('cost', calls)
        self.assertNotIn('cost:', out.getvalue())

    def test_g1_gates_have_no_cost_line_and_their_table(self):
        self.statusline()
        for gate, name, heading, text in (('G1-A', 'scope-review.md', '### Scope Review findings',
                                           'READY FOR CONFIRMATION\n\n## Findings\n- NITPICK a.py:1 x\n'),
                                          ('G1-B', 'plan-review.md', '### Plan Review findings', JUDGED)):
            self.put(name, text)
            r = self.pre(gate, report=False)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn(heading, r.stdout)
            self.assertIn(f'findings: {name}', r.stdout)
            self.assertIn('Report: ', r.stdout)
        self.assertTrue(all('cost:' not in l for l in log_lines(self.task)))
        self.assertEqual(sum('ask:' in l for l in log_lines(self.task)), 2)

    def test_no_cost_data_goes_on(self):
        self.put('review.md', REVIEW)
        r = self.pre()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.count('no cost line'), 1)
        self.assertEqual(len(log_lines(self.task)), 1)
        self.assertIn('ask:', log_lines(self.task)[0])
        self.assertIn('Report: not opened (', r.stdout)
        self.assertIn(f'task folder: {self.task}', r.stdout)

    def test_judgment_file_without_findings(self):
        self.put('plan-review.md', 'READY FOR APPROVAL\n\n## Findings\n')
        r = self.pre('G1-B', report=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('- none', r.stdout)

    def test_missing_judgment_file_prints_one_fail_line(self):
        r = self.pre()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('findings: FAIL', r.stdout)
        self.assertNotIn('| Severity |', r.stdout)
        self.assertEqual(sum('ask:' in l for l in log_lines(self.task)), 1)
        self.assertIn('Report: ', r.stdout)

    def test_prose_refused_before_any_write(self):
        self.put('review.md', REVIEW)
        r = self.pre('G3', 'prose=1')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(log_lines(self.task), [])
        self.assertNotIn('Report:', r.stdout)

    def test_report_text_without_takeaway_exits_3(self):
        self.put('review.md', REVIEW)
        self.report.write_text(REPORT.replace('### Takeaway', '### Other'), encoding='utf-8')
        r = self.pre()
        self.assertEqual(r.returncode, 3)
        self.assertEqual(log_lines(self.task), [])
        self.assertIn('Takeaway', r.stdout + r.stderr)

    def test_missing_report_text_exits_3(self):
        self.report.unlink()
        r = self.pre()
        self.assertEqual(r.returncode, 3)
        self.assertEqual(log_lines(self.task), [])

    def test_bad_gate_exits_2(self):
        r = run_script(SCRIPT, '--gate', 'G9', '--task', str(self.task), 'q=x', 'rec=y', env=self.env)
        self.assertEqual(r.returncode, 2)

    def test_no_active_task_exits_1(self):
        other = Path(tempfile.mkdtemp()) / 'other'
        self.addCleanup(__import__('shutil').rmtree, other.parent)
        other.mkdir()
        r = run_script(SCRIPT, '--gate', 'G1-B', '--task', str(other), 'q=x', 'rec=y', '--data-dir', str(self.data),
                       env=self.env)
        self.assertEqual(r.returncode, 1)


if __name__ == '__main__':
    unittest.main()
