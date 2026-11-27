"""check-commands.py and ma_checks.py: the check script, its record and logs, the fingerprint (architecture Q47)."""
import contextlib
import hashlib
import importlib.util
import io
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import L4, run_script

import ma_checks
import ma_schema

SCRIPT = L4 / 'scripts' / 'check-commands.py'
FIXTURES = Path(__file__).resolve().parent / 'judge-fixtures'
TASK = '261127-probe-task'

OK_A = 'python3 -c "print(\'a\')"'
OK_B = 'python3 -c "print(\'b\')"'
OK_C = 'python3 -c "print(\'c\')"'


def git(root, *args):
    subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True)


def plan_text(units, coder=True):
    """units: [(id, [check command, ...])]; a command given as ('nested', text) goes in a nested bullet."""
    out = ['# Plan: probe', '', '## Work units', '']
    for uid, cmds in units:
        out += [f'### {uid} Name', '', f'- Agent: `my-agent:{"coder" if coder else "writer"}`',
                '- Files to change: `a.py`', '- Change: x']
        flat = [c for c in cmds if isinstance(c, str)]
        out.append('- Check commands: ' + ', '.join(f'`{c}` (criterion 1)' for c in flat) if flat else '- Check commands:')
        out += [f'  - `{c[1]}` (criterion 1)' for c in cmds if not isinstance(c, str)]
        out += ['- Parallel group: group 1', '- Completion criteria: 1', '- Status: done', '']
    return '\n'.join(out + ['## Approval', '', '- Approved 2026-11-27 09:00 G1-B', ''])


def load_script():
    spec = importlib.util.spec_from_file_location('check_commands_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'proj'
        self.root.mkdir()
        git(self.root, 'init', '-q')
        git(self.root, 'config', 'user.email', 't@example.com')
        git(self.root, 'config', 'user.name', 't')
        (self.root / 'base.txt').write_text('base\n', encoding='utf-8')
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-q', '-m', 'base')
        self.task = self.root / '.my-agent' / TASK
        self.task.mkdir(parents=True)

    def setup_task(self, units, explore=None, profile='dev', scope=None, coder=True, location=None):
        location = location or self.root
        (self.task / 'intake.md').write_text(f'Status: active\nLocation: {location}\nProfile: {profile}\nTask: {TASK}\n',
                                             encoding='utf-8')
        (self.task / 'plan.md').write_text(plan_text(units, coder), encoding='utf-8')
        if explore is not None:
            (self.task / 'explore.md').write_text('# Explore\n\n## Check commands\n' + '\n'.join(explore) + '\n',
                                                  encoding='utf-8')
        if scope is not None:
            (self.task / 'scope.md').write_text('# Scope\n\n## Environment\n' + '\n'.join(scope) + '\n', encoding='utf-8')

    def run_cc(self, *extra):
        return run_script(SCRIPT, '--task', str(self.task), *extra)

    def record(self):
        return ma_checks.parse_record((self.task / ma_schema.CHECKS).read_text(encoding='utf-8'))

    def record_text(self):
        return (self.task / ma_schema.CHECKS).read_text(encoding='utf-8')


class CheckCommandsTest(Base):
    def test_unit_commands_before_explore_in_plan_order(self):
        self.setup_task([('u1', [OK_A]), ('u2', [OK_B, ('nested', OK_C)])], explore=[f'- `{OK_B}`: pass (1 s)',
                                                                                    '- `python3 -c "print(\'d\')"`: pass'])
        res = self.run_cc()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(res.stdout.splitlines()[0],
                         f'check-commands: 4 run, 0 failed, 0 not run (Environment); record: {self.task}/checks.md')
        rec = self.record()
        self.assertEqual([l['command'] for l in rec['lines']],
                         [OK_A, OK_B, OK_C, 'python3 -c "print(\'d\')"'])
        self.assertEqual([l['source'] for l in rec['lines']], ['u1', 'explore, u2', 'u2', 'explore'])
        self.assertEqual([l['n'] for l in rec['lines']], ['01', '02', '03', '04'])
        self.assertEqual(rec['result'], '4 run, 0 failed, 0 not run')
        text = self.record_text()
        self.assertRegex(text.splitlines()[1], r'^Fingerprint: head=[0-9a-f]{40} files=[0-9a-f]{12} paths=0$')
        self.assertRegex(text.splitlines()[2], r'^Taken: \d{4}-\d\d-\d\d \d\d:\d\d:\d\d$')
        self.assertIn(f'- 01 `{OK_A}` (u1) → exit 0 | a | ', text)
        self.assertIn('| checks/01.log', text)
        self.assertIn('\n## Fingerprint paths\n', text)
        log = (self.task / 'checks' / '01.log').read_text(encoding='utf-8').splitlines()
        self.assertEqual(log[0], f'$ {OK_A}')
        self.assertEqual(log[1], f'cwd: {self.root}')
        self.assertRegex(log[2], r'^time limit: \d+ s$')
        self.assertEqual(log[3], 'a')
        self.assertRegex(log[-1], r'^exit 0 after \d+ s$')

    def test_failing_command_exits_1_and_names_unit_and_log(self):
        bad = 'python3 -c "import sys; print(\'boom\'); sys.exit(3)"'
        self.setup_task([('u1', [OK_A]), ('u2', [bad])])
        res = self.run_cc()
        self.assertEqual(res.returncode, 1, res.stdout)
        lines = res.stdout.splitlines()
        self.assertEqual(lines[0], f'check-commands: 2 run, 1 failed, 0 not run (Environment); record: {self.task}/checks.md')
        self.assertEqual(lines[1], f'failed: {bad} (u2) exit 3: boom; log: {self.task}/checks/02.log')
        rec = self.record()
        self.assertEqual((rec['lines'][1]['kind'], rec['lines'][1]['code']), ('exit', 3))
        self.assertIn(f'- 02 `{bad}` (u2) → exit 3 | boom | ', self.record_text())
        self.assertRegex((self.task / 'checks' / '02.log').read_text(encoding='utf-8').splitlines()[-1],
                         r'^exit 3 after \d+ s$')

    def test_summaries(self):
        ut_ok = 'python3 -c "import sys; sys.stderr.write(\'Ran 3 tests in 0.001s\\n\\nOK\\n\')"'
        ut_bad = 'python3 -c "import sys; sys.stderr.write(\'F\\nRan 1 test in 0.002s\\n\\nFAILED (failures=1)\\n\'); sys.exit(1)"'
        other = 'python3 -c "print(\'first\'); print(\'last line\'); print()"'
        silent = 'python3 -c "pass"'
        long = 'python3 -c "print(\'x\' * 300)"'
        self.setup_task([('u1', [ut_ok, ut_bad, other, silent, long])])
        self.run_cc()
        got = [l['summary'] for l in self.record()['lines']]
        self.assertEqual(got, ['Ran 3 tests in 0.001s, OK', 'Ran 1 test in 0.002s, FAILED (failures=1)', 'last line',
                               '(no output)', 'x' * 200])

    def test_fixture_records_parse(self):
        for name, ok in (('checks-stale', True), ('checks-log-mismatch', True)):
            rec = ma_checks.parse_record((FIXTURES / name / 'checks.md').read_text(encoding='utf-8'))
            self.assertIsNotNone(rec, name)
            self.assertEqual(len(rec['lines']), 1, name)
            line = rec['lines'][0]
            self.assertEqual((line['n'], line['kind'], line['code'], line['source'], line['log']),
                             ('01', 'exit', 0, 'explore, u1', 'checks/01.log'), name)
            self.assertIn(", OK", line['summary'])
            self.assertEqual(rec['head'], '4f2b9c0d7e1a3b5c6d8e9f0a1b2c3d4e5f6a7b8c')
        self.assertIsNone(ma_checks.parse_record('# nothing\n'))
        self.assertIsNone(ma_checks.parse_record(''))

    def test_same_command_in_explore_and_plan_runs_once(self):
        self.setup_task([('u4', [OK_A])], explore=[f'- `{OK_A}`: pass (1 s)'])
        res = self.run_cc()
        self.assertEqual(res.returncode, 0, res.stdout)
        rec = self.record()
        self.assertEqual(len(rec['lines']), 1)
        self.assertEqual(rec['lines'][0]['source'], 'explore, u4')
        self.assertIn(f'`{OK_A}` (explore, u4) →', self.record_text())

    def test_environment_not_run_replaced_and_fails_before(self):
        scope = [f'- Environment: `{OK_A}` — not run here (needs the network)',
                 f'- Environment: {OK_B} — replaced by `{OK_C}`',
                 '- Environment: `python3 -c "print(\'d\')"` — fails before the task (test_x, test_y)']
        self.setup_task([('u1', [OK_A, OK_B, 'python3 -c "print(\'d\')"'])], scope=scope)
        res = self.run_cc()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertEqual(res.stdout.splitlines()[0], f'check-commands: 2 run, 0 failed, 1 not run (Environment); record: {self.task}/checks.md')
        rec = self.record()
        first, second, third = rec['lines']
        self.assertEqual((first['kind'], first['reason'], first['command']), ('not run', 'needs the network', OK_A))
        self.assertIn(f'- 01 `{OK_A}` (u1) → not run (scope: Environment: needs the network)\n', self.record_text())
        self.assertFalse((self.task / 'checks' / '01.log').exists())
        self.assertEqual((second['command'], second['source']), (OK_C, f'u1; replaces `{OK_B}`'))
        self.assertEqual(second['summary'], 'c')
        self.assertEqual(third['source'], 'u1; fails before the task: test_x, test_y')
        self.assertEqual(third['summary'], 'd')
        self.assertEqual(rec['result'], '2 run, 0 failed, 1 not run')

    def test_environment_is_read_from_plan_when_there_is_no_scope(self):
        self.setup_task([('u1', [OK_A, OK_B, OK_C])])
        plan = self.task / 'plan.md'
        plan.write_text(plan.read_text(encoding='utf-8') +
                        f'\n- Environment: `{OK_A}` — not run here (no docker)\n'
                        f'- Environment: `{OK_B}` — replaced by `python3 -c "print(\'r\')"`\n'
                        f'- Environment: `{OK_C}` — fails before the task (test_z)\n', encoding='utf-8')
        res = self.run_cc()
        self.assertEqual(res.returncode, 0, res.stdout)
        first, second, third = self.record()['lines']
        self.assertEqual(first['reason'], 'no docker')
        self.assertEqual((second['command'], second['source']), ('python3 -c "print(\'r\')"', f'u1; replaces `{OK_B}`'))
        self.assertEqual(third['source'], 'u1; fails before the task: test_z')

    def test_environment_lines_with_the_persons_choice_mark(self):
        scope = [f"- Environment: `{OK_A}` — not run here (no docker) (the person's choice)",
                 f"- Environment: `{OK_B}` — replaced by `{OK_C}` (the person's choice)"]
        self.setup_task([('u1', [OK_A, OK_B])], scope=scope)
        self.assertEqual(self.run_cc().returncode, 0)
        first, second = self.record()['lines']
        self.assertEqual((first['kind'], first['reason']), ('not run', 'no docker'))
        self.assertEqual((second['command'], second['summary']), (OK_C, 'c'))

    def test_timeout_is_killed_and_counts_as_failed(self):
        slow = 'python3 -c "import time; time.sleep(30)"'
        self.setup_task([('u1', [slow])], explore=[f'- `{slow}`: pass (0.2 s)'])
        mod = load_script()
        old = ma_checks.MIN_LIMIT
        ma_checks.MIN_LIMIT = 1
        self.addCleanup(setattr, ma_checks, 'MIN_LIMIT', old)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mod.main(['--task', str(self.task)])
        self.assertEqual(code, 1, out.getvalue())
        line = self.record()['lines'][0]
        self.assertEqual((line['kind'], line['code'], line['limit']), ('timeout', None, 1))
        self.assertIn('→ timeout after 1 s |', self.record_text())
        self.assertIn('timeout after 1 s: ', out.getvalue().splitlines()[1])
        self.assertEqual((self.task / 'checks' / '01.log').read_text(encoding='utf-8').splitlines()[-1], 'timeout after 1 s')

    def test_time_limits(self):
        explore = ['- `cmd a`: pass (10 s)', '- `cmd b`: pass (100 s)', '- `cmd c`: pass (5 s)', '- `cmd z`: pass']
        durations = ma_checks.explore_commands('## Check commands\n' + '\n'.join(explore) + '\n')
        self.assertEqual(ma_checks.time_limit('cmd b', durations), 200)
        self.assertEqual(ma_checks.time_limit('cmd a', durations), 60)      # 20 s lifted to the floor
        self.assertEqual(ma_checks.time_limit('cmd other', durations), 200)  # twice the longest
        self.assertEqual(ma_checks.time_limit('cmd z', durations), 200)      # a line without a duration: another command
        self.assertEqual(ma_checks.time_limit('cmd x', []), 600)
        self.assertEqual(ma_checks.time_limit('cmd x', [('cmd z', None)]), 600)
        entries = ma_checks.command_list(plan_text([('u1', ['cmd b', 'cmd new'])]),
                                         '## Check commands\n' + '\n'.join(explore) + '\n', '')
        self.assertEqual([(e['command'], e['limit']) for e in entries],
                         [('cmd b', 200), ('cmd new', 200), ('cmd a', 60), ('cmd c', 60), ('cmd z', 200)])

    def test_no_check_commands_prints_line_and_removes_old_record(self):
        for profile, coder, units in (('research', True, [('u1', [OK_A])]), ('general', False, [('u1', [OK_A])]),
                                      ('dev', True, [('u1', [])])):
            self.setup_task(units, profile=profile, coder=coder)
            (self.task / ma_schema.CHECKS).write_text('old\n', encoding='utf-8')
            (self.task / ma_schema.CHECKS_LOGS).mkdir(exist_ok=True)
            (self.task / ma_schema.CHECKS_LOGS / '01.log').write_text('old\n', encoding='utf-8')
            res = self.run_cc()
            self.assertEqual(res.returncode, 0, (profile, res.stdout, res.stderr))
            self.assertEqual(res.stdout.strip(), 'check-commands: no check commands; no record', profile)
            self.assertFalse((self.task / ma_schema.CHECKS).exists(), profile)
            self.assertFalse((self.task / ma_schema.CHECKS_LOGS).exists(), profile)

    def test_general_profile_with_a_coder_unit_runs(self):
        loc = Path(self.tmp.name) / 'plain'
        loc.mkdir()
        self.setup_task([('u1', [OK_A])], profile='general', location=loc)
        res = self.run_cc()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertEqual(len(self.record()['lines']), 1)

    def test_unreadable_inputs_exit_3_without_a_record(self):
        self.setup_task([('u1', [OK_A])])
        (self.task / 'plan.md').unlink()
        (self.task / ma_schema.CHECKS).write_text('old\n', encoding='utf-8')
        res = self.run_cc()
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertRegex(res.stdout.strip(), r'^check-commands: not run: .+; no record$')
        self.assertFalse((self.task / ma_schema.CHECKS).exists())
        (self.task / 'intake.md').unlink()
        self.assertEqual(self.run_cc().returncode, 3)

    def test_record_that_cannot_be_written_exits_3(self):
        self.setup_task([('u1', [OK_A])])
        (self.task / '.checks.md.tmp').mkdir()   # the record is written through this temporary file
        res = self.run_cc()
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertRegex(res.stdout.strip(), r'^check-commands: not run: .+; no record$')
        self.assertFalse((self.task / ma_schema.CHECKS).exists())

    def test_bad_arguments_exit_2(self):
        self.assertEqual(run_script(SCRIPT).returncode, 2)

    def test_unexpected_error_exits_3_without_a_record(self):
        """Any other exception ends in the one `not run` line and exit 3, not a traceback and exit 1."""
        self.setup_task([('u1', [OK_A])])
        mod = load_script()

        def boom(*args, **kwargs):
            raise ValueError('boom')

        for target, name in ((mod.ma_checks, 'commands_for'), (mod, 'run_command')):
            with self.subTest(name=name):
                (self.task / ma_schema.CHECKS).write_text('old\n', encoding='utf-8')
                old = getattr(target, name)
                setattr(target, name, boom)
                try:
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        code = mod.main(['--task', str(self.task)])
                finally:
                    setattr(target, name, old)
                self.assertEqual(code, 3, out.getvalue())
                self.assertEqual(out.getvalue().strip(),
                                 'check-commands: not run: unexpected error: ValueError: boom; no record')
                self.assertFalse((self.task / ma_schema.CHECKS).exists())
                self.assertFalse((self.task / ma_schema.CHECKS_LOGS).exists())
                self.assertFalse((self.task / '.checks.md.tmp').exists())

    # --- fingerprint ---

    def test_fingerprint_lists_untracked_folder_files_rename_and_deleted(self):
        (self.root / 'old.txt').write_text('old\n', encoding='utf-8')
        (self.root / 'gone.txt').write_text('gone\n', encoding='utf-8')
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-q', '-m', 'more')
        git(self.root, 'mv', 'old.txt', 'new.txt')
        (self.root / 'gone.txt').unlink()
        (self.root / 'dir' / 'sub').mkdir(parents=True)
        (self.root / 'dir' / 'a.txt').write_text('a\n', encoding='utf-8')
        (self.root / 'dir' / 'sub' / 'b.txt').write_text('b\n', encoding='utf-8')
        fp = ma_checks.fingerprint(self.root, self.task)
        self.assertEqual(sorted(fp['paths']), ['dir/a.txt', 'dir/sub/b.txt', 'gone.txt', 'new.txt', 'old.txt'])
        self.assertEqual(fp['paths']['gone.txt'], 'deleted')
        self.assertEqual(fp['paths']['old.txt'], 'deleted')
        self.assertEqual(fp['paths']['dir/a.txt'], hashlib.sha1(b'a\n').hexdigest()[:12])
        lines = ''.join(f'{p}\t{fp["paths"][p]}\n' for p in sorted(fp['paths']))
        self.assertEqual(fp['files'], hashlib.sha1(lines.encode()).hexdigest()[:12])
        self.assertRegex(fp['head'], r'^[0-9a-f]{40}$')

    def test_fingerprint_leaves_out_the_task_folder_ignored_or_not_and_ignored_files(self):
        (self.root / 'x.txt').write_text('x\n', encoding='utf-8')
        (self.task / 'notes.md').write_text('n\n', encoding='utf-8')
        before = ma_checks.fingerprint(self.root, self.task)   # the task folder is untracked, not ignored
        self.assertEqual(sorted(before['paths']), ['x.txt'])
        (self.task / 'later.md').write_text('l\n', encoding='utf-8')
        (self.task / 'checks').mkdir()
        (self.task / 'checks' / '01.log').write_text('log\n', encoding='utf-8')
        self.assertEqual(ma_checks.fingerprint(self.root, self.task), before)
        (self.root / '.gitignore').write_text('.my-agent/\n*.cache\n', encoding='utf-8')
        (self.root / 'a.cache').write_text('c\n', encoding='utf-8')
        after = ma_checks.fingerprint(self.root, self.task)
        self.assertEqual(sorted(after['paths']), ['.gitignore', 'x.txt'])   # ignored file and ignored folder: not in it
        (self.task / 'more.md').write_text('m\n', encoding='utf-8')
        self.assertEqual(ma_checks.fingerprint(self.root, self.task), after)

    def test_fingerprint_hash_is_the_maps_hash(self):
        f = self.root / 'f.txt'
        f.write_bytes(b'hello\n')
        self.assertEqual(ma_checks.file_fp(f), hashlib.sha1(b'hello\n').hexdigest()[:12])
        self.assertEqual(ma_checks.file_fp(self.root / 'nope.txt'), 'deleted')
        spec = importlib.util.spec_from_file_location('cf_under_test', L4 / 'scripts' / 'changed-files.py')
        cf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cf)
        self.assertIs(cf.file_fp, ma_checks.file_fp)

    def test_outside_git_has_no_fingerprint(self):
        loc = Path(self.tmp.name) / 'plain'
        loc.mkdir()
        self.assertIsNone(ma_checks.fingerprint(loc, self.task))
        self.setup_task([('u1', [OK_A])], profile='general', location=loc)
        res = self.run_cc()
        self.assertEqual(res.returncode, 0, res.stdout)
        text = self.record_text()
        self.assertEqual(text.splitlines()[1], 'Fingerprint: none (not a git location)')
        self.assertNotIn('## Fingerprint paths', text)

    def test_a_run_that_changes_the_tree_leaves_no_fingerprint(self):
        touch = 'python3 -c "open(\'made.txt\', \'w\').write(\'x\')"'
        self.setup_task([('u1', [touch])])
        res = self.run_cc()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn('tree changed by the run: 1 paths (made.txt)', res.stdout.splitlines())
        text = self.record_text()
        self.assertEqual(text.splitlines()[1], 'Fingerprint: none (tree changed by the run: 1 paths)')
        self.assertNotIn('## Fingerprint paths', text)

    def test_a_second_fingerprint_that_cannot_be_taken_says_so(self):
        self.setup_task([('u1', [OK_A])])
        mod = load_script()
        real, calls = mod.ma_checks.fingerprint, []

        def first_only(location, records_folder):
            calls.append(location)
            return real(location, records_folder) if len(calls) == 1 else None

        mod.ma_checks.fingerprint = first_only
        self.addCleanup(setattr, mod.ma_checks, 'fingerprint', real)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mod.main(['--task', str(self.task)])
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(len(calls), 2)
        text = self.record_text()
        self.assertEqual(text.splitlines()[1], 'Fingerprint: none (git status failed after the run)')
        self.assertNotIn('## Fingerprint paths', text)
        self.assertNotIn('tree changed', out.getvalue())
        self.assertEqual(ma_checks.status(self.task, self.root, 'dev', (self.task / 'plan.md').read_text(encoding='utf-8')),
                         'no fingerprint')

    def test_a_run_that_writes_only_into_the_task_folder_changes_nothing(self):
        write = f'python3 -c "open(\'{self.task}/out.txt\', \'w\').write(\'x\')"'
        self.setup_task([('u1', [write])])
        res = self.run_cc()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertNotIn('tree changed', res.stdout)
        self.assertRegex(self.record_text().splitlines()[1], r'^Fingerprint: head=')

    def test_record_is_current_right_after_the_run(self):
        self.setup_task([('u1', [OK_A])])
        (self.root / 'wip.txt').write_text('w\n', encoding='utf-8')
        self.run_cc()
        rec = self.record()
        now = ma_checks.fingerprint(self.root, self.task)
        self.assertEqual((rec['head'], rec['files'], rec['count']), (now['head'], now['files'], 1))
        self.assertEqual(rec['paths'], now['paths'])


# --- docs-only rounds (architecture Q48) ---

UT = 'python3 -m unittest discover -s tests'
UT_HALF = "python3 -m unittest discover -s tests -p 'test_[a-m]*.py'"
LINT = 'python3 -c "print(\'lint ok\')"'
BAD = 'python3 -c "import sys; sys.exit(1)"'
TEST_GUIDE = '''import unittest
from pathlib import Path


class Guide(unittest.TestCase):
    def test_guide(self):
        guide = Path(__file__).resolve().parents[1] / 'docs' / 'guide.md'
        self.assertTrue(not guide.exists() or 'add' in guide.read_text())
'''
TEST_CALC = '''import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import calc


class Calc(unittest.TestCase):
    def test_add(self):
        self.assertEqual(calc.add(1, 2), 3)

    def test_notes(self):
        notes = Path(__file__).resolve().parents[1] / 'docs' / 'calc-notes.md'
        self.assertTrue(notes.read_text())
'''


class DocsRoundBase(Base):
    def setUp(self):
        super().setUp()
        self.put('.gitignore', '__pycache__/\n')
        self.put('calc.py', 'def add(a, b):\n    return a + b\n')
        self.put('docs/guide.md', 'add adds\n')
        self.put('docs/calc-notes.md', 'notes\n')
        self.put('tests/test_guide.py', TEST_GUIDE)
        self.put('tests/test_calc.py', TEST_CALC)
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-q', '-m', 'project')
        self.setup_task([('u1', [UT, LINT])])

    def put(self, rel, body):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')

    def kept(self):
        folder = self.task / ma_schema.CHECKS_LOGS / ma_schema.CHECKS_KEPT
        return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []

    def first(self, res):
        return res.stdout.splitlines()[0]

    def full_run(self, code=0):
        res = self.run_cc()
        self.assertEqual(res.returncode, code, res.stdout + res.stderr)
        self.assertNotIn('docs-only', res.stdout)
        return res

    def assert_full(self, res, n=2, failed=0):
        self.assertEqual(self.first(res), f'check-commands: {n} run, {failed} failed, 0 not run (Environment); '
                                          f'record: {self.task}/checks.md', res.stdout)
        self.assertNotIn('docs-only', res.stdout)
        self.assertEqual(self.kept(), [])
        self.assertNotIn('carried', self.record()['result'])


class DocsRoundTest(DocsRoundBase):
    def test_first_run_is_full_in_the_old_format(self):
        res = self.full_run()
        self.assert_full(res)
        self.assertEqual(self.record()['result'], '2 run, 0 failed, 0 not run')

    def test_document_change_narrows_the_unittest_command(self):
        self.full_run()
        base = self.record()
        base_id = ma_checks.record_id(base)
        self.put('docs/guide.md', 'add adds two numbers\n')
        res = self.run_cc()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        lines = res.stdout.splitlines()
        self.assertEqual(lines[0], 'check-commands: docs-only round: 2 run (1 narrowed), 0 carried, 0 failed, '
                                   f'0 not run (Environment); record: {self.task}/checks.md')
        self.assertEqual(lines[1], 'docs-only: 1 paths (docs/guide.md); test files: test_guide.py')
        rec = self.record()
        self.assertEqual(rec['result'], '2 run, 0 failed, 0 not run, 0 carried')
        first, second = rec['lines']
        self.assertEqual((first['kind'], first['files'], first['ref'], first['log'], first['command']),
                         ('narrowed', ['test_guide.py'], f'{base_id}/01', 'checks/01.log', UT))
        self.assertEqual((second['kind'], second['command']), ('exit', LINT))
        self.assertIn(f'`{UT}` (u1) → narrowed to test_guide.py: exit 0 | Ran 1 test in ', self.record_text())
        self.assertIn(f'; rest carried from {base_id}/01', self.record_text())
        kept = self.task / 'checks' / 'kept' / base_id
        self.assertEqual(kept.name, self.kept()[0])
        self.assertEqual((kept / 'checks.md').read_text(encoding='utf-8').splitlines()[:2],
                         [f'# Check record: {TASK}', f'Fingerprint: head={base["head"]} files={base["files"]} paths=0'])
        self.assertTrue((kept / '01.log').is_file() and (kept / '02.log').is_file())
        log = (self.task / 'checks' / '01.log').read_text(encoding='utf-8').splitlines()
        self.assertEqual(log[0], '$ python3 -m unittest discover -s tests -p test_guide.py')
        self.assertRegex(log[-1], r'^exit 0 after \d+ s$')

    def test_document_no_test_reads_is_carried(self):
        self.full_run()
        base_id = ma_checks.record_id(self.record())
        self.put('docs/unread.md', 'nobody reads this\n')
        res = self.run_cc()
        self.assertEqual(res.returncode, 0, res.stdout)
        lines = res.stdout.splitlines()
        self.assertEqual(lines[0], 'check-commands: docs-only round: 1 run (0 narrowed), 1 carried, 0 failed, '
                                   f'0 not run (Environment); record: {self.task}/checks.md')
        self.assertEqual(lines[1], 'docs-only: 1 paths (docs/unread.md); test files: none')
        rec = self.record()
        self.assertEqual(rec['result'], '1 run, 0 failed, 0 not run, 1 carried')
        first, second = rec['lines']
        self.assertEqual((first['kind'], first['ref'], first['log']),
                         ('carried', f'{base_id}/01', f'checks/kept/{base_id}/01.log'))
        self.assertEqual(second['kind'], 'exit')
        self.assertFalse((self.task / 'checks' / '01.log').exists())
        self.assertTrue((self.task / 'checks' / 'kept' / base_id / '01.log').is_file())
        self.assertIn(f'→ carried from {base_id}/01: exit 0 | Ran ', self.record_text())

    def test_failed_or_fingerprintless_base_and_no_record_run_in_full(self):
        self.setup_task([('u1', [UT, BAD])])
        res = self.full_run(1)
        self.put('docs/guide.md', 'add changed\n')
        self.assert_full(self.full_run(1), failed=1)     # the base failed
        self.setup_task([('u1', [UT, LINT])])
        self.assert_full(self.full_run())
        text = self.record_text()
        none = text.split('\n## Fingerprint paths')[0].splitlines()
        none[1] = 'Fingerprint: none (not a git location)'
        (self.task / 'checks.md').write_text('\n'.join(none) + '\n', encoding='utf-8')
        self.put('docs/guide.md', 'add changed again\n')
        self.assert_full(self.full_run())

    def test_a_document_and_another_file_changed_runs_in_full(self):
        self.full_run()
        self.put('docs/guide.md', 'add changed\n')
        self.put('calc.py', 'def add(a, b):\n    return b + a\n')
        self.assert_full(self.full_run())

    def test_path_under_a_tests_folder_is_not_a_document(self):
        self.full_run()
        self.put('tests/docs/x.md', 'x\n')
        self.assert_full(self.full_run())

    def test_commit_after_the_record_runs_in_full(self):
        self.full_run()
        self.put('docs/guide.md', 'add committed\n')
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-q', '-m', 'docs')
        self.assert_full(self.full_run())

    def test_outside_git_runs_in_full(self):
        plain = Path(self.tmp.name) / 'plain'
        plain.mkdir()
        self.setup_task([('u1', [OK_A])], profile='general', location=plain)
        for _ in range(2):
            res = self.full_run()
            self.assertEqual(self.first(res), f'check-commands: 1 run, 0 failed, 0 not run (Environment); '
                                              f'record: {self.task}/checks.md')
        self.assertEqual(self.record_text().splitlines()[1], 'Fingerprint: none (not a git location)')

    def test_command_missing_from_the_base_runs_in_full_and_not_run_stays(self):
        nr = 'python3 -c "print(\'nr\')"'
        new = "python3 -m unittest discover -s tests -p 'test_guide.py'"
        scope = [f'- Environment: `{nr}` — not run here (no docker)']
        self.setup_task([('u1', [UT, LINT, nr])], scope=scope)
        self.full_run()
        self.setup_task([('u1', [UT, LINT, nr, new])], scope=scope)
        self.put('docs/guide.md', 'add changed\n')
        res = self.run_cc()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertEqual(self.first(res), 'check-commands: docs-only round: 3 run (1 narrowed), 0 carried, 0 failed, '
                                          f'1 not run (Environment); record: {self.task}/checks.md')
        kinds = [(l['kind'], l['command']) for l in self.record()['lines']]
        self.assertEqual(kinds, [('narrowed', UT), ('exit', LINT), ('not run', nr), ('exit', new)])

    def test_consecutive_rounds_chain_and_unreached_kept_folders_go(self):
        self.full_run()
        id1 = ma_checks.record_id(self.record())
        self.put('docs/guide.md', 'add round two\n')
        self.assertEqual(self.run_cc().returncode, 0)
        rec2 = self.record()
        self.put('docs/calc-notes.md', 'notes round three\n')
        stray = self.task / 'checks' / 'kept' / '260101-000000'
        stray.mkdir(parents=True)
        (stray / 'checks.md').write_text('old\n', encoding='utf-8')
        res = self.run_cc()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertEqual(res.stdout.splitlines()[1], 'docs-only: 1 paths (docs/calc-notes.md); test files: test_calc.py')
        rec3 = self.record()
        line = rec3['lines'][0]
        kept = self.kept()
        id2 = [k for k in kept if k != id1][0]
        self.assertEqual((line['kind'], line['files'], line['ref']), ('narrowed', ['test_calc.py'], f'{id2}/01'))
        self.assertFalse(stray.exists())
        self.assertEqual(sorted(ma_checks.kept_closure(self.task, rec3)), sorted([id1, id2]))
        self.assertEqual(kept, sorted([id1, id2]))
        self.assertTrue(ma_checks.passed(rec3) and ma_checks.passed(rec2))
        # a carried line takes over the reference of a carried base line
        self.put('docs/unread.md', 'u\n')
        self.assertEqual(self.run_cc().returncode, 0)
        carried = self.record()['lines'][0]
        self.assertEqual((carried['kind'], carried['ref'].split('/')[0] in self.kept()), ('carried', True))
        self.put('docs/unread2.md', 'u\n')
        self.assertEqual(self.run_cc().returncode, 0)
        again = self.record()['lines'][0]
        self.assertEqual((again['kind'], again['ref'], again['log']), ('carried', carried['ref'], carried['log']))

    def test_same_test_file_under_two_commands_narrows_both(self):
        self.setup_task([('u1', [UT_HALF, UT])])
        self.full_run()
        self.put('docs/guide.md', 'add changed\n')
        res = self.run_cc()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertEqual(self.first(res), 'check-commands: docs-only round: 2 run (2 narrowed), 0 carried, 0 failed, '
                                          f'0 not run (Environment); record: {self.task}/checks.md')
        self.assertEqual([l['files'] for l in self.record()['lines']], [['test_guide.py'], ['test_guide.py']])

    def test_deleted_document_finds_its_readers(self):
        self.full_run()
        (self.root / 'docs' / 'guide.md').unlink()
        res = self.run_cc()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertEqual(res.stdout.splitlines()[1], 'docs-only: 1 paths (docs/guide.md); test files: test_guide.py')

    def test_renamed_document_finds_its_readers(self):
        self.full_run()
        git(self.root, 'mv', 'docs/guide.md', 'docs/guide-new.md')
        res = self.run_cc()
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertEqual(res.stdout.splitlines()[1],
                         'docs-only: 2 paths (docs/guide-new.md, docs/guide.md); test files: test_guide.py')

    def test_failing_narrowed_command_fails_the_record_and_the_next_run_is_full(self):
        self.full_run()
        self.put('docs/guide.md', 'no word here\n')
        res = self.run_cc()
        self.assertEqual(res.returncode, 1, res.stdout)
        lines = res.stdout.splitlines()
        self.assertTrue(lines[0].startswith('check-commands: docs-only round: 2 run (1 narrowed), 0 carried, 1 failed'))
        failed = [l for l in lines if l.startswith('failed: ')]
        self.assertEqual(len(failed), 1)
        self.assertIn('python3 -m unittest discover -s tests -p test_guide.py (u1) exit 1:', failed[0])
        self.assertFalse(ma_checks.passed(self.record()))
        res = self.run_cc()
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertNotIn('docs-only', res.stdout)
        self.assertEqual(self.kept(), [])

    def test_narrowed_summary_joins_one_part_per_invocation(self):
        self.put('tests/test_guide_two.py', TEST_GUIDE.replace('Guide', 'GuideTwo'))
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-q', '-m', 'second reader')
        self.full_run()
        self.put('docs/guide.md', 'add changed\n')
        self.assertEqual(self.run_cc().returncode, 0)
        line = self.record()['lines'][0]
        self.assertEqual(line['files'], ['test_guide.py', 'test_guide_two.py'])
        parts = line['summary'].split('; ')
        self.assertEqual(len(parts), 2, line['summary'])
        log = (self.task / 'checks' / '01.log').read_text(encoding='utf-8')
        for part in parts:
            self.assertRegex(part, r'^Ran 1 test in [\d.]+s, OK$')
            self.assertIn(part.split(', OK')[0], log)
        self.assertIn(' && ', log.splitlines()[0])

    def test_summary_of_several_ran_lines(self):
        mod = load_script()
        out = 'Ran 2 tests in 0.1s\n\nOK\n.\nRan 1 test in 0.2s\n\nFAILED (failures=1)\n'
        self.assertEqual(mod.summary_of(out), 'Ran 2 tests in 0.1s, OK; Ran 1 test in 0.2s, FAILED (failures=1)')
        self.assertEqual(mod.summary_of('Ran 3 tests in 0.001s\n\nOK\n'), 'Ran 3 tests in 0.001s, OK')

    def test_kill_after_the_logs_moved_leaves_no_record_and_the_next_run_is_full(self):
        self.full_run()
        self.put('docs/guide.md', 'add changed\n')
        mod = load_script()

        def boom(*args, **kwargs):
            raise ValueError('boom')

        mod.run_command = boom
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mod.main(['--task', str(self.task)])
        self.assertEqual(code, 3, out.getvalue())
        self.assertFalse((self.task / ma_schema.CHECKS).exists())
        self.assert_full(self.full_run())

    def test_docs_round_decision_and_status_strings(self):
        plan = (self.task / 'plan.md').read_text(encoding='utf-8')
        self.assertEqual(ma_checks.docs_round(self.task, self.root, 'dev', plan)['kind'], 'full')   # no record
        self.full_run()
        self.assertEqual(ma_checks.docs_round(self.task, self.root, 'dev', plan)['status'], 'current')
        self.put('docs/guide.md', 'add changed\n')
        decision = ma_checks.docs_round(self.task, self.root, 'dev', plan)
        self.assertEqual((decision['kind'], decision['docs']), ('run due', ['docs/guide.md']))
        self.assertEqual(decision['status'], 'docs-only (run due; 1 paths differ: docs/guide.md; test files: test_guide.py)')
        self.run_cc()
        kept = self.kept()[0]
        self.assertEqual(ma_checks.status(self.task, self.root, 'dev', plan),
                         f'docs-only (checked; 1 document paths since {kept}: docs/guide.md)')

    def test_docs_round_failure_falls_back_to_documented_stale_and_says_why(self):
        plan = (self.task / 'plan.md').read_text(encoding='utf-8')
        err = io.StringIO()
        original = ma_checks._decide
        ma_checks._decide = lambda *a: (_ for _ in ()).throw(ValueError('reader finder broke'))
        try:
            with contextlib.redirect_stderr(err):
                decision = ma_checks.docs_round(self.task, self.root, 'dev', plan)
        finally:
            ma_checks._decide = original
        self.assertEqual(decision, {'kind': 'full', 'status': 'stale (0 paths differ: none)'})
        self.assertIn('ValueError: reader finder broke', err.getvalue())

    def test_docs_only_fixture_records_parse(self):
        docs_only = ma_checks.parse_record((FIXTURES / 'checks-docs-only' / 'checks.md').read_text(encoding='utf-8'))
        line = docs_only['lines'][0]
        self.assertEqual((line['kind'], line['outcome'], line['code'], line['files'], line['ref'], line['log']),
                         ('narrowed', 'exit', 0, ['check_guide.py'], '261120-100000/01', 'checks/01.log'))
        self.assertEqual(docs_only['result'], '1 run, 0 failed, 0 not run, 0 carried')
        self.assertEqual(docs_only['paths'], {'docs/guide.md': '17e725ef2188'})
        kept_dir = FIXTURES / 'checks-docs-only' / 'checks' / 'kept' / '261120-100000'
        kept = ma_checks.parse_record((kept_dir / 'checks.md').read_text(encoding='utf-8'))
        self.assertEqual((kept['lines'][0]['kind'], kept['lines'][0]['ref']), ('exit', None))
        self.assertTrue(ma_checks.passed(kept) and ma_checks.passed(docs_only))
        self.assertEqual(ma_checks.record_id(kept), '261120-100000')
        for name in ('checks-docs-and-code', 'checks-readme-only'):
            rec = ma_checks.parse_record((FIXTURES / name / 'checks.md').read_text(encoding='utf-8'))
            self.assertEqual((rec['lines'][0]['kind'], rec['lines'][0]['summary']), ('exit', 'Ran 4 tests in 0.001s, OK'))
        carried = ('# Check record: t\nFingerprint: none (not a git location)\nTaken: 2026-11-27 14:02:11\n'
                   'Result: 0 run, 0 failed, 0 not run, 1 carried\n\n'
                   '- 01 `x` (u1) → carried from 261127-140211/02: exit 0 | Ran 1 test in 0.1s, OK | 3 s | '
                   'checks/kept/261127-140211/02.log\n')
        item = ma_checks.parse_record(carried)['lines'][0]
        self.assertEqual((item['kind'], item['ref'], item['log']), ('carried', '261127-140211/02',
                                                                    'checks/kept/261127-140211/02.log'))
        self.assertIsNone(ma_checks.parse_record(carried.replace('→ carried from', '→ carried frm')))


if __name__ == '__main__':
    unittest.main()
