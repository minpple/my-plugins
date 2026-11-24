"""Background research (Q45) in the Report tab of web/index.html: the timeline row name, the G1a and
G1b rows, the question group above the work units, and the Korean strings. Static reads of the page,
plus node runs of the helpers extracted by regex."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / 'web' / 'index.html'

STEP_NAME_LINE = "const STEP_NAME = {1:'Intake',2:'Explore → Scope',3:'Plan',4:'Plan Review → G1b',5:'Execute',6:'Merge · Self-check',7:'Verify',8:'Review → Deliver'};"
STEP_CODE_LINE = "const STEP_CODE = {1:'1A',2:'1B',3:'2A',4:'2B',5:'3A',6:'3B',7:'4A',8:'4B'};"


def line(html, name):
    m = re.search(r'(?m)^const ' + name + r' = .*$', html)
    assert m, name
    return m.group(0)


def func(html, name):
    m = re.search(r'(?ms)^function ' + name + r'\(.*?^\}$', html)
    assert m, name
    return m.group(0)


class BackgroundPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text(encoding='utf-8')

    def node(self, parts, body, lang='en'):
        src = "let LANG = '%s';\n" % lang
        src += '\n'.join(line(self.html, p) for p in parts) + '\n'
        src += body
        r = subprocess.run(['node', '-e', src], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    # ---- timeline row name (criterion 1)
    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_step_name_node(self):
        parts = ['STEP_CODE', 'L', 'stepCode', 'rpStepName']
        body = ("const f = s => stepCode(s.n) + ' ' + rpStepName(s);"
                "console.log(JSON.stringify([f({n: 2, name: 'Background-research'}), f({n: 2, name: 'Explore-Scope'}),"
                " f({n: 2, name: 'background-research'}), f({n: 3, name: 'Background-research'})]));")
        self.assertEqual(self.node(parts, body), ['1B Background research', '1B Explore-Scope', '1B background-research', '2A Background-research'])
        self.assertEqual(self.node(parts, body, 'ko'), ['1B 배경 조사', '1B Explore-Scope', '1B background-research', '2A Background-research'])

    def test_timeline_uses_step_name(self):
        m = re.search(r'(?s)function rpTimeline\(t\) \{.*?\n\}\n', self.html)
        tl = m.group(0)
        self.assertEqual(tl.count('rpStepName(s)'), 2)
        self.assertIn("rpEsc(stepCode(s.n))} ${rpEsc(rpStepName(s))}", tl)
        self.assertNotIn('rpEsc(s.name)', tl)
        self.assertIn('RP_COLORS[i % RP_COLORS.length]', tl)
        self.assertIn('b.row === i', tl)

    def test_step_tables_unchanged(self):
        self.assertIn('\n' + STEP_NAME_LINE + '\n', self.html)
        self.assertIn('\n' + STEP_CODE_LINE + '\n', self.html)

    # ---- gate rows (criterion 2)
    def gate(self, gate, lang='en'):
        src = "let LANG = '%s';\n" % lang
        src += '\n'.join(line(self.html, n) for n in ('L', 'rpEsc', 'rpBgQs', 'rpBgNotFound'))
        src += '\n' + func(self.html, 'rpGateBody')
        src += "\nconsole.log(JSON.stringify(rpGateBody(%s, {})));" % json.dumps(gate)
        r = subprocess.run(['node', '-e', src], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_g1a_row(self):
        g = {'id': 'G1a', 'purpose': 'p', 'non_goals': ['x'], 'background_research': {'questions': 2, 'ids': ['b1', 'b2']}}
        self.assertIn('<dt>Background research</dt><dd>2 questions (b1, b2)</dd>', self.gate(g))
        self.assertIn('<dt>배경 조사</dt><dd>질문 2개 (b1, b2)</dd>', self.gate(g, 'ko'))
        g['background_research'] = {'questions': 1, 'ids': ['b1']}
        self.assertIn('<dd>1 question (b1)</dd>', self.gate(g))
        self.assertIn('<dd>질문 1개 (b1)</dd>', self.gate(g, 'ko'))
        self.assertTrue(self.gate(g).endswith('</dd></dl>'))
        self.assertIn('<dt>Background research</dt>', self.gate(g)[-80:])

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_g1b_row(self):
        g = {'id': 'G1b', 'units': [], 'models': None, 'background_research': {'questions': 2, 'not_found': 1}}
        self.assertIn('<dt>Background research</dt><dd>2 questions, 1 Not found</dd>', self.gate(g))
        self.assertIn('<dt>배경 조사</dt><dd>질문 2개, Not found 1건</dd>', self.gate(g, 'ko'))
        g['background_research']['not_found'] = 0
        self.assertIn('2 questions, 0 Not found', self.gate(g))
        self.assertTrue(self.gate(g).endswith('</dd></dl>'))

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_null_gives_no_row(self):
        for gid in ('G1a', 'G1b'):
            base = {'id': gid, 'units': [], 'non_goals': []}
            for lang in ('en', 'ko'):
                without = self.gate(base, lang)
                withnull = self.gate(dict(base, background_research=None), lang)
                self.assertEqual(without, withnull)
                self.assertNotIn('Background research', withnull)
                self.assertNotIn('배경 조사', withnull)

    def test_gate_numbers_untouched(self):
        self.assertNotIn('background_research', func(self.html, 'rpGateNumbers'))

    # ---- question group (criterion 3)
    def group(self, bg, lang='en'):
        src = "let LANG = '%s';\nconst rpIsOpen = () => false;\n" % lang
        src += '\n'.join(line(self.html, n) for n in ('L', 'rpEsc', 'rpPad', 'rpDur', 'rpBgState'))
        src += '\n' + func(self.html, 'rpRow') + '\n' + func(self.html, 'rpBgGroup')
        src += "\nconsole.log(JSON.stringify(rpBgGroup(%s)));" % json.dumps(bg)
        r = subprocess.run(['node', '-e', src], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_group_rows(self):
        bg = [{'id': 'b1', 'question': 'Q one <x>?', 'state': 'pending', 'secs': None},
              {'id': 'b2', 'question': 'Q two?', 'state': 'running', 'secs': 40},
              {'id': 'b3', 'question': 'Q three?', 'state': 'stopped', 'secs': None},
              {'id': 'b4', 'question': 'Q four?', 'state': 'done', 'secs': 130}]
        none_en, none_ko = 'No time recorded.', '기록된 시간이 없습니다.'
        for lang, words, head, ran, none in (
                ('en', ['pending', 'running', 'stopped', 'done'], 'Background research', 'Ran ', none_en),
                ('ko', ['대기', '진행 중', '중단됨', '완료'], '배경 조사', '실행 ', none_ko)):
            h = self.group(bg, lang)
            self.assertTrue(h.startswith('<div class="gh">' + head + '</div><div class="rows">'))
            for i, w in enumerate(words, 1):
                self.assertIn('id="rb-b%d"' % i, h)
                self.assertRegex(h, r'<span class="stt(?: other)?">%s</span>' % w)
            self.assertIn('Q one &lt;x&gt;?', h)
            self.assertIn('<span class="stt">' + words[3] + '</span>', h)
            self.assertIn('<span class="stt other">' + words[0] + '</span>', h)
            self.assertIn('<p>%s2m 10s.</p>' % ran, h)
            self.assertIn('<p>%s40s.</p>' % ran, h)
            self.assertEqual(h.count(ran), 2)
            self.assertEqual(h.count('<p>' + none + '</p>'), 2)
            self.assertIn('vdot pass', h)
            self.assertIn('vdot run', h)

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_group_empty(self):
        self.assertEqual(self.group(None), '')
        self.assertEqual(self.group([]), '')

    def test_group_above_units(self):
        m = re.search(r"rpDisc\('rd-units'.*", self.html)
        self.assertIn('rpBgGroup(d.background_research) + ub)', m.group(0))
        self.assertIn('${done} / ${units.length}', m.group(0))

    # ---- bilingual (criterion 4)
    def test_new_labels_bilingual(self):
        labels = ["'Background research'", "'1 question'", '`${n} questions`', '`${n} Not found`',
                  "'pending'", "'running'", "'stopped'", "'done'", "'Ran '",
                  "'No time recorded.'"]
        for en in labels:
            ms = re.findall(r'L\(' + re.escape(en) + r', ([^)]*?)\)', self.html)
            self.assertTrue(ms, en)
            self.assertTrue(any(re.search('[가-힣]', k) for k in ms), en)
        self.assertIn("L('Ran ', '실행 ')", self.html)


if __name__ == '__main__':
    unittest.main()
