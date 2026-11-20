"""Cross-surface checks for the step labels (1A..4B): no numeric step display, equal tables."""
import ast
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / 'plugins/my-agent/monitor/web/index.html'
SWIFT = REPO / 'plugins/my-agent-tray/macos/menubar/Sources/MenuModel.swift'
TEMPLATE = REPO / 'tools/docs-template.html'
CODES = {1: '1A', 2: '1B', 3: '2A', 4: '2B', 5: '3A', 6: '3B', 7: '4A', 8: '4B'}

DISPLAY_FILES = [
    'README.md', 'README-ko.md', 'docs/index.html', 'docs/index-ko.html',
    'tools/docs-template.html', 'plugins/my-agent/monitor/web/index.html',
    'plugins/my-agent/monitor/README.md', 'plugins/my-agent-tray/README.md',
    'plugins/my-agent-tray/macos/menubar/README.md',
]
SWEEP = [
    re.compile(r'\b[1-8]\.? (Intake|Explore|Plan|Execute|Build|Merge|Verify|Review)\b'),
    re.compile(r'\b[1-8] (접수|탐색|계획|실행|병합|검증|리뷰)'),
]
# a bare "step 5" display; checked in the Swift sources and the two feature pages only
BARE_STEP = re.compile(r'\bstep [1-8]\b')
BARE_STEP_FILES = {'docs/index.html', 'docs/index-ko.html'}


def read(p):
    return Path(p).read_text(encoding='utf-8')


def js_table(text):
    m = re.search(r'const STEP_CODE = \{(.*?)\};', text)
    assert m, 'STEP_CODE literal not found'
    return {int(k): v for k, v in re.findall(r"'?(\d+)'?:\s*'([^']*)'", m.group(1))}


def swift_table(text, name):
    m = re.search(r'let %s: \[Int: String\] = \[(.*?)\]\n' % name, text, re.S)
    assert m, name + ' not found'
    return {int(k): v for k, v in re.findall(r'(\d+): "([^"]*)"', m.group(1))}


class StepLabels(unittest.TestCase):
    def test_no_numeric_step_in_display_files(self):
        files = [REPO / f for f in DISPLAY_FILES]
        files += sorted((REPO / 'plugins/my-agent-tray/macos/menubar/Sources').glob('*.swift'))
        hits = []
        for f in files:
            for i, line in enumerate(read(f).splitlines(), 1):
                if line.lstrip().startswith(('/*', '//')):
                    continue  # code comments are not display text
                bare = f.suffix == '.swift' or str(f.relative_to(REPO)) in BARE_STEP_FILES
                if any(p.search(line) for p in SWEEP) or (bare and BARE_STEP.search(line)):
                    hits.append(f'{f.relative_to(REPO)}:{i}: {line.strip()[:80]}')
        self.assertEqual(hits, [])

    def test_letter_tables_agree(self):
        self.assertEqual(js_table(read(WEB)), CODES)
        self.assertEqual(js_table(read(TEMPLATE)), CODES)
        self.assertEqual(swift_table(read(SWIFT), 'stepCodes'), CODES)

    def test_name_tables_agree(self):
        web = read(WEB)
        m = re.search(r'const STEP_NAME = (\{.*?\});', web)
        self.assertTrue(m)
        web_names = {int(k): v for k, v in re.findall(r"(\d+):'([^']*)'", m.group(1))}
        swift = read(SWIFT)
        swift_names = swift_table(swift, 'stepNames')
        self.assertEqual(len(web_names), 8)
        self.assertEqual(swift_names, web_names)
        for text, anchor in ((swift, 'let stepNames'), (web, 'const STEP_NAME =')):
            above = text[:text.index(anchor)].rstrip().splitlines()[-1]
            self.assertIn('change both together', above)


if __name__ == '__main__':
    unittest.main()
