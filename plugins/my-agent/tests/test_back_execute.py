"""back-execute.py: Back to Execute in one script (archive, plan statuses, .active phase, Execute step line)."""
import importlib.util
import io
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import L4, log_lines, make_task, run_script

SCRIPT = L4 / 'scripts' / 'back-execute.py'
PLAN = ('# Plan\n\n### u1 First\n- Agent: `my-agent:coder`\n- Status: done\n\n### u2 Second\n- Agent: `my-agent:coder`\n'
        '- Status: done\n\n### u3 Third\n- Agent: `my-agent:coder`\n- Status: done\n\n'
        '### u4 Docs\n- Agent: `my-agent:writer`\n- Status: done\n')


class BackExecuteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.task = make_task(self.root, phase='4', session='s-test')
        (self.task / 'intake.md').write_text('Status: active\n', encoding='utf-8')
        (self.task / 'plan.md').write_text(PLAN, encoding='utf-8')
        (self.task / 'verify.md').write_text('Verdict: FAIL\nRun: 2\n- 1. FAIL x\n', encoding='utf-8')
        (self.task / 'review.md').write_text('BLOCKER 0\n', encoding='utf-8')
        self.active = self.task.parent / '.active'
        self.env = {'MA_DATA_DIR': str(self.root / 'none'), 'CLAUDE_CODE_SESSION_ID': 's-test',
                    'MA_CLAUDE_PROJECTS': str(self.root / 'projects'), 'MA_STATUSLINE_DIR': str(self.root / 'sl')}

    def tearDown(self):
        self.tmp.cleanup()

    def args(self, *units, back='Verify FAIL 1'):
        a = ['--task', str(self.task)]
        if units:
            a += ['--units', *units]
        return a + ['--back', back, '--model', 'opus', '--data-dir', str(self.root / 'data'), '--task-dir', '.my-agent']

    def run_be(self, *units, **kw):
        return run_script(SCRIPT, *self.args(*units, **kw), cwd=str(self.root), env=self.env)

    def snapshot(self):
        return {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file() and '.git' not in p.parts}

    def statuses(self):
        text = (self.task / 'plan.md').read_text(encoding='utf-8')
        return [l.split(': ')[1] for l in text.splitlines() if l.startswith('- Status:')]

    def test_normal(self):
        r = self.run_be('u2')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        folders = list((self.task / 'archive').glob('*-run2'))
        self.assertEqual(len(folders), 1)
        self.assertEqual({p.name for p in folders[0].iterdir()}, {'verify.md', 'review.md'})
        self.assertEqual(self.statuses(), ['done', 'pending', 'done', 'pending'])   # the writer follows
        self.assertIn('phase: 3', self.active.read_text(encoding='utf-8'))
        line = log_lines(self.task)[-1]
        self.assertIn('step: n=3A name=Execute', line)
        self.assertIn('back="Verify FAIL 1"', line)
        self.assertIn(f'archive=archive/{folders[0].name}', line)
        self.assertIn(folders[0].name, r.stdout)

    def test_comment_line_in_fenced_block_does_not_cut_the_unit(self):
        plan = PLAN.replace('### u2 Second\n- Agent: `my-agent:coder`\n',
                            '### u2 Second\n```sh\n# a comment\n### not a heading\n```\n- Agent: `my-agent:coder`\n')
        (self.task / 'plan.md').write_text(plan, encoding='utf-8')
        r = self.run_be('u2')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.statuses(), ['done', 'pending', 'done', 'pending'])

    def test_last_writer_unit_follows(self):
        r = self.run_be('u1', 'u3')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.statuses(), ['pending', 'done', 'pending', 'pending'])

    def test_writer_alone_does_not_set_itself_twice(self):
        r = self.run_be('u4')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.statuses(), ['done', 'done', 'done', 'pending'])

    def refused(self, *units):
        before = self.snapshot()
        r = self.run_be(*units)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.task / 'archive').exists())
        return r

    def test_nothing_to_archive(self):
        for n in ('verify.md', 'review.md'):
            (self.task / n).unlink()
        self.refused('u2')

    def test_no_run_line(self):
        (self.task / 'verify.md').write_text('Verdict: FAIL\n', encoding='utf-8')
        self.refused('u2')

    def test_no_units(self):
        self.refused()

    def test_unit_not_in_plan(self):
        r = self.refused('u9')
        self.assertIn('u9', r.stdout + r.stderr)

    def test_plan_write_failure_after_archive(self):
        spec = importlib.util.spec_from_file_location('back_execute', SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        active, log = self.active.read_bytes(), (self.task / 'run-log.md').exists()
        out = io.StringIO()
        with mock.patch.object(mod, 'write_plan', side_effect=OSError('disk full')), \
                mock.patch.dict('os.environ', self.env), contextlib.redirect_stdout(out):
            code = mod.main(self.args('u2'))
        self.assertEqual(code, 3)
        folder = next((self.task / 'archive').iterdir()).name
        self.assertIn(f'back-execute: written: archive/{folder}; failed: plan.md: ', out.getvalue())
        self.assertEqual(self.active.read_bytes(), active)
        self.assertEqual((self.task / 'run-log.md').exists(), log)
        self.assertEqual(self.statuses(), ['done'] * 4)


if __name__ == '__main__':
    unittest.main()
