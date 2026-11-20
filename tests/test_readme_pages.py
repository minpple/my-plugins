"""Both READMEs name the architecture page and the feature pages correctly and agree with each other."""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
READMES = [REPO / 'README.md', REPO / 'README-ko.md']
PAGES_URL = 'https://minpple.github.io/my-plugins/'


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


class ReadmePagesTest(unittest.TestCase):
    def test_architecture_page_is_named_and_linked(self):
        for path in READMES:
            text = read(path)
            self.assertIn('docs/architecture.html', text, path.name)
            self.assertIn(PAGES_URL + 'architecture.html', text, path.name)

    def test_feature_pages_have_file_list_entries(self):
        for path in READMES:
            text = read(path)
            for name in ('docs/index.html', 'docs/index-ko.html'):
                self.assertRegex(text, r'(?m)^- `%s`' % re.escape(name), '%s %s' % (path.name, name))

    def test_root_page_is_not_called_the_architecture_page(self):
        for path in READMES:
            lines = [l for l in read(path).splitlines() if 'docs/index.html' in l]
            self.assertTrue(lines, path.name)
            for line in lines:
                self.assertNotIn('architecture', line.lower(), path.name)
                self.assertNotIn('아키텍처', line, path.name)

    def test_page_paths_and_urls_match_between_the_twins(self):
        def pages(text):
            return re.findall(r'docs/[\w-]+\.html', text)

        def urls(text):
            return [u.rstrip('.,;)>') for u in re.findall(r'https://minpple\.github\.io/[^\s>)`]*', text)]

        en, ko = read(READMES[0]), read(READMES[1])
        self.assertEqual(pages(en), pages(ko))
        self.assertEqual(urls(en), urls(ko))
        self.assertTrue(urls(en))

    def test_auto_row_says_l1_answers_g3(self):
        """Delegated approval covers G3; G2 and escalations still go to the person."""
        old = {'README.md': 'the final acceptance (G3) and escalations still go to you',
               'README-ko.md': '최종 인수(G3)와 에스컬레이션은 계속 사람에게'}
        for path in READMES:
            row = next(l for l in read(path).splitlines() if l.startswith('| `/my-agent --auto'))
            self.assertNotIn(old[path.name], row, path.name)
            for word in ('G3', 'G2'):
                self.assertIn(word, row, path.name)

    def test_monitor_autostart_is_off_by_default(self):
        """Every README that describes the monitor start names the setting that turns it on."""
        docs = READMES + [REPO / 'plugins' / 'my-agent' / 'monitor' / 'README.md',
                          REPO / 'plugins' / 'my-agent-tray' / 'README.md',
                          REPO / 'plugins' / 'my-agent-tray' / 'macos' / 'menubar' / 'README.md']
        for path in docs:
            self.assertIn('"autostart": true', read(path), str(path))
        self.assertNotIn('default true', read(docs[2]))


if __name__ == '__main__':
    unittest.main()
