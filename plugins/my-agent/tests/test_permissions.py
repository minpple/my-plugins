"""permissions/permissions.json: the G2 ask/deny list permission-guard.py applies during a task (architecture 4.4
"actions G2 asks about", 4.12 secret blocking).

Live run: `git -C <repo> commit` did not match `Bash(git commit:*)` and committed without the G2 ask.
Deny list 2026-11-22: `.env` templates are no longer denied. Plugin 0.26.0: the list holds no Bash deny pattern; the
git-guard hook denies the force-push and hook-skipping forms during a task, and nothing is merged into user settings."""
import fnmatch
import json
import re
import unittest

from helpers import L4

ASK = [
    'Bash(git commit:*)', 'Bash(git push:*)', 'Bash(git * commit*)', 'Bash(git * push*)', 'Bash(rm -rf:*)',
    'Bash(npm i:*)', 'Bash(npm install:*)', 'Bash(pip install:*)', 'Bash(pip3 install:*)', 'Bash(brew install:*)',
    'mcp__plugin_slack_slack__slack_send_message', 'mcp__plugin_slack_slack__slack_schedule_message',
    'mcp__plugin_github_github__create_pull_request', 'mcp__plugin_github_github__create_or_update_file',
    'mcp__plugin_github_github__push_files', 'mcp__plugin_vercel_vercel__create_deployment',
]
DENY = [
    'Read(//**/.env)',
    'Read(//**/.env.local)', 'Read(//**/.env.production)', 'Read(//**/.env.development)',
    'Read(//**/.env.staging)', 'Read(//**/.env.test)', 'Read(//**/.env.*.local)',
    'Read(//**/*.pem)', 'Read(//**/*.key)',
    'Read(~/.ssh/**)', 'Read(~/.aws/**)', 'Read(~/.config/gh/**)', 'Read(~/.netrc)',
    'Read(~/.gnupg/**)', 'Read(~/.config/gcloud/**)', 'Read(~/.kube/**)', 'Read(~/.docker/config.json)',
    'Read(~/.npmrc)', 'Read(~/.pypirc)', 'Read(~/.git-credentials)', 'Read(//**/*.p12)',
]
ADDED_CREDENTIAL_RULES = DENY[-8:]

def load():
    return json.loads((L4 / 'permissions' / 'permissions.json').read_text(encoding='utf-8'))


def deny():
    return load()['permissions']['deny']


class PermissionsTest(unittest.TestCase):
    def test_lists(self):
        data = load()
        self.assertEqual(set(data), {'permissions'})
        self.assertEqual(data['permissions'], {'ask': ASK, 'deny': DENY})
        self.assertEqual(len(DENY), 21)
        self.assertEqual(len(set(DENY)), 21)

    def test_no_bash_deny_pattern(self):
        # the git guard denies force pushes and hook skipping from the parsed command; a text pattern here would
        # also deny a commit whose message only mentions the form
        self.assertFalse([r for r in deny() if not r.startswith('Read(')])

    def test_env_rules(self):
        names = [m.group(1) for m in (re.fullmatch(r'Read\(//\*\*/(\.env[^/]*)\)', r) for r in deny()) if m]

        def denied(name):
            return any(fnmatch.fnmatchcase(name, pattern) for pattern in names)

        for name in ('.env', '.env.local', '.env.production', '.env.development', '.env.staging', '.env.test',
                     '.env.production.local'):
            with self.subTest(name=name):
                self.assertTrue(denied(name))
        for name in ('.env.example', '.env.sample', '.env.template'):
            with self.subTest(name=name):
                self.assertFalse(denied(name))

    def test_credential_rules(self):
        rules = deny()
        self.assertEqual(len(ADDED_CREDENTIAL_RULES), 8)
        for rule in ADDED_CREDENTIAL_RULES:
            with self.subTest(rule=rule):
                self.assertIn(rule, rules)
        self.assertEqual(rules.count('Read(//**/*.key)'), 1)


if __name__ == '__main__':
    unittest.main()
