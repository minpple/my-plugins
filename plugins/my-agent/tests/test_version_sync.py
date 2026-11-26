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
