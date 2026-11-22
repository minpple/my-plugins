"""cd-guard.py: the `Cd(...)` deny rule that keeps a session out of the coder worktrees of a task location."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import L4, run_script

SCRIPT = L4 / 'scripts' / 'cd-guard.py'
WARNING = ' (Claude Code may warn at startup that this rule matches no tool; the rule still works)'


class CdGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.loc = Path(self.tmp.name).resolve() / 'proj'
        self.loc.mkdir()
        self.settings = self.loc / '.claude' / 'settings.local.json'
        self.rule = f'Cd(/{self.loc}/.claude/worktrees/agent-*/**)'

    def tearDown(self):
        self.tmp.cleanup()

    def run_guard(self, *args):
        return run_script(SCRIPT, *(args or ('--location', str(self.loc))))

    def deny(self):
        return json.loads(self.settings.read_text(encoding='utf-8'))['permissions']['deny']

    def test_creates_the_file_and_says_it_is_new(self):
        r = self.run_guard()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.deny(), [self.rule])
        self.assertTrue(r.stdout.startswith(f'cd-guard: added {self.rule} to {self.settings}{WARNING} (new file: '), r.stdout)
        self.assertIn('new file', r.stdout)
        self.assertTrue(self.settings.read_text(encoding='utf-8').endswith('}\n'))

    def test_added_line_names_the_harmless_warning(self):
        r = self.run_guard()
        self.assertIn('matches no tool', r.stdout)
        self.assertIn('the rule still works', r.stdout)
        r = self.run_guard()
        self.assertEqual(r.stdout.strip(), 'cd-guard: present')

    def test_second_run_changes_nothing(self):
        self.run_guard()
        before = self.settings.read_text(encoding='utf-8')
        r = self.run_guard()
        self.assertEqual((r.returncode, r.stdout.strip()), (0, 'cd-guard: present'))
        self.assertEqual(self.settings.read_text(encoding='utf-8'), before)

    def test_keeps_what_the_file_holds(self):
        self.settings.parent.mkdir()
        self.settings.write_text(json.dumps({'permissions': {'allow': ['Bash(git add *)'], 'deny': ['Read(~/.ssh/**)']},
                                             'env': {'A': '1'}}), encoding='utf-8')
        r = self.run_guard()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('new file', r.stdout)
        self.assertEqual(r.stdout.strip(), f'cd-guard: added {self.rule} to {self.settings}{WARNING}')
        data = json.loads(self.settings.read_text(encoding='utf-8'))
        self.assertEqual(data['permissions']['allow'], ['Bash(git add *)'])
        self.assertEqual(data['permissions']['deny'], ['Read(~/.ssh/**)', self.rule])
        self.assertEqual(data['env'], {'A': '1'})

    def test_file_without_permissions(self):
        self.settings.parent.mkdir()
        self.settings.write_text('{"env": {}}', encoding='utf-8')
        self.assertEqual(self.run_guard().returncode, 0)
        self.assertEqual(self.deny(), [self.rule])

    def test_unreadable_shapes_are_left_alone(self):
        self.settings.parent.mkdir()
        for text in ('{not json', '[]', '{"permissions": []}', '{"permissions": {"deny": "x"}}'):
            with self.subTest(text=text):
                self.settings.write_text(text, encoding='utf-8')
                r = self.run_guard()
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertTrue(r.stdout.startswith('cd-guard: not added: '), r.stdout)
                self.assertEqual(self.settings.read_text(encoding='utf-8'), text)

    def test_missing_location_and_rule_characters(self):
        r = self.run_guard('--location', str(self.loc / 'none'))
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stdout.startswith('cd-guard: not added: '), r.stdout)
        odd = self.loc.parent / 'a(b)'
        odd.mkdir()
        r = self.run_guard('--location', str(odd))
        self.assertEqual(r.returncode, 1)
        self.assertFalse((odd / '.claude').exists())

    def test_bad_arguments(self):
        self.assertEqual(self.run_guard('--nope').returncode, 2)

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.loc), *args], capture_output=True, text=True, timeout=30)

    def test_git_excludes_the_file_when_git_does_not_ignore_it(self):
        self.git('init', '-q')
        self.git('config', 'core.excludesFile', '/dev/null')   # the person's global ignore file must not decide
        r = self.run_guard()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.strip().endswith('; excluded from git'), r.stdout)
        self.assertIn(WARNING + ' (new file: ', r.stdout)
        exclude = (self.loc / '.git' / 'info' / 'exclude').read_text(encoding='utf-8')
        self.assertIn('.claude/settings.local.json\n', exclude)
        self.assertEqual(self.git('status', '--porcelain').stdout, '')
        self.run_guard()
        self.assertEqual((self.loc / '.git' / 'info' / 'exclude').read_text(encoding='utf-8'), exclude)

    def test_git_ignore_already_covers_the_file(self):
        self.git('init', '-q')
        self.git('config', 'core.excludesFile', '/dev/null')
        (self.loc / '.gitignore').write_text('.claude/settings.local.json\n', encoding='utf-8')
        info = self.loc / '.git' / 'info' / 'exclude'
        before = info.read_text(encoding='utf-8') if info.exists() else None
        r = self.run_guard()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('excluded from git', r.stdout)
        self.assertEqual(info.read_text(encoding='utf-8') if info.exists() else None, before)


if __name__ == '__main__':
    unittest.main()
