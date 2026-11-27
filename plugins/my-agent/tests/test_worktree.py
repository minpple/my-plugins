"""worktree.py: coder copies made from a snapshot of the task location (git and non-git), merged back with a patch."""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from helpers import L4, run_script

SCRIPT = L4 / 'scripts' / 'worktree.py'
GUARD = L4 / 'scripts' / 'cd-guard.py'
SETTINGS = '.claude/settings.local.json'


def git(cwd, *args, check=True) -> str:
    r = subprocess.run(['git', '-C', str(cwd), '-c', 'user.email=t@t', '-c', 'user.name=t', *args],
                       check=check, capture_output=True, text=True)
    return r.stdout


def load_module():
    spec = importlib.util.spec_from_file_location('worktree_under_test', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Base:
    """Shared fixture and helpers; `kind` is 'git' or 'nongit'."""
    kind = ''

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.make_location('proj')

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text, base=None):
        path = (base or self.loc) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode('utf-8') if isinstance(text, str) else text)
        return path

    def make_location(self, name, ignore='root'):
        self.loc = self.root / name
        self.loc.mkdir()
        self.task = self.loc / '.my-agent' / 't1'
        self.task.mkdir(parents=True)
        self.put('.my-agent/t1/log.md', 'log\n')
        self.put('a.txt', 'a\n')
        self.put('b.txt', 'b\n')
        self.put('lines.txt', ''.join(f'line {i}\n' for i in range(1, 51)))
        self.put('run.sh', '#!/bin/sh\n')
        if self.kind == 'git':
            git(self.loc, 'init', '-q', '-b', 'main')
            if ignore in ('root', 'root+inner'):
                self.put('.gitignore', '.my-agent/\n*.log\n')
            if ignore in ('exclude',):
                self.put('.git/info/exclude', '.my-agent/\n')
            if ignore in ('root+inner', 'inner'):
                self.put('.my-agent/.gitignore', '*\n')
            git(self.loc, 'add', '-A', '--', '.', ':(exclude).my-agent', check=False)
            git(self.loc, 'commit', '-q', '-m', 'init', '--allow-empty')

    def wt(self, unit, loc=None):
        return (loc or self.loc) / '.claude' / 'worktrees' / f'my-agent-t1-{unit}'

    def call(self, action, *units, env=None, drop=(), loc=None, task=None):
        args = [action, '--location', str(loc or self.loc), '--task', str(task or self.task)]
        for u in units:
            args += ['--unit', u]
        return run_script(SCRIPT, *args, env=env, drop=drop)

    def inproc(self, argv, **patches):
        mod = load_module()
        buf = io.StringIO()
        with contextlib.ExitStack() as stack:
            for name, value in patches.items():
                stack.enter_context(mock.patch.object(mod, name, value))
            stack.enter_context(contextlib.redirect_stdout(buf))
            code = mod.main(argv)
        return code, buf.getvalue()

    def state(self):
        return json.loads((self.task / 'unit-copies.json').read_text(encoding='utf-8'))

    def lines(self, r):
        return r.stdout.splitlines()

    def create_ok(self, *units):
        r = self.call('create', *units)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def merge_ok(self, unit):
        r = self.call('merge', unit)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def read(self, rel, base=None):
        return (base or self.loc / '.').joinpath(rel).read_bytes().decode('utf-8')

    def apply_check_exit(self, patch):
        env = dict(os.environ)
        cmd = ['git']
        if self.kind == 'nongit':
            store = self.task / 'copy-store'
            env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
            cmd += ['--git-dir', str(store), '--work-tree', str(self.loc)]
        r = subprocess.run(cmd + ['apply', '--check', str(patch)], cwd=self.loc, env=env, capture_output=True, text=True)
        return r.returncode

    def copy_files(self, unit):
        return {p.relative_to(self.wt(unit)).as_posix() for p in self.wt(unit).rglob('*')
                if p.is_file() and '.git' not in p.relative_to(self.wt(unit)).parts[:1]}


class Common(Base):
    def test_constants(self):
        mod = load_module()
        self.assertEqual((mod.MAX_BYTES, mod.MAX_FILES), (100_000_000, 20_000))

    def test_create_prints_guard_first_then_copies_and_base_and_records_state(self):
        r = self.create_ok('u1', 'u2')
        out = self.lines(r)
        self.assertTrue(out[0].startswith('cd-guard: added '), out[0])
        self.assertEqual(out[1:3], [f'worktree: u1 {self.wt("u1")}', f'worktree: u2 {self.wt("u2")}'])
        self.assertTrue(out[3].startswith('base: '))
        self.assertEqual(self.state()['running'], ['u1', 'u2'])
        self.assertEqual(self.state()['created'], ['.claude', SETTINGS, '.claude/worktrees'])
        self.assertTrue((self.wt('u1') / '.git').is_file())
        self.assertFalse((self.wt('u1') / '.my-agent').exists())
        self.assertEqual(self.read('a.txt', self.wt('u2')), 'a\n')

    def test_second_create_runs_guard_again_and_keeps_created(self):
        self.create_ok('u1')
        created = self.state()['created']
        r = self.create_ok('u2')
        self.assertEqual(self.lines(r)[0], 'cd-guard: present')
        self.assertEqual(self.state()['created'], created)
        self.assertEqual(self.state()['running'], ['u1', 'u2'])

    def test_guard_not_added_is_sequential_and_a_later_create_repeats_the_first_path(self):
        self.put('.claude/settings.local.json', '{bad')
        r = self.call('create', 'u1')
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertEqual(len(self.lines(r)), 1)
        self.assertTrue(r.stdout.startswith('sequential: session guard not added: '), r.stdout)
        self.assertFalse((self.task / 'unit-copies.json').exists())
        self.assertFalse(self.wt('u1').exists())
        self.put('.claude/settings.local.json', '{}')
        r = self.create_ok('u1')
        self.assertTrue(self.lines(r)[0].startswith('cd-guard: added '))
        self.assertTrue(self.wt('u1').exists())
        self.assertNotIn(SETTINGS, self.state()['created'])   # the file existed before

    def test_bad_arguments_change_nothing(self):
        self.assertEqual(self.call('create').returncode, 2)
        self.assertEqual(self.call('create', 'x1').returncode, 2)
        self.assertEqual(self.call('create', 'u1', 'u1').returncode, 2)
        self.assertEqual(self.call('merge', 'u1', 'u2').returncode, 2)
        self.assertFalse((self.task / 'unit-copies.json').exists())
        self.assertFalse((self.loc / '.claude').exists())

    def test_merge_moves_the_unit_changes_and_removes_the_copy(self):
        self.create_ok('u1')
        self.put('a.txt', 'a by u1\n', self.wt('u1'))
        self.put('new.txt', 'new\n', self.wt('u1'))
        r = self.merge_ok('u1')
        self.assertIn('merged u1: 2 files', r.stdout)
        self.assertIn('file: M a.txt', r.stdout)
        self.assertIn('file: A new.txt', r.stdout)
        self.assertIn(f'removed: {self.wt("u1")}', r.stdout)
        self.assertEqual(self.read('a.txt'), 'a by u1\n')
        self.assertEqual(self.read('new.txt'), 'new\n')
        self.assertFalse(self.wt('u1').exists())
        self.assertTrue((self.task / 'work' / 'u1.patch').is_file())
        self.assertEqual(self.state()['running'], [])

    def test_two_units_of_one_group_change_different_files_and_both_merge(self):
        self.create_ok('u1', 'u2')
        self.put('a.txt', 'a by u1\n', self.wt('u1'))
        self.put('b.txt', 'b by u2\n', self.wt('u2'))
        self.merge_ok('u1')
        self.merge_ok('u2')
        self.assertEqual((self.read('a.txt'), self.read('b.txt')), ('a by u1\n', 'b by u2\n'))

    def test_same_line_conflict_exits_4_keeps_the_copy_and_applies_nothing(self):
        self.create_ok('u1', 'u2')
        self.put('a.txt', 'a by u1\n', self.wt('u1'))
        self.put('a.txt', 'a by u2\n', self.wt('u2'))
        self.merge_ok('u1')
        r = self.call('merge', 'u2')
        self.assertEqual(r.returncode, 4, r.stdout)
        self.assertIn('conflict u2:', r.stdout)
        self.assertIn(f'kept: {self.wt("u2")} (not merged)', r.stdout)
        self.assertEqual(self.read('a.txt'), 'a by u1\n')
        self.assertTrue(self.wt('u2').exists())
        self.assertEqual(self.state()['running'], [])

    def test_separate_lines_of_one_file_are_still_a_conflict(self):
        self.create_ok('u1', 'u2')
        for unit, n in (('u1', 2), ('u2', 40)):
            text = self.read('lines.txt', self.wt(unit)).replace(f'line {n}\n', f'line {n} by {unit}\n')
            self.put('lines.txt', text, self.wt(unit))
        self.merge_ok('u1')
        merged = self.read('lines.txt')
        r = self.call('merge', 'u2')
        self.assertEqual(r.returncode, 4, r.stdout)
        self.assertIn('conflict u2: changed in the main tree since the copy was made: lines.txt', r.stdout)
        self.assertEqual(self.read('lines.txt'), merged)
        self.assertIn('line 40 by u2', self.read('lines.txt', self.wt('u2')))
        print(f'git apply --check (separate lines): exit {self.apply_check_exit(self.task / "work" / "u2.patch")}',
              file=sys.stderr)

    def test_added_by_both_and_exec_bit_changed_by_both_are_conflicts(self):
        self.create_ok('u1', 'u2')
        self.put('both.txt', 'one\n', self.wt('u1'))
        self.put('both.txt', 'two\n', self.wt('u2'))
        (self.wt('u1') / 'run.sh').chmod(0o755)
        (self.wt('u2') / 'run.sh').chmod(0o755)
        self.put('only2.txt', 'x\n', self.wt('u2'))
        self.merge_ok('u1')
        r = self.call('merge', 'u2')
        self.assertEqual(r.returncode, 4, r.stdout)
        self.assertIn('both.txt', r.stdout)
        self.assertIn('run.sh', r.stdout)
        self.assertEqual(self.read('both.txt'), 'one\n')
        self.assertFalse((self.loc / 'only2.txt').exists())

    def test_exec_bit_alone_conflicts(self):
        self.create_ok('u1', 'u2')
        (self.wt('u1') / 'run.sh').chmod(0o755)
        self.put('x.txt', 'x\n', self.wt('u2'))
        (self.wt('u2') / 'run.sh').chmod(0o755)
        self.merge_ok('u1')
        self.assertEqual(self.call('merge', 'u2').returncode, 4)
        self.assertFalse((self.loc / 'x.txt').exists())

    def test_eol_conversion_gives_no_false_conflict_or_difference(self):
        self.put('.gitattributes', '*.txt text eol=crlf\n')
        self.put('crlf.txt', b'one\r\ntwo\r\n')
        if self.kind == 'git':
            git(self.loc, 'add', '.gitattributes', 'crlf.txt')
            git(self.loc, 'commit', '-q', '-m', 'eol')
            (self.loc / 'crlf.txt').unlink()
            git(self.loc, 'checkout', '--', 'crlf.txt')
        self.create_ok('u1')
        self.put('crlf.txt', (self.wt('u1') / 'crlf.txt').read_bytes() + b'three\n', self.wt('u1'))
        r = self.call('merge', 'u1')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('removed:', r.stdout)
        self.assertNotIn('conflict', r.stdout)
        self.assertNotIn('differs', r.stdout)
        self.assertIn('three', (self.loc / 'crlf.txt').read_text(encoding='utf-8'))

    def test_deleted_file_is_gone_after_merge(self):
        self.create_ok('u1')
        (self.wt('u1') / 'b.txt').unlink()
        r = self.merge_ok('u1')
        self.assertIn('file: D b.txt', r.stdout)
        self.assertFalse((self.loc / 'b.txt').exists())

    def test_no_change_merges_zero_files_and_removes_the_copy(self):
        self.create_ok('u1')
        r = self.merge_ok('u1')
        self.assertIn('merged u1: 0 files', r.stdout)
        self.assertFalse(self.wt('u1').exists())
        self.assertEqual(self.state()['running'], [])

    def test_ignored_file_is_reported_and_not_merged(self):
        self.put('.gitignore', '*.log\n.my-agent/\n')
        self.create_ok('u1')
        self.put('x.log', 'noise\n', self.wt('u1'))
        self.put('a.txt', 'a by u1\n', self.wt('u1'))
        r = self.merge_ok('u1')
        self.assertIn('ignored: 1 not merged: x.log', r.stdout)
        self.assertFalse((self.loc / 'x.log').exists())
        self.assertEqual(self.read('a.txt'), 'a by u1\n')

    def test_only_ignored_change_is_reported_with_zero_files_merged(self):
        self.put('.gitignore', '*.log\n.my-agent/\n')
        self.create_ok('u1')
        self.put('x.log', 'noise\n', self.wt('u1'))
        r = self.merge_ok('u1')
        self.assertIn('merged u1: 0 files', r.stdout)
        self.assertIn('ignored: 1 not merged: x.log', r.stdout)
        self.assertFalse((self.loc / 'x.log').exists())
        self.assertFalse(self.wt('u1').exists())
        self.assertEqual(self.state()['running'], [])

    def test_conflicted_copy_is_kept_and_remove_deletes_it(self):
        self.create_ok('u1', 'u2')
        self.put('a.txt', '1\n', self.wt('u1'))
        self.put('a.txt', '2\n', self.wt('u2'))
        self.merge_ok('u1')
        self.assertEqual(self.call('merge', 'u2').returncode, 4)
        self.assertIn('(kept)', self.call('list').stdout)
        r = self.call('remove', 'u2')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn(f'removed: {self.wt("u2")}', r.stdout)
        self.assertFalse(self.wt('u2').exists())

    def test_merge_exit_1_applies_nothing_keeps_the_copy_and_drops_the_unit(self):
        self.create_ok('u1')
        self.put('a.txt', 'a by u1\n', self.wt('u1'))
        (self.task / 'work' / 'u1.patch').mkdir(parents=True)
        r = self.call('merge', 'u1')
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn(f'kept: {self.wt("u1")} (not merged)', r.stdout)
        self.assertEqual(self.read('a.txt'), 'a\n')
        self.assertTrue(self.wt('u1').exists())
        self.assertEqual(self.state()['running'], [])

    def test_merge_exit_2_for_an_unknown_unit_changes_nothing(self):
        self.create_ok('u1')
        before = (self.task / 'unit-copies.json').read_bytes()
        r = self.call('merge', 'u9')
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertEqual((self.task / 'unit-copies.json').read_bytes(), before)
        self.assertTrue(self.wt('u1').exists())

    def test_keep_drops_the_unit_and_leaves_the_copy_untouched(self):
        self.create_ok('u1', 'u2')
        self.put('a.txt', 'work in progress\n', self.wt('u1'))
        files = self.copy_files('u1')
        r = self.call('keep', 'u1')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(r.stdout.strip(), f'kept: {self.wt("u1")} (given up)')
        self.assertEqual(self.state()['running'], ['u2'])
        self.assertEqual(self.copy_files('u1'), files)
        self.assertEqual(self.read('a.txt', self.wt('u1')), 'work in progress\n')
        self.assertIn(f'worktree: u1 {self.wt("u1")} (kept)', self.call('list').stdout)
        self.assertEqual(self.call('create', 'u3').returncode, 0)
        self.assertEqual(self.call('keep', 'u7').returncode, 1)

    def test_a_failing_second_unit_removes_the_first_copy_and_keeps_running(self):
        self.put('.claude/worktrees/my-agent-t1-u2', 'in the way\n')
        r = self.call('create', 'u1', 'u2')
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertFalse(self.wt('u1').exists())
        self.assertEqual(self.state()['running'], [])
        self.assertNotIn('worktree: u1', self.call('list').stdout)
        self.assertNotIn('my-agent-t1-u1', git(self.loc, 'worktree', 'list') if self.kind == 'git' else '')

    def test_size_limits_are_sequential_and_leave_no_copy(self):
        for patches in ({'MAX_BYTES': 10}, {'MAX_FILES': 2}):
            code, out = self.inproc(['create', '--location', str(self.loc), '--task', str(self.task), '--unit', 'u1'],
                                    **patches)
            self.assertEqual(code, 3, out)
            self.assertEqual(len(out.splitlines()), 1)
            self.assertTrue(out.startswith('sequential: '), out)
            self.assertRegex(out, r'\d+ bytes in \d+ files')
            self.assertIn('ignore file', out)
            self.assertFalse(self.wt('u1').exists())
            self.assertFalse((self.task / 'copy-store').exists())
            self.assertFalse((self.task / 'unit-copies.json').exists())

    def test_records_files_do_not_count_toward_the_limit(self):
        for i in range(6):
            self.put(f'.my-agent/t1/more{i}.md', 'x\n')
        rest = len([p for p in self.loc.rglob('*') if p.is_file() and '.my-agent' not in p.parts
                    and p.relative_to(self.loc).parts[0] not in ('.git', '.claude')])
        code, out = self.inproc(['create', '--location', str(self.loc), '--task', str(self.task), '--unit', 'u1'],
                                MAX_FILES=rest + 2)
        self.assertEqual(code, 0, out)

    def test_nested_repository_is_sequential(self):
        self.put('vendor/lib.txt', 'x\n')
        subprocess.run(['git', 'init', '-q', str(self.loc / 'vendor')], check=True, capture_output=True)
        r = self.call('create', 'u1')
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertTrue(r.stdout.startswith('sequential: '), r.stdout)
        self.assertFalse(self.wt('u1').exists())

    def test_a_linked_worktree_left_under_the_copies_folder_is_not_a_nested_repository(self):
        other = self.root / 'other-repo'
        other.mkdir()
        git(other, 'init', '-q', '-b', 'main')
        self.put('o.txt', 'o\n', other)
        git(other, 'add', '.')
        git(other, 'commit', '-q', '-m', 'o')
        (self.loc / '.claude' / 'worktrees').mkdir(parents=True)
        git(other, 'worktree', 'add', '-q', '--detach', str(self.loc / '.claude' / 'worktrees' / 'other'))
        r = self.call('create', 'u1')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_no_git_program_is_sequential(self):
        r = self.call('create', 'u1', env={'PATH': str(self.root / 'nothing')})
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertEqual(r.stdout.strip(), 'sequential: no git program')
        self.assertFalse(self.wt('u1').exists())

    def test_windows_is_sequential(self):
        fake = types.SimpleNamespace(**dict(vars(os), name='nt'))
        code, out = self.inproc(['create', '--location', str(self.loc), '--task', str(self.task), '--unit', 'u1'],
                                os=fake)
        self.assertEqual(code, 3, out)
        self.assertTrue(out.startswith('sequential: ') and 'Windows' in out, out)
        self.assertFalse(self.wt('u1').exists())

    def test_list_shows_running_and_kept_copies(self):
        self.assertEqual(self.call('list').stdout.splitlines()[0], 'worktree: none')
        self.create_ok('u1', 'u2')
        self.call('keep', 'u2')
        out = self.call('list').stdout
        self.assertIn(f'worktree: u1 {self.wt("u1")} (running)', out)
        self.assertIn(f'worktree: u2 {self.wt("u2")} (kept)', out)

    def test_cleanup_runs_the_guard_removal_in_every_case(self):
        settings = self.loc / SETTINGS
        def rule_gone():
            data = json.loads(settings.read_text(encoding='utf-8'))
            return not data['permissions']['deny']
        # no state file, no copy ever made, no record: nothing to remove
        r = self.call('cleanup')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(r.stdout.startswith('cd-guard: nothing to remove'), r.stdout)
        cases = [('no git program', {'env': {'PATH': str(self.root / 'nothing')}}), ('plain', {})]
        for name, kw in cases:
            with self.subTest(name):
                self.assertEqual(run_script(GUARD, '--location', str(self.loc), '--task', str(self.task)).returncode, 0)
                r = self.call('cleanup', **kw)
                self.assertEqual(r.returncode, 0, r.stdout)
                self.assertTrue(r.stdout.startswith('cd-guard: removed '), r.stdout)
                self.assertTrue(rule_gone())
        with self.subTest('windows'):
            self.assertEqual(run_script(GUARD, '--location', str(self.loc), '--task', str(self.task)).returncode, 0)
            fake = types.SimpleNamespace(**dict(vars(os), name='nt'))
            code, out = self.inproc(['cleanup', '--location', str(self.loc), '--task', str(self.task)], os=fake)
            self.assertEqual(code, 0, out)
            self.assertTrue(out.startswith('cd-guard: '), out)
            self.assertTrue(rule_gone())
        with self.subTest('task outside the location'):
            outside = self.root / 'outside-task'
            outside.mkdir()
            self.assertEqual(run_script(GUARD, '--location', str(self.loc), '--task', str(outside)).returncode, 0)
            r = self.call('cleanup', task=outside)
            self.assertTrue(r.stdout.startswith('cd-guard: removed '), r.stdout)
            self.assertTrue(rule_gone())


class GitTest(Common, unittest.TestCase):
    kind = 'git'

    def test_records_folder_setups_all_create_and_merge_without_the_records(self):
        for i, setup in enumerate(('root', 'exclude', 'root+inner', 'inner', 'none')):
            with self.subTest(setup):
                self.make_location(f'p{i}', ignore=setup)
                self.create_ok('u1')
                self.assertFalse((self.wt('u1') / '.my-agent').exists())
                self.put('a.txt', 'a by u1\n', self.wt('u1'))
                r = self.merge_ok('u1')
                self.assertIn('merged u1: 1 files', r.stdout)
                self.assertEqual(self.read('a.txt'), 'a by u1\n')
                self.assertEqual(self.read('.my-agent/t1/log.md'), 'log\n')

    def test_tracked_records_files_stay_out_of_the_copy_and_untouched_in_the_main_tree(self):
        self.make_location('tracked', ignore='none')
        git(self.loc, 'add', '-f', '.my-agent')
        git(self.loc, 'commit', '-q', '-m', 'records')
        index = git(self.loc, 'ls-files', '-s')
        self.put('.my-agent/t1/log.md', 'changed log\n')
        self.create_ok('u1')
        self.assertFalse((self.wt('u1') / '.my-agent').exists())
        self.put('a.txt', 'a by u1\n', self.wt('u1'))
        self.merge_ok('u1')
        self.assertEqual(self.read('.my-agent/t1/log.md'), 'changed log\n')
        self.assertEqual(git(self.loc, 'ls-files', '-s'), index)
        self.assertIn('M .my-agent/t1/log.md', git(self.loc, 'status', '--porcelain').replace(' M', 'M'))

    def test_records_files_of_an_unignored_folder_do_not_count_toward_the_limit(self):
        self.make_location('unignored', ignore='none')
        git(self.loc, 'add', '-f', '.my-agent/t1/log.md')
        git(self.loc, 'commit', '-q', '-m', 'records')
        for i in range(6):
            self.put(f'.my-agent/t1/more{i}.md', 'x\n')
        # 4 files outside the records folder; with the tracked and untracked records files it would be 11
        code, out = self.inproc(['create', '--location', str(self.loc), '--task', str(self.task), '--unit', 'u1'],
                                MAX_FILES=6)
        self.assertEqual(code, 0, out)

    def test_create_merge_and_remove_change_no_ref_head_index_stash_or_history(self):
        git(self.loc, 'stash', 'list')
        def picture():
            return [git(self.loc, *a) for a in (('for-each-ref',), ('rev-parse', 'HEAD'), ('diff', '--cached'),
                                                ('stash', 'list'), ('log', '--oneline'), ('branch', '--list'))]
        self.put('staged.txt', 's\n')
        git(self.loc, 'add', 'staged.txt')
        before = picture()
        self.create_ok('u1', 'u2')
        self.put('a.txt', 'a by u1\n', self.wt('u1'))
        self.merge_ok('u1')
        self.assertEqual(self.call('remove', 'u2').returncode, 0)
        self.assertEqual(picture(), before)
        self.assertIn('A  staged.txt', git(self.loc, 'status', '--porcelain'))

    def test_a_submodule_is_sequential(self):
        sha = git(self.loc, 'rev-parse', 'HEAD').strip()
        git(self.loc, 'update-index', '--add', '--cacheinfo', f'160000,{sha},sub')
        r = self.call('create', 'u1')
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertTrue(r.stdout.startswith('sequential: '), r.stdout)

    def test_a_location_below_the_repository_top_is_sequential(self):
        sub = self.loc / 'inner'
        (sub / '.my-agent' / 't1').mkdir(parents=True)
        r = self.call('create', 'u1', loc=sub, task=sub / '.my-agent' / 't1')
        self.assertEqual(r.returncode, 3, r.stdout)

    def test_a_linked_worktree_location_gets_nested_copies_and_the_merge_lands_in_it(self):
        linked = self.root / 'linked'
        git(self.loc, 'worktree', 'add', '-q', '--detach', str(linked))
        task = linked / '.my-agent' / 't1'
        task.mkdir(parents=True)
        r = self.call('create', 'u1', loc=linked, task=task)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.wt('u1', linked).is_dir())
        self.put('a.txt', 'a by u1\n', self.wt('u1', linked))
        r = self.call('merge', 'u1', loc=linked, task=task)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read('a.txt', linked), 'a by u1\n')
        self.assertEqual(self.read('a.txt'), 'a\n')

    def test_cleanup_keeps_the_settings_file_of_a_git_location(self):
        self.create_ok('u1')
        self.merge_ok('u1')
        r = self.call('cleanup')
        self.assertTrue(r.stdout.startswith('cd-guard: removed '), r.stdout)
        self.assertTrue((self.loc / SETTINGS).is_file())
        self.assertTrue((self.loc / '.claude').is_dir())
        self.assertFalse((self.loc / '.claude' / 'worktrees').exists())   # created and empty: removed


class NonGitTest(Common, unittest.TestCase):
    kind = 'nongit'

    def assert_still_not_a_repository(self):
        self.assertFalse((self.loc / '.git').exists())
        self.assertFalse((self.loc / '.gitignore').exists() and not self._had_ignore)
        r = subprocess.run(['git', '-C', str(self.loc), 'status'], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('not a git repository', r.stderr)

    _had_ignore = False

    def test_two_copies_merge_and_the_folder_stays_a_non_repository(self):
        self.create_ok('u1', 'u2')
        self.put('a.txt', 'a by u1\n', self.wt('u1'))
        self.put('b.txt', 'b by u2\n', self.wt('u2'))
        self.merge_ok('u1')
        self.merge_ok('u2')
        self.assertEqual((self.read('a.txt'), self.read('b.txt')), ('a by u1\n', 'b by u2\n'))
        self.assert_still_not_a_repository()
        self.assertTrue((self.task / 'copy-store').is_dir())

    def test_a_later_group_starts_from_the_merged_result(self):
        self.create_ok('u1')
        self.put('a.txt', 'a by u1\n', self.wt('u1'))
        self.put('new.txt', 'new\n', self.wt('u1'))
        self.merge_ok('u1')
        self.create_ok('u2')
        self.assertEqual(self.read('a.txt', self.wt('u2')), 'a by u1\n')
        self.assertEqual(self.read('new.txt', self.wt('u2')), 'new\n')

    def test_a_gitignore_added_by_a_unit_keeps_the_folder_out_of_the_next_group(self):
        self.put('big/data.bin', 'x' * 100)
        self.create_ok('u1')
        self.assertTrue((self.wt('u1') / 'big' / 'data.bin').exists())
        self.put('.gitignore', 'big/\n', self.wt('u1'))
        self.merge_ok('u1')
        self.create_ok('u2')
        self.assertFalse((self.wt('u2') / 'big').exists())
        self.assertTrue((self.loc / 'big' / 'data.bin').exists())
        code, out = self.inproc(['create', '--location', str(self.loc), '--task', str(self.task), '--unit', 'u3'],
                                MAX_BYTES=600)
        self.assertEqual(code, 0, out)   # big/ is ignored now, so it does not count

    def test_gitignore_files_apply_and_global_excludes_do_not(self):
        self.put('.gitignore', '*.tmp\n')
        self.put('sub/.gitignore', '*.dat\n')
        for name in ('x.tmp', 'sub/y.dat', 'sub/y.tmp', 'keep.txt', 'x.glob', 'x.xdg'):
            self.put(name, 'x\n')
        glob_ignore = self.root / 'global-ignore'
        glob_ignore.write_text('*.glob\n', encoding='utf-8')
        gitconfig = self.root / 'gitconfig'
        gitconfig.write_text(f'[core]\n\texcludesFile = {glob_ignore}\n', encoding='utf-8')
        xdg = self.root / 'xdg'
        (xdg / 'git').mkdir(parents=True)
        (xdg / 'git' / 'ignore').write_text('*.xdg\n', encoding='utf-8')
        r = self.call('create', 'u1', env={'GIT_CONFIG_GLOBAL': str(gitconfig), 'XDG_CONFIG_HOME': str(xdg)})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        files = self.copy_files('u1')
        self.assertTrue({'keep.txt', 'x.glob', 'x.xdg', '.gitignore', 'sub/.gitignore'} <= files, files)
        self.assertFalse(files & {'x.tmp', 'sub/y.dat', 'sub/y.tmp'}, files)

    def test_without_any_gitignore_only_the_records_and_the_copies_folder_are_left_out(self):
        self.put('x.tmp', 'x\n')
        self.create_ok('u1')
        self.create_ok('u2')
        files = self.copy_files('u2')
        self.assertIn('x.tmp', files)
        self.assertFalse(any(f.startswith(('.my-agent', '.claude/worktrees')) for f in files), files)

    def test_cleanup_leaves_no_git_store_or_created_folders(self):
        self.create_ok('u1')
        self.merge_ok('u1')
        r = self.call('cleanup')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn(f'cleanup: store removed: {self.task / "copy-store"}', r.stdout)
        self.assertFalse((self.task / 'copy-store').exists())
        self.assertFalse((self.loc / '.claude').exists())
        self.assert_still_not_a_repository()

    def test_cleanup_keeps_a_claude_folder_that_held_another_file(self):
        self.put('.claude/other.txt', 'mine\n')
        self.create_ok('u1')
        self.assertEqual(self.state()['created'], [SETTINGS, '.claude/worktrees'])
        self.merge_ok('u1')
        self.call('cleanup')
        self.assertTrue((self.loc / '.claude' / 'other.txt').is_file())
        self.assertFalse((self.loc / SETTINGS).exists())
        self.assertFalse((self.loc / '.claude' / 'worktrees').exists())

    def test_cleanup_with_a_kept_copy_then_a_second_cleanup_finishes(self):
        self.create_ok('u1', 'u2')
        self.merge_ok('u1')
        self.call('keep', 'u2')
        r = self.call('cleanup')
        store = self.task / 'copy-store'
        self.assertIn(f'cleanup: kept copy {self.wt("u2")}', r.stdout)
        self.assertIn(f'cleanup: store kept: {store}', r.stdout)
        self.assertTrue(self.wt('u2').is_dir() and store.is_dir())
        self.assertTrue((self.loc / '.claude' / 'worktrees').is_dir())
        self.assertTrue((self.task / 'unit-copies.json').exists())
        self.assertIn('.claude/worktrees', self.state()['created'])
        self.assertEqual(self.call('remove', 'u2').returncode, 0)
        r = self.call('cleanup')
        self.assertIn(f'cleanup: store removed: {store}', r.stdout)
        self.assertFalse(store.exists())
        self.assertFalse((self.loc / '.claude').exists())
        self.assert_still_not_a_repository()

    def test_settings_file_that_existed_before_or_holds_another_entry_is_kept(self):
        for name, content in (('existed', '{"permissions": {"deny": []}}'),
                              ('other entry', '{"permissions": {"deny": ["Read(x)"]}}')):
            with self.subTest(name):
                self.make_location(f's-{name.replace(" ", "")}')
                self.put(SETTINGS, content)
                self.create_ok('u1')
                self.merge_ok('u1')
                self.call('cleanup')
                data = json.loads((self.loc / SETTINGS).read_text(encoding='utf-8'))
                self.assertEqual(data['permissions']['deny'], json.loads(content)['permissions']['deny'])
        self.make_location('s-added-other')
        self.create_ok('u1')   # the file is new, then another entry arrives
        settings = self.loc / SETTINGS
        data = json.loads(settings.read_text(encoding='utf-8'))
        data['permissions']['deny'].append('Read(y)')
        settings.write_text(json.dumps(data), encoding='utf-8')
        self.merge_ok('u1')
        self.call('cleanup')
        self.assertEqual(json.loads(settings.read_text(encoding='utf-8'))['permissions']['deny'], ['Read(y)'])

    def test_list_scans_the_copies_folder_when_the_store_is_missing(self):
        self.create_ok('u1')
        import shutil
        shutil.rmtree(self.task / 'copy-store')
        out = self.call('list').stdout
        self.assertIn(f'worktree: u1 {self.wt("u1")} (running)', out)
        self.assertNotIn('store:', out)

    def test_list_names_the_store(self):
        self.create_ok('u1')
        out = self.call('list').stdout
        self.assertIn(f'store: {self.task / "copy-store"}', out)


if __name__ == '__main__':
    unittest.main()
