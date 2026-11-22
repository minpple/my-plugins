"""permission-guard.py (architecture 4.4 "Permission guard"): the ask and deny rules of permissions.json act only
while a task is active, for the session that owns it, on Claude Code."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import CLAUDE_HOOK_ENV, L4, make_task, run_hook

SID = 's-owner'
SCRIPT = 'permission-guard.py'

spec = importlib.util.spec_from_file_location('permission_guard', L4 / 'hooks' / SCRIPT)
pg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pg)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.L = self.root / 'proj'
        self.L.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.L)], check=True)
        self.env = dict(CLAUDE_HOOK_ENV, MA_TASKS_DIR=str(self.root / 'agent-tasks'))

    def tearDown(self):
        self.tmp.cleanup()

    def task(self, session=SID):
        return make_task(self.L, git=False, session=session)

    def run_tool(self, tool, ti, session=SID, env=None, **extra):
        payload = dict({'hook_event_name': 'PreToolUse', 'tool_name': tool, 'tool_input': ti, 'session_id': session},
                       **extra)
        return run_hook(SCRIPT, None, payload, self.L, env=dict(self.env, **(env or {})))

    def verdict(self, tool, ti, **kw):
        r = self.run_tool(tool, ti, **kw)
        self.assertEqual((r.returncode, r.stderr), (0, ''), r.stderr)
        if not r.stdout:
            return None, None
        out = json.loads(r.stdout)['hookSpecificOutput']
        self.assertEqual(out['hookEventName'], 'PreToolUse')
        return out['permissionDecision'], out['permissionDecisionReason']

    def bash(self, cmd, **kw):
        return self.verdict('Bash', {'command': cmd}, **kw)


class OnlyDuringATaskTest(Base):
    CALLS = (('Bash', {'command': 'git commit -m x'}), ('Bash', {'command': 'rm -rf build'}),
             ('Bash', {'command': 'cat .env'}), ('Read', {'file_path': '.env'}),
             ('mcp__plugin_slack_slack__slack_send_message', {'text': 'x'}))

    def test_no_task_gives_no_output(self):
        for tool, ti in self.CALLS:
            with self.subTest(tool=tool, ti=ti):
                self.assertEqual(self.verdict(tool, ti), (None, None))

    def test_task_gives_verdicts(self):
        self.task()
        got = [self.verdict(tool, ti)[0] for tool, ti in self.CALLS]
        self.assertEqual(got, ['ask', 'ask', 'deny', 'deny', 'ask'])

    def test_another_session_gives_no_output(self):
        self.task()
        for tool, ti in self.CALLS:
            with self.subTest(tool=tool, ti=ti):
                self.assertEqual(self.verdict(tool, ti, session='s-other'), (None, None))

    def test_broken_active_gives_no_output(self):
        task = self.task()
        (task.parent / '.active').write_text('phase: 1\n', encoding='utf-8')
        self.assertEqual(self.bash('git commit -m x'), (None, None))

    def test_subagent_of_the_owner_is_judged(self):
        self.task()
        self.assertEqual(self.bash('pip install x', agent_id='a1', agent_type='my-agent:coder')[0], 'ask')
        self.assertEqual(self.verdict('Read', {'file_path': '.env'}, agent_id='a1', agent_type='Explore')[0], 'deny')

    def test_other_hosts_give_no_output(self):
        self.task()
        for host in ('codex', 'antigravity'):
            with self.subTest(host=host):
                r = self.run_tool('Bash', {'command': 'git commit -m x'}, env={'MA_HOST': host})
                self.assertEqual((r.returncode, r.stdout, r.stderr), (0, '', ''))


class BashRulesTest(Base):
    def setUp(self):
        super().setUp()
        self.task()

    def test_ask_forms(self):
        for cmd in ('git commit -m x', 'git push', 'git push origin main', 'git -C /r commit -m x',
                    'git -c k=v push origin main', 'sudo git push', 'sh -c "git commit -m x"',
                    'cd src && git commit -m x', 'rm -rf build', 'npm i', 'npm install left-pad', 'pip install x',
                    'pip3 install x', 'brew install jq', 'ls; pip install x',
                    'git commit -m "$(cat <<\'EOF\'\nmessage\nEOF\n)"'):
            with self.subTest(cmd=cmd):
                decision, reason = self.bash(cmd)
                self.assertEqual(decision, 'ask')
                self.assertTrue(reason.startswith('my-agent permission rules: `Bash('), reason)
                self.assertTrue(reason.endswith(' (G2)'), reason)

    def test_no_verdict(self):
        for cmd in ('', 'ls', 'git status', 'git log --oneline', 'echo git commit', 'rm -r build', 'npm run build',
                    'npm installer', 'pip list', 'cat README.md', 'cat .env.example'):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), (None, None))

    def test_bypass_mode_turns_an_ask_into_a_deny(self):
        decision, reason = self.bash('git commit -m x', permission_mode='bypassPermissions')
        self.assertEqual(decision, 'deny')
        self.assertIn('bypassPermissions', reason)
        for mode in ('default', 'acceptEdits', 'plan', 'auto', 'dontAsk'):
            with self.subTest(mode=mode):
                self.assertEqual(self.bash('git commit -m x', permission_mode=mode)[0], 'ask')

    def test_deny_wins_over_ask(self):
        decision, reason = self.bash('cat .env && git commit -m x')
        self.assertEqual(decision, 'deny')
        self.assertIn('`Read(//**/.env)`', reason)


class ReadRulesTest(Base):
    def setUp(self):
        super().setUp()
        self.task()

    def test_denied_paths(self):
        home = str(Path.home())
        for path in ('.env', 'app/.env.local', '/srv/app/.env.production', 'x/.env.staging.local', 'certs/server.pem',
                     'id.key', 'store.p12', 'CERTS/SERVER.PEM', '~/.ssh/id_ed25519', home + '/.aws/credentials',
                     '~/.netrc', '~/.kube/config', '~/.docker/config.json', '~/.config/gh/hosts.yml'):
            with self.subTest(path=path):
                decision, reason = self.verdict('Read', {'file_path': path})
                self.assertEqual(decision, 'deny')
                self.assertIn(f'a read of `{path}`', reason)
                self.assertTrue(reason.endswith('not allowed during a my-agent task'), reason)

    def test_passing_paths(self):
        for path in ('README.md', '.env.example', '.env.sample', '.env.prod', 'env', 'keys.txt', 'a.pem.txt',
                     '~/.docker/other.json', '~/.sshx/id'):
            with self.subTest(path=path):
                self.assertEqual(self.verdict('Read', {'file_path': path}), (None, None))

    def test_grep_and_glob_path(self):
        self.assertEqual(self.verdict('Grep', {'pattern': 'x', 'path': '~/.ssh'})[0], 'deny')
        self.assertEqual(self.verdict('Glob', {'pattern': '*', 'path': '~/.aws'})[0], 'deny')
        self.assertEqual(self.verdict('Grep', {'pattern': 'x', 'path': 'app/.env'})[0], 'deny')
        self.assertEqual(self.verdict('Grep', {'pattern': 'x'}), (None, None))
        self.assertEqual(self.verdict('Grep', {'pattern': 'x', 'path': 'src'}), (None, None))

    def test_bash_reads(self):
        for cmd in ('cat .env', 'head -n 3 certs/server.pem', 'grep KEY app/.env.local', 'cat < ~/.netrc',
                    'ls ~/.ssh', 'cd app && cat .env'):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd)[0], 'deny')

    def test_a_read_it_cannot_name_passes(self):
        # the stated limit: a path built from a variable, and a subprocess
        self.assertEqual(self.bash('cat "$HOME/.ssh/id"'), (None, None))
        self.assertEqual(self.bash('python3 tool.py'), (None, None))
        self.assertEqual(self.bash("sh -c 'cat \"$HOME\"/x.key'"), (None, None))   # the README example
        self.assertEqual(self.bash("sh -c 'cat x.key'"), (None, None))   # a bare name that is no file is not a path
        (self.L / 'x.key').write_text('k', encoding='utf-8')
        self.assertEqual(self.bash("sh -c 'cat x.key'")[0], 'deny')
        self.assertEqual(self.bash('cat x.key')[0], 'deny')


class OtherToolsTest(Base):
    def setUp(self):
        super().setUp()
        self.task()

    def test_mcp_ask_tools(self):
        for tool in pg.load()['ask']:
            if '(' in tool:
                continue
            with self.subTest(tool=tool):
                decision, reason = self.verdict(tool, {})
                self.assertEqual(decision, 'ask')
                self.assertIn(f'the tool `{tool}`', reason)

    def test_other_tools_pass(self):
        for tool in ('mcp__plugin_slack_slack__slack_read_channel', 'Edit', 'Write', 'Agent'):
            with self.subTest(tool=tool):
                self.assertEqual(self.verdict(tool, {'file_path': '.env'}), (None, None))


class ErrorTest(Base):
    def test_bad_stdin_blocks(self):
        for stdin in ('nope', '[]'):
            r = run_hook(SCRIPT, None, stdin, self.L, env=self.env)
            self.assertEqual(r.returncode, 2)
            self.assertTrue(r.stderr.startswith('permission-guard: '), r.stderr)

    def test_unknown_rule_form_is_an_error(self):
        for rule in ('Edit(//x)', 'Read(src/**)', 'Bash()', 'a b'):
            with self.subTest(rule=rule):
                with self.assertRaises(ValueError):
                    pg.hit(rule, 'Read', ['x'], ['x'], self.L)


class MatcherTest(unittest.TestCase):
    def test_bash_match(self):
        yes = (('git commit:*', 'git commit'), ('git commit:*', 'git commit -m x'), ('git * push*', 'git -C r push'),
               ('git * push*', 'git -C r push origin'), ('npm i:*', 'npm i'), ('ls *', 'ls'), ('ls *', 'ls -l'))
        no = (('git commit:*', 'git commits'), ('git commit:*', 'echo git commit'), ('npm i:*', 'npm install'),
              ('git * push*', 'git push'), ('a * b *', 'a x b'))
        for pattern, text in yes:
            self.assertTrue(pg.bash_match(pattern, text), (pattern, text))
        for pattern, text in no:
            self.assertFalse(pg.bash_match(pattern, text), (pattern, text))

    def test_every_shipped_rule_parses(self):
        rules = pg.load()
        for rule in rules['ask'] + rules['deny']:
            name, pattern = pg.split(rule)
            if name == 'Read':
                pg.read_regex(pattern)


if __name__ == '__main__':
    unittest.main()
