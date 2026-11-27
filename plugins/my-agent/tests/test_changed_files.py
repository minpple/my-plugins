"""changed-files.py: the changed-file map L1 hands to the verifier and the reviewer (accept.md step 7)."""
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from helpers import L4, run_script

import ma_schema

SCRIPT = L4 / 'scripts' / 'changed-files.py'
TASK = '261106-probe-task'

PLAN = """# Plan: 261106-probe-task

Lead.

## Work units

### u1 Parser
- Agent: my-agent:coder
- Files to change: `plugins/demo/lib/parser.py`, new `plugins/demo/tests/test_parser.py`
- Parallel group: group 1
- Completion criteria: 1, 2
- Status: done

### u2 View
- Agent: my-agent:coder
- Files to change: `web/view.html`
- Parallel group: group 1
- Completion criteria: 3
- Status: done

## Approval
"""


CHECK_SCRIPT = L4 / 'scripts' / 'check-commands.py'
ARCHIVE_SCRIPT = L4 / 'scripts' / 'archive.py'
PLAN_CHECKS = PLAN.replace('- Parallel group: group 1\n- Completion criteria: 1, 2',
                           '- Check commands: `python3 -c "print(1)"` (criterion 1)\n- Parallel group: group 1\n- Completion criteria: 1, 2')


def git(root, *args):
    subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True)


def first_line(res):
    """The map line of the two-line output (the second line is `checks: <status>`)."""
    return res.stdout.splitlines()[0]


class ChangedFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / 'proj'
        self.root.mkdir()
        git(self.root, 'init', '-q')
        git(self.root, 'config', 'user.email', 't@example.com')
        git(self.root, 'config', 'user.name', 't')
        for rel, body in (('plugins/demo/lib/parser.py', 'a = 1\n'), ('web/view.html', '<p>x</p>\n'),
                          ('plugins/demo/tests/helpers.py', 'h = 1\n'), ('README.md', 'r\n')):
            self.write(rel, body)
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-q', '-m', 'base')
        self.task = self.root / '.my-agent' / TASK
        self.task.mkdir(parents=True)
        (self.task / 'intake.md').write_text(f'Status: active\nLocation: {self.root}\nProfile: dev\nTask: {TASK}\n',
                                             encoding='utf-8')
        (self.task / 'plan.md').write_text(PLAN, encoding='utf-8')
        (self.task / 'scope.md').write_text(
            '# Scope\n\n## Completion criteria\n1. one\n2. two\n3. three\n4. four\n5. five\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, body):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')

    def run_cf(self, *extra):
        return run_script(SCRIPT, '--task', str(self.task), *extra)

    def table(self):
        text = (self.task / ma_schema.CHANGED_FILES).read_text(encoding='utf-8')
        rows, rejudge = ma_schema.changed_files_rows(text)
        return text, {r['file']: r for r in rows}, rejudge

    def test_first_run_maps_units_and_lists_unmapped(self):
        self.write('plugins/demo/lib/parser.py', 'a = 2\n')
        self.write('plugins/demo/tests/test_parser.py', 'def test(): pass\n')   # untracked, named by u1
        self.write('web/view.html', '<p>y</p>\n')
        self.write('README.md', 'r2\n')
        (self.task / 'notes.md').write_text('task record\n', encoding='utf-8')
        res = self.run_cf()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(first_line(res), 'changed-files: 4 files, 1 unmapped')
        text, rows, rejudge = self.table()
        self.assertEqual(rejudge, 'all')
        self.assertIn('Previous: none', text)
        self.assertEqual(rows['plugins/demo/lib/parser.py']['units'], 'u1')
        self.assertEqual(rows['plugins/demo/lib/parser.py']['criteria'], '1, 2')
        self.assertEqual(rows['plugins/demo/tests/test_parser.py']['units'], 'u1')
        self.assertEqual(rows['web/view.html']['criteria'], '3')
        self.assertEqual(rows['README.md']['units'], 'unmapped')
        self.assertEqual(rows['README.md']['criteria'], 'all')
        self.assertFalse(any(f.startswith('.my-agent/') for f in rows))   # the task records are left out
        self.assertRegex(rows['web/view.html']['fingerprint'], r'^[0-9a-f]{12}$')
        self.assertEqual(rows['web/view.html']['since'], '-')

    def first_then_archive(self):
        self.write('plugins/demo/lib/parser.py', 'a = 2\n')
        self.write('web/view.html', '<p>y</p>\n')
        self.assertEqual(self.run_cf().returncode, 0)
        arch = self.task / 'archive' / '261106-120000-run1'
        arch.mkdir(parents=True)
        (arch / ma_schema.CHANGED_FILES).write_text((self.task / ma_schema.CHANGED_FILES).read_text(encoding='utf-8'),
                                                     encoding='utf-8')
        (arch / 'verify.md').write_text('Verdict: FAIL\nRun: 1\n- 3. FAIL x\n', encoding='utf-8')
        return arch

    def test_previous_marks_changed_and_limits_rejudge(self):
        arch = self.first_then_archive()
        self.write('web/view.html', '<p>z</p>\n')
        res = self.run_cf('--previous', str(arch / ma_schema.CHANGED_FILES))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(first_line(res), 'changed-files: 2 files, 0 unmapped, 1 changed since Run 1')
        text, rows, rejudge = self.table()
        self.assertEqual(rejudge, '3')
        self.assertEqual(rows['web/view.html']['since'], 'changed')
        self.assertEqual(rows['plugins/demo/lib/parser.py']['since'], 'same')
        self.assertIn('(Run 1)', text)

    def test_shared_helper_change_rejudges_all(self):
        arch = self.first_then_archive()
        self.write('plugins/demo/tests/helpers.py', 'h = 2\n')
        res = self.run_cf('--previous', str(arch / ma_schema.CHANGED_FILES))
        self.assertEqual(res.returncode, 0, res.stderr)
        _text, rows, rejudge = self.table()
        self.assertEqual(rows['plugins/demo/tests/helpers.py']['units'], 'shared')
        self.assertEqual(rows['plugins/demo/tests/helpers.py']['criteria'], 'all')
        self.assertEqual(rejudge, 'all')

    def test_unmapped_change_since_previous_rejudges_all(self):
        arch = self.first_then_archive()
        self.write('README.md', 'r3\n')
        self.run_cf('--previous', str(arch / ma_schema.CHANGED_FILES))
        self.assertEqual(self.table()[2], 'all')

    def test_deleted_file(self):
        arch = self.first_then_archive()
        (self.root / 'web' / 'view.html').unlink()
        self.run_cf('--previous', str(arch / ma_schema.CHANGED_FILES))
        _text, rows, rejudge = self.table()
        self.assertEqual(rows['web/view.html']['fingerprint'], 'deleted')
        self.assertEqual(rows['web/view.html']['since'], 'changed')
        self.assertEqual(rejudge, '3')

    def test_reverted_file_counts_as_changed(self):
        """A file in the previous map that is no longer changed (reverted) is touched by the fix."""
        arch = self.first_then_archive()
        git(self.root, 'checkout', '--', 'web/view.html')
        res = self.run_cf('--previous', str(arch / ma_schema.CHANGED_FILES))
        _text, rows, rejudge = self.table()
        self.assertEqual(rows['web/view.html']['fingerprint'], 'reverted')
        self.assertEqual(rows['web/view.html']['since'], 'changed')
        self.assertEqual(rejudge, '3')
        self.assertIn('1 changed since Run 1', res.stdout)

    def test_reverted_row_is_listed_once(self):
        """The map after the one that marked a file `reverted` leaves it out, so the map does not grow with it."""
        arch = self.first_then_archive()
        git(self.root, 'checkout', '--', 'web/view.html')
        self.run_cf('--previous', str(arch / ma_schema.CHANGED_FILES))
        arch2 = self.task / 'archive' / '261106-130000-run2'
        arch2.mkdir(parents=True)
        (arch2 / ma_schema.CHANGED_FILES).write_text((self.task / ma_schema.CHANGED_FILES).read_text(encoding='utf-8'),
                                                      encoding='utf-8')
        (arch2 / 'verify.md').write_text('Verdict: FAIL\nRun: 2\n- 1. FAIL x\n', encoding='utf-8')
        res = self.run_cf('--previous', str(arch2 / ma_schema.CHANGED_FILES))
        self.assertEqual(res.returncode, 0, res.stderr)
        _text, rows, rejudge = self.table()
        self.assertNotIn('web/view.html', rows)
        self.assertEqual(rows['plugins/demo/lib/parser.py']['since'], 'same')
        self.assertEqual(rejudge, 'none')
        self.assertEqual(first_line(res), 'changed-files: 1 files, 0 unmapped, 0 changed since Run 2')

    def test_non_ascii_path_is_not_quoted(self):
        """git quotes non-ASCII paths by default (core.quotepath); the map keeps the real name and maps it."""
        (self.task / 'plan.md').write_text(PLAN.replace('`web/view.html`', '`web/보기.html`'), encoding='utf-8')
        self.write('web/보기.html', '<p>k</p>\n')
        res = self.run_cf()
        self.assertEqual(res.returncode, 0, res.stderr)
        _text, rows, _r = self.table()
        self.assertEqual(rows['web/보기.html']['units'], 'u2')
        self.assertNotEqual(rows['web/보기.html']['fingerprint'], 'deleted')

    def test_missing_plan_and_previous(self):
        (self.task / 'plan.md').unlink()
        res = self.run_cf()
        self.assertEqual(res.returncode, 1)
        self.assertIn('changed-files: ', res.stdout)
        (self.task / 'plan.md').write_text(PLAN, encoding='utf-8')
        res = self.run_cf('--previous', str(self.task / 'nope.md'))
        self.assertEqual(res.returncode, 2)

    def test_not_a_git_location_lists_work_files(self):
        """A general task: the files under work/ and deliverable/, mapped by any backticked path of a unit."""
        (self.task / 'intake.md').write_text(f'Status: active\nLocation: {self.root.parent}\nProfile: general\nTask: {TASK}\n',
                                             encoding='utf-8')
        plan = PLAN.replace('`web/view.html`', f'`.my-agent/{TASK}/work/draft.md`')
        (self.task / 'plan.md').write_text(plan, encoding='utf-8')
        (self.task / 'work').mkdir()
        (self.task / 'work' / 'draft.md').write_text('d\n', encoding='utf-8')
        res = self.run_cf()
        self.assertEqual(res.returncode, 0, res.stderr)
        _text, rows, _r = self.table()
        self.assertEqual(list(rows), ['work/draft.md'])
        self.assertEqual(rows['work/draft.md']['units'], 'u2')

    def test_general_task_lists_code_changed_in_place(self):
        """Outside the dev profile git lists nothing, so a coder unit's `Files to change` that exist are on the map."""
        (self.task / 'intake.md').write_text(f'Status: active\nLocation: {self.root}\nProfile: general\nTask: {TASK}\n',
                                             encoding='utf-8')
        (self.task / 'work').mkdir()
        (self.task / 'work' / 'draft.md').write_text('d\n', encoding='utf-8')
        res = self.run_cf()
        self.assertEqual(res.returncode, 0, res.stderr)
        _text, rows, _r = self.table()
        # the new test file of u1 does not exist yet, so it is not listed
        self.assertEqual(list(rows), ['plugins/demo/lib/parser.py', 'web/view.html', 'work/draft.md'])
        self.assertEqual((rows['plugins/demo/lib/parser.py']['units'], rows['plugins/demo/lib/parser.py']['criteria']),
                         ('u1', '1, 2'))
        self.assertEqual(rows['work/draft.md']['units'], 'unmapped')
        first = self.task / 'first.md'
        first.write_text((self.task / ma_schema.CHANGED_FILES).read_text(encoding='utf-8'), encoding='utf-8')
        self.write('web/view.html', '<p>y</p>\n')
        res = self.run_cf('--previous', str(first))
        self.assertEqual(res.returncode, 0, res.stderr)
        _text, rows, rejudge = self.table()
        self.assertEqual(rows['web/view.html']['since'], 'changed')
        self.assertEqual(rows['plugins/demo/lib/parser.py']['since'], 'same')
        self.assertEqual(rejudge, '3')

    def plan_with_files(self, files_block):
        """PLAN with u2's `Files to change` line replaced by `files_block` (its lines, nested bullets included)."""
        return PLAN.replace('- Files to change: `web/view.html`', files_block)

    def test_two_paths_on_one_files_line_map(self):
        """Control case of #84: two paths on one `Files to change` line both map to the unit."""
        (self.task / 'plan.md').write_text(self.plan_with_files('- Files to change: `README.md`, `README-ko.md`'),
                                           encoding='utf-8')
        self.write('README.md', 'r2\n')
        self.write('README-ko.md', 'k2\n')
        res = self.run_cf()
        self.assertEqual(res.returncode, 0, res.stderr)
        _text, rows, _r = self.table()
        self.assertEqual((rows['README.md']['units'], rows['README-ko.md']['units']), ('u2', 'u2'))
        self.assertEqual(first_line(res), 'changed-files: 2 files, 0 unmapped')

    def test_two_paths_in_one_nested_bullet_map(self):
        """#84: a nested bullet of `Files to change` that holds two paths maps both, not only the first."""
        block = '- Files to change:\n  - `README.md` and `README-ko.md`: same table row'
        (self.task / 'plan.md').write_text(self.plan_with_files(block), encoding='utf-8')
        self.write('README.md', 'r2\n')
        self.write('README-ko.md', 'k2\n')
        res = self.run_cf()
        self.assertEqual(res.returncode, 0, res.stderr)
        _text, rows, _r = self.table()
        self.assertEqual((rows['README.md']['units'], rows['README-ko.md']['units']), ('u2', 'u2'))
        self.assertEqual(first_line(res), 'changed-files: 2 files, 0 unmapped')

    def test_absolute_files_to_change_paths_map(self):
        """#75 candidate: a plan that writes absolute paths maps files that git lists relative to its root."""
        block = f'- Files to change: `{self.root}/web/view.html`, `{self.root}/plugins/demo/lib/parser.py`'
        (self.task / 'plan.md').write_text(self.plan_with_files(block), encoding='utf-8')
        self.write('web/view.html', '<p>y</p>\n')
        self.write('plugins/demo/lib/parser.py', 'a = 3\n')
        res = self.run_cf()
        self.assertEqual(res.returncode, 0, res.stderr)
        _text, rows, _r = self.table()
        self.assertEqual(rows['web/view.html']['units'], 'u2')
        self.assertEqual(rows['plugins/demo/lib/parser.py']['units'], 'u1, u2')   # u1 names it too, relative
        self.assertEqual(first_line(res), 'changed-files: 2 files, 0 unmapped')

    def test_location_below_git_root_maps(self):
        """#75 candidate: the task location is a folder below the git root and the plan writes paths relative to it."""
        (self.root / 'app').mkdir()
        self.write('app/src/main.js', 'm = 1\n')
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-q', '-m', 'app')
        (self.task / 'intake.md').write_text(
            f'Status: active\nLocation: {self.root}/app\nProfile: dev\nTask: {TASK}\n', encoding='utf-8')
        (self.task / 'plan.md').write_text(self.plan_with_files('- Files to change: `src/main.js`, new `src/new.js`'),
                                           encoding='utf-8')
        self.write('app/src/main.js', 'm = 2\n')
        self.write('app/src/new.js', 'n = 1\n')
        res = self.run_cf()
        self.assertEqual(res.returncode, 0, res.stderr)
        _text, rows, _r = self.table()
        self.assertEqual((rows['app/src/main.js']['units'], rows['app/src/new.js']['units']), ('u2', 'u2'))
        self.assertEqual(first_line(res), 'changed-files: 2 files, 0 unmapped')

    def test_dot_slash_paths_map(self):
        """#75 candidate: `./web/view.html` in the plan is the same file as `web/view.html` in git's list."""
        (self.task / 'plan.md').write_text(
            self.plan_with_files('- Files to change: `./web/view.html`, new `./web/new.js`'), encoding='utf-8')
        self.write('web/view.html', '<p>y</p>\n')
        self.write('web/new.js', 'n = 1\n')
        res = self.run_cf()
        self.assertEqual(res.returncode, 0, res.stderr)
        _text, rows, _r = self.table()
        self.assertEqual((rows['web/view.html']['units'], rows['web/new.js']['units']), ('u2', 'u2'))
        self.assertEqual(first_line(res), 'changed-files: 2 files, 0 unmapped')

    def test_parser_tolerates_missing_text(self):
        self.assertEqual(ma_schema.changed_files_rows(None), ([], None))
        self.assertEqual(ma_schema.changed_files_rows(''), ([], None))

    # --- findings merged into Re-judge and the `## Findings` section ---

    B4 = '- BLOCKER web/view.html:4 broken → fix [criterion 4]'
    S5 = '- SHOULD-FIX src/cli.py:30 exit code → return 2 [criterion 5]'
    SN = '- SHOULD-FIX src/util.py:8 two helpers → keep one [criterion none]'

    def rerun(self, lines, *extra, first='BLOCKER 1', verify='Verdict: PASS\nRun: 1\n', review=True, changed='web/view.html',
              leftover=False):
        """First run, archive it with a review.md of `lines` (and verify.md), change `changed`, run with --previous.
        `leftover`: the review is older than the archived changed-files.md (a copy from an earlier round)."""
        shutil.rmtree(self.task / 'archive', ignore_errors=True)   # a test may rerun several cases
        git(self.root, 'checkout', '--', '.')
        arch = self.first_then_archive()
        (arch / 'verify.md').write_text(verify, encoding='utf-8')
        if changed:
            self.write(changed, '<p>again</p>\n')
        args = ['--previous', str(arch / ma_schema.CHANGED_FILES)]
        if review:
            (arch / 'review.md').write_text(f'{first}\n\n## Findings\n' + '\n'.join(lines) + '\n', encoding='utf-8')
            if leftover:
                old = (arch / ma_schema.CHANGED_FILES).stat().st_mtime - 100
                os.utime(arch / 'review.md', (old, old))
            args += ['--review', str(arch / 'review.md')]
        self.arch = arch
        return self.run_cf(*args, *extra)

    def findings(self):
        text = (self.task / ma_schema.CHANGED_FILES).read_text(encoding='utf-8')
        return text, (text.split('## Findings\n', 1)[1].splitlines() if '## Findings' in text else None)

    def test_review_blocker_rerun_adds_its_criterion(self):
        res = self.rerun([self.B4, self.S5])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(first_line(res), 'changed-files: 2 files, 0 unmapped, 1 changed since Run 1, 1 criterion from findings')
        text, found = self.findings()
        self.assertEqual(self.table()[2], '3, 4')
        self.assertEqual(found, [self.B4])   # the SHOULD-FIX is not picked: nothing added, not copied
        self.assertEqual(ma_schema.changed_files_rows(text)[1], '3, 4')

    def test_applied_after_review_does_not_remove_a_blocker(self):
        arch_lines = [self.B4, '', '## Applied after review', '- web/view.html:4 fixed before this review']
        res = self.rerun(arch_lines)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.table()[2], '3, 4')
        self.assertEqual(self.findings()[1], [self.B4])

    def test_blocker_zero_counts_lines_not_the_first_line(self):
        res = self.rerun([], '--rework-criterion', '2: x', first='BLOCKER 0')
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.table()[2], '2, 3')
        self.assertEqual(self.findings()[1], ['- Criterion 2 (G3 Rework): x'])
        res = self.rerun([], first='BLOCKER 0')   # nothing to add
        self.assertEqual(self.table()[2], '3')
        self.assertIsNone(self.findings()[1])
        self.assertEqual(first_line(res), 'changed-files: 2 files, 0 unmapped, 1 changed since Run 1')
        self.rerun(['- BLOCKER web/view.html:4 stray → fix [criterion 3]'], '--rework-criterion', '2: x', first='BLOCKER 0')
        self.assertEqual(self.table()[2], '2, 3')

    def test_g3_rework_criterion_and_picked_should_fix(self):
        res = self.rerun([self.S5, self.SN], '--rework-criterion', '2: the message names no path',
                         '--rework-finding', 'src/cli.py:30', first='BLOCKER 0')
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.table()[2], '2, 3, 5')
        self.assertEqual(self.findings()[1], [self.S5, '- Criterion 2 (G3 Rework): the message names no path'])
        self.assertTrue(first_line(res).endswith(', 2 criteria from findings'))

    def test_rework_inputs_alone(self):
        self.rerun([self.S5], '--rework-finding', 'src/cli.py:30', first='BLOCKER 0')
        self.assertEqual((self.table()[2], self.findings()[1]), ('3, 5', [self.S5]))
        self.rerun([self.S5], '--rework-criterion', '4: short', first='BLOCKER 0')
        self.assertEqual((self.table()[2], self.findings()[1]), ('3, 4', ['- Criterion 4 (G3 Rework): short']))

    def test_criterion_none_adds_nothing(self):
        res = self.rerun(['- BLOCKER a.py:1 reuse parse() [criterion none]', self.SN], '--rework-finding', 'src/util.py:8')
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.table()[2], '3')
        self.assertIsNone(self.findings()[1])
        self.assertEqual(first_line(res), 'changed-files: 2 files, 0 unmapped, 1 changed since Run 1')

    def test_marked_blocker_keeps_rejudge_scope(self):
        marked = '- BLOCKER web/view.html:4 broken → new unit [plan] [criterion 2]'
        res = self.rerun([marked])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.table()[2], '2, 3')   # 3 from the changed file, 2 from the finding; the mark does not give all
        self.assertEqual(self.findings()[1], [marked])
        self.assertTrue(first_line(res).endswith(', 1 criterion from findings'), res.stdout)

    def test_marked_none_adds_nothing(self):
        res = self.rerun(['- BLOCKER a.py:1 reuse parse() [plan] [criterion none]'])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.table()[2], '3')
        self.assertIsNone(self.findings()[1])
        self.assertEqual(first_line(res), 'changed-files: 2 files, 0 unmapped, 1 changed since Run 1')

    def test_marked_picked_should_fix(self):
        marked = '- SHOULD-FIX src/cli.py:30 exit code → other approach [plan] [criterion 3]'
        res = self.rerun([marked, self.SN], '--rework-finding', 'src/cli.py:30', first='BLOCKER 0', changed=None)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.table()[2], '3')   # nothing changed: the 3 comes from the finding alone
        self.assertEqual(self.findings()[1], [marked])
        self.assertTrue(first_line(res).endswith(', 1 criterion from findings'), res.stdout)

    def test_missing_or_invalid_tag_gives_all_and_is_copied(self):
        for tagged in ('- BLOCKER web/view.html:4 off by one → use <=',
                       '- BLOCKER web/view.html:4 x → y [criterion 9]', '- BLOCKER web/view.html:4 x → y [criterion 0]',
                       '- BLOCKER web/view.html:4 x → y [criterion x]', '- BLOCKER web/view.html:4 x → y [criterion 2, none]'):
            res = self.rerun([tagged])
            self.assertEqual(self.table()[2], 'all', tagged)
            self.assertEqual(self.findings()[1], [tagged])
            self.assertTrue(first_line(res).endswith(', 1 finding without a valid criterion tag (Re-judge: all)'), res.stdout)
        res = self.rerun(['- SHOULD-FIX src/cli.py:30 x → y'], '--rework-finding', 'src/cli.py:30')
        self.assertEqual(self.table()[2], 'all')
        self.assertEqual(self.findings()[1], ['- SHOULD-FIX src/cli.py:30 x → y'])

    def test_several_numbers_count_once(self):
        res = self.rerun(['- BLOCKER a.py:1 x [criterion 2, 5]', '- BLOCKER b.py:2 y [criterion 5, 5]'])
        self.assertEqual(self.table()[2], '2, 3, 5')
        self.assertEqual(len(self.findings()[1]), 2)
        self.assertTrue(first_line(res).endswith(', 2 criteria from findings'))

    def test_already_all_and_changed_none(self):
        res = self.rerun([self.B4], changed='README.md')
        self.assertEqual(self.table()[2], 'all')
        self.assertEqual(self.findings()[1], [self.B4])
        self.assertTrue(first_line(res).endswith(', 1 criterion from findings'))
        self.rerun(['- BLOCKER a.py:1 x [criterion 3]'], changed=None)
        self.assertEqual(self.table()[2], '3')

    def test_a_leftover_review_next_to_a_failed_verify_is_not_read(self):
        """The sequential FAIL round: no reviewer ran, so review.md is older than the round's changed-files.md."""
        res = self.rerun([self.B4], verify='Verdict: FAIL\nRun: 1\n- 3. FAIL x\n', leftover=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.table()[2], '3')
        self.assertIsNone(self.findings()[1])
        self.assertTrue(first_line(res).endswith(', review not read (Verify FAIL in that run)'), res.stdout)

    def test_the_sequential_fail_round_archive_skips_its_review(self):
        """The same flow as below with review.md written before changed-files.md (a leftover of an earlier round),
        archived by archive.py."""
        (self.task / 'review.md').write_text(f'BLOCKER 1\n\n## Findings\n{self.B4}\n', encoding='utf-8')
        time.sleep(0.05)
        self.write('web/view.html', '<p>y</p>\n')
        self.assertEqual(self.run_cf().returncode, 0)
        time.sleep(0.05)
        (self.task / 'verify.md').write_text('Verdict: FAIL\nRun: 1\n- 3. FAIL x\n', encoding='utf-8')
        res = run_script(ARCHIVE_SCRIPT, '--task', str(self.task), '--name', 'run1', '--only', 'verify.md', 'review.md',
                         ma_schema.CHANGED_FILES)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        arch = self.task / res.stdout.strip()
        self.write('web/view.html', '<p>again</p>\n')
        res = self.run_cf('--previous', str(arch / ma_schema.CHANGED_FILES), '--review', str(arch / 'review.md'))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.table()[2], '3')
        self.assertIsNone(self.findings()[1])
        self.assertTrue(first_line(res).endswith(', review not read (Verify FAIL in that run)'), res.stdout)

    def test_a_review_of_a_failed_verify_round_is_read_when_newer_than_the_map(self):
        """Both judges ran in a round with a record: changed-files.md, then verify.md (FAIL), then review.md (BLOCKER).
        The archive is made by archive.py, as back-execute.py does (it keeps the file times)."""
        self.write('web/view.html', '<p>y</p>\n')
        self.assertEqual(self.run_cf().returncode, 0)
        time.sleep(0.05)
        (self.task / 'verify.md').write_text('Verdict: FAIL\nRun: 1\n- 3. FAIL x\n', encoding='utf-8')
        time.sleep(0.05)
        (self.task / 'review.md').write_text(f'BLOCKER 1\n\n## Findings\n{self.B4}\n', encoding='utf-8')
        res = run_script(ARCHIVE_SCRIPT, '--task', str(self.task), '--name', 'run1', '--only', 'verify.md', 'review.md',
                         ma_schema.CHANGED_FILES)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        arch = self.task / res.stdout.strip()
        self.assertGreater((arch / 'review.md').stat().st_mtime, (arch / ma_schema.CHANGED_FILES).stat().st_mtime)
        for name in ('verify.md', 'review.md'):
            (self.task / name).unlink()
        self.write('web/view.html', '<p>again</p>\n')
        res = self.run_cf('--previous', str(arch / ma_schema.CHANGED_FILES), '--review', str(arch / 'review.md'))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.table()[2], '3, 4')   # 3 from the changed file, 4 from the BLOCKER
        self.assertEqual(self.findings()[1], [self.B4])
        self.assertNotIn('review not read', res.stdout)

    def test_unreadable_sibling_verify_exits_2(self):
        arch = self.first_then_archive()
        (arch / 'review.md').write_text(f'BLOCKER 0\n\n## Findings\n{self.B4}\n', encoding='utf-8')
        (arch / 'verify.md').write_bytes(b'\xff\xfe\x00Verdict: FAIL\n')
        (self.task / ma_schema.CHANGED_FILES).write_text('old\n', encoding='utf-8')
        res = self.run_cf('--previous', str(arch / ma_schema.CHANGED_FILES), '--review', str(arch / 'review.md'))
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertTrue(res.stdout.startswith('changed-files: cannot read'), res.stdout)
        self.assertNotIn('Traceback', res.stderr)
        self.assertEqual((self.task / ma_schema.CHANGED_FILES).read_text(encoding='utf-8'), 'old\n')

    def test_no_review_no_section(self):
        self.rerun([], review=False)
        self.assertEqual((self.table()[2], self.findings()[1]), ('3', None))
        self.rerun(['- NITPICK a.py:1 long (new)'])   # a review without BLOCKER lines
        self.assertIsNone(self.findings()[1])
        (self.task / 'plan.md').write_text(PLAN, encoding='utf-8')
        self.write('web/view.html', '<p>q</p>\n')
        res = self.run_cf()   # first run
        self.assertEqual((self.table()[2], self.findings()[1]), ('all', None))
        self.assertEqual(first_line(res), 'changed-files: 2 files, 0 unmapped')

    def test_review_without_findings_section(self):
        arch = self.first_then_archive()
        (arch / 'review.md').write_text('BLOCKER 0\n', encoding='utf-8')
        self.write('web/view.html', '<p>n</p>\n')
        res = self.run_cf('--previous', str(arch / ma_schema.CHANGED_FILES), '--review', str(arch / 'review.md'))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((self.table()[2], self.findings()[1]), ('3', None))

    def test_errors_exit_2_and_write_nothing(self):
        arch = self.first_then_archive()
        (self.task / ma_schema.CHANGED_FILES).write_text('old\n', encoding='utf-8')
        (arch / 'review.md').write_text(f'BLOCKER 0\n\n## Findings\n{self.S5}\n', encoding='utf-8')
        prev, rev = str(arch / ma_schema.CHANGED_FILES), str(arch / 'review.md')
        cases = (('--review', str(arch / 'nope.md')),
                 ('--previous', prev, '--review', rev, '--rework-criterion', '9: x'),
                 ('--previous', prev, '--review', rev, '--rework-criterion', '2'),
                 ('--previous', prev, '--rework-finding', 'src/cli.py:30'),
                 ('--previous', prev, '--review', rev, '--rework-finding', 'src/cli.py:31'))
        for extra in cases:
            res = self.run_cf(*extra)
            self.assertEqual(res.returncode, 2, extra)
            self.assertTrue(res.stdout.startswith('changed-files: '), res.stdout)
            self.assertEqual((self.task / ma_schema.CHANGED_FILES).read_text(encoding='utf-8'), 'old\n', extra)
        self.assertIn(str(arch / 'nope.md'), self.run_cf('--review', str(arch / 'nope.md')).stdout)
        self.assertIn('9', self.run_cf('--previous', prev, '--rework-criterion', '9: x').stdout)

    def test_previous_findings_section_is_read_as_before_and_not_carried(self):
        arch = self.first_then_archive()
        text = (arch / ma_schema.CHANGED_FILES).read_text(encoding='utf-8')
        (arch / ma_schema.CHANGED_FILES).write_text(text + f'\n## Findings\n{self.B4}\n', encoding='utf-8')
        self.write('web/view.html', '<p>w</p>\n')
        res = self.run_cf('--previous', str(arch / ma_schema.CHANGED_FILES))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.table()[2], '3')
        self.assertIsNone(self.findings()[1])

    # --- the check record status (second output line and `Checks:` header) ---

    def checks_status(self, res=None):
        res = res or self.run_cf()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        lines = res.stdout.splitlines()
        self.assertEqual(len(lines), 2, res.stdout)
        self.assertTrue(lines[1].startswith('checks: '), res.stdout)
        text, _rows, _rejudge = self.table()
        header = text.splitlines()[4]   # right after `Re-judge:`
        self.assertEqual(header, 'Checks: ' + lines[1][len('checks: '):])
        self.assertTrue(text.splitlines()[3].startswith('Re-judge:'))
        return lines[1][len('checks: '):]

    def run_checks(self):
        res = run_script(CHECK_SCRIPT, '--task', str(self.task))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        return res

    def with_checks(self, plan=PLAN_CHECKS):
        (self.task / 'plan.md').write_text(plan, encoding='utf-8')

    def test_checks_status_current_stale_head_moved_and_missing(self):
        self.with_checks()
        self.assertEqual(self.checks_status(), 'missing')   # check commands exist, no record
        self.write('web/view.html', '<p>y</p>\n')
        self.run_checks()
        self.assertEqual(self.checks_status(), 'current')
        self.write('web/view.html', '<p>z</p>\n')
        self.assertEqual(self.checks_status(), 'stale (1 paths differ: web/view.html)')
        self.write('web/view.html', '<p>y</p>\n')
        self.write('web/other.html', '<p>o</p>\n')
        self.assertEqual(self.checks_status(), 'stale (1 paths differ: web/other.html)')
        (self.root / 'web' / 'other.html').unlink()
        self.assertEqual(self.checks_status(), 'current')
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-q', '-m', 'work')
        self.assertEqual(self.checks_status(), 'stale (HEAD moved)')
        (self.task / ma_schema.CHECKS).write_text('not a record\n', encoding='utf-8')
        self.assertEqual(self.checks_status(), 'missing')   # an unreadable record

    def test_checks_status_lists_at_most_five_paths(self):
        self.with_checks()
        self.run_checks()
        for n in range(7):
            self.write(f'many/f{n}.txt', f'{n}\n')
        status = self.checks_status()
        self.assertTrue(status.startswith('stale (7 paths differ: many/f0.txt, many/f1.txt'), status)
        self.assertEqual(status.count('many/'), 5)

    def test_checks_status_without_a_fingerprint(self):
        self.with_checks(PLAN_CHECKS.replace('print(1)', "open('made.txt', 'w').write('x')"))
        self.run_checks()   # the command creates an untracked file: the record has no fingerprint
        self.assertEqual(self.checks_status(), 'no fingerprint')
        plain = Path(self.tmp.name) / 'plain'
        plain.mkdir()
        (self.task / 'intake.md').write_text(f'Status: active\nLocation: {plain}\nProfile: general\nTask: {TASK}\n',
                                             encoding='utf-8')
        self.with_checks()
        self.run_checks()   # not a git location
        self.assertEqual(self.checks_status(), 'no fingerprint')

    def test_checks_status_not_needed_without_check_commands(self):
        self.assertEqual(self.checks_status(), 'not needed (no check commands)')
        (self.task / 'intake.md').write_text(f'Status: active\nLocation: {self.root}\nProfile: research\nTask: {TASK}\n',
                                             encoding='utf-8')
        self.with_checks()
        self.assertEqual(self.checks_status(), 'not needed (no check commands)')

    def test_checks_status_in_a_general_task_with_a_coder_unit(self):
        (self.task / 'intake.md').write_text(f'Status: active\nLocation: {self.root}\nProfile: general\nTask: {TASK}\n',
                                             encoding='utf-8')
        self.with_checks()
        self.assertEqual(self.checks_status(), 'missing')   # computed, not `not needed`
        self.run_checks()
        self.assertEqual(self.checks_status(), 'current')
        self.with_checks(PLAN_CHECKS.replace('my-agent:coder', 'my-agent:writer'))
        self.assertEqual(self.checks_status(), 'not needed (no check commands)')

    def test_checks_problem_does_not_change_the_map(self):
        self.write('web/view.html', '<p>y</p>\n')
        before = self.run_cf()
        self.with_checks()
        after = self.run_cf()
        self.assertEqual((before.returncode, after.returncode), (0, 0))
        self.assertEqual(first_line(before), first_line(after))
        self.assertEqual(self.table()[1].keys(), {'web/view.html'})


if __name__ == '__main__':
    unittest.main()
