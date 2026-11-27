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


if __name__ == '__main__':
    unittest.main()
