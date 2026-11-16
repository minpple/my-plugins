"""Codex fixtures: every fixture parses, has its manifest fields, and carries no real data."""
import json
import re
import unittest
from pathlib import Path

DIR = Path(__file__).resolve().parent / 'fixtures' / 'codex'
# A system account name is not personal data, and Codex agent paths start with `/root/` (`/root/helper_one` in the
# session fixture), so the bare-name check skips it; the `/Users/<name>` checks still apply.
SYSTEM_ACCOUNTS = {'root'}
MANIFEST = json.loads((DIR / 'manifest.json').read_text())
SECRET_NAME = re.compile(r'key|token|secret|auth|pass', re.I)
# token-count fields hold numbers, not credentials
COUNT_NAME = re.compile(r'tokens$|tokens_|token_usage', re.I)


def load(name):
    text = (DIR / name).read_text()
    if name.endswith('.jsonl'):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


def real_data_problems(text, home_name):
    """How `text` shows the home folder name `home_name`: the `/Users/<name>` prefix (built at run time, so the real
    prefix is not written into a committed file) and the bare name. Empty when it shows neither."""
    prefix = '/Users/' + home_name
    found = [prefix + end for end in ('/', '"') if prefix + end in text]
    if home_name.lower() not in SYSTEM_ACCOUNTS and home_name.lower() in text.lower():
        found.append(home_name.lower())
    return found


def walk(node):
    """Yield (key, value) for every dict entry at any depth."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield k, v
            yield from walk(v)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


class CodexFixtures(unittest.TestCase):
    def test_manifest_lists_every_fixture_file(self):
        on_disk = {p.name for p in DIR.iterdir()} - {'manifest.json'}
        self.assertEqual(on_disk, set(MANIFEST['fixtures']))
        self.assertTrue(MANIFEST['codex_version'].startswith('codex-cli '))

    def test_hook_fixtures_have_manifest_fields(self):
        for name, spec in MANIFEST['fixtures'].items():
            if spec['kind'] != 'hook':
                continue
            with self.subTest(name):
                data = load(name)
                self.assertEqual(data['hook_event_name'], spec['event'])
                for field in spec['fields']:
                    self.assertIn(field, data)
                for field in spec.get('tool_input_fields', []):
                    self.assertIn(field, data['tool_input'])
                if 'tool_name' in spec:
                    self.assertEqual(data['tool_name'], spec['tool_name'])

    def test_session_fixture_has_line_types_and_subagent_link(self):
        for name, spec in MANIFEST['fixtures'].items():
            if spec['kind'] != 'session':
                continue
            with self.subTest(name):
                lines = load(name)
                types = {line['type'] for line in lines}
                self.assertTrue(set(spec['line_types']) <= types)
                for line in lines:
                    self.assertIn('payload', line)
                sub = [x for x in lines if x['type'] == 'session_meta'
                       and isinstance(x['payload'].get('source'), dict)]
                self.assertEqual(len(sub), 1)
                spawn = sub[0]['payload']['source']['subagent']['thread_spawn']
                self.assertEqual(spawn['parent_thread_id'], sub[0]['payload']['parent_thread_id'])
                usage = [x for x in lines if x['type'] == 'token_usage_record']
                self.assertTrue(usage)
                for line in usage:
                    for f in spec['usage_fields']:
                        self.assertIn(f, line['payload']['usage'])

    def test_real_data_check_catches_a_personal_home_name(self):
        self.assertEqual(real_data_problems('{"cwd": "/Users/jdoe/dev"}', 'jdoe'), ['/Users/jdoe/', 'jdoe'])
        self.assertEqual(real_data_problems('{"user": "/Users/jdoe"}', 'jdoe'), ['/Users/jdoe"', 'jdoe'])
        self.assertEqual(real_data_problems('owner: JDoe', 'jdoe'), ['jdoe'])
        self.assertEqual(real_data_problems('{"agent_path": "/root/helper_one"}', 'root'), [])
        self.assertEqual(real_data_problems('{"cwd": "/Users/root/dev"}', 'root'), ['/Users/root/'])

    def test_no_real_data(self):
        for name in MANIFEST['fixtures']:
            with self.subTest(name):
                text = (DIR / name).read_text()
                self.assertEqual(real_data_problems(text, Path.home().name), [])
                data = load(name)
                for k, v in walk(data):
                    if SECRET_NAME.search(k) and not COUNT_NAME.search(k):
                        self.fail(f'secret-like field {k!r} in {name}')
                    if isinstance(v, str):
                        self.assertNotRegex(v, r'(sk-|ghp_|Bearer )')
                        for m in re.findall(r'/Users/[^/\s"]+', v):
                            self.assertEqual(m, '/Users/x')

    def test_no_env_values(self):
        for name in MANIFEST['fixtures']:
            with self.subTest(name):
                for k, _ in walk(load(name)):
                    self.assertNotIn(k, ('env', 'env_values', 'env_names'))


class CodexSubagentFixtures(unittest.TestCase):
    """Outcome I: a worker call carries its own agent_id/agent_type."""

    def test_new_fixtures_are_in_manifest(self):
        for name in ('hook-pre-tool-use-file-change.json', 'hook-post-tool-use-file-change.json',
                     'hook-pre-tool-use-worker-bash.json', 'hook-pre-tool-use-worker-file-change.json',
                     'hook-subagent-start-worker-a.json', 'hook-subagent-start-worker-b.json',
                     'hook-subagent-stop-worker-a.json', 'hook-subagent-stop-worker-b.json'):
            with self.subTest(name):
                self.assertIn(name, MANIFEST['fixtures'])

    def test_file_change_shape(self):
        for name in ('hook-pre-tool-use-file-change.json', 'hook-post-tool-use-file-change.json',
                     'hook-pre-tool-use-worker-file-change.json'):
            with self.subTest(name):
                data = load(name)
                self.assertEqual(data['tool_name'], 'apply_patch')
                patch = data['tool_input']['command']
                self.assertTrue(patch.startswith('*** Begin Patch\n'))
                self.assertIn('*** Add File: ', patch)
                self.assertTrue(patch.rstrip().endswith('*** End Patch'))
        self.assertIn('Success', load('hook-post-tool-use-file-change.json')['tool_response'])

    def test_main_session_calls_have_no_agent_fields(self):
        for name in ('hook-pre-tool-use-file-change.json', 'hook-post-tool-use-file-change.json'):
            with self.subTest(name):
                data = load(name)
                self.assertNotIn('agent_id', data)
                self.assertNotIn('agent_type', data)

    def test_worker_link_matches_subagent_start(self):
        start_a = load('hook-subagent-start-worker-a.json')
        start_b = load('hook-subagent-start-worker-b.json')
        stop_a = load('hook-subagent-stop-worker-a.json')
        stop_b = load('hook-subagent-stop-worker-b.json')
        self.assertNotEqual(start_a['agent_id'], start_b['agent_id'])
        self.assertNotEqual(start_a['agent_type'], start_b['agent_type'])
        for start, stop in ((start_a, stop_a), (start_b, stop_b)):
            self.assertEqual(start['agent_id'], stop['agent_id'])
            self.assertEqual(start['agent_type'], stop['agent_type'])
            self.assertRegex(start['agent_type'], r'^my-agent-[a-z-]+$')
        # session_id is shared by main and workers, so it is not the link
        self.assertEqual(start_a['session_id'], start_b['session_id'])
        for name in ('hook-pre-tool-use-worker-bash.json', 'hook-pre-tool-use-worker-file-change.json'):
            with self.subTest(name):
                call = load(name)
                self.assertEqual(call['agent_id'], start_a['agent_id'])
                self.assertEqual(call['agent_type'], start_a['agent_type'])
                self.assertNotEqual(call['agent_id'], start_b['agent_id'])
                self.assertEqual(call['session_id'], start_a['session_id'])


if __name__ == '__main__':
    unittest.main()
