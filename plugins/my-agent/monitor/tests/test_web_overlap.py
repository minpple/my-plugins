"""Overlapping 4A and 4B in web/index.html: `stats()` ends step 7 at its last agent run when that is later than step 8's
start. Static reads of the page, plus node runs of `stats()`."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / 'web' / 'index.html'


def line(html, name):
    m = re.search(r'(?m)^const ' + name + r' = .*(?:\n  : .*)?$', html)
    assert m, name
    return m.group(0)


def stats_src(html):
    m = re.search(r'(?s)function stats\(t, R\) \{.*?\n\}\n', html)
    assert m
    return m.group(0)


def agent(s, start, a, end=None, **kw):
    return {'t': start, 's': s, 'r': 0, 'k': 'agent', 'a': a, 'live': end is None, 'et': end, 'c': None, 'dur': 1,
            'model': 'sonnet', 'actual': None, **kw}


def phase(s, start):
    return {'t': start, 's': s, 'r': 0, 'k': 'phase', 'a': 'orchestrator', 'tx': f'step {s}'}


class WebOverlapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text(encoding='utf-8')

    def test_stats_reads_the_end_of_agent_items(self):
        self.assertIn('e.et', stats_src(self.html))

    def stats(self, log, now='23:40'):
        t = {'log': log, 'revs': None, 'main': {}, 'status': 'done', 'now': now}
        src = '\n'.join(line(self.html, n) for n in ('num', 'mins', 'dm', 'modelOf', 'latestRev', 'rOf', 'mainOf', 'hasMain', 'revEnd'))
        src += '\n' + stats_src(self.html) + '\nconsole.log(JSON.stringify(stats(%s).steps));' % json.dumps(t)
        r = subprocess.run(['node', '-e', src], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_overlapping_round_ends_step_7_after_step_8_starts(self):
        steps = self.stats([phase(7, '23:10'), phase(8, '23:10'), agent(7, '23:10', 'verifier', '23:22'),
                            agent(8, '23:10', 'reviewer', '23:21')])
        self.assertEqual((steps['7']['start'], steps['7']['end'], steps['7']['min']), ('23:10', '23:22', 12))
        self.assertEqual((steps['8']['start'], steps['8']['end']), ('23:10', '23:40'))
        self.assertEqual(steps['7']['agents'], 1)

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_step_7_ends_after_step_8_start_with_a_later_step_8(self):
        steps = self.stats([phase(7, '23:10'), agent(7, '23:10', 'verifier', '23:22'), phase(8, '23:11'),
                            agent(8, '23:11', 'reviewer', '23:21')])
        self.assertEqual((steps['7']['end'], steps['7']['min']), ('23:22', 12))
        self.assertEqual(steps['8']['start'], '23:11')

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_sequential_round_is_unchanged(self):
        steps = self.stats([phase(7, '23:10'), agent(7, '23:10', 'verifier', '23:20'), phase(8, '23:21'),
                            agent(8, '23:21', 'reviewer', '23:25')])
        self.assertEqual((steps['7']['end'], steps['7']['min']), ('23:21', 11))
        self.assertEqual((steps['8']['start'], steps['8']['end']), ('23:21', '23:40'))

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_running_verifier_and_midnight(self):
        steps = self.stats([phase(7, '23:50'), phase(8, '23:50'), agent(7, '23:50', 'verifier', '00:05'),
                            agent(8, '23:50', 'reviewer', '00:01')], now='00:10')
        self.assertEqual((steps['7']['end'], steps['7']['min']), ('00:05', 15))
        steps = self.stats([phase(7, '23:10'), phase(8, '23:10'), agent(7, '23:10', 'verifier'), agent(8, '23:10', 'reviewer', '23:20')])
        self.assertEqual((steps['7']['end'], steps['7']['min']), ('23:10', 0))


if __name__ == '__main__':
    unittest.main()
