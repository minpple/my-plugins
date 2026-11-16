"""archive.py: copy the task folder (or named judgment files) into archive/<time>-<name>/ and compare the copy."""
import re
import tempfile
import unittest
from pathlib import Path

from helpers import L4, run_script

SCRIPT = L4 / 'scripts' / 'archive.py'
NAME = re.compile(r'^archive/\d{6}-\d{6}-[A-Za-z0-9._-]+$')


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.task = Path(self.tmp.name).resolve() / '.my-agent' / '261116-demo'
        (self.task / 'work').mkdir(parents=True)
        for name, text in (('intake.md', 'Status: active\n'), ('plan.md', '# Plan\n'), ('run-log.md', 'x\n'),
                           ('verify.md', 'Verdict: FAIL\nRun: 2\n'), ('work/note.md', 'note\n')):
            (self.task / name).write_text(text, encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def run_archive(self, *args):
        return run_script(SCRIPT, '--task', str(self.task), *args)

    def copied(self, line):
        folder = self.task / line
        return sorted(p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file())

    def test_whole_folder_without_archive(self):
        (self.task / 'archive' / '261115-000000-rev0-draft').mkdir(parents=True)
        (self.task / 'archive' / '261115-000000-rev0-draft' / 'plan.md').write_text('old\n', encoding='utf-8')
        r = self.run_archive('--name', 'rev0-draft')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = r.stdout.strip()
        self.assertEqual(len(r.stdout.splitlines()), 1)
        self.assertRegex(line, NAME)
        self.assertTrue(line.endswith('-rev0-draft'))
        self.assertEqual(self.copied(line), ['intake.md', 'plan.md', 'run-log.md', 'verify.md', 'work/note.md'])
        self.assertEqual((self.task / line / 'work' / 'note.md').read_text(encoding='utf-8'), 'note\n')
        self.assertEqual((self.task / line / 'plan.md').stat().st_mtime_ns, (self.task / 'plan.md').stat().st_mtime_ns)

    def test_only_keeps_named_files_that_exist(self):
        r = self.run_archive('--name', 'run2', '--only', 'verify.md', 'review.md', 'changed-files.md')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.copied(r.stdout.strip()), ['verify.md'])

    def test_only_with_nothing_to_copy(self):
        r = self.run_archive('--name', 'run1', '--only', 'review.md')
        self.assertEqual(r.returncode, 1)
        self.assertIn('nothing to archive', r.stdout)
        self.assertFalse((self.task / 'archive').exists())

    def test_same_second_gets_a_new_folder(self):
        first = self.run_archive('--name', 'rev1').stdout.strip()
        second = self.run_archive('--name', 'rev1').stdout.strip()
        self.assertNotEqual(first, second)
        for line in (first, second):
            self.assertTrue((self.task / line / 'plan.md').is_file(), line)

    def test_bad_arguments(self):
        for args in (('--name', '../up'), ('--name', 'a b'), ('--name', ''), ('--name', 'run1', '--only', '../x.md'),
                     ('--name', 'run1', '--only', 'archive/x.md')):
            r = self.run_archive(*args)
            self.assertEqual(r.returncode, 2, args)
        r = run_script(SCRIPT, '--task', str(self.task / 'missing'), '--name', 'rev1')
        self.assertEqual(r.returncode, 2)
        self.assertIn('no such task folder', r.stdout)
        self.assertFalse((self.task / 'archive').exists())


if __name__ == '__main__':
    unittest.main()
