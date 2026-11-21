"""Phase timeline of web/index.html: one return mark per return on its own row, room at the
right, a general legend line. Static reads of the page, plus node runs of the helpers."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / 'web' / 'index.html'


def line(html, name):
    m = re.search(r'(?m)^const ' + name + r' = .*$', html)
    assert m, name
    return m.group(0)


def rule(html, sel):
    m = re.search(r'(?m)^#p-report ' + re.escape(sel) + r' \{(.*)\}$', html)
    assert m, sel
    return m.group(1)


def timeline_src(html):
    m = re.search(r'(?s)function rpTimeline\(t\) \{.*?\n\}\n', html)
    assert m
    return m.group(0)


class TimelineBacksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text(encoding='utf-8')
        cls.tl = timeline_src(cls.html)

    def node(self, body, lang='en'):
        src = "let LANG = '%s';\n" % lang
        src += '\n'.join(line(self.html, n) for n in ('STEP_CODE', 'L', 'stepCode', 'rpBackTip', 'rpBackLeft', 'rpRoom'))
        src += '\n' + body
        r = subprocess.run(['node', '-e', src], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_marks_use_row_not_step_number(self):
        self.assertIn('b.row === i', self.tl)
        self.assertNotIn('b.from === s.n', self.tl)

    def test_mark_is_icon_with_tip(self):
        self.assertIn('role="img" aria-label="${rpEsc(rpBackTip(b))}" title="${rpEsc(rpBackTip(b))}"', self.tl)
        self.assertRegex(self.tl, r'style="left:\$\{rpBackLeft\(s, b\.slot\)\}">&crarr;</span>')
        self.assertNotRegex(self.tl, r'rtl-back[^`]*>[^<]*back to [^<]*</span>')

    def test_tip_line_static(self):
        ln = line(self.html, 'rpBackTip')
        self.assertIn('stepCode(b.to)', ln)
        self.assertRegex(ln, r"b\.why \?[^:]*': '")
        self.assertIn('back to ', ln)
        self.assertIn('단계로 되돌아감', ln)
        self.assertIn('L(', ln)

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_tip_in_node(self):
        long = 'x' * 600
        body = ("console.log(JSON.stringify([rpBackTip({to: 5, why: 'Verify FAIL 3'}), rpBackTip({to: 3, why: 'Plan Review REVISE'}),"
                " rpBackTip({to: 5, why: ''}), rpBackTip({to: 5, why: '%s'})]));" % long)
        got = self.node(body)
        self.assertEqual(got[:3], ['back to 3A: Verify FAIL 3', 'back to 2A: Plan Review REVISE', 'back to 3A'])
        self.assertEqual(got[3], 'back to 3A: ' + long)
        ko = self.node("console.log(JSON.stringify([rpBackTip({to: 5, why: 'Verify FAIL 3'}), rpBackTip({to: 5, why: ''})]));", 'ko')
        self.assertEqual(ko, ['3A 단계로 되돌아감: Verify FAIL 3', '3A 단계로 되돌아감'])

    def test_long_reason_keeps_layout(self):
        mark = re.search(r'<span class="rtl-back".*?</span>', self.tl).group(0)
        self.assertEqual(mark.count('rpBackTip(b)'), 2)
        self.assertNotIn('b.why', mark)
        self.assertTrue(mark.endswith('>&crarr;</span>'))
        self.assertIn('width: 14px', rule(self.html, '.rtl-back'))

    def test_positions_static(self):
        ln = line(self.html, 'rpBackLeft')
        self.assertIn('max(', ln)
        self.assertIn('%, 4px)', ln)
        self.assertIn('2 + 16 *', ln)
        self.assertRegex(line(self.html, 'rpRoom'), r'n \? 16 \* n \+ 8 : 0')

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_positions_in_node(self):
        body = ("console.log(JSON.stringify([rpBackLeft({left: 10, width: 0.2}, 0), rpBackLeft({left: 10, width: 0.2}, 1),"
                " [0, 1, 2, 3].map(rpRoom)]));")
        a, b, room = self.node(body)
        self.assertIn('max(0.2%, 4px)', a)
        self.assertTrue(a.endswith('+ 2px)') or a.endswith('+ 2px'), a)
        self.assertIn('+ 18px', b)
        self.assertEqual(room[0], 0)
        for n in (1, 2, 3):
            self.assertGreaterEqual(room[n], 2 + 16 * (n - 1) + 14 + 4)

    def test_room_shared_by_time_area(self):
        for sel in ('.rtl-gates', '.rtl-axis', '.rtl-track', '.rtl-marks'):
            self.assertIn('var(--room', rule(self.html, sel), sel)
        self.assertNotIn('translateX', rule(self.html, '.rtl-back'))
        self.assertIn('min-width: 4px', rule(self.html, '.rtl-bar'))
        media = re.search(r'@media \(max-width: 520px\) \{.*', self.html).group(0).split('\n')[0]
        self.assertNotIn('--room', media)
        self.assertIn('--room:${rpRoom(t.slots)}px', self.tl)

    def test_legend_general_line(self):
        self.assertNotIn('backs[0].why', self.html)
        pair = "L('went back to an earlier step', '이전 단계로 되돌아감')"
        self.assertIn(pair, self.tl)
        ln = next(x for x in self.tl.split('\n') if pair in x)
        self.assertRegex(ln, r'backs\.some\(b => b\.row != null\) \?')

    def test_durations_from_data(self):
        self.assertIn('rpDur(s.secs)', self.tl)
        self.assertNotIn('(s.b - s.a) / 1000', self.tl)

    def test_summary_follows_chart_end(self):
        ln = next(x for x in self.html.split('\n') if 'const tsum = ' in x)
        self.assertIn('tl.chart_end || tl.end', ln)
        self.assertNotIn('(tl.end || Date.now())', ln)

    def test_no_steps_unchanged(self):
        self.assertIn("if (!steps.length) return NYW('run-log.md')", self.tl)


if __name__ == '__main__':
    unittest.main()
