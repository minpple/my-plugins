"""The project blueprint (architecture 4.7.5): ma_blueprint and scripts/blueprint.py."""
import os
import re
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from helpers import L4, REPO, run_script
import ma_blueprint

FEATURES = """# Features

## Login
- Purpose: People sign in with an email and a password.
- Where: `src/auth/`
- Tasks: 261117-add-login, 261120-login-lockout-b
- Updated: 2026-11-20

1. A wrong password shows an error [check: command] → `tests/test_auth.py::test_wrong_password`
2. Five wrong tries lock the account [check: person] → checked by the person: locked after five tries
"""
DECISIONS = """# Decisions

## Constraints
- The public API of `auth` keeps its signatures — two other services call it (261117-add-login)

## Non-goals
- No social login — out of the first release (261117-add-login)

## Decisions
- Sessions live in a signed cookie — no server store to run (261117-add-login)
"""
BACKLOG = """# Backlog

- [review] SHOULD-FIX src/auth/session.py:40 the cookie has no max age (261117-add-login)
- [check] Criterion 3: the reset mail arrives, checked by the user later (261120-login-lockout-b)
- [next] Password reset by mail (261117-add-login)
"""


class BlueprintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.loc = self.root / 'proj'
        self.folder = self.loc / 'docs' / 'blueprint'
        self.folder.mkdir(parents=True)
        self.env = {'MA_DATA_DIR': str(self.root / 'data')}

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, features=FEATURES, decisions=DECISIONS, backlog=BACKLOG):
        for name, text in zip(ma_blueprint.FILES, (features, decisions, backlog)):
            if text is not None:
                (self.folder / name).write_text(text, encoding='utf-8')

    def problems(self, **files):
        self.write(**files)
        return ma_blueprint.check(self.folder)[1]

    def script(self, loc=None):
        return run_script(L4 / 'scripts' / 'blueprint.py', 'check', '--loc', str(loc or self.loc), env=self.env)

    def test_good_files(self):
        self.write()
        counts, problems = ma_blueprint.check(self.folder)
        self.assertEqual(problems, [])
        self.assertEqual(counts, {'features.md': 1, 'decisions.md': 3, 'backlog.md': 3})

    def test_missing_files_count_zero(self):
        counts, problems = ma_blueprint.check(self.folder)
        self.assertEqual((counts, problems), ({'features.md': 0, 'decisions.md': 0, 'backlog.md': 0}, []))
        self.assertEqual(ma_blueprint.check(self.root / 'nowhere')[1], [])

    def test_title_lines(self):
        got = self.problems(features=FEATURES.replace('# Features', '# Feature list'))
        self.assertEqual(got, ['features.md:1 the first line is not `# Features`'])

    def test_feature_entry_needs_its_lines(self):
        got = self.problems(features='# Features\n\n## Export\n- Purpose: x\n')
        self.assertEqual(got, ['features.md:3 entry `Export` has no `- Tasks:` line',
                               'features.md:3 entry `Export` has no `- Updated:` line',
                               'features.md:3 entry `Export` has no numbered criterion'])

    def test_feature_values(self):
        text = FEATURES.replace('261117-add-login, 261120-login-lockout-b', 'the login task')
        text = text.replace('Updated: 2026-11-20', 'Updated: last week')
        text = text.replace(' → `tests/test_auth.py::test_wrong_password`', '')
        self.assertEqual(self.problems(features=text),
                         ['features.md:6 `- Tasks:` is not a list of task IDs',
                          'features.md:7 `- Updated:` is not a date (YYYY-MM-DD)',
                          'features.md:9 the criterion has no ` → <evidence>`'])

    def test_decision_sections(self):
        got = self.problems(decisions='# Decisions\n\n## Constraints\n\n## Decisions\n- Use a cookie (261117-add-login)\n'
                                      '- Keep it small\n\n## History\n')
        self.assertEqual(got, ['decisions.md:7 the item does not end with `(<task-id>)`',
                               'decisions.md:9 unknown section `## History`',
                               'decisions.md:1 section `## Non-goals` appears 0 times (need 1)'])

    def test_empty_sections_are_fine(self):
        self.assertEqual(self.problems(decisions='# Decisions\n\n## Constraints\n\n## Non-goals\n\n## Decisions\n',
                                       backlog='# Backlog\n'), [])

    def test_backlog_items(self):
        got = self.problems(backlog='# Backlog\n\n- [todo] Reset by mail (261117-add-login)\n- [next] Reset by mail\n')
        self.assertEqual(got, ['backlog.md:3 the item does not start with one of [review], [check], [next]',
                               'backlog.md:4 the item does not end with `(<task-id>)`'])

    def test_script_ok(self):
        self.write()
        r = self.script()
        self.assertEqual((r.returncode, r.stderr), (0, ''))
        self.assertEqual(r.stdout.splitlines(), [f'blueprint: {self.folder}', 'ok: features 1, decisions 3, backlog 3'])

    def test_script_without_a_folder(self):
        loc = self.root / 'fresh'
        loc.mkdir()
        r = self.script(loc)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.splitlines(),
                         [f'blueprint: {loc / "docs" / "blueprint"}', 'ok: features 0, decisions 0, backlog 0'])

    def test_direct_work_reference(self):
        """A change made without a my-agent task is named `direct-<yymmdd>-<slug>` (blueprint-format.md)."""
        ref = 'direct-261121-fix-typo'
        got = self.problems(features=FEATURES.replace('- Tasks: ', f'- Tasks: {ref}, ', 1),
                            decisions=DECISIONS.replace('(261117-add-login)', f'({ref})', 1),
                            backlog=BACKLOG.replace('(261117-add-login)', f'({ref})', 1))
        self.assertEqual(got, [])
        got = self.problems(decisions=DECISIONS.replace('(261117-add-login)', '(direct-fix-typo)', 1),
                            backlog=BACKLOG.replace('(261117-add-login)', '(a1b2c3d)', 1))
        self.assertEqual(len(got), 2)

    def test_script_problems(self):
        self.write(backlog='# Backlog\n\n- Reset by mail\n')
        r = self.script()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.splitlines()[1:],
                         ['problem: backlog.md:3 the item does not start with one of [review], [check], [next]',
                          'problem: backlog.md:3 the item does not end with `(<task-id>)`'])

    def test_script_off_in_the_data_folder(self):
        data = self.root / 'data'
        data.mkdir()
        r = self.script(data)
        self.assertEqual((r.returncode, r.stdout), (0, 'blueprint: off (the task location is the data folder)\n'))
        with mock.patch.dict(os.environ, MA_DATA_DIR=str(data)):
            self.assertIsNone(ma_blueprint.root(data))
            self.assertEqual(ma_blueprint.root(self.loc), self.loc / 'docs' / 'blueprint')

    def test_script_bad_location(self):
        r = self.script(self.root / 'nowhere')
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, '')



class BlueprintRulesTest(unittest.TestCase):
    """The rule texts that read and update the blueprint (4.7.5) agree with the code."""

    def text(self, *parts):
        return REPO.joinpath(*parts).read_text(encoding='utf-8')

    def blueprint_bullet(self):
        define = self.text('l1-orchestration', 'phases', 'define.md')
        return next(line for line in define.splitlines() if '**Blueprint:**' in line)

    def test_format_file_names_what_the_check_reads(self):
        fmt = self.text('l3-workers', 'blueprint-format.md')
        self.assertIn(f'`{ma_blueprint.DIR}/`', fmt)
        for name, title in ma_blueprint.TITLES.items():
            self.assertIn(f'### `{name}`', fmt)
            self.assertIn(f'```text\n{title}\n', fmt)
        for key in ma_blueprint.FEATURE_KEYS:
            self.assertIn(f'- {key}: ', fmt)
        for section in ma_blueprint.DECISION_SECTIONS:
            self.assertIn(f'\n## {section}\n', fmt)
        for tag in ma_blueprint.BACKLOG_TAGS:
            self.assertIn(f'- [{tag}] ', fmt)
        self.assertIn('4. **Language:** write the blueprint text in English, in a new file and in an existing one. '
                      'A line found in another language is rewritten in English when the entry it belongs to is updated. '
                      'A code name or a screen string quoted inside backticks stays as written.\n', fmt)
        self.assertIn('Keep the title lines, the `## ` section names, the line labels', fmt)
        self.assertIn('the tags in English as written here.', fmt)
        arch = self.text('docs', 'build-guide', 'my-agent-architecture.md')
        language = arch[arch.index('**Language (2026-11-22):**'):]
        language = language[:language.index('\n')]
        self.assertIn('English in every project', language)
        self.assertIn('inside backticks', language)

    def test_format_file_examples_pass_the_check(self):
        """The three example blocks, filled with a task ID and a date, are valid files."""
        fmt = self.text('l3-workers', 'blueprint-format.md')
        blocks = [b for b in fmt.split('```text\n')[1:]]
        with tempfile.TemporaryDirectory() as tmp:
            for name, block in zip(ma_blueprint.FILES, blocks):
                body = block.split('```')[0].replace('<task-id>', '261117-add-login').replace('<YYYY-MM-DD>', '2026-11-17')
                Path(tmp, name).write_text(body, encoding='utf-8')
            counts, problems = ma_blueprint.check(tmp)
        self.assertEqual(problems, [])
        self.assertEqual(counts, {'features.md': 1, 'decisions.md': 3, 'backlog.md': 3})
        # A line already written in another language stays valid: the check reads formats, not language.
        korean = ''.join(chr(c) for c in (0xd55c, 0xad6d, 0xc5b4, 0x20, 0xc124, 0xba85))
        with tempfile.TemporaryDirectory() as tmp:
            for name, block in zip(ma_blueprint.FILES, blocks):
                body = block.split('```')[0].replace('<task-id>', '261117-add-login').replace('<YYYY-MM-DD>', '2026-11-17')
                if name == 'features.md':
                    body = re.sub(r'- Purpose: .*', '- Purpose: ' + korean, body)
                    self.assertIn(korean, body)
                Path(tmp, name).write_text(body, encoding='utf-8')
            counts, problems = ma_blueprint.check(tmp)
        self.assertEqual(problems, [])
        self.assertEqual(counts, {'features.md': 1, 'decisions.md': 3, 'backlog.md': 3})

    def test_accept_updates_after_the_answer_and_before_done(self):
        accept = self.text('l1-orchestration', 'phases', 'accept.md')
        item6 = accept[accept.index('6. **Accept:**'):accept.index('7. **Rework:**')]
        self.assertLess(item6.index('deliver path=<path>'), item6.index('Do "Blueprint update" below'))
        self.assertLess(item6.index('Do "Blueprint update" below'), item6.index('`Status: done`'))
        section = accept[accept.index('## Blueprint update'):]
        self.assertIn('blueprint.py" check --loc "<task location>" --data-dir "<data folder>"', section)
        self.assertIn('`my-agent:writer`, with no `Work unit:` line', section)
        self.assertIn('${CLAUDE_PLUGIN_ROOT}/l3-workers/blueprint-format.md', section)
        self.assertIn('never undoes the Accept or Commit', section)

    def test_dev_commit_includes_the_blueprint(self):
        dev = self.text('l1-orchestration', 'profiles', 'dev.md')
        commit = dev[dev.index('4. **Commit:**'):dev.index('5. **Rework**')]
        self.assertLess(commit.index('Do accept.md "Blueprint update" first'), commit.index('"Check before anything leaves"'))
        self.assertLess(commit.index('"Check before anything leaves"'), commit.index('`git add <files>`'))
        self.assertIn('and the blueprint files of item 4', dev)

    def test_define_reads_the_blueprint(self):
        define = self.text('l1-orchestration', 'phases', 'define.md')
        self.assertIn(f'`<task location>/{ma_blueprint.DIR}/` has a file', define)
        self.assertIn('hand Explore to explorer in every profile', define)
        bullet = self.blueprint_bullet()
        self.assertIn('`Keep it` / `Change it`', bullet)
        self.assertNotIn('Keep it (Recommended)', bullet)
        self.assertNotIn('rec="Keep it"', bullet)
        self.assertIn('rec="<', bullet)

    def test_blueprint_popup_recommends_the_judged_choice(self):
        bullet = self.blueprint_bullet()
        for part in ('the choice you judge right first with `(Recommended)`', 'the question gives the reason in one line',
                     'Recommend `Change it` when the request cannot be met while the line stays or a change is better',
                     'else `Keep it` (e.g. an incidental conflict)', '`answer gate=Q`',
                     'on `Change it`, write the change into the scope'):
            self.assertIn(part, bullet)

    def test_blueprint_popup_one_per_line(self):
        self.assertIn('one popup per line', self.blueprint_bullet())

    def test_define_size_kept(self):
        size = len(self.text('l1-orchestration', 'phases', 'define.md'))
        self.assertLessEqual(size, 12450, f'define.md: {size} characters')

    def test_agents_know_their_part(self):
        writer = self.text('l3-workers', 'agents', 'writer.md')
        self.assertIn('**Blueprint update (after G3):**', writer)
        self.assertIn(f'to `{ma_blueprint.DIR}/` in the task location', writer)
        explorer = self.text('l3-workers', 'agents', 'explorer.md')
        self.assertIn('## Blueprint\n- Feature: ', explorer)
        self.assertIn('- none (no blueprint)', explorer)
        self.assertIn(f'the project blueprint (`{ma_blueprint.DIR}/`', self.text('l3-workers', 'agents', 'coder.md'))
        self.assertIn('8. **Blueprint:**', self.text('l2-design-judge', 'agents', 'plan-reviewer.md'))
        self.assertIn(f'Plan no work unit that writes `{ma_blueprint.DIR}/`', self.text('l2-design-judge', 'agents', 'architect.md'))


if __name__ == '__main__':
    unittest.main()
