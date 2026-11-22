"""git-guard.py (architecture 4.4 "Git guard") on the three hosts: Claude Code, Codex and Antigravity.

The real hook script runs with a Claude-shaped, a Codex-shaped and an Antigravity-shaped input on a temp task. The
denied literals are built here from pieces: the user settings of a developer machine may deny a Bash command line that
carries them."""
import json
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import CLAUDE_HOOK_ENV, REPO, log_lines, make_task, parse, run_hook
import ma_logline

SID = '019a0000-0000-7000-8000-000000000001'
FIX = REPO / 'tests' / 'fixtures' / 'codex'
SCRIPT = 'git-guard.py'

SKIP = '--no-' + 'verify'                  # the long hook-skipping option
FORCE = '-' + 'f'
LONG_FORCE = '--' + 'force'
LEASE = '--force-with-' + 'lease'
PUSH_F = 'push ' + FORCE
PUSH_LONG = 'push ' + LONG_FORCE
HOSTS = ('claude', 'codex', 'antigravity')

# every deny form of Mock-up Part A, as the text after `git` (name, tail)
DENY_TAILS = (
    ('force first', f'push {FORCE}'),
    ('force last', f'push origin main {FORCE}'),
    ('force in a cluster', f'push -u{FORCE[1:]} origin main'),
    ('long force', f'push {LONG_FORCE}'),
    ('plus refspec', 'push origin +main'),
    ('plus refspec with a target', 'push origin +HEAD:main'),
    ('mirror', 'push --mirror'),
    ('delete refspec', 'push origin :old'),
    ('delete option', 'push --delete origin old'),
    ('delete letter', 'push -d origin old'),
    ('prune', 'push --prune origin'),
    ('commit n', 'commit -n -m x'),
    ('commit n in a cluster', 'commit -anm x'),
    ('skip on commit', f'commit {SKIP} -m x'),
    ('skip on push', f'push {SKIP}'),
    ('skip on merge', f'merge {SKIP} topic'),
    ('hooks path option', '-c core.hooksPath=/dev/null commit -m x'),
    ('hooks path config env option', '--config-env=core.hooksPath=V commit -m x'),
)
WRAPS = (
    ('plain', lambda t: f'git {t}'),
    ('global option', lambda t: f'git -C /r {t}'),
    ('git dir option', lambda t: f'git --git-dir=/r/.git --work-tree /r {t}'),
    ('prefix word', lambda t: f'sudo git {t}'),
    ('sh -c', lambda t: f'sh -c "git {t}"'),
    ('substitution', lambda t: f'echo "$(git {t})"'),
)
HOOKS_PATH_ENV = 'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/x git commit -m y'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.L = self.root / 'proj'
        self.L.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.L)], check=True)
        self.T = make_task(self.L, git=False, session=SID)
        self.env = {'MA_TASKS_DIR': str(self.root / 'agent-tasks'), 'MA_GATE_REPORT_DIR': str(self.root / 'gate-report')}

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, cmd, host, session=SID, agent=False, mode=None):
        if host == 'antigravity':
            d = {'hookEventName': 'PreToolUse', 'conversationId': session,
                 'toolCall': {'id': 'toolu_1', 'name': 'run_command', 'args': {'CommandLine': cmd}}}
            if agent:
                d.update(agentType='my-agent-coder', agentId='sub-1')
            if mode:
                d['permission_mode'] = mode
            return d
        if host == 'codex':
            d = json.loads((FIX / 'hook-pre-tool-use-bash.json').read_text(encoding='utf-8'))
            d.update(session_id=session, tool_input={'command': cmd})
            if agent:
                d.update(agent_id='019a0000-0000-7000-8000-0000000000b1', agent_type='my-agent-coder')
        else:
            d = {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': cmd},
                 'session_id': session}
            if agent:
                d.update(agent_id='a1', agent_type='my-agent:coder')
        if mode:
            d['permission_mode'] = mode
        return d

    def run_host(self, cmd, host='claude', **kw):
        env = dict(self.env, **({'MA_HOST': 'codex'} if host == 'codex' else CLAUDE_HOOK_ENV if host == 'claude' else {}))
        return run_hook(SCRIPT, None, self.payload(cmd, host, **kw), self.L, env=env)

    def outcome(self, r, host):
        """(decision, reason) of a hook run: decision is 'deny', 'ask' or None (no verdict); the exit code and the
        output form are checked for the host."""
        if host == 'antigravity':
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(r.stderr, '')
            d = {'allow': None, 'deny': 'deny', 'force_ask': 'ask'}[out['decision']]
            return d, out.get('reason')
        if host == 'codex' and r.returncode == 2:
            self.assertEqual(r.stdout, '')
            self.assertTrue(r.stderr.startswith('my-agent G2 (git-guard): '), r.stderr)
            return 'ask', r.stderr
        self.assertEqual(r.returncode, 0, r.stderr)
        if not r.stdout:
            return None, None
        h = json.loads(r.stdout)['hookSpecificOutput']
        self.assertEqual(h['hookEventName'], 'PreToolUse')
        return h['permissionDecision'], h['permissionDecisionReason']

    def verdict(self, cmd, host='claude', **kw):
        return self.outcome(self.run_host(cmd, host, **kw), host)

    def ask_lines(self):
        return [parse(x) for x in log_lines(self.T) if ' ask: ' in x]


class DenyTest(Base):
    def test_each_form_denied_on_each_host(self):   # criteria 1 and 5
        for host in HOSTS:
            for name, tail in DENY_TAILS:
                for wrap, make in WRAPS:
                    cmd = make(tail)
                    with self.subTest(host=host, form=name, wrap=wrap):
                        d, reason = self.verdict(cmd, host)
                        self.assertEqual(d, 'deny', cmd)
                        self.assertTrue(reason.startswith('my-agent git guard: '), reason)
                        self.assertTrue(reason.endswith('; not allowed during a my-agent task'), reason)

    def test_hooks_path_environment_variable_denied_on_each_host(self):   # criterion 1
        for host in HOSTS:
            with self.subTest(host=host):
                d, reason = self.verdict(HOOKS_PATH_ENV, host)
                self.assertEqual(d, 'deny')
                self.assertIn('hooks-path override (`GIT_CONFIG_KEY_0=core.hooksPath`)', reason)

    def test_claude_deny_output_is_the_documented_json(self):   # Mock-up Part C
        r = self.run_host('git push origin +main')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {'hookSpecificOutput': {
            'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
            'permissionDecisionReason': 'my-agent git guard: force push with a + refspec (`+main`) in '
                                        '`git push origin +main`; not allowed during a my-agent task'}})
        r = self.run_host('git push origin +main', 'antigravity')
        self.assertEqual(json.loads(r.stdout), {'decision': 'deny', 'reason': 'my-agent git guard: force push with a '
                         '+ refspec (`+main`) in `git push origin +main`; not allowed during a my-agent task'})


class PassTest(Base):
    def test_pass_cases_give_no_verdict_on_each_host(self):   # criteria 2 and 5
        cases = (f'echo x {SKIP}', f'grep -- {SKIP} f', f'git commit -m "fix {PUSH_F}"',
                 f"git commit -m 'push {LONG_FORCE}'", 'git commit -mn', 'git push -of origin main')
        for host in HOSTS:
            for cmd in cases:
                with self.subTest(host=host, cmd=cmd):
                    r = self.run_host(cmd, host)
                    self.assertEqual(self.outcome(r, host), (None, None))
                    if host == 'antigravity':
                        self.assertEqual(json.loads(r.stdout), {'decision': 'allow'})
                    else:
                        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, '', ''))

    def test_empty_and_non_git_commands_pass(self):   # exception: empty command, no git
        for host in HOSTS:
            for cmd in ('', 'ls -la', 'echo git', 'git status'):
                with self.subTest(host=host, cmd=cmd):
                    self.assertEqual(self.verdict(cmd, host), (None, None))

    def test_other_tools_pass(self):
        d = self.payload(f'git {PUSH_F}', 'claude')
        d['tool_name'] = 'Write'
        r = run_hook(SCRIPT, None, d, self.L, env=dict(self.env, **CLAUDE_HOOK_ENV))
        self.assertEqual((r.returncode, r.stdout), (0, ''))


class AskTest(Base):
    def test_lease_is_ask_on_each_host(self):   # criteria 3 and 5
        cmd = f'git push {LEASE} origin main'
        d, reason = self.verdict(cmd, 'claude')
        self.assertEqual((d, reason), ('ask', f'my-agent git guard: force push with lease (`{LEASE}`) in `{cmd}`; '
                                              'allow it only if this is your own request, not the task\'s'))
        d, reason = self.verdict(cmd, 'codex')
        self.assertEqual(d, 'ask')
        self.assertTrue(reason.startswith('my-agent G2 (git-guard): my-agent git guard: '), reason)
        ask = self.ask_lines()
        self.assertEqual(len(ask), 1)
        self.assertEqual((ask[0]['gate'], ask[0]['agent'], ask[0]['tool'], ask[0]['hook'], ask[0]['session']),
                         ('G2', 'main', 'Bash', 'git-guard', SID))
        self.assertRegex(ask[0]['key'], r'^[0-9a-f]{16}$')
        d, reason = self.verdict(cmd, 'antigravity')
        self.assertEqual(d, 'ask')
        r = self.run_host(cmd, 'antigravity')
        self.assertEqual(json.loads(r.stdout)['decision'], 'force_ask')

    def test_lease_forms_are_ask(self):
        for tail in (f'push {LEASE}', f'push {LEASE}=main', f'push {LEASE}=main:abc1234 origin', 'push --force-w'):
            with self.subTest(tail=tail):
                self.assertEqual(self.verdict(f'git {tail}')[0], 'ask')

    def test_lease_with_a_stricter_form_is_deny_on_each_host(self):   # criterion 3
        for host in HOSTS:
            for extra in (FORCE, '+main', '--mirror', '--delete'):
                with self.subTest(host=host, extra=extra):
                    self.assertEqual(self.verdict(f'git push {LEASE} {extra} origin main', host)[0], 'deny')

    def test_unparsed_commit_shape_is_ask(self):   # exception: a command that does not tokenize
        for host in HOSTS:
            with self.subTest(host=host):
                d, reason = self.verdict('git commit -m "x', host)
                self.assertEqual(d, 'ask')
                self.assertIn('cannot parse the command', reason)
            with self.subTest(host=host, form='visible'):
                self.assertEqual(self.verdict(f'git {PUSH_F} "x', host)[0], 'deny')

    def test_substitution_in_a_slot_is_ask(self):
        d, reason = self.verdict('git push origin $(git branch --show-current)')
        self.assertEqual(d, 'ask')
        self.assertIn('cannot tell what `$(git branch --show-current)` expands to', reason)

    def test_codex_ask_released_once_by_an_answer(self):   # exception: a G2 ask with nobody to answer it
        cmd = f'git push {LEASE}'
        self.assertEqual(self.verdict(cmd, 'codex')[0], 'ask')
        key = self.ask_lines()[0]['key']
        with open(self.T / 'run-log.md', 'a', encoding='utf-8') as f:
            f.write(ma_logline.format_line('answer', [('gate', 'G2'), ('tool', 'Bash'), ('key', key),
                                                      ('result', 'allowed')]) + '\n')
        r = self.run_host(cmd, 'codex')
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, '', ''))
        release = [parse(x) for x in log_lines(self.T) if ' release: ' in x]
        self.assertEqual([(x['hook'], x['tool'], x['key']) for x in release], [('git-guard', 'Bash', key)])
        self.assertEqual(self.verdict(cmd, 'codex')[0], 'ask')   # one answer releases one call
        self.assertEqual(len(self.ask_lines()), 2)

    def test_codex_ask_names_the_answer_command(self):
        d, reason = self.verdict(f'git push {LEASE}', 'codex')
        self.assertIn('G2 popup', reason)
        m = re.search(r'record the answer with (.*?) \(result=denied for Deny\)', reason, re.S)
        self.assertTrue(m, reason)
        self.assertIn('run-log.py', shlex.split(m.group(1))[1])


class ModeTest(Base):
    def test_subagent_ask_becomes_deny_on_each_host(self):   # exception: a G2 ask with nobody to answer it
        for host in HOSTS:
            for cmd in (f'git push {LEASE}', 'git commit -m "x'):
                with self.subTest(host=host, cmd=cmd):
                    d, reason = self.verdict(cmd, host, agent=True)
                    self.assertEqual(d, 'deny')
                    self.assertTrue(reason.endswith('; my-agent workers do not push or commit, so it is denied: '
                                                    'report it to L1'), reason)
        self.assertEqual(self.ask_lines(), [])   # nothing reached the Codex G2 path

    def test_bypass_mode_ask_becomes_deny(self):
        for host in ('claude', 'codex', 'antigravity'):
            with self.subTest(host=host):
                d, reason = self.verdict(f'git push {LEASE}', host, mode='bypassPermissions')
                self.assertEqual(d, 'deny')
                self.assertTrue(reason.endswith('; the bypassPermissions mode may run an ask without the G2 dialog, '
                                                'so it is denied'), reason)

    def test_auto_mode_keeps_ask(self):
        for mode in ('auto', 'default', 'acceptEdits', 'plan', 'dontAsk'):
            with self.subTest(mode=mode):
                self.assertEqual(self.verdict(f'git push {LEASE}', 'claude', mode=mode)[0], 'ask')

    def test_deny_does_not_depend_on_the_mode(self):
        for mode in ('auto', 'default', 'plan', 'bypassPermissions'):
            with self.subTest(mode=mode):
                self.assertEqual(self.verdict(f'git {PUSH_F}', 'claude', mode=mode)[0], 'deny')


class CallerTest(Base):
    def test_no_active_task_no_verdict(self):   # criterion 6
        (self.L / '.my-agent' / '.active').unlink()
        for host in HOSTS:
            with self.subTest(host=host):
                self.assertEqual(self.verdict(f'git {PUSH_F}', host), (None, None))

    def test_broken_active_gives_no_output(self):   # the other gate hooks warn; this one stays quiet
        (self.L / '.my-agent' / '.active').write_text('phase: 1\n', encoding='utf-8')
        r = self.run_host(f'git {PUSH_F}')
        self.assertEqual((r.returncode, r.stdout), (0, ''), r.stderr)

    def test_other_session_no_verdict(self):   # criterion 6
        for host in HOSTS:
            with self.subTest(host=host):
                self.assertEqual(self.verdict(f'git {PUSH_F}', host, session='another-session'), (None, None))

    def test_owner_main_session_is_judged(self):   # criterion 6
        for host in HOSTS:
            with self.subTest(host=host):
                self.assertEqual(self.verdict(f'git {PUSH_F}', host)[0], 'deny')

    def test_owner_subagent_is_judged(self):   # criterion 6
        for host in HOSTS:
            with self.subTest(host=host):
                self.assertEqual(self.verdict(f'git {PUSH_F}', host, agent=True)[0], 'deny')

    def test_subagent_of_another_session_no_verdict(self):
        for host in HOSTS:
            with self.subTest(host=host):
                self.assertEqual(self.verdict(f'git {PUSH_F}', host, session='another-session', agent=True),
                                 (None, None))


class CrashTest(Base):
    def test_invalid_input_blocks(self):   # the crash rule
        for raw in ('not json', '[]', '{', json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 5},
                                                       'session_id': SID, 'turn_id': 't'})):
            with self.subTest(raw=raw):
                r = run_hook(SCRIPT, None, raw, self.L, env=dict(self.env, **CLAUDE_HOOK_ENV))
                self.assertEqual((r.returncode, r.stdout), (2, ''))
                self.assertTrue(r.stderr.startswith('git-guard: '), r.stderr)


class ReasonTest(Base):
    def test_reason_names_the_form(self):   # the UX line
        cases = (
            (f'git {PUSH_F} origin main', f'force push (`{FORCE}`) in `git {PUSH_F} origin main`'),
            ('git push origin :old', 'push that deletes remote refs (`:old`) in `git push origin :old`'),
            ('git commit -n -m x', 'commit that skips hooks (`-n`) in `git commit -n -m x`'),
            (f'git commit {SKIP} -m x', f'hook-skipping option (`{SKIP}`) in `git commit {SKIP} -m x`'),
            ('git -c core.hooksPath=/dev/null commit -m x',
             'hooks-path override (`core.hooksPath`) in `git -c core.hooksPath=/dev/null commit -m x`'),
            ('git push --mirror', 'mirror push (`--mirror`) in `git push --mirror`'),
        )
        for cmd, want in cases:
            with self.subTest(cmd=cmd):
                d, reason = self.verdict(cmd)
                self.assertEqual(d, 'deny')
                self.assertTrue(reason.startswith('my-agent git guard: ' + want), reason)
        self.assertEqual(reason.count('\n'), 0)

    def test_first_deny_wins_over_an_ask(self):
        d, reason = self.verdict(f'git push {LEASE} && git {PUSH_F}')
        self.assertEqual(d, 'deny')
        self.assertIn(f'force push (`{FORCE}`)', reason)


if __name__ == '__main__':
    unittest.main()
