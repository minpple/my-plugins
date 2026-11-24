"""Background research in the report data: gate rows, the question group, the unchanged timeline and units."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run directly: tests/<name>.py
sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor import report
from test_report import G1A, G1B, G3, PROJECT, snapshot, temp_copy

B1 = '- b1: Does library X still stream? — decides the split\n'
B2 = '- b2: What is the rate limit of API Y? — decides batching\n'
STAMP = '2026-11-24 03:%02d:00 '


def add_section(task, *lines):
    scope = task / 'scope.md'
    scope.write_text(scope.read_text(encoding='utf-8').rstrip('\n') + '\n\n## Background research\n' + ''.join(lines),
                     encoding='utf-8')


def add_log(task, *rows):
    log = task / 'run-log.md'
    text = log.read_text(encoding='utf-8')
    log.write_text(text + ''.join(f'{STAMP % i}{body}\n' for i, (body) in enumerate(rows)), encoding='utf-8')


def note(task, name, text):
    (task / 'background').mkdir(exist_ok=True)
    (task / 'background' / name).write_text(text, encoding='utf-8')


def build(task, info):
    return report.build_report(PROJECT, task, info, [])


class GateRowTest(unittest.TestCase):
    def gate(self, name, edit, status=None):
        tmp, task, info = temp_copy(name, status)
        with tmp:
            edit(task)
            data = build(task, info)
        return data['gate'], data

    def test_g1a_two_questions(self):
        g, _ = self.gate(G1A, lambda t: add_section(t, B1, B2))
        self.assertEqual(g['background_research'], {'questions': 2, 'ids': ['b1', 'b2']})

    def test_g1a_one_question(self):
        g, _ = self.gate(G1A, lambda t: add_section(t, B1))
        self.assertEqual(g['background_research'], {'questions': 1, 'ids': ['b1']})
        self.assertEqual((g['criteria'], g['non_goals']), (4, ['No change to the file format.', 'No GUI.']))

    def test_g1b_not_found(self):
        def edit(t):
            add_section(t, B1, B2)
            note(t, 'api-y.md', '# API Y\n- Not found: the limit\n- Found: x\n')
            note(t, 'lib-x.md', '# Lib X\n- Found: streaming\n')
        g, _ = self.gate(G1B, edit)
        self.assertEqual(g['background_research'], {'questions': 2, 'not_found': 1})

    def test_g1b_folder_missing(self):
        g, _ = self.gate(G1B, lambda t: add_section(t, B1, B2))
        self.assertEqual(g['background_research'], {'questions': 2, 'not_found': 0})

    def test_g1b_question_without_note(self):
        def edit(t):
            add_section(t, B1, B2)
            note(t, 'lib-x.md', '- Not found: a\n')
        g, _ = self.gate(G1B, edit)
        self.assertEqual(g['background_research'], {'questions': 2, 'not_found': 1})

    def test_g1b_unlisted_note_counts(self):
        def edit(t):
            add_section(t, B1)
            note(t, 'lib-x.md', '- Found: a\n')
            note(t, 'old-cdn.md', '- Not found: cdn\n')
        g, _ = self.gate(G1B, edit)
        self.assertEqual(g['background_research'], {'questions': 1, 'not_found': 1})

    def test_line_without_dash_not_counted(self):
        def edit(t):
            add_section(t, B1)
            note(t, 'a.md', 'Not found: x\n  - Not found: indented\n')
        g, _ = self.gate(G1B, edit)
        self.assertEqual(g['background_research']['not_found'], 0)

    def test_malformed_lines_left_out(self):
        def edit(t):
            add_section(t, B1, '- b2: no dash part\n', '- c1: Other? — nope\n', 'b3 what about Z\n')
        g, data = self.gate(G1A, edit)
        self.assertEqual(g['background_research'], {'questions': 1, 'ids': ['b1']})
        self.assertEqual([r['id'] for r in data['background_research']], ['b1'])

    def test_no_section_or_no_question_line(self):
        for name in (G1A, G1B):
            for edit in (lambda t: None, lambda t: add_section(t, '- b1: no dash part\n', 'text\n')):
                g, data = self.gate(name, edit)
                self.assertIsNone(g['background_research'])
                self.assertIsNone(data['background_research'])

    def test_g3_has_no_key_and_banner_unchanged(self):
        tmp, task, info = temp_copy(G3)
        with tmp:
            add_section(task, B1)
            g = build(task, info)['gate']
        self.assertNotIn('background_research', g)
        g, _ = self.gate(G1A, lambda t: add_section(t, B1))
        self.assertEqual((g['id'], g['q']), ('G1a', 'Scope confirmation: 261107-gate-g1a'))

    def test_read_only(self):
        tmp, task, info = temp_copy(G1B)
        with tmp:
            add_section(task, B1, B2)
            note(task, 'a.md', '- Not found: x\n')
            before = snapshot(task)
            build(task, info)
            self.assertEqual(snapshot(task), before)


class GroupStateTest(unittest.TestCase):
    def group(self, rows, status='running', ids=(B1,)):
        tmp, task, info = temp_copy(G1A, status)
        with tmp:
            add_section(task, *ids)
            add_log(task, *rows)
            data = build(task, info)
        return data['background_research']

    CALL = 'call: agent=my-agent:researcher unit=b1 session=s1'

    def stop(self, end, secs):
        return f'stop: agent=my-agent:researcher unit=b1 end={end} secs={secs} session=s1'

    def check(self, rows, state, secs, status='running'):
        g = self.group(rows, status)
        self.assertEqual(len(g), 1)
        self.assertEqual((g[0]['id'], g[0]['question'], g[0]['state'], g[0]['secs']),
                         ('b1', 'Does library X still stream?', state, secs))

    def test_pending(self):
        self.check([], 'pending', None)

    def test_running(self):
        self.check([self.CALL], 'running', None)

    def test_call_without_stop_in_finished_task(self):
        self.check([self.CALL], 'stopped', None, status='done')

    def test_partial_stop(self):
        self.check([self.CALL, self.stop('partial', 40)], 'stopped', 40)

    def test_ok_stop(self):
        self.check([self.CALL, self.stop('ok', 130)], 'done', 130)

    def test_retry_while_running(self):
        self.check([self.CALL, self.stop('partial', 40), self.CALL], 'running', 40)

    def test_run_again(self):
        self.check([self.CALL, self.stop('partial', 40), self.CALL, self.stop('ok', 90)], 'done', 130)
        self.check([self.CALL, self.stop('ok', 60), self.CALL, self.stop('ok', 30)], 'done', 90)

    def test_two_questions_are_separate(self):
        rows = [self.CALL, self.stop('ok', 10)]
        g = self.group(rows, ids=(B1, B2))
        self.assertEqual([(r['id'], r['state'], r['secs']) for r in g], [('b1', 'done', 10), ('b2', 'pending', None)])

    def test_units_and_timeline_unchanged(self):
        tmp, task, info = temp_copy(G1B)
        with tmp:
            plain = build(task, info)
            add_section(task, B1)
            add_log(task, self.CALL, self.stop('ok', 50))
            data = build(task, info)
        self.assertEqual(data['units'], plain['units'])
        self.assertEqual([u['id'] for u in data['units']], ['u1', 'u2'])

    def test_step_rows_keep_raw_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp) / 'a-task'
            task.mkdir()
            (task / 'intake.md').write_text('Status: active\nProfile: dev\n', encoding='utf-8')
            (task / 'run-log.md').write_text('2026-11-24 03:10:00 step: n=2 name=Explore-Scope\n'
                                             '2026-11-24 03:34:10 step: n=2 name=Background-research\n', encoding='utf-8')
            steps = report.build_report(Path(tmp), task, {'id': 'a-task', 'profile': 'dev', 'status': 'running'}, [])['timeline']['steps']
        self.assertEqual([(s['n'], s['name']) for s in steps], [(2, 'Explore-Scope'), (2, 'Background-research')])


if __name__ == '__main__':
    unittest.main()
