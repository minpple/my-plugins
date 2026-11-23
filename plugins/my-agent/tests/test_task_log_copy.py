"""task-log-copy.py: the task folder of a task worktree is copied back to the main checkout."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import L4, run_script

SCRIPT = L4 / 'scripts' / 'task-log-copy.py'


def git(cwd, *args):
    subprocess.run(['git', '-C', str(cwd), '-c', 'user.email=t@t', '-c', 'user.name=t', *args],
                   check=True, capture_output=True)


class TaskLogCopyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.main = Path(self.tmp.name).resolve() / 'proj'
        self.main.mkdir()
        git(self.main, 'init', '-q')
        (self.main / 'a.txt').write_text('a', encoding='utf-8')
        git(self.main, 'add', 'a.txt')
        git(self.main, 'commit', '-q', '-m', 'init')
        self.wt = self.main / '.claude' / 'worktrees' / 'task-t1'
        git(self.main, 'worktree', 'add', '-q', '-b', 'my-agent-task/t1', str(self.wt))
        self.task = self.wt / '.my-agent' / 't1'
        (self.task / 'work').mkdir(parents=True)
        (self.task / 'intake.md').write_text('Status: done\n', encoding='utf-8')
        (self.task / 'work' / 'n.md').write_text('note', encoding='utf-8')
        (self.wt / '.my-agent' / '.gitignore').write_text('*\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def run_copy(self, location=None, task=None):
        return run_script(SCRIPT, '--location', str(location or self.wt), '--task', str(task or self.task))

    def test_copies_the_task_folder_and_the_gitignore(self):
        r = self.run_copy()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        target = self.main / '.my-agent' / 't1'
        self.assertEqual((target / 'work' / 'n.md').read_text(encoding='utf-8'), 'note')
        self.assertEqual((self.main / '.my-agent' / '.gitignore').read_text(encoding='utf-8'), '*\n')
        self.assertIn(f'copied {self.task} to {target} (also .gitignore)', r.stdout)
        self.assertTrue((self.task / 'intake.md').exists())

    def test_keeps_an_existing_gitignore(self):
        (self.main / '.my-agent').mkdir()
        (self.main / '.my-agent' / '.gitignore').write_text('# my-agent: commit\n', encoding='utf-8')
        r = self.run_copy()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn('also .gitignore', r.stdout)
        self.assertEqual((self.main / '.my-agent' / '.gitignore').read_text(encoding='utf-8'), '# my-agent: commit\n')

    def test_never_overwrites(self):
        self.run_copy()
        r = self.run_copy()
        self.assertEqual(r.returncode, 1)
        self.assertIn('exists already', r.stdout)

    def test_main_checkout_is_nothing_to_do(self):
        (self.main / '.my-agent' / 't2').mkdir(parents=True)
        r = self.run_copy(self.main, self.main / '.my-agent' / 't2')
        self.assertEqual(r.returncode, 0)
        self.assertIn('nothing to do (not a linked worktree)', r.stdout)

    def test_other_branch_is_nothing_to_do(self):
        other = self.main / '.claude' / 'worktrees' / 'agent-x'
        git(self.main, 'worktree', 'add', '-q', '-b', 'other', str(other))
        (other / '.my-agent' / 't3').mkdir(parents=True)
        r = self.run_copy(other, other / '.my-agent' / 't3')
        self.assertEqual(r.returncode, 0)
        self.assertIn('branch is not my-agent-task/*', r.stdout)
        self.assertFalse((self.main / '.my-agent').exists())

    def test_task_outside_location_is_refused(self):
        r = self.run_copy(task=self.main / 'a.txt')
        self.assertEqual(r.returncode, 1)
        self.assertIn('not copied', r.stdout)

    def test_not_a_git_tree(self):
        d = Path(self.tmp.name) / 'plain'
        (d / '.my-agent' / 't4').mkdir(parents=True)
        r = self.run_copy(d, d / '.my-agent' / 't4')
        self.assertEqual(r.returncode, 0)
        self.assertIn('not a git work tree', r.stdout)

    def pipe_in_task(self):
        os.mkfifo(self.task / 'pipe')

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'needs named pipes')
    def test_failed_copy_leaves_nothing(self):
        self.pipe_in_task()
        r = self.run_copy()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith('task-log-copy: not copied'), r.stdout)
        self.assertNotIn('cleanup incomplete', r.stdout)
        self.assertFalse((self.main / '.my-agent' / 't1').exists())
        self.assertFalse((self.main / '.my-agent' / '.gitignore').exists())
        self.assertFalse((self.main / '.my-agent').exists())

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'needs named pipes')
    def test_failed_copy_keeps_an_existing_gitignore(self):
        self.pipe_in_task()
        (self.main / '.my-agent').mkdir()
        (self.main / '.my-agent' / '.gitignore').write_text('# my-agent: commit\n', encoding='utf-8')
        r = self.run_copy()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual((self.main / '.my-agent' / '.gitignore').read_text(encoding='utf-8'), '# my-agent: commit\n')
        self.assertFalse((self.main / '.my-agent' / 't1').exists())

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'needs named pipes')
    def test_failed_copy_keeps_an_existing_folder(self):
        self.pipe_in_task()
        (self.main / '.my-agent').mkdir()
        r = self.run_copy()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertFalse((self.main / '.my-agent' / '.gitignore').exists())
        self.assertFalse((self.main / '.my-agent' / 't1').exists())
        self.assertTrue((self.main / '.my-agent').is_dir())

    def test_links_are_copied_as_links(self):
        (self.task / 'link-rel').symlink_to('../../a.txt')
        (self.task / 'link-abs').symlink_to(self.main / 'a.txt')
        r = self.run_copy()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        target = self.main / '.my-agent' / 't1'
        for name in ('link-rel', 'link-abs'):
            self.assertTrue((target / name).is_symlink(), name)
            self.assertEqual(os.readlink(target / name), os.readlink(self.task / name))

    def test_bad_arguments_exit_2(self):
        self.assertEqual(run_script(SCRIPT).returncode, 2)
        self.assertEqual(run_script(SCRIPT, '--location', str(self.wt)).returncode, 2)


if __name__ == '__main__':
    unittest.main()
