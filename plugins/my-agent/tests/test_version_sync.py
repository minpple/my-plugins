"""The plugin versions in the manifests and the README plugin tables agree (CLAUDE.md, Version)."""
import json
import re
import unittest

from helpers import REPO

ROOT = REPO.parent.parent


def manifest_version(path):
    return json.loads(path.read_text(encoding='utf-8'))['version']


def readme_version(name, readme):
    text = (ROOT / readme).read_text(encoding='utf-8')
    rows = re.findall(r'^\| `%s` \| ([^ |]+) \|' % re.escape(name), text, re.M)
    assert len(rows) == 1, (readme, name, rows)
    return rows[0]


class VersionSyncTest(unittest.TestCase):
    def test_my_agent_manifests_and_readme_rows_match(self):
        claude = manifest_version(REPO / '.claude-plugin' / 'plugin.json')
        self.assertEqual(manifest_version(REPO / '.codex-plugin' / 'plugin.json'), claude)
        self.assertEqual(manifest_version(REPO / '.antigravity-plugin' / 'plugin.json'), claude)
        self.assertEqual(readme_version('my-agent', 'README.md'), claude)
        self.assertEqual(readme_version('my-agent', 'README-ko.md'), claude)

    def test_my_agent_tray_manifest_and_readme_rows_match(self):
        tray = manifest_version(ROOT / 'plugins' / 'my-agent-tray' / '.claude-plugin' / 'plugin.json')
        self.assertEqual(readme_version('my-agent-tray', 'README.md'), tray)
        self.assertEqual(readme_version('my-agent-tray', 'README-ko.md'), tray)

    def test_every_version_place_shows_0_37_0(self):
        for path in (REPO / '.claude-plugin' / 'plugin.json', REPO / '.codex-plugin' / 'plugin.json',
                     REPO / '.antigravity-plugin' / 'plugin.json'):
            self.assertEqual(manifest_version(path), '0.37.0', path)
        self.assertEqual(readme_version('my-agent', 'README.md'), '0.37.0')
        self.assertEqual(readme_version('my-agent', 'README-ko.md'), '0.37.0')

    def test_maintenance_notes_record_0_37_0(self):
        notes = (REPO / 'maintenance-notes.md').read_text(encoding='utf-8')
        start = '- 2026-11-27 (ARCH v0.86, plugin 0.37.0'
        for heading, words in (('L1 orchestration', ('check-commands.py', 'Judges together', 'work-branch',
                                                     'findings list table', 'hosts.md')),
                               ('L2 design', ('verifier.md', 'reviewer.md', 'checks.md')),
                               ('L4 tools · guards', ('check-commands.py', 'ma_checks.py', 'Checks:', 'verdict-fresh-check.py')),
                               ('Monitor', ('4A', '4B', 'overlap'))):
            section = notes.split('\n## %s' % heading, 1)[1].split('\n## ', 1)[0]
            found = [line for line in section.splitlines() if line.startswith(start)]
            self.assertTrue(any(all(w in line for w in words) for line in found), (heading, words))

    def test_maintenance_notes_record_size_limit_15000(self):
        notes = (REPO / 'maintenance-notes.md').read_text(encoding='utf-8')
        section = notes.split('\n## L1 orchestration', 1)[1].split('\n## ', 1)[0]
        lines = [line for line in section.splitlines() if line.startswith('- 2026-11-27 (ARCH v0.86, plugin 0.37.0')]
        self.assertTrue(any('raised from 12,700 to 15,000' in line and 'Reason:' in line for line in lines))
        self.assertTrue(any('SKILL.md limit is also raised from 12,700 to 15,000' in line for line in lines))
        self.assertTrue(any('about 6,465 tokens on Codex' in line for line in lines))
        self.assertFalse(any('6,466' in line for line in lines))

    def test_maintenance_notes_work_branch_arguments(self):
        notes = (REPO / 'maintenance-notes.md').read_text(encoding='utf-8')
        section = notes.split('\n## L1 orchestration', 1)[1].split('\n## ', 1)[0]
        lines = [line for line in section.splitlines() if line.startswith('- 2026-11-27 (ARCH v0.86, plugin 0.37.0')]
        self.assertTrue(any('`intake.py work-branch --loc <location> --slug <slug>`' in line
                            and '`--task-id <id>`' in line for line in lines))
        self.assertFalse(any('work-branch --task-id' in line for line in lines))

    def test_maintenance_notes_record_0_36_0(self):
        notes = (REPO / 'maintenance-notes.md').read_text(encoding='utf-8')
        start = '- 2026-11-27 (ARCH v0.85, plugin 0.36.0'
        for heading, words in (('L1 orchestration', ('unit-copies.md',)), ('L2 design', ('unit copies',)),
                               ('L3 workers', ('Worktree:',)),
                               ('L4 tools · guards', ('worktree.py', 'cd-guard.py', 'fail-closed'))):
            section = notes.split('\n## %s' % heading, 1)[1].split('\n## ', 1)[0]
            found = [line for line in section.splitlines() if line.startswith(start)]
            self.assertTrue(any(all(w in line for w in words) for line in found), (heading, words))

    def test_maintenance_notes_record_0_35_0(self):
        notes = (REPO / 'maintenance-notes.md').read_text(encoding='utf-8')

        def entries(heading):
            section = notes.split('\n## %s' % heading, 1)[1].split('\n## ', 1)[0]
            start = '- 2026-11-26 (ARCH v0.84, plugin 0.35.0'
            return [line for line in section.splitlines() if line.startswith(start)]

        for heading, words in (('L1 orchestration', ('define.md', 'new-task.md', 'reason in one line', 'facts reruns',
                                                     '/my-agent continue', '; skipped <target>')),
                               ('L4 tools · guards', ('cd-guard', 'taken over', '--candidate', 'CODEX_HOME',
                                                      '~<unknown user>', 'is_within'))):
            found = entries(heading)
            self.assertTrue(any(all(w in line for w in words) for line in found), (heading, words, len(found)))
        # since the Codex cache folder was added, Codex is not covered by the plugin-root rule alone
        self.assertFalse([line for line in entries('L4 tools · guards') if 'plugin-root rule only' in line])


if __name__ == '__main__':
    unittest.main()
