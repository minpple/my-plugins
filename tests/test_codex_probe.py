"""tools/codex-probe/probe.py: `snapshot` with a fake codex, `check install`, the skills-listing helpers, the capability table
and the plugin's real hooks on Codex inputs."""
import ast
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROBE = REPO / 'tools' / 'codex-probe' / 'probe.py'
FIXS = REPO / 'tests' / 'fixtures' / 'codex-probe'
CAPS = REPO / 'tools' / 'codex-probe' / 'capabilities.json'

spec = importlib.util.spec_from_file_location('codex_probe', PROBE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

FAKE = '''#!{py}
import json, os, sys
with open({log!r}, 'a') as f:
    f.write(json.dumps({{'argv': sys.argv[1:], 'cwd': os.getcwd()}}) + '\\n')
if sys.argv[1:2] == ['--version']:
    print('codex-cli 9.9.9')
elif sys.argv[1:2] == ['exec']:
    print(json.dumps({{'type': 'thread.started'}}))
else:
    print('listing ' + ' '.join(sys.argv[1:]))
'''


def make_fake(tmp: Path):
    log = tmp / 'fake-calls.jsonl'
    script = tmp / 'fake-codex'
    script.write_text(FAKE.format(py=sys.executable, log=str(log)), encoding='utf-8')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, log


def calls(log: Path):
    return [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]


def run_main(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = probe.main(argv)
    return code, out.getvalue()


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fake, self.log = make_fake(self.tmp)

    def test_snapshot_read_only_subcommands(self):
        out = self.tmp / 'snap'
        code = probe.main(['--codex', str(self.fake), 'snapshot', '--out', str(out)])
        self.assertEqual(code, 0)
        argvs = [c['argv'] for c in calls(self.log)]
        self.assertEqual(argvs, [['--version'], ['plugin', 'list'], ['plugin', 'marketplace', 'list']])
        self.assertIn('9.9.9', (out / 'codex-version.txt').read_text(encoding='utf-8'))
        self.assertIn('listing plugin list', (out / 'plugin-list.txt').read_text(encoding='utf-8'))
        self.assertTrue((out / 'marketplace-list.txt').is_file())

    def test_removed_subcommands_give_the_unknown_command_error(self):
        # These subcommands were removed on purpose; the names below pin the argparse error, they are not references.
        for argv in (['kit', 'x'], ['run', 'x', 'hooks'], ['summary', 'x', '--out', 'y'], ['findings', 'x', '--out', 'y'],
                     ['report', 'x', '--findings', 'f', '--out', 'y'], ['e2e-setup', 'x'], ['check', 'findings', 'x']):
            err = io.StringIO()
            with redirect_stderr(err), self.assertRaises(SystemExit) as raised:
                probe.main(argv)
            self.assertEqual(raised.exception.code, 2, argv)
            self.assertIn('invalid choice', err.getvalue(), argv)
        self.assertEqual(calls(self.log) if self.log.exists() else [], [])


APPROVED_PLAN = '# Plan\n\n## Approval\n- Approved 2026-11-04 00:55 G1b\n'

HOOKS = REPO / 'plugins' / 'my-agent' / 'l4-tools-guards' / 'hooks'
CODEX_FIX = REPO / 'plugins' / 'my-agent' / 'tests' / 'fixtures' / 'codex'
MAIN_SESSION = '019a0000-0000-7000-8000-000000000001'
FOREIGN_SESSION = '019a0000-0000-7000-8000-0000000000ee'


class RealHookAssumptionsTest(unittest.TestCase):
    """The Assumes lines of the Codex probe, against the real hook scripts on a temp approved task."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp.resolve()
        self.repo = self.root / 'repo'
        self.agent = self.repo / '.my-agent'
        (self.agent / '260101-demo').mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        (self.agent / '.active').write_text(
            f'task: 260101-demo\nphase: 5\nsession: {MAIN_SESSION}\nstarted: 2026-01-01 09:00\n', encoding='utf-8')
        self.plan = self.agent / '260101-demo' / 'plan.md'
        self.plan.write_text(APPROVED_PLAN, encoding='utf-8')
        self.env = dict(os.environ, MA_TASKS_DIR=str(self.root / 'data'))

    def fixture(self, name, **over):
        d = json.loads((CODEX_FIX / name).read_text(encoding='utf-8'))
        d.update(over, cwd=str(self.repo))
        return d

    def hook(self, script, payload):
        return subprocess.run([sys.executable, str(HOOKS / script)], input=json.dumps(payload), capture_output=True,
                              text=True, cwd=self.repo, env=self.env, timeout=30)

    def spawn(self, agent, session):
        d = self.fixture('hook-pre-tool-use-spawn-agent.json', session_id=session)
        d['tool_input'] = dict(d['tool_input'], agent_type=agent)
        return d

    def test_foreign_session_spawn_passes_plan_approved_check(self):
        self.plan.write_text('# Plan\n', encoding='utf-8')   # not approved: the control must be denied
        control = self.hook('plan-approved-check.py', self.spawn('my-agent-coder', MAIN_SESSION))
        self.assertIn('deny', control.stdout)
        r = self.hook('plan-approved-check.py', self.spawn('my-agent-coder', FOREIGN_SESSION))
        self.assertEqual((r.returncode, r.stdout), (0, ''), r.stderr)
        self.plan.write_text(APPROVED_PLAN, encoding='utf-8')
        r = self.hook('plan-approved-check.py', self.spawn('my-agent-explorer', FOREIGN_SESSION))
        self.assertEqual((r.returncode, r.stdout), (0, ''), r.stderr)

    def test_explorer_apply_patch_denied_with_guard_line(self):
        d = self.fixture('hook-pre-tool-use-worker-file-change.json', session_id=FOREIGN_SESSION,
                         agent_type='my-agent-explorer')
        d['tool_input'] = {'command': '*** Begin Patch\n*** Add File: role-check.txt\n+x\n*** End Patch'}
        r = self.hook('scope-guard.py', d)
        self.assertEqual(r.returncode, 2, r.stderr)
        lines = [x for x in (self.agent / '260101-demo' / 'run-log.md').read_text(encoding='utf-8').splitlines()
                 if ' guard: ' in x]
        self.assertEqual(len(lines), 1)
        self.assertIn('hook=scope-guard', lines[0])
        self.assertIn('agent=my-agent:explorer', lines[0])
        self.assertIn('decision=deny', lines[0])

    def coder_patch(self, path):
        d = self.fixture('hook-pre-tool-use-worker-file-change.json', session_id=FOREIGN_SESSION,
                         agent_type='my-agent-coder')
        d['tool_input'] = {'command': f'*** Begin Patch\n*** Add File: {path}\n+x\n*** End Patch'}
        return d

    def guard_lines(self):
        log = self.agent / '260101-demo' / 'run-log.md'
        return [x for x in log.read_text(encoding='utf-8').splitlines() if ' guard: ' in x] if log.is_file() else []

    def test_coder_apply_patch_outside_location_denied_with_guard_line(self):
        r = self.hook('scope-guard.py', self.coder_patch(self.root / 'role-check.txt'))
        self.assertEqual(r.returncode, 2, r.stderr)
        lines = self.guard_lines()
        self.assertEqual(len(lines), 1)
        for part in ('hook=scope-guard', 'agent=my-agent:coder', 'decision=deny'):
            self.assertIn(part, lines[0])

    def test_coder_apply_patch_inside_location_let_through(self):
        r = self.hook('scope-guard.py', self.coder_patch(self.repo / 'src-new.txt'))
        self.assertEqual((r.returncode, r.stdout), (0, ''), r.stderr)
        self.assertEqual(self.guard_lines(), [])

    def test_session_notice_leaves_active_unchanged(self):
        active = self.agent / '.active'
        before = active.read_bytes()
        r = self.hook('session-notice.py', self.fixture('hook-session-start.json', session_id=FOREIGN_SESSION))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(active.read_bytes(), before)


MANIFEST = {'name': 'my-agent', 'version': '0.8.0', 'skills': ['./']}
LIST_FORM = """Marketplace `my-plugins`
{root}/.agents/plugins/marketplace.json

PLUGIN                    STATUS              VERSION  SOURCE
my-agent@my-plugins       {status}  {version}    {root}/plugins/my-agent
my-agent-tray@my-plugins  not installed                {root}/plugins/my-agent-tray

Marketplace `other`
/x/other/.agents/plugins/marketplace.json

PLUGIN       STATUS         VERSION  SOURCE
a@other      not installed  1.0.0    /x
"""


class InstallCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def install_folder(self, root='/Users/x/repo', status='installed, enabled', version='0.8.0', cache=True,
                       skills='my-agent:my-agent\nmy-agent:monitor\n', cached=None, cache_version='0.8.0', source='prompt-input'):
        folder = self.tmp / 'install'
        shutil.rmtree(folder, True)
        (folder / 'cache' / cache_version).mkdir(parents=True)
        (folder / 'plugin-list.txt').write_text(LIST_FORM.format(root=root, status=status, version=version), encoding='utf-8')
        (folder / 'skills-list.txt').write_text(skills, encoding='utf-8')
        if source is not None:
            (folder / 'skills-source.txt').write_text(source + '\n', encoding='utf-8')
        if cache:
            (folder / 'cache' / cache_version / 'codex-plugin.json').write_text(json.dumps(cached or MANIFEST), encoding='utf-8')
        return folder

    def repo_root(self, manifest=MANIFEST):
        root = self.tmp / 'repo-root'
        (root / 'plugins' / 'my-agent' / '.codex-plugin').mkdir(parents=True, exist_ok=True)
        (root / 'plugins' / 'my-agent' / '.codex-plugin' / 'plugin.json').write_text(json.dumps(manifest), encoding='utf-8')
        return root

    def check_install(self, folder, root, *extra):
        return probe.main(['check', 'install', str(folder), '--root', str(root)] + list(extra))

    def test_check_install(self):
        root = self.repo_root()
        # the list names a made-up root; --root must equal it, so write the list with the real temp root
        ok = self.install_folder(root=str(root))
        self.assertEqual(self.check_install(ok, root), 0)
        self.assertEqual(self.check_install(ok, root, '--version', '0.8.0'), 0)
        self.assertEqual(self.check_install(ok, '/Users/x/other'), 1)
        self.assertEqual(self.check_install(self.install_folder(root=str(root), status='installed, disabled'), root), 1)
        self.assertEqual(self.check_install(self.install_folder(root=str(root), skills='my-agent\n'), root), 1)
        self.assertEqual(self.check_install(self.install_folder(root=str(root), skills='my-agent:monitor\n'), root), 1)
        self.assertEqual(self.check_install(self.install_folder(root=str(root), cache=False), root), 1)
        self.assertEqual(self.check_install(self.install_folder(root=str(root), cached={**MANIFEST, 'description': 'x'}), root), 1)
        old = self.install_folder(root=str(root), version='0.7.0', cache_version='0.7.0', cached={**MANIFEST, 'version': '0.7.0'})
        root = self.repo_root({**MANIFEST, 'version': '0.7.0'})
        self.assertEqual(self.check_install(old, root), 0)
        self.assertEqual(self.check_install(old, root, '--version', '0.8.0'), 1)

    def test_check_install_default_root_is_repository_root(self):
        real = json.loads((REPO / 'plugins' / 'my-agent' / '.codex-plugin' / 'plugin.json').read_text(encoding='utf-8'))
        folder = self.install_folder(root=str(REPO), version=real['version'], cache_version=real['version'], cached=real)
        self.assertEqual(probe.main(['check', 'install', str(folder)]), 0)

    def test_check_install_missing_folder_and_wrong_version_unchanged(self):
        root = self.repo_root()
        code, out = run_main(['check', 'install', str(self.tmp / 'no-such-folder'), '--root', str(root)])
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), [
            'plugin-list.txt has no my-agent@my-plugins row',
            'skills evidence is not from a hard source',
            'skills-list.txt holds my-agent:monitor 0 time(s), not exactly once',
            'skills-list.txt holds my-agent:my-agent 0 time(s), not exactly once',
            'no cache copy of .codex-plugin/plugin.json for version ? (an old Claude-format install has none)'])
        folder = self.install_folder(root=str(root))
        code, out = run_main(['check', 'install', str(folder), '--root', str(root), '--version', '0.9.0'])
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), ['plugin-list.txt shows version 0.8.0, not 0.9.0',
                                            'the cached manifest version is 0.8.0, not 0.9.0'])

    def test_check_install_old_claude_form_copy_fails(self):
        root = self.repo_root()
        folder = self.install_folder(root=str(root), cache=False)
        (folder / 'cache' / '0.8.0' / 'claude-plugin.json').write_text(json.dumps(MANIFEST), encoding='utf-8')
        self.assertEqual(self.check_install(folder, root), 1)


class E2eToolingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fake, self.log = make_fake(self.tmp)

    def test_snapshot_cache_and_skills(self):
        home = self.tmp / 'home'
        ver = home / 'plugins' / 'cache' / 'mk' / 'pl' / '1.2.3'
        (ver / '.codex-plugin').mkdir(parents=True)
        (ver / '.codex-plugin' / 'plugin.json').write_text(json.dumps(MANIFEST), encoding='utf-8')
        (ver / 'SKILL.md').write_text('secret body', encoding='utf-8')
        out = self.tmp / 'snap'
        h = ['--codex', str(self.fake), '--codex-home', str(home)]
        self.assertEqual(probe.main(h + ['snapshot', '--out', str(out), '--skills', str(self.tmp), '--cache', 'mk/pl']), 0)
        files = (out / 'cache-files.txt').read_text(encoding='utf-8').split('\n')
        self.assertIn('1.2.3/SKILL.md', files)
        self.assertIn('1.2.3/.codex-plugin/plugin.json', files)
        self.assertEqual(json.loads((out / 'cache' / '1.2.3' / 'codex-plugin.json').read_text(encoding='utf-8')), MANIFEST)
        self.assertEqual(sorted(str(p.relative_to(out)) for p in (out / 'cache').rglob('*') if p.is_file()),
                         ['cache/1.2.3/codex-plugin.json'])
        self.assertTrue((out / 'skills-list.txt').is_file())
        self.assertEqual([c['argv'] for c in calls(self.log) if c['argv'][:1] == ['exec']], [])
        self.assertEqual(len([c for c in calls(self.log) if c['argv'][:2] == ['debug', 'prompt-input']]), 1)
        self.assertEqual((out / 'skills-source.txt').read_text(encoding='utf-8').strip(), 'none')
        for argv in [c['argv'] for c in calls(self.log)]:
            self.assertNotIn(argv[:1], (['login'], ['logout']))
            self.assertFalse(set(argv) & {'add', 'remove', 'upgrade'}, argv)

    def test_capabilities_rows(self):
        rows = json.loads(CAPS.read_text(encoding='utf-8'))['rows']
        self.assertGreaterEqual(len(rows), 15)
        ids = set()
        for row in rows:
            for key in ('id', 'capability', 'status', 'needed_by', 'how_tried', 'result', 'effect', 'facts', 'failure_patterns'):
                self.assertTrue(row.get(key), (row.get('id'), key))
            self.assertIn(row['status'], ('available', 'partial', 'gap'))
            self.assertNotIn(row['id'], ids)
            ids.add(row['id'])
            for needed in row['needed_by']:
                self.assertTrue((REPO / needed).is_file(), needed)
        by = {r['id']: r for r in rows}
        self.assertNotEqual(by['agent-identity']['status'], 'gap')
        self.assertIn('Outcome I', by['agent-identity']['result'])
        popup = by['question-popup']
        self.assertEqual(popup['status'], 'partial')
        self.assertEqual(popup['effect'], 'gates are asked through request_user_input only; when it is unavailable '
                                          'L1 stops and names the flag (hosts.md)')
        self.assertIn('request_user_input_async', popup['result'])
        self.assertIn('options', popup['result'])
        self.assertIn('Plan mode', popup['result'])
        self.assertNotIn('TUI showed the gate choices', popup['result'])
        self.assertIn('plugins/my-agent/l1-orchestration/hosts.md', popup['needed_by'])
        mode = by['question-default-mode']
        self.assertEqual(mode['status'], 'partial')
        self.assertIn('default_mode_request_user_input', mode['result'])
        self.assertIn('build-codex.py --check-question-tool', mode['effect'])
        self.assertIn('plugins/my-agent/l4-tools-guards/scripts/build-codex.py', mode['needed_by'])
        ids_in_order = [r['id'] for r in rows]
        self.assertEqual(ids_in_order.index('question-default-mode'), ids_in_order.index('question-popup') + 1)
        self.assertIn('crash ends in exit 2', by['fail-closed-malformed']['effect'])
        self.assertIn('onFailure', by['on-failure-block']['capability'])

    def test_no_home_path_in_new_files(self):
        for path in [CAPS, PROBE]:
            if path.is_file():
                text = path.read_text(encoding='utf-8')
                self.assertNotIn('jahoon' + 'jin', text, str(path))


# ---- skills listing helpers ----

ENTRY_TEXT = """## Skills
### Skill roots
- `r0` = `/Users/x/.agents/skills`
- `r6` = `/Users/x/.codex/plugins/cache/ma-probe`
### Available skills
- pdf: Use this skill whenever the user wants to do anything with PDF files. (file: r0/pdf/SKILL.md)
- ma-probe:ma-probe-dir: Probe skill in a skills folder. Use when asked to use ma-probe-dir. (file: r6/ma-probe/0.0.1/skills/ma-probe-dir/SKILL.md)
- other:thing: A description that is
  re-wrapped  across
  lines. (file: r9/thing/SKILL.md)
- plain: Text without a root alias. (file: /abs/plain/SKILL.md)
</skills_instructions>"""
LONG = ('MA-SKILL-s9-sub Probe skill with a rather long description, made-up text, used to test that a listing '
        'entry cut short by Codex still matches the skill when enough of it is left.')


def entries_matching(path, desc):
    """Listing entries of a source whose description part matches `desc` (a string or a list)."""
    descs = [desc] if isinstance(desc, str) else desc
    return [e for e in probe.all_entries(path) if any(probe.description_matches(e['description'], d) for d in descs)]


class SkillsListingRuleTest(unittest.TestCase):
    def test_parse_entries_and_aliases(self):
        entries, aliases = probe.parse_listing(ENTRY_TEXT)
        self.assertEqual(aliases['r6'], '/Users/x/.codex/plugins/cache/ma-probe')
        by = {e['name']: e for e in entries}
        self.assertEqual(set(by), {'pdf', 'ma-probe:ma-probe-dir', 'other:thing', 'plain'})
        self.assertEqual(by['ma-probe:ma-probe-dir']['path'],
                         '/Users/x/.codex/plugins/cache/ma-probe/ma-probe/0.0.1/skills/ma-probe-dir/SKILL.md')
        self.assertEqual(by['ma-probe:ma-probe-dir']['raw_path'], 'r6/ma-probe/0.0.1/skills/ma-probe-dir/SKILL.md')
        self.assertEqual(by['other:thing']['path'], 'unresolved')
        self.assertEqual(by['plain']['path'], '/abs/plain/SKILL.md')
        self.assertEqual(by['pdf']['line'], 6)

    def test_rewrapped_description_with_doubled_spaces_matches(self):
        entries, _ = probe.parse_listing(ENTRY_TEXT)
        e = next(x for x in entries if x['name'] == 'other:thing')
        self.assertTrue(probe.description_matches(e['description'], 'A description that is re-wrapped across lines.'))

    def test_cut_description_needs_sixty_characters(self):
        self.assertTrue(probe.description_matches(LONG[:61], LONG))
        self.assertEqual(len(probe.norm_desc(LONG[:60])), 59)   # the space at the cut does not count
        self.assertTrue(probe.description_matches(LONG[:62], LONG))
        self.assertTrue(probe.description_matches('ab' * 30, 'ab' * 30 + ' tail'))
        self.assertFalse(probe.description_matches('ab' * 29 + 'a', 'ab' * 29 + 'ab tail'))
        self.assertTrue(probe.description_matches(LONG[:90] + '…', LONG))
        self.assertTrue(probe.description_matches(LONG[:90] + '...', LONG))
        self.assertTrue(probe.description_matches(LONG, LONG))
        self.assertFalse(probe.description_matches(LONG[:59], LONG))
        self.assertFalse(probe.description_matches(LONG[:50] + '…', LONG))
        self.assertFalse(probe.description_matches('Different text ' + LONG[15:], LONG))
        short = 'Short skill text'
        self.assertTrue(probe.description_matches(short, short))
        self.assertFalse(probe.description_matches(short[:10], short))

    def test_listing_record_sample(self):
        record = FIXS / 'skills-listing-record' / 'record.jsonl'
        found = {'dir': entries_matching(record, 'Probe skill in a skills folder. Use when asked to use ma-probe-dir.'),
                 'root': entries_matching(record, 'Probe skill at the plugin root. Use when asked to use ma-probe-root.')}
        self.assertEqual([e['name'] for e in probe.distinct_entries(found['dir'])], ['ma-probe:ma-probe-dir'])
        self.assertEqual(found['root'], [])
        self.assertTrue(found['dir'][0]['path'].endswith('/ma-probe/0.0.1/skills/ma-probe-dir/SKILL.md'))
        self.assertTrue(found['dir'][0]['path'].startswith('/Users/x/.codex/plugins/cache/ma-probe/'))
        self.assertEqual(bool(probe.all_entries(record)), True)

    def test_marker_only_in_tool_output_or_answer_does_not_count(self):
        desc = 'MA-SKILL-sx-root Probe skill, made-up text, use only when asked to use MA-SKILL-sx-root.'
        line = f'- p:p: {desc} (file: /abs/SKILL.md)'
        objs = [
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text', 'text': 'nothing here'}]}},
            {'type': 'response_item', 'payload': {'type': 'custom_tool_call_output', 'output': 'cat\n' + line}},
            {'type': 'response_item', 'payload': {'type': 'function_call_output', 'output': line}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': line}]}},
            {'type': 'event_msg', 'payload': {'type': 'item_completed', 'item': {'type': 'agent_message', 'text': line}}},
            {'type': 'response_item', 'payload': {'type': 'reasoning', 'summary': line}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                                                  'content': [{'type': 'input_text', 'text': 'Reply with exactly: ok. Do not run any command.\n' + line}]}},
        ]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'record.jsonl'
            path.write_text('\n'.join(json.dumps(o) for o in objs) + '\n', encoding='utf-8')
            self.assertEqual(entries_matching(path, desc), [])
            objs.append({'type': 'response_item', 'payload': {'type': 'message', 'role': 'developer',
                                                              'content': [{'type': 'input_text', 'text': line}]}})
            path.write_text('\n'.join(json.dumps(o) for o in objs) + '\n', encoding='utf-8')
            self.assertEqual(len(entries_matching(path, desc)), 1)

    def test_json_escaped_em_dash_counts(self):
        desc = 'Use when a request needs several steps — made-up text for the test, long enough to be matched whole.'
        text = '### Available skills\n- a:b: ' + desc + ' (file: /abs/SKILL.md)\n'
        escaped = json.dumps({'input': [{'text': text}]})
        self.assertIn('\\u2014', escaped)
        with tempfile.TemporaryDirectory() as d:
            for name, content in (('prompt-input.txt', escaped + '\n'),
                                  ('record.jsonl', json.dumps({'type': 'response_item', 'payload': {
                                      'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text', 'text': text}]}}) + '\n')):
                path = Path(d) / name
                path.write_text(content, encoding='utf-8')
                self.assertEqual(len(entries_matching(path, desc)), 1, name)

    def test_distinct_paths_count_and_same_listing_in_two_items_counts_once(self):
        desc = 'MA-SKILL-sx-sub Probe skill, made-up text, use only when asked to use MA-SKILL-sx-sub.'
        text = ('### Available skills\n- p:s: %s (file: /abs/one/SKILL.md)\n- p:s: %s (file: /abs/two/SKILL.md)\n' % (desc, desc))
        item = {'type': 'response_item', 'payload': {'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text', 'text': text}]}}
        state = {'type': 'world_state', 'payload': {'state': {'host_skills': {'body': text}}}}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'record.jsonl'
            path.write_text(json.dumps(item) + '\n' + json.dumps(state) + '\n', encoding='utf-8')
            found = entries_matching(path, desc)
            self.assertEqual(len(probe.distinct_entries(found)), 2)

    def test_undefined_alias_is_unresolved_but_counts_by_description(self):
        desc = 'MA-SKILL-sx-sub Probe skill, made-up text, use only when asked to use MA-SKILL-sx-sub.'
        text = '### Skill roots\n- `r1` = `/Users/x/a`\n### Available skills\n- p:s: %s (file: r7/p/SKILL.md)\n' % desc
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'prompt-input.txt'
            path.write_text(text, encoding='utf-8')
            found = entries_matching(path, desc)
            self.assertEqual([e['path'] for e in found], ['unresolved'])


# ---- install evidence from the hard source ----

MONITOR_DESC = 'Start, check, or stop the my-agent monitor web page (local, read-only). Run only when called as /my-agent:monitor.'
ROOT_DESC = 'Use when a request needs several steps from plan to review; made-up root skill description for the install test.'
PI_LISTING = """### Skill roots
- `r1` = `/Users/x/.codex/plugins/cache`
### Available skills
- pdf: A made-up other skill. (file: /abs/pdf/SKILL.md)
- {name}: {desc} (file: r1/my-plugins/my-agent/0.7.0/skills/monitor/SKILL.md)
"""
FAKE_PI = '''#!{py}
import json, os, sys
with open({log!r}, 'a') as f:
    f.write(json.dumps({{'argv': sys.argv[1:], 'cwd': os.getcwd()}}) + '\\n')
if sys.argv[1:2] == ['--version']:
    print('codex-cli 9.9.9')
elif sys.argv[1:3] == ['debug', 'prompt-input']:
    sys.stdout.write(open({pi!r}).read())
else:
    print('listing ' + ' '.join(sys.argv[1:]))
'''
UNKNOWN_SKILL = 'Unknown skill my-agent'
UNLISTED_SKILL = 'skill my-agent is not listed'
NOT_GIT = 'fatal: not a git repository (or any of the parent directories): .git'
NO_ACTIVE = 'run-log: no active my-agent task under /x/repo'
PATH_MISSING = 'cannot read /x/plugins/cache/my-plugins/my-agent/0.7.0/SKILL.md: No such file or directory'


class SkillsInstallEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / 'codex-home'
        ver = self.home / 'plugins' / 'cache' / 'my-plugins' / 'my-agent' / '0.7.0'
        (ver / 'skills' / 'monitor').mkdir(parents=True)
        (ver / '.codex-plugin').mkdir()
        (ver / 'SKILL.md').write_text(f'---\nname: my-agent\ndescription: {ROOT_DESC}\n---\nbody\n', encoding='utf-8')
        (ver / 'skills' / 'monitor' / 'SKILL.md').write_text(
            f'---\nname: monitor\ndescription: {MONITOR_DESC}\n---\nbody\n', encoding='utf-8')
        self.repo = self.tmp / 'repo'
        self.repo.mkdir()

    def snapshot(self, pi_text, name='snap'):
        pi = self.tmp / f'{name}-pi.txt'
        pi.write_text(pi_text, encoding='utf-8')
        log = self.tmp / f'{name}-calls.jsonl'
        fake = self.tmp / f'{name}-fake'
        fake.write_text(FAKE_PI.format(py=sys.executable, log=str(log), pi=str(pi)), encoding='utf-8')
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        out = self.tmp / name
        code = probe.main(['--codex', str(fake), '--codex-home', str(self.home), 'snapshot', '--out', str(out),
                           '--skills', str(self.repo), '--cache', 'my-plugins/my-agent'])
        self.assertEqual(code, 0)
        return out, log

    def read(self, out, name):
        return (out / name).read_text(encoding='utf-8')

    def test_root_description_read_from_the_skills_folder_of_a_new_version(self):
        new = self.home / 'plugins' / 'cache' / 'my-plugins' / 'my-agent' / '0.8.0' / 'skills' / 'my-agent'
        new.mkdir(parents=True)
        (new / 'SKILL.md').write_text('---\nname: my-agent\ndescription: New layout root.\n---\nbody\n', encoding='utf-8')
        self.assertEqual(sorted(probe.my_agent_descriptions(self.home)['root']), sorted([ROOT_DESC, 'New layout root.']))

    def test_monitor_entry_writes_name_and_prompt_input(self):
        out, _ = self.snapshot(PI_LISTING.format(name='my-agent:monitor', desc=MONITOR_DESC))
        self.assertEqual(self.read(out, 'skills-list.txt').split(), ['my-agent:monitor'])
        self.assertEqual(self.read(out, 'skills-source.txt').strip(), 'prompt-input')
        evidence = self.read(out, 'skills-evidence.txt')
        self.assertIn('my-agent:monitor', evidence)
        self.assertIn('<codex-home>/plugins/cache/my-plugins/my-agent/0.7.0/skills/monitor/SKILL.md', evidence)
        self.assertNotIn('pdf', evidence)
        self.assertNotIn('`r1`', evidence)
        self.assertNotIn('/Users/', evidence)

    def test_description_outside_a_listing_entry_does_not_count(self):
        plain = (f'### Skill roots\nNote: {MONITOR_DESC}\n### Available skills\n'
                 '- pdf: A made-up other skill. (file: /abs/pdf/SKILL.md)\n')
        out, _ = self.snapshot(plain)
        self.assertEqual(self.read(out, 'skills-list.txt').split(), [])
        self.assertEqual(self.read(out, 'skills-source.txt').strip(), 'prompt-input')
        out, _ = self.snapshot(f'Plain prompt text. {MONITOR_DESC}\n', 'snap2')
        self.assertEqual(self.read(out, 'skills-list.txt').split(), [])
        self.assertEqual(self.read(out, 'skills-source.txt').strip(), 'none')

    def test_no_listing_entry_is_none(self):
        out, _ = self.snapshot('nothing listed here\n')
        self.assertEqual(self.read(out, 'skills-source.txt').strip(), 'none')
        self.assertEqual(self.read(out, 'skills-list.txt').split(), [])

    def test_prompt_input_not_exec_and_no_extra_files(self):
        out, log = self.snapshot(PI_LISTING.format(name='my-agent:monitor', desc=MONITOR_DESC))
        made = calls(log)
        argvs = [c['argv'] for c in made]
        self.assertEqual(argvs[:3], [['--version'], ['plugin', 'list'], ['plugin', 'marketplace', 'list']])
        debug = [c for c in made if c['argv'][:2] == ['debug', 'prompt-input']]
        self.assertEqual(len(debug), 1)
        self.assertEqual(os.path.realpath(debug[0]['cwd']), os.path.realpath(self.repo))
        for argv in argvs:
            self.assertNotEqual(argv[:1], ['exec'])
            self.assertFalse(set(argv) & {'add', 'remove', 'upgrade'}, argv)
        files = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file())
        self.assertEqual(files, ['cache-files.txt', 'codex-version.txt', 'marketplace-list.txt', 'plugin-list.txt',
                                 'skills-evidence.txt', 'skills-list.txt', 'skills-source.txt'])
        for f in files:
            self.assertNotIn('Available skills', self.read(out, f))

    def test_evidence_is_reduced(self):
        out, _ = self.snapshot(PI_LISTING.format(name='my-agent:monitor', desc=MONITOR_DESC))
        for f in ('skills-evidence.txt', 'skills-list.txt', 'skills-source.txt'):
            text = self.read(out, f)
            self.assertNotIn('/Users/', text)
            self.assertNotIn(str(self.home), text)
            self.assertNotRegex(text, r'`r\d+`')

    # check install

    def helper(self):
        t = InstallCheckTest('test_check_install')
        t.tmp = self.tmp
        return t

    def check(self, **kw):
        t = self.helper()
        root = t.repo_root()
        folder = t.install_folder(root=str(root), **kw)
        return run_main(['check', 'install', str(folder), '--root', str(root)])

    def test_check_install_passes_with_both_skills_listed_once(self):
        for source in ('prompt-input', 'session-record'):
            code, out = self.check(source=source)
            self.assertEqual(code, 0, out)
            self.assertEqual(out.strip(), 'listed: my-agent:my-agent, my-agent:monitor')
            self.assertNotIn('expected gap', out)

    def test_check_install_fails(self):
        for kw, text in (({'source': None}, 'skills evidence is not from a hard source'),
                         ({'source': 'none'}, 'skills evidence is not from a hard source'),
                         ({'source': 'model-answer'}, 'skills evidence is not from a hard source'),
                         ({'skills': 'my-agent\nmonitor\n'}, 'my-agent:monitor'),
                         ({'skills': 'other:monitor\n'}, 'my-agent:monitor'),
                         ({'skills': 'my-agent:my-agent\nmy-agent:monitor\nmy-agent:monitor\n'}, '2'),
                         ({'skills': 'my-agent:monitor\n'},
                          'skills-list.txt holds my-agent:my-agent 0 time(s), not exactly once'),
                         ({'skills': 'my-agent:my-agent\nmy-agent:my-agent\nmy-agent:monitor\n'},
                          'skills-list.txt holds my-agent:my-agent 2 time(s), not exactly once')):
            code, out = self.check(**kw)
            self.assertEqual(code, 1, (kw, out))
            self.assertIn(text, out, kw)
            self.assertNotIn('expected gap', out, kw)
            self.assertNotIn('listed:', out, kw)

    def test_check_install_missing_skills_list_fails(self):
        t = self.helper()
        root = t.repo_root()
        folder = t.install_folder(root=str(root))
        (folder / 'skills-list.txt').unlink()
        self.assertEqual(run_main(['check', 'install', str(folder), '--root', str(root)])[0], 1)

    def test_plugin_skill_discovery_row(self):
        rows = {r['id']: r for r in json.loads(CAPS.read_text(encoding='utf-8'))['rows']}
        row = rows['plugin-skill-discovery']
        self.assertEqual(row['status'], 'available')
        self.assertEqual(row['effect'], 'the main skill is started by name on both hosts; no start by path (hosts.md)')
        self.assertEqual(row['facts'], ['Plugin skill discovery outcome', 'Skill listing source'])
        self.assertEqual(row['needed_by'], ['plugins/my-agent/.codex-plugin/plugin.json',
                                             'plugins/my-agent/skills/my-agent/SKILL.md'])
        self.assertEqual(rows['skill-path-variables']['effect'],
                         'the session line names the plugin, data and task folders; without it the plugin folder is '
                         'two levels above the SKILL.md folder (hosts.md)')
        others = [p for r in rows.values() if r is not row for p in r['failure_patterns']]
        for text in (UNKNOWN_SKILL, UNLISTED_SKILL, PATH_MISSING):
            self.assertTrue(any(re.search(p, text, re.I) for p in row['failure_patterns']), text)
            self.assertFalse(any(re.search(p, text, re.I) for p in others), text)

    def test_ask_asymmetry_row(self):
        rows = {r['id']: r for r in json.loads(CAPS.read_text(encoding='utf-8'))['rows']}
        row = rows['ask-asymmetry']
        self.assertEqual(row['status'], 'gap')
        self.assertEqual(row['needed_by'], ['plugins/my-agent/l4-tools-guards/lib/ma_g2.py',
                                             'plugins/my-agent/l4-tools-guards/lib/ma_host.py'])
        self.assertEqual(row['effect'], 'every ask of the gate hooks is exit 2 on Codex; L1 asks the person in a G2 '
                                        'popup and writes answer gate=G2, which releases exactly one call (hosts.md)')
        ids = list(rows)
        self.assertEqual(ids.index('ask-asymmetry'), ids.index('permission-dialog') + 1)
        self.assertIn("hookSpecificOutput.decision.behavior", rows['permission-dialog']['effect'])
        self.assertIn("exit 2", rows['permission-dialog']['effect'])
        others = [p for r in rows.values() if r is not row for p in r['failure_patterns']]
        for text in ('hook returned permissionDecision ask, which is not supported',
                     'ask is unsupported for PreToolUse hooks'):
            self.assertTrue(any(re.search(p, text, re.I) for p in row['failure_patterns']), text)
            self.assertFalse(any(re.search(p, text, re.I) for p in others), text)
        for text in ('G2 dialog was skipped', 'PermissionRequest shown'):
            self.assertFalse(any(re.search(p, text, re.I) for p in row['failure_patterns']), text)

    def test_unlisted_intake_failures_have_rows(self):
        rows = {r['id']: r for r in json.loads(CAPS.read_text(encoding='utf-8'))['rows']}
        for rid, text, needed in (
                ('plugin-rules-version', NOT_GIT, ['plugins/my-agent/skills/my-agent/SKILL.md']),
                ('intake-order', NO_ACTIVE, ['plugins/my-agent/skills/my-agent/SKILL.md',
                                       'plugins/my-agent/l4-tools-guards/scripts/run-log.py'])):
            row = rows[rid]
            self.assertEqual(row['status'], 'gap')
            self.assertEqual(row['needed_by'], needed)
            others = [p for r in rows.values() if r is not row for p in r['failure_patterns']]
            self.assertTrue(any(re.search(p, text, re.I) for p in row['failure_patterns']), text)
            self.assertFalse(any(re.search(p, text, re.I) for p in others), text)
        self.assertFalse(any(re.search(p, 'ordinary text', re.I)
                             for rid in ('plugin-rules-version', 'intake-order') for p in rows[rid]['failure_patterns']))

    def test_no_home_path_in_fixtures(self):
        user = 'jahoon' + 'jin'
        for f in FIXS.rglob('*'):
            if f.is_file():
                self.assertNotIn(user, f.read_text(encoding='utf-8', errors='replace'), str(f))
        self.assertNotIn(user, CAPS.read_text(encoding='utf-8'))


class ProbeShapeTest(unittest.TestCase):
    def test_every_function_and_constant_is_reachable(self):
        tree = ast.parse(PROBE.read_text(encoding='utf-8'))
        defs = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                defs[node.name] = node
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    for name in ast.walk(target):
                        if isinstance(name, ast.Name):
                            defs[name.id] = node
        reached, todo = set(), ['main']
        while todo:
            name = todo.pop()
            if name in reached or name not in defs:
                continue
            reached.add(name)
            todo += [n.id for n in ast.walk(defs[name]) if isinstance(n, ast.Name)]
        self.assertEqual(sorted(set(defs) - reached), [])

    def test_every_fixture_is_named_by_a_test(self):
        text = Path(__file__).read_text(encoding='utf-8')
        names = {n.value for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for entry in sorted(FIXS.iterdir()):
            self.assertIn(entry.name, names, entry.name)


if __name__ == '__main__':
    unittest.main()
