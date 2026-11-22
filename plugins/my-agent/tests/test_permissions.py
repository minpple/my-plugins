"""permissions/permissions.json: the G2 ask/deny list (architecture 4.4 "actions G2 asks about", 4.12 secret blocking).

Live run: `git -C <repo> commit` did not match `Bash(git commit:*)` and committed without the G2 ask.
Deny list 2026-11-22: the force rules end at the option (a rule never matches `--force-with-lease`), the hook-skipping
rule is git-only, `.env` templates are no longer denied. The git-guard hook covers the forms the patterns miss."""
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
    'Bash(git push --force *)',
    'Bash(git push * --force)', 'Bash(git push * --force *)',
    'Bash(git push -f *)',
    'Bash(git push * -f)', 'Bash(git push * -f *)',
    'Bash(git * push --force)', 'Bash(git * push --force *)',
    'Bash(git * push * --force)', 'Bash(git * push * --force *)',
    'Bash(git * push -f)', 'Bash(git * push -f *)',
    'Bash(git * push * -f)', 'Bash(git * push * -f *)',
    'Bash(git * --no-verify)', 'Bash(git * --no-verify *)',
    'Read(//**/.env)',
    'Read(//**/.env.local)', 'Read(//**/.env.production)', 'Read(//**/.env.development)',
    'Read(//**/.env.staging)', 'Read(//**/.env.test)', 'Read(//**/.env.*.local)',
    'Read(//**/*.pem)', 'Read(//**/*.key)',
    'Read(~/.ssh/**)', 'Read(~/.aws/**)', 'Read(~/.config/gh/**)', 'Read(~/.netrc)',
    'Read(~/.gnupg/**)', 'Read(~/.config/gcloud/**)', 'Read(~/.kube/**)', 'Read(~/.docker/config.json)',
    'Read(~/.npmrc)', 'Read(~/.pypirc)', 'Read(~/.git-credentials)', 'Read(//**/*.p12)',
]
ADDED_CREDENTIAL_RULES = DENY[-8:]
SKIP_OPTION = '--no-' + 'verify'
FORCE_OPTIONS = ('--force', '-f')
PUSH_PREFIXES = ('git push', 'git push *', 'git * push', 'git * push *')


def load():
    return json.loads((L4 / 'permissions' / 'permissions.json').read_text(encoding='utf-8'))


def deny():
    return load()['permissions']['deny']


class PermissionsTest(unittest.TestCase):
    def test_lists(self):
        data = load()
        self.assertEqual(set(data), {'permissions'})
        self.assertEqual(data['permissions'], {'ask': ASK, 'deny': DENY})
        self.assertEqual(len(DENY), 37)
        self.assertEqual(len(set(DENY)), 37)

    def test_force_rules_stand_alone(self):
        # a rule written as `-f*` would also match `--force-with-lease`: the option must end the word
        found = 0
        for rule in deny():
            if not rule.startswith('Bash('):
                continue
            for m in re.finditer(r'(?<= )(--force|-f)(.?)', rule):
                found += 1
                self.assertIn(m.group(2), (')', ' '), rule)
        self.assertEqual(found, 14)

    def test_force_rules_keep_the_old_positions(self):
        rules = set(deny())
        for option in FORCE_OPTIONS:
            for prefix in PUSH_PREFIXES:
                with self.subTest(option=option, prefix=prefix):
                    # a trailing ` *` also matches the bare end only when it is the rule's only wildcard
                    want = [f'Bash({prefix} {option} *)']
                    if prefix.count('*') > 0:
                        want.append(f'Bash({prefix} {option})')
                    for rule in want:
                        self.assertIn(rule, rules)

    def test_hook_skip_rule_is_git_only(self):
        rules = deny()
        self.assertFalse([r for r in rules if r.startswith('Bash(*')])
        skip = [r for r in rules if SKIP_OPTION in r]
        self.assertEqual(len(skip), 2)
        for rule in skip:
            self.assertTrue(rule.startswith('Bash(git '), rule)

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
