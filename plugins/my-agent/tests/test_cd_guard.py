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
        self.task = Path(self.tmp.name).resolve() / 'task'
        self.task.mkdir()
        self.record = self.task / 'cd-guard.json'
        self.rule = f'Cd(/{self.loc}/.claude/worktrees/agent-*/**)'

    def tearDown(self):
        self.tmp.cleanup()

    def run_guard(self, *args):
        return run_script(SCRIPT, *(args or ('--location', str(self.loc), '--task', str(self.task))))

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
        r = self.run_guard('--location', str(self.loc / 'none'), '--task', str(self.task))
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stdout.startswith('cd-guard: not added: '), r.stdout)
        odd = self.loc.parent / 'a(b)'
        odd.mkdir()
        r = self.run_guard('--location', str(odd), '--task', str(self.task))
        self.assertEqual(r.returncode, 1)
        self.assertFalse((odd / '.claude').exists())

    def test_bad_arguments(self):
        self.assertEqual(self.run_guard('--nope').returncode, 2)
        self.assertEqual(self.run_guard('--location', str(self.loc)).returncode, 2)
        self.assertEqual(self.run_guard('--remove', '--location', str(self.loc)).returncode, 2)
        self.assertFalse(self.settings.exists())

    def remove(self):
        return self.run_guard('--remove', '--location', str(self.loc), '--task', str(self.task))

    def test_add_writes_the_record(self):
        r = self.run_guard()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(self.record.read_text(encoding='utf-8')),
                         {'file': str(self.settings), 'rule': self.rule})
        self.assertEqual(self.run_guard().stdout.strip(), 'cd-guard: present')

    def test_remove_takes_out_the_added_rule(self):
        self.run_guard()
        r = self.remove()
        self.assertEqual((r.returncode, r.stdout.strip()), (0, f'cd-guard: removed {self.rule} from {self.settings}'), r.stderr)
        self.assertEqual(self.deny(), [])
        self.assertTrue(self.record.exists())
        before = self.settings.read_bytes()
        r = self.remove()
        self.assertEqual((r.returncode, r.stdout.strip()), (0, 'cd-guard: nothing to remove (rule not in file)'))
        self.assertEqual(self.settings.read_bytes(), before)

    def test_remove_keeps_other_entries(self):
        self.settings.parent.mkdir()
        self.settings.write_text(json.dumps({'permissions': {'allow': ['Bash(git add *)'], 'deny': ['Read(~/.ssh/**)']},
                                             'env': {'A': '1'}}), encoding='utf-8')
        self.run_guard()
        self.assertEqual(self.remove().returncode, 0)
        data = json.loads(self.settings.read_text(encoding='utf-8'))
        self.assertEqual(data, {'permissions': {'allow': ['Bash(git add *)'], 'deny': ['Read(~/.ssh/**)']}, 'env': {'A': '1'}})

    def test_remove_keeps_the_persons_own_rule(self):
        self.settings.parent.mkdir()
        self.settings.write_text(json.dumps({'permissions': {'deny': [self.rule]}}), encoding='utf-8')
        r = self.run_guard()
        self.assertEqual(r.stdout.strip(), 'cd-guard: present')
        self.assertFalse(self.record.exists())
        r = self.remove()
        self.assertEqual((r.returncode, r.stdout.strip()), (0, 'cd-guard: nothing to remove (no record)'))
        self.assertEqual(self.deny(), [self.rule])

    def test_remove_when_absent(self):
        r = self.remove()   # no record, no file
        self.assertEqual((r.returncode, r.stdout.strip()), (0, 'cd-guard: nothing to remove (no record)'))
        self.assertFalse(self.settings.exists())
        self.record.write_text(json.dumps({'file': str(self.settings), 'rule': self.rule}), encoding='utf-8')
        r = self.remove()   # record, no file
        self.assertEqual((r.returncode, r.stdout.strip()), (0, 'cd-guard: nothing to remove (file absent)'))
        self.assertFalse(self.settings.exists())
        self.settings.parent.mkdir()
        self.settings.write_text('{"permissions": {"deny": ["x"]}}', encoding='utf-8')
        r = self.remove()   # record, rule not in the file
        self.assertEqual((r.returncode, r.stdout.strip()), (0, 'cd-guard: nothing to remove (rule not in file)'))
        self.assertEqual(self.settings.read_text(encoding='utf-8'), '{"permissions": {"deny": ["x"]}}')

    def test_remove_uses_the_file_the_record_stored(self):
        other = self.loc.parent / 'moved' / '.claude' / 'settings.local.json'
        other.parent.mkdir(parents=True)
        other.write_text(json.dumps({'permissions': {'deny': [self.rule, 'x']}}), encoding='utf-8')
        self.record.write_text(json.dumps({'file': str(other), 'rule': self.rule}), encoding='utf-8')
        r = self.remove()   # --location points elsewhere than the record
        self.assertEqual((r.returncode, r.stdout.strip()), (0, f'cd-guard: removed {self.rule} from {other}'), r.stderr)
        self.assertEqual(json.loads(other.read_text(encoding='utf-8'))['permissions']['deny'], ['x'])
        self.assertFalse(self.settings.exists())

    def test_remove_invalid_json_left_unchanged(self):
        self.record.write_text(json.dumps({'file': str(self.settings), 'rule': self.rule}), encoding='utf-8')
        self.settings.parent.mkdir()
        for text in ('{not json', '[]', '{"permissions": {"deny": "x"}}'):
            with self.subTest(text=text):
                self.settings.write_text(text, encoding='utf-8')
                r = self.remove()
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertEqual(len(r.stdout.strip().splitlines()), 1, r.stdout)
                self.assertTrue(r.stdout.startswith('cd-guard: not removed: '), r.stdout)
                self.assertEqual(self.settings.read_text(encoding='utf-8'), text)

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
