"""copy-probe.sh and copy-probe-hook.py: static checks of the live probe for parallel coders in copies (no Claude run)."""
import json
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import REPO

PROBE = REPO / 'tests' / 'probe'
SCRIPT = PROBE / 'copy-probe.sh'
HOOK = PROBE / 'copy-probe-hook.py'


def code(text):
    """The script without comment lines."""
    return '\n'.join(l for l in text.splitlines() if not l.lstrip().startswith('#'))


class ScriptTextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding='utf-8')
        cls.code = code(cls.text)

    def test_syntax_and_argument(self):
        r = subprocess.run(['sh', '-n', str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('usage: copy-probe.sh <evidence folder>', self.text)
        self.assertIn('EVID=', self.code)

    def test_two_locations_and_two_units_per_create(self):
        self.assertEqual(self.code.count('mktemp -d'), 1)   # one helper, called for "git" and for "nongit"
        self.assertIn('prepare() {', self.code)
        self.assertRegex(self.code, r'run_kind_prepare git')
        self.assertRegex(self.code, r'run_kind_prepare nongit')
        self.assertIn('git -C "$loc" init', self.code)
        self.assertRegex(self.code, r'worktree\.py|\$WORKTREE_PY')
        self.assertRegex(self.code, r'create --location "\$loc" --task "\$task" --unit u1 --unit u2')

    def test_coders_and_prompt_lines(self):
        self.assertIn('my-agent:coder', self.code)
        self.assertIn("Work unit: %s probe\\nWorktree: %s\\n", self.code)
        self.assertIn('in ONE message', self.code)
        self.assertIn('BEGIN u1', self.code)
        self.assertIn('BEGIN u2', self.code)

    def test_write_cases_in_order(self):
        own = self.code.index('1. Write %s/probe-%s.txt')
        main = self.code.index('2. Write %s/probe-main-%s.txt')
        other = self.code.index('3. Write %s/probe-from-%s.txt')
        self.assertLess(own, main)
        self.assertLess(main, other)
        for case in ('first-call', 'own-copy-write', 'main-tree-write', 'other-copy-write'):
            self.assertIn(case, self.code)

    def test_prompt_asks_for_three_parallel_writes_in_one_message(self):
        prompts = self.code[self.code.index('coder_prompt() {'):self.code.index('first_message() {')]
        self.assertIn('three Write calls as three parallel tool calls in ONE message', prompts)
        self.assertIn('with no tool call before that message', prompts)
        self.assertNotIn('no other tool call before or between them', prompts)
        self.assertNotIn('one call each, in this order', prompts)

    def test_prompt_says_writes_2_and_3_are_expected_refused(self):
        prompts = self.code[self.code.index('coder_prompt() {'):self.code.index('first_message() {')]
        self.assertIn('Writes 2 and 3 are expected to be refused by the guard', prompts)
        self.assertIn('a refusal of one Write does not cancel the others', prompts)
        self.assertIn('do not try another way around a refusal', prompts)
        self.assertNotIn('If a write is refused, do not try another way.', prompts)

    def test_write_cases_need_evidence(self):
        judge = self.code[self.code.index('judge() {'):self.code.index('run_kind_prepare() {')]
        self.assertIn('attempted() {', judge)
        self.assertIn('denied_in_run_log() {', judge)
        self.assertIn('say "$kind $u $case: not attempted"', judge)
        self.assertIn('fail "$kind:$u:$case:not-attempted"', judge)

    def test_working_copy_plugin_only(self):
        self.assertEqual(self.code.count('--plugin-dir "$PLUGIN"'), 2)
        self.assertRegex(self.code, r'PLUGIN=\$\(cd "\$HERE/\.\./\.\." && pwd -P\)')
        self.assertEqual(self.code.count('--setting-sources project,local'), 2)
        self.assertEqual(self.code.count('--settings "$d/settings.json"'), 2)
        self.assertNotIn('~/.claude', self.code)
        self.assertNotIn('$HOME/.claude', self.code)

    def test_move_is_the_cd_command_as_second_user_message(self):
        self.assertIn('--input-format stream-json --output-format stream-json', self.code)
        self.assertEqual(len(re.findall(r'feed "\$msg" "/cd \$loc/\.claude/worktrees/my-agent-\$TASK_ID-u1"', self.code)), 2)
        feed = self.code[self.code.index('feed() {'):self.code.index('prepare() {')]
        self.assertLess(feed.index('"$1"'), feed.index('"type":"result"'))   # the second message waits for the first turn
        self.assertLess(feed.index('"type":"result"'), feed.rindex('"$2"'))
        # no prompt asks for a Bash cd or pwd as the move
        prompts = self.code[self.code.index('coder_prompt() {'):self.code.index('first_message() {')]
        self.assertNotRegex(prompts, r'\bBash\b|\bpwd\b|\bcd\b')

    def test_move_outcomes(self):
        judge = self.code[self.code.index('judge() {'):self.code.index('run_kind_prepare() {')]
        self.assertIn("grep -qF 'excluded by the Cd(' \"$out\"", judge)
        self.assertRegex(judge, r'refused\) say "\$kind cd move: refused"')
        self.assertRegex(judge, r'moved\) say "\$kind cd move: moved"; fail "\$kind:cd-move-moved"')
        self.assertIn('cd move: not driven; open a session in $loc and type: /cd $copy1', judge)
        self.assertIn('open risk:', judge)
        # not driven also when claude --help has no --input-format
        self.assertIn('*--input-format*) FMT=', self.code)
        self.assertRegex(judge, r'\[ "\$FMT" = "\$\{FMT#--input-format\}" \]; then move=notdriven')
        # the not-driven branch keeps the temp folder and runs no cleanup; the other branch cleans up and removes it
        branch = judge[judge.index('if [ "$move" = notdriven ]'):]
        keep, clean = branch.split('else', 1)
        self.assertNotIn('cleanup', keep)
        self.assertNotIn('rm -rf', keep)
        self.assertIn('Cd rule on, copy u1 present', keep)
        self.assertIn('cleanup --location', clean)
        self.assertIn('rm -rf "$loc"', clean)

    def test_budget_cap(self):
        self.assertEqual(self.code.count('claude -p'), 2)
        self.assertEqual(self.code.count('--max-budget-usd "$BUDGET_USD_PER_SESSION"'), 2)
        self.assertIn('BUDGET_USD_PER_SESSION=${COPY_PROBE_BUDGET_USD:-2.00}', self.code)
        self.assertIn('echo "copy-probe: 2 sessions (git, nongit), 2 coders each, cap $BUDGET_USD_PER_SESSION USD per session ($CAP_RUN USD per run)"', self.code)
        self.assertLess(self.code.index('--max-budget-usd*'), self.code.index('mktemp -d'))
        self.assertLess(self.code.index('--max-budget-usd*'), self.code.index('claude -p'))

    def test_evidence_and_result_line(self):
        for name in ('hook-log.jsonl', 'guard-lines.txt', 'files.txt', 'output.json', 'cost.txt', 'summary.txt'):
            self.assertIn(name, self.code)
        self.assertIn('result: pass', self.code)
        self.assertIn('result: fail:', self.code)


class JudgeTest(unittest.TestCase):
    """Runs the script's own judge() on a made-up evidence folder (no claude, no session)."""

    def run_judge(self, hook_recs, guard_lines, files):
        text = SCRIPT.read_text(encoding='utf-8')
        funcs = text[text.index('say() {'):text.index('# prepare <kind>')] + text[text.index('# judge <kind>'):text.index('run_kind_prepare() {')]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            loc = tmp / 'loc'
            task = 'T'
            c1 = loc / '.claude' / 'worktrees' / f'my-agent-{task}-u1'
            c2 = loc / '.claude' / 'worktrees' / f'my-agent-{task}-u2'
            for d in (c1, c2, loc / '.my-agent' / task):
                d.mkdir(parents=True)
            ev = tmp / 'ev' / 'git'
            ev.mkdir(parents=True)
            (ev / 'location.txt').write_text(str(loc))
            (ev / 'output.json').write_text('{"type":"result"}\n')
            recs = [dict(r, path=r['path'].format(loc=loc, c1=c1, c2=c2), worktree=str(c1 if r['unit'] == 'u1' else c2),
                         tool='Write') for r in hook_recs]
            (ev / 'hook-log.jsonl').write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in recs))
            (loc / '.my-agent' / task / 'run-log.md').write_text(''.join(
                'guard: hook=scope-guard tool=Write decision=deny why="x: %s"\n' % g.format(loc=loc, c1=c1, c2=c2) for g in guard_lines))
            for f in files:
                Path(f.format(loc=loc, c1=c1, c2=c2)).write_text('x')
            script = (f'SUMMARY={tmp}/summary.txt; : > "$SUMMARY"; FAILS=""; EVID={tmp}/ev; TASK_ID={task}\n'
                      f'FMT="--output-format x"; WORKTREE_PY=/nonexistent; OUT=/dev/null\n{funcs}\njudge git\necho "FAILS=$FAILS"\n')
            r = subprocess.run(['sh', '-c', script], capture_output=True, text=True, timeout=60)
            return r.stdout, (tmp / 'summary.txt').read_text()

    def full(self, skip=()):
        recs, guards, files = [], [], []
        for u, own, other in (('u1', 'c1', 'c2'), ('u2', 'c2', 'c1')):
            cases = [('own-copy-write', '{%s}/probe-%s.txt' % (own, u)),
                     ('main-tree-write', '{loc}/probe-main-%s.txt' % u),
                     ('other-copy-write', '{%s}/probe-from-%s.txt' % (other, u))]
            for i, (case, path) in enumerate(cases):
                if (u, case) in skip:
                    continue
                recs.append({'unit': u, 'path': path, 'first': i == 0})
                if i == 0:
                    files.append(path)
                else:
                    guards.append(path)
        return recs, guards, files

    def test_all_attempted_and_judged(self):
        out, summ = self.run_judge(*self.full())
        self.assertIn('FAILS=\n', out)
        self.assertIn('git u1 main-tree-write: pass (denied)', summ)
        self.assertIn('git u2 other-copy-write: pass (denied)', summ)
        self.assertNotIn('not attempted', summ)

    def test_first_marker_on_any_write_of_the_agent_passes_first_call(self):
        for idx in (1, 2):   # the "first" marker lands on the main-tree or the other-copy Write
            recs, guards, files = self.full()
            for r in recs:
                r['first'] = False
            u1 = [r for r in recs if r['unit'] == 'u1']
            u1[idx]['first'] = True
            u1[0]['first'] = False
            u2 = [r for r in recs if r['unit'] == 'u2']
            u2[0]['first'] = True
            out, summ = self.run_judge(recs, guards, files)
            self.assertIn('FAILS=\n', out)
            self.assertIn('git u1 first-call: pass', summ)

    def test_no_first_record_for_the_unit_fails_first_call(self):
        recs, guards, files = self.full()
        for r in recs:
            r['first'] = r['unit'] == 'u2' and r['path'].endswith('probe-u2.txt')
        out, summ = self.run_judge(recs, guards, files)
        self.assertIn('u1:first-call', out)
        self.assertNotIn('git u1 first-call: pass', summ)
        self.assertIn('git u2 first-call: pass', summ)

    def test_run1_shape_no_other_copy_attempt_is_not_attempted_and_fails(self):
        recs, guards, files = self.full(skip=(('u1', 'other-copy-write'), ('u2', 'other-copy-write')))
        guards = [g for g in guards if 'probe-from-' not in g]
        out, summ = self.run_judge(recs, guards, files)
        self.assertIn('git u1 other-copy-write: not attempted', summ)
        self.assertIn('git u2 other-copy-write: not attempted', summ)
        self.assertNotIn('other-copy-write: pass', summ)
        self.assertIn('u1:other-copy-write:not-attempted', out)

    def test_attempt_without_a_deny_line_naming_the_path_fails(self):
        recs, guards, files = self.full()
        guards = [g for g in guards if g != '{loc}/probe-main-u1.txt']
        out, summ = self.run_judge(recs, guards, files)
        self.assertNotIn('git u1 main-tree-write: pass', summ)
        self.assertIn('u1:main-tree-write', out)
        self.assertIn('git u2 main-tree-write: pass (denied)', summ)

    def test_written_file_in_a_denied_case_fails_and_missing_own_file_fails(self):
        recs, guards, files = self.full()
        out, summ = self.run_judge(recs, guards, files + ['{loc}/probe-main-u2.txt'])
        self.assertIn('u2:main-tree-write', out)
        out, summ = self.run_judge(recs, guards, [f for f in files if 'probe-u1.txt' not in f])
        self.assertIn('u1:own-copy-write', out)
        self.assertNotIn('git u1 own-copy-write: pass', summ)

    def test_own_copy_attempt_missing_is_not_attempted(self):
        out, summ = self.run_judge(*self.full(skip=(('u2', 'own-copy-write'),)))
        self.assertIn('git u2 own-copy-write: not attempted', summ)
        self.assertIn('u2:own-copy-write:not-attempted', out)


class StubClaudeTest(unittest.TestCase):
    def run_script(self, help_text):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'bin').mkdir()
            calls = tmp / 'calls.txt'
            stub = tmp / 'bin' / 'claude'
            stub.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\n'
                            f'[ "$1" = --help ] && {{ cat <<\'EOF\'\n{help_text}\nEOF\nexit 0; }}\nexit 1\n', encoding='utf-8')
            stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
            env = dict(os.environ, PATH=f'{tmp / "bin"}:{os.environ["PATH"]}')
            r = subprocess.run(['sh', str(SCRIPT), str(tmp / 'evidence')], capture_output=True, text=True, env=env, timeout=60)
            made = (tmp / 'evidence' / 'git').exists()
            return r, calls.read_text(encoding='utf-8').splitlines() if calls.exists() else [], made

    def test_no_budget_flag_exits_2_without_a_session(self):
        r, calls, made = self.run_script('  --input-format <format>   Input format\n  --model <m>   model')
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(len(r.stdout.strip().splitlines()), 1, r.stdout)
        self.assertIn('--max-budget-usd', r.stdout)
        self.assertEqual(calls, ['--help'])   # no session
        self.assertFalse(made)

    def test_missing_argument_exits_2(self):
        r = subprocess.run(['sh', str(SCRIPT)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertIn('usage:', r.stdout)


class HookTest(unittest.TestCase):
    def run_hook(self, tmp, inp):
        env = dict(os.environ, COPY_PROBE_LOG=str(tmp / 'hook-log.jsonl'), MA_CLAUDE_PROJECTS=str(tmp / 'projects'))
        return subprocess.run(['python3', str(HOOK)], input=json.dumps(inp), capture_output=True, text=True, env=env, timeout=30)

    def test_records_first_call_and_unit_from_the_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            sub = tmp / 'projects' / 'p' / 'sess1' / 'subagents'
            sub.mkdir(parents=True)
            prompt = 'Work unit: u1 probe\nWorktree: /loc/.claude/worktrees/my-agent-t-u1\nWrite things'
            (sub / 'agent-A1.jsonl').write_text(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': prompt}}) + '\n',
                                               encoding='utf-8')
            inp = {'agent_id': 'A1', 'agent_type': 'my-agent:coder', 'session_id': 'sess1', 'cwd': '/loc',
                   'tool_name': 'Write', 'tool_input': {}}
            for _ in range(2):
                r = self.run_hook(tmp, inp)
                self.assertEqual((r.returncode, r.stdout), (0, ''))
            recs = [json.loads(l) for l in (tmp / 'hook-log.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([x['first'] for x in recs], [True, False])
            for x in recs:
                self.assertEqual((x['unit'], x['worktree'], x['tool'], x['cwd'], x['prompt_read']),
                                 ('u1', '/loc/.claude/worktrees/my-agent-t-u1', 'Write', '/loc', True))
            # the script's evidence greps rely on these exact spellings
            line = (tmp / 'hook-log.jsonl').read_text(encoding='utf-8').splitlines()[0]
            for piece in ('"first": true', '"unit": "u1"', '"tool": "Write"', '"worktree": "/loc/.claude/worktrees/my-agent-t-u1"'):
                self.assertIn(piece, line)

    def test_records_the_file_path_of_the_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self.run_hook(tmp, {'agent_id': 'A', 'session_id': 's', 'cwd': '/l', 'tool_name': 'Write',
                                'tool_input': {'file_path': '/l/x.txt', 'content': 'c'}})
            self.run_hook(tmp, {'agent_id': 'A', 'session_id': 's', 'cwd': '/l', 'tool_name': 'Read', 'tool_input': 'odd'})
            text = (tmp / 'hook-log.jsonl').read_text(encoding='utf-8')
            self.assertEqual([json.loads(l)['path'] for l in text.splitlines()], ['/l/x.txt', None])
            self.assertIn('"path": "/l/x.txt"', text)

    def test_unreadable_transcript_is_recorded_and_main_thread_calls_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self.run_hook(tmp, {'tool_name': 'Agent', 'session_id': 's', 'cwd': '/loc'})   # no agent id
            self.assertFalse((tmp / 'hook-log.jsonl').exists())
            self.run_hook(tmp, {'agent_id': 'NOPE', 'session_id': 's', 'cwd': '/loc', 'tool_name': 'Write'})
            rec = json.loads((tmp / 'hook-log.jsonl').read_text(encoding='utf-8'))
            self.assertEqual((rec['prompt_read'], rec['unit'], rec['worktree'], rec['first']), (False, None, None, True))

    def test_unit_only_from_the_first_line_and_worktree_only_from_the_second(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('copy_probe_hook', HOOK)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.unit_and_worktree('Work unit: u2 x\nWorktree: /a b\n'), ('u2', '/a b'))
        self.assertEqual(mod.unit_and_worktree('note\nWork unit: u2\nWorktree: /a'), (None, None))
        self.assertEqual(mod.unit_and_worktree('Work unit: u2\nnote\nWorktree: /a'), ('u2', None))


class ResultsRecordTest(unittest.TestCase):
    """tests/probe/results.md holds the 261126 section (criterion 14): both locations, both coders and the four evidence
    cases each, plus the Cd move row per location with its source."""

    @classmethod
    def setUpClass(cls):
        text = (PROBE / 'results.md').read_text(encoding='utf-8')
        head = '## Parallel coders in unit copies (261126)'
        assert head in text, 'results.md has no 261126 section'
        cls.section = text[text.index(head):]
        cls.section = cls.section.split('\n## ', 1)[0]

    def sub(self, name, end):
        start = self.section.index(name)
        return self.section[start:self.section.index(end, start)] if end else self.section[start:]

    def test_method_names_the_script_run_and_cost(self):
        method = self.sub('### Method', '### Evidence per location and coder')
        for word in ('copy-probe.sh', 'copy-probe-hook.py', '`run4`', '`run3`', 'two real `claude -p` sessions', '4 coders',
                     '--plugin-dir', '--setting-sources project,local', 'parallel calls in one message',
                     'not attempted', '--max-budget-usd', 'total_cost_usd', '0.51 USD', '`run1`', '`run2`'):
            self.assertIn(word, method, word)

    def test_each_location_and_coder_has_the_four_evidence_cases(self):
        for name, nxt in (('#### Location: git', '#### Location: non-git'),
                          ('#### Location: non-git', 'What the run shows')):
            table = self.sub(name, nxt)
            rows = [l for l in table.splitlines() if l.startswith('| u')]
            self.assertEqual(len(rows), 8, (name, rows))
            for unit in ('u1', 'u2'):
                mine = [l for l in rows if l.startswith(f'| {unit} |')]
                self.assertEqual(len(mine), 4, (name, unit))
                for case in ('first call: unit read', 'own-copy write allowed', 'main-tree write denied',
                             'other-copy write denied'):
                    row = next((l for l in mine if f'| {case} |' in l), None)
                    self.assertIsNotNone(row, (name, unit, case))
                    cells = [c.strip() for c in row.strip('|').split('|')]
                    self.assertTrue(cells[2], row)            # evidence: file and field
                    self.assertTrue(cells[3].startswith('pass'), row)
                    self.assertTrue('hook-log.jsonl' in row or 'guard-lines.txt' in row or 'files.txt' in row
                                    or 'attempt' in row, row)

    def test_cd_move_row_per_location_says_whose_observation_it_is(self):
        cd = self.sub('### Cd move', '### Open risks')
        rows = [l for l in cd.splitlines() if l.startswith('| git |') or l.startswith('| non-git |')]
        self.assertEqual(len(rows), 4, rows)
        for loc in ('git', 'non-git'):
            mine = [l for l in rows if l.startswith(f'| {loc} |')]
            probe = next(l for l in mine if "the probe's own `/cd`" in l)
            self.assertTrue(probe.rstrip().endswith('| not driven |'), probe)
            typed = next(l for l in mine if 'L1 typed `/cd <u1 copy>` in an interactive session via tmux (the person\'s choice)' in l)
            self.assertTrue(typed.rstrip().endswith('| refused |'), typed)
            self.assertIn('excluded by the Cd(', typed + cd)
        self.assertIn('not typed by the person', cd)
        self.assertIn('matches no tool', cd)

    def test_open_risk_names_the_unapplied_new_settings_file(self):
        risks = self.sub('### Open risks', None)
        self.assertIn('A new settings file read only from the next session', risks)
        self.assertIn('only in sessions started after', risks)


if __name__ == '__main__':
    unittest.main()
