"""Antigravity host support: manifest/hooks/agents build, ma_host adaptation, hooks, models and host mapping."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import L4, REPO, log_lines, make_task, parse, run_hook, run_script
import ma_host
import ma_models
import ma_schema

BUILD = L4 / 'scripts' / 'build-antigravity.py'
MODELS = L4 / 'scripts' / 'agent-models.py'
HOSTS_AGY = REPO / 'l1-orchestration' / 'hosts-antigravity.md'


def agy_payload(event, tool_name=None, args=None, session='conv-1', cwd=None, agent_type=None, agent_id=None,
                artifact_dir=None):
    d = {'hookEventName': event, 'conversationId': session}
    if cwd is not None:
        d['cwd'] = str(cwd)
    if tool_name is not None:
        d['toolCall'] = {'id': 'toolu_1', 'name': tool_name, 'args': args or {}}
    if agent_type is not None:
        d['agentType'] = agent_type
    if agent_id is not None:
        d['agentId'] = agent_id
    if artifact_dir is not None:
        d['artifactDirectoryPath'] = str(artifact_dir)
    return d


class AntigravityBuildTest(unittest.TestCase):
    def run_build(self, *args, root=None):
        cmd = [sys.executable, str(BUILD), *args]
        if root:
            cmd += ['--root', str(root)]
        return subprocess.run(cmd, capture_output=True, text=True)

    def copy_tree(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        for sub in ('l2-design-judge/agents', 'l3-workers/agents', '.claude-plugin',
                    'antigravity', '.antigravity-plugin', 'rules'):
            src = REPO / sub
            if src.is_dir():
                shutil.copytree(src, tmp / sub)
        if (REPO / 'hooks.json').is_file():
            shutil.copy2(REPO / 'hooks.json', tmp / 'hooks.json')
        return tmp

    def test_check_passes(self):
        r = self.run_build('--check')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_manifest_matches_claude(self):
        claude = json.loads((REPO / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))
        agy = json.loads((REPO / '.antigravity-plugin' / 'plugin.json').read_text(encoding='utf-8'))
        for key in ('name', 'version', 'description', 'author'):
            self.assertEqual(agy[key], claude[key])
        self.assertNotIn('agents', agy)
        self.assertNotIn('hooks', agy)

    def test_root_hooks_json_shape_and_targets(self):
        data = json.loads((REPO / 'hooks.json').read_text(encoding='utf-8'))
        self.assertIn('my-agent', data)
        spec = data['my-agent']
        self.assertEqual(set(spec), {'PreToolUse', 'PostToolUse', 'SessionStart'})
        for event in ('PreToolUse', 'PostToolUse'):
            for group in spec[event]:
                for h in group['hooks']:
                    self.assertEqual(h['type'], 'command')
                    script = h['command'].split()[1]
                    self.assertTrue((REPO / script).is_file(), script)
        for h in spec['SessionStart']:
            self.assertEqual(h['type'], 'command')
            script = h['command'].split()[1]
            self.assertTrue((REPO / script).is_file(), script)

    def test_ten_unique_agents_no_root_agents_folder(self):
        self.assertFalse((REPO / 'agents').exists(), 'root agents/ would duplicate agents in Claude Code')
        files = sorted((REPO / 'antigravity' / 'agents').glob('*.md'))
        self.assertEqual(len(files), 10)
        for f in files:
            text = f.read_text(encoding='utf-8')
            self.assertTrue(text.startswith('---\n'), f.name)
            self.assertIn('\nmodel: inherit\n', text, f.name)
            self.assertIn('\nsubagent: true\n', text, f.name)
            self.assertNotIn('/Users/', text, f.name)

    def test_write_removes_stray_agent_file(self):
        tmp = self.copy_tree()
        stray = tmp / 'antigravity' / 'agents' / 'old.md'
        stray.write_text('---\nname: old\n---\n', encoding='utf-8')
        self.assertEqual(self.run_build('--check', root=tmp).returncode, 1)
        self.assertEqual(self.run_build('--write', root=tmp).returncode, 0)
        self.assertFalse(stray.exists())
        self.assertEqual(self.run_build('--check', root=tmp).returncode, 0)

    def test_install_and_check_agents_lifecycle(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        r = self.run_build('--check-agents', '--agy-home', str(home))
        self.assertEqual(r.returncode, 1)
        self.assertIn('Antigravity agents: not installed', r.stdout)

        r = self.run_build('--install-agents', '--agy-home', str(home))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('Antigravity agents: installed 10 (', r.stdout)
        installed = sorted((home / 'agents').glob('*.md'))
        self.assertEqual(len(installed), 10)
        for p in installed:
            text = p.read_text(encoding='utf-8')
            self.assertTrue(text.startswith('---\n'), p.name)
            self.assertIn('<!-- my-agent ', text, p.name)

        r = self.run_build('--check-agents', '--agy-home', str(home))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        # User-owned file without marker is never overwritten
        custom = home / 'agents' / 'my-agent-coder.md'
        custom.write_text('---\nname: my-agent-coder\n---\ncustom body\n', encoding='utf-8')
        r = self.run_build('--install-agents', '--agy-home', str(home))
        self.assertEqual(r.returncode, 1)
        self.assertIn('skipped: not generated by my-agent: my-agent-coder.md', r.stdout)
        self.assertIn('custom body', custom.read_text(encoding='utf-8'))

    def test_agy_cli_validates_plugin_strictly(self):
        if not shutil.which('agy'):
            self.skipTest('agy CLI not on PATH')
        r = subprocess.run(['agy', 'plugin', 'validate', '--strict', str(REPO)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class AntigravityHostAdapterTest(unittest.TestCase):
    def test_detect_and_adapt_tools(self):
        p = agy_payload('PreToolUse', 'run_command', {'CommandLine': 'git status'}, cwd='/tmp/proj')
        c = ma_host.parse(json.dumps(p))
        self.assertEqual(c.host, 'antigravity')
        self.assertEqual(c.inps[0]['tool_name'], 'Bash')
        self.assertEqual(c.inps[0]['tool_input'], {'command': 'git status'})
        self.assertEqual(c.inps[0]['session_id'], 'conv-1')

        p_edit = agy_payload('PreToolUse', 'edit_file', {'Path': 'a.py', 'Target': 'x', 'Replacement': 'y'})
        ti = ma_host.parse(json.dumps(p_edit)).inps[0]
        self.assertEqual((ti['tool_name'], ti['tool_input']),
                         ('Edit', {'file_path': 'a.py', 'old_string': 'x', 'new_string': 'y'}))

        p_write = agy_payload('PreToolUse', 'write_file', {'Path': 'b.py', 'Content': 'hi'})
        ti = ma_host.parse(json.dumps(p_write)).inps[0]
        self.assertEqual((ti['tool_name'], ti['tool_input']), ('Write', {'file_path': 'b.py', 'content': 'hi'}))

        p_sub = agy_payload('PreToolUse', 'invoke_subagent',
                            {'TypeName': 'my-agent-coder', 'Role': 'Coder', 'Prompt': 'Work unit: u1',
                             'Model': 'pro', 'Workspace': 'share'})
        ti = ma_host.parse(json.dumps(p_sub)).inps[0]
        self.assertEqual(ti['tool_name'], 'Agent')
        self.assertEqual(ti['tool_input']['subagent_type'], 'my-agent:coder')
        self.assertEqual(ti['tool_input']['model'], 'pro')
        self.assertEqual(ti['tool_input']['isolation'], 'worktree')

        p_wf = agy_payload('PreToolUse', 'run_workflow', {'Description': 'fanout'})
        self.assertEqual(ma_host.parse(json.dumps(p_wf)).inps[0]['tool_name'], 'Workflow')

    def test_malformed_inputs_raise(self):
        for bad in (
            agy_payload('PreToolUse'),
            agy_payload('PreToolUse', 'run_command', {}),
            agy_payload('PreToolUse', 'write_file', {}),
            agy_payload('PreToolUse', 'invoke_subagent', {'Prompt': 'hi'}),
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ma_host.parse(json.dumps(bad))

    def test_emit_antigravity_decisions(self):
        call = ma_host.Call('antigravity', [], False)
        cases = (
            (None, {'decision': 'allow'}),
            ({'hookSpecificOutput': {'permissionDecision': 'deny', 'permissionDecisionReason': 'no'}},
             {'decision': 'deny', 'reason': 'no'}),
            ({'hookSpecificOutput': {'permissionDecision': 'ask', 'permissionDecisionReason': 'confirm?'}},
             {'decision': 'force_ask', 'reason': 'confirm?'}),
            ({'systemMessage': 'warn'}, {'decision': 'allow', 'reason': 'warn'}),
        )
        for out, expected in cases:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(ma_host.emit(call, out), 0)
            self.assertEqual(json.loads(buf.getvalue()), expected)

    def test_env_host_session_and_main_model(self):
        clean = {k: v for k, v in os.environ.items()
                 if k not in ('MA_HOST', 'CLAUDECODE', 'CLAUDE_CODE_SESSION_ID', 'CODEX_THREAD_ID',
                              'ANTIGRAVITY_AGENT', 'ANTIGRAVITY_CONVERSATION_ID', 'CLAUDE_PLUGIN_ROOT', 'PLUGIN_ROOT')}
        with mock.patch.dict(os.environ, {**clean, 'ANTIGRAVITY_AGENT': '1',
                                          'ANTIGRAVITY_CONVERSATION_ID': 'conv-42',
                                          'PLUGIN_ROOT': '/tmp/plug'}, clear=True):
            self.assertEqual(ma_host.env_host(), 'antigravity')
            self.assertEqual(ma_host.session_id(), 'conv-42')
            self.assertEqual(ma_host.plugin_root('/fallback'), Path('/tmp/plug'))
        self.assertEqual(ma_schema.antigravity_family('gemini-4-neon'), 'gemini-4-neon')
        self.assertFalse(ma_host.main_mismatch('gemini-4-neon'))
        self.assertEqual(ma_host.main_family('gemini-4-neon'), 'gemini-4-neon')


class AntigravityHooksEndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.data = self.root / 'data'
        self.proj = self.root / 'proj'
        self.proj.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.proj)], check=True)
        self.task = make_task(self.proj, phase='2', session='conv-1', git=False)
        self.env = {'MA_DATA_DIR': str(self.data), 'PLUGIN_ROOT': str(REPO)}

    def tearDown(self):
        self.tmp.cleanup()

    def test_session_notice_injects_system_message(self):
        p = agy_payload('SessionStart', session='conv-1', cwd=self.proj)
        r = run_hook('session-notice.py', None, p, self.proj, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        msg = data['injectSteps'][0]['systemMessage']['systemMessage']
        self.assertIn('my-agent on Antigravity:', msg)
        self.assertIn('hosts-antigravity.md', msg)
        self.assertIn('session conv-1', msg)
        self.assertIn('Unfinished my-agent task `261025-probe-task`', msg)

    def test_scope_guard_fast_path_and_deny(self):
        main_call = agy_payload('PreToolUse', 'read_file', {'Path': str(self.proj / 'a.txt')}, cwd=self.proj)
        r = run_hook('scope-guard.py', None, main_call, self.proj, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {'decision': 'allow'})

        # A Claude Code payload whose tool_input text mentions "toolCall" must stay silent (not emit Antigravity JSON)
        claude_call = {'hook_event_name': 'PreToolUse', 'tool_name': 'Write',
                       'tool_input': {'file_path': str(self.proj / 'note.txt'), 'content': 'has "toolCall" text'}}
        r = run_hook('scope-guard.py', None, claude_call, self.proj,
                     env={'MA_DATA_DIR': str(self.data), 'CLAUDECODE': '1'})
        self.assertEqual((r.returncode, r.stdout), (0, ''), r.stderr)

        secret_call = agy_payload('PreToolUse', 'read_file', {'Path': str(self.proj / '.env')},
                                  cwd=self.proj, agent_type='my-agent-explorer', agent_id='sub-1')
        r = run_hook('scope-guard.py', None, secret_call, self.proj, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out['decision'], 'deny')
        self.assertIn('Secret paths', out['reason'])

    def architect_call(self, tool, args):
        p = agy_payload('PreToolUse', tool, args, cwd=self.proj, agent_type='my-agent-architect', agent_id='sub-1')
        r = run_hook('scope-guard.py', None, p, self.proj, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_scope_guard_architect_single_replace_tools(self):
        plan = self.task / 'plan.md'
        plan.write_text('# Plan\n\n## Work units\n', encoding='utf-8')
        other = self.proj / 'src.py'
        other.write_text('x\n', encoding='utf-8')
        forms = (('replace_file_content', 'TargetFile', 'TargetContent', 'ReplacementContent'),
                 ('edit_file', 'Path', 'Target', 'Replacement'))
        for tool, path_key, old_key, new_key in forms:
            with self.subTest(tool=tool):
                out = self.architect_call(tool, {path_key: str(plan), old_key: '## Work units', new_key: '## Units'})
                self.assertNotEqual(out['decision'], 'deny', out)
                out = self.architect_call(tool, {path_key: str(other), old_key: 'x', new_key: 'y'})
                self.assertEqual(out['decision'], 'deny')
                self.assertIn('Outside the write scope', out['reason'])

    def test_scope_guard_architect_multi_replace_denied(self):
        plan = self.task / 'plan.md'
        plan.write_text('# Plan\n\n## Work units\n', encoding='utf-8')
        out = self.architect_call('multi_replace_file_content', {'TargetFile': str(plan), 'ReplacementChunks': []})
        self.assertEqual(out['decision'], 'deny')
        self.assertIn('Write', out['reason'])

    def test_plan_approved_check_denies_coder_and_asks_outside_write(self):
        coder_call = agy_payload('PreToolUse', 'invoke_subagent',
                                 {'TypeName': 'my-agent-coder', 'Prompt': 'code'}, cwd=self.proj)
        r = run_hook('plan-approved-check.py', None, coder_call, self.proj, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['decision'], 'deny')

        explorer_call = agy_payload('PreToolUse', 'invoke_subagent',
                                    {'TypeName': 'my-agent-explorer', 'Prompt': 'look'}, cwd=self.proj)
        r = run_hook('plan-approved-check.py', None, explorer_call, self.proj, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {'decision': 'allow'})

        outside = agy_payload('PreToolUse', 'write_file',
                              {'Path': str(self.proj / 'src.py'), 'Content': 'x'}, cwd=self.proj)
        r = run_hook('plan-approved-check.py', None, outside, self.proj, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['decision'], 'force_ask')

    def test_verdict_fresh_check_asks_stale_commit_and_denies_stale_deliver(self):
        commit = agy_payload('PreToolUse', 'run_command', {'CommandLine': 'git commit -m test'}, cwd=self.proj)
        r = run_hook('verdict-fresh-check.py', None, commit, self.proj, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['decision'], 'force_ask')

        deliver = agy_payload('PreToolUse', 'write_file',
                              {'Path': str(self.task / 'deliverable' / 'out.md'), 'Content': 'x'}, cwd=self.proj)
        r = run_hook('verdict-fresh-check.py', None, deliver, self.proj, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['decision'], 'deny')

    def test_subagent_and_permission_hooks_return_valid_json(self):
        sub = agy_payload('PreToolUse', 'invoke_subagent',
                          {'TypeName': 'my-agent-explorer', 'Prompt': 'Work unit: u1\nexplore', 'Model': 'flash'},
                          cwd=self.proj)
        r = run_hook('subagent-log.py', 'call', sub, self.proj, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {'decision': 'allow'})
        lines = log_lines(self.task)
        self.assertEqual(len(lines), 1)
        f = parse(lines[0])
        self.assertEqual((f['agent'], f['model'], f['unit']), ('my-agent:explorer', 'flash', 'u1'))

        post = agy_payload('PostToolUse', 'run_command', {'CommandLine': 'ls'}, cwd=self.proj)
        r = run_hook('permission-log.py', 'answer', post, self.proj, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {})


class AntigravityModelsAndDocsTest(unittest.TestCase):
    def test_agent_models_antigravity_section(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = Path(tmp.name)
        (data / 'agent-models.json').write_text(json.dumps({
            'antigravity': {
                'dev': {
                    'fast': {'explorer': {'model': 'flash'}, 'coder': {'model': 'pro'}, 'writer': {'model': 'inline'}},
                }
            }
        }), encoding='utf-8')
        r = run_script(MODELS, 'show', '--profile', 'dev', '--preset', 'fast', '--data-dir', str(data),
                       env={'MA_HOST': 'antigravity'}, drop=('MA_DATA_DIR',))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('antigravity section', r.stdout)
        self.assertIn('explorer        model=flash', r.stdout)
        self.assertIn('writer          model=inline', r.stdout)

    def test_hosts_antigravity_doc_size_and_rows(self):
        text = HOSTS_AGY.read_text(encoding='utf-8')
        self.assertLess(len(text), 11500)
        for word in ('ask_question', 'invoke_subagent', 'my-agent-<role>', 'run_command', 'edit_file', 'write_file',
                     'read_file', 'ANTIGRAVITY_CONVERSATION_ID', 'force_ask', 'build-antigravity.py'):
            self.assertIn(word, text)
        for bad in ('fallback', 'workaround'):
            self.assertNotIn(bad, text.lower())

    def test_isolation_row_says_no_unit_copies(self):
        """Criterion 3: Antigravity does not use unit copies; coder units of one parallel group run one at a time."""
        row = next(l for l in HOSTS_AGY.read_text(encoding='utf-8').splitlines() if l.startswith('| `isolation: "worktree"`'))
        for text in ('does not use unit copies', 'coder units of one parallel group one at a time in the main tree',
                     '"inherit"'):
            self.assertIn(text, row)

    def test_background_research_on_websearch_row(self):
        row = next(l for l in HOSTS_AGY.read_text(encoding='utf-8').splitlines() if l.startswith('| `WebSearch`'))
        self.assertIn('Background research', row)

    def test_judges_row_follows_the_cited_source(self):
        """Criterion 8 (exception: Antigravity cannot run two subagents at once): together only with an https source, else one after the other and why."""
        row = next(l for l in HOSTS_AGY.read_text(encoding='utf-8').splitlines() if l.startswith('| Verifier and reviewer'))
        self.assertIn('`accept.md` 4A item 3', row)
        if 'one after the other' in row:
            self.assertIn('no cited Antigravity source shows two subagents running at once', row)
            self.assertNotIn('https://', row)
        else:
            self.assertRegex(row, r'two `invoke_subagent` calls in one turn')
            self.assertRegex(row, r'https://[^ )"]+')
            self.assertIn('invoke multiple subagents concurrently', row)


if __name__ == '__main__':
    unittest.main()
