"""web/index.html shows a step as phase digit + step letter (3A Execute). Static reads of the page;
the helper behaviour is also run in node when it is installed."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / 'web' / 'index.html'
CODES = {1: '1A', 2: '1B', 3: '2A', 4: '2B', 5: '3A', 6: '3B', 7: '4A', 8: '4B'}
NAMES = {1: 'Intake', 2: 'Explore → Scope', 3: 'Plan', 4: 'Plan Review → G1-B', 5: 'Execute',
         6: 'Merge · Self-check', 7: 'Verify', 8: 'Review → Deliver'}
HELPERS = ('stepCode', 'stepLetter', 'stepLabel', 'stepTx', 'stepsText')


def table(html, name):
    m = re.search(r'(?m)^const ' + name + r' = \{(.*)\};$', html)
    assert m, name
    return {int(k): v for k, v in re.findall(r"(\d+):'([^']*)'", m.group(1))}


def helper_lines(html):
    out = {}
    for name in HELPERS:
        m = re.search(r'(?m)^const ' + name + r' = .*$', html)
        assert m, name
        out[name] = m.group(0)
    return out


class StepLabelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text(encoding='utf-8')

    def test_step_code_table(self):
        self.assertEqual(table(self.html, 'STEP_CODE'), CODES)

    def test_step_name_table_and_comment(self):
        self.assertEqual(table(self.html, 'STEP_NAME'), NAMES)
        lines = self.html.split('\n')
        i = next(k for k, line in enumerate(lines) if line.startswith('const STEP_NAME = '))
        self.assertIn('my-agent-tray/macos/menubar/Sources/MenuModel.swift', lines[i - 1])
        self.assertIn('change both together', lines[i - 1])

    def test_no_old_gate_names_in_the_page(self):
        self.assertIsNone(re.search(r'G1[ab]', self.html))

    def test_phase_labels_unchanged(self):
        for p in ('① Define', '② Plan', '③ Build', '④ Accept'):
            self.assertIn("{ n: '" + p + "'", self.html)

    def test_no_numeric_step_display(self):
        old = ["t.step + '. '", '${t.step}. ', '${x.s}. ', '${e.s}. ', "${curStep ?? '–'}. ",
               'step ${e.s}', 'step ${x.s}', '${e.s}단계', '${x.s}단계', "'✓' : n}",
               '3. Plan', '${rpEsc(s.n)} ${rpEsc(s.name)}', 'back to ${rpEsc(b.to)}',
               'step ${rpEsc(wt.step)}', '${rpEsc(v.step.n)}', '${rpEsc(dv.step.n)}',
               'Numbers in the top row are step numbers']
        for o in old:
            self.assertNotIn(o, self.html, o)

    def test_out_of_range_fallback_static(self):
        lines = helper_lines(self.html)
        for name in ('stepCode', 'stepLetter', 'stepLabel'):
            self.assertIn('String(n)', lines[name], name)

    def test_no_step_keeps_dash(self):
        self.assertIn("stepLabel(t.step)) : '–'", self.html)
        self.assertIn("curStep ? esc(stepLabel(curStep)) : '–'", self.html)

    def test_done_tile_keeps_done(self):
        line = next(x for x in self.html.split('\n') if 'const nowTile = ' in x)
        self.assertIn("t.status === 'done' ?", line)
        self.assertIn("✓ ${L('Done', '완료')}", line)
        self.assertNotIn('stepLabel', line)

    def test_korean_strings_stay_korean(self):
        for s in ('단계에서 생김', '에서`',
                  '위 칸의 표시는 단계입니다: 앞 숫자는 페이즈, 뒤 글자는 그 안의 단계 (3A = 페이즈 3의 첫 단계)'):
            self.assertIn(s, self.html, s)
        self.assertIn('Labels in the top row are steps: phase digit and step letter (3A = phase 3, first step).', self.html)

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_helpers_in_node(self):
        src = '\n'.join(re.search(r'(?m)^const ' + n + r' = .*$', self.html).group(0) for n in ('STEP_NAME', 'STEP_CODE'))
        src += '\n' + '\n'.join(helper_lines(self.html).values())
        src += '''
const out = [];
for (let n = 1; n <= 8; n++) out.push(stepLabel(n));
out.push(stepLetter(5), stepCode(6), stepLabel(9), stepLabel(0));
out.push(stepTx('step 5 · Execute'), stepTx('step 6'), stepTx('back to Execute · Verify FAIL 2'), stepTx('① Define start'), stepTx('step 12 · x'));
out.push(stepsText('1 Intake, 2 Explore-Scope'), stepsText(''));
console.log(JSON.stringify(out));'''
        r = subprocess.run(['node', '-e', src], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got[:8], [CODES[n] + ' ' + NAMES[n] for n in range(1, 9)])
        self.assertEqual(got[8:], ['A', '3B', '9', '0', 'step 3A · Execute', 'step 3B',
                                   'back to Execute · Verify FAIL 2', '① Define start', 'step 12 · x',
                                   '1A Intake, 1B Explore-Scope', ''])


if __name__ == '__main__':
    unittest.main()
