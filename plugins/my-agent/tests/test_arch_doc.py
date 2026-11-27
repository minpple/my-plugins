"""The architecture doc (4.7.1) agrees with SKILL.md and the profile folder on the arguments."""
import json
import re
import unittest

from helpers import REPO
import ma_schema
from test_skill_md import SKILL, frontmatter

ARCH = REPO / 'docs' / 'build-guide' / 'my-agent-architecture.md'
PROFILES = REPO / 'l1-orchestration' / 'profiles'


def unquote(value):
    return value.strip().strip('\'"')


class ArchDocTest(unittest.TestCase):
    def setUp(self):
        self.text = ARCH.read_text(encoding='utf-8')

    def test_arch_doc_argument_hint_matches_skill_md(self):
        hints = re.findall(r'^argument-hint:(.*)$', self.text, re.M)
        self.assertEqual(len(hints), 1, hints)
        skill = frontmatter(SKILL.read_text(encoding='utf-8'))['argument-hint']
        self.assertEqual(unquote(hints[0]), unquote(skill))

    def test_arch_doc_names_every_flag(self):
        start = self.text.index('### 4.7.1 ')
        end = self.text.index('### 4.7.2 ')
        section = self.text[start:end]
        for path in sorted(PROFILES.glob('*.md')):
            self.assertIn(f'--{path.stem}', section)

    def test_arch_doc_states_flag_ignored_and_dev_fallback(self):
        start = self.text.index('**Profile flag (Q19):**')
        section = self.text[start:self.text.index('**Draft frontmatter**')]
        self.assertIn('If the person picks `Continue it` or `Cancel`, the flag is ignored.', section)
        self.assertIn('`Request:` keeps `--dev` as its first word while `Profile:` is general', section)
        self.assertIn('the label is `(set by you)` because the person chose general', section)
        self.assertIn('No flag (2026-11-15): the Router recommends a profile from the request and the person '
                      'confirms it in a popup of Intake item 3', section)
        self.assertIn('a confirmed recommendation keeps `(Router)`', section)

    def test_draft_frontmatter_has_no_hooks_key(self):
        start = self.text.index('**Draft frontmatter**')
        block = re.search(r'```yaml\n(.*?)```', self.text[start:], re.S).group(1)
        self.assertNotRegex(block, r'(?m)^hooks:')

    def test_plugin_hook_table_lists_the_gate_hooks_with_their_matchers(self):
        start = self.text.index('### 4.5.1 ')
        section = self.text[start:self.text.index('### 4.6 ')]
        for script, matcher in (('plan-approved-check.py', 'Agent\\|Workflow\\|Edit\\|Write\\|NotebookEdit\\|Bash'),
                                ('verdict-fresh-check.py', 'Bash\\|Edit\\|Write\\|NotebookEdit'),
                                ('git-guard.py', 'Bash'),
                                ('permission-guard.py', 'Bash\\|Read\\|Grep\\|Glob\\|mcp__.*')):
            rows = [l for l in section.splitlines() if l.startswith('|') and script in l]
            self.assertEqual(len(rows), 1, script)
            self.assertIn(f'`{matcher}`', rows[0], script)

    def section(self, start, end):
        a = self.text.index(start)
        return self.text[a:self.text.index(end, a)]

    def git_guard_bullet(self):
        lines = self.section('**actions G2 asks about**', '**Storing the deliverable after G3').splitlines()
        start = next(i for i, l in enumerate(lines) if l.startswith('- **Git guard (2026-11-22, plugin 0.24.0):**'))
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith('- ')), len(lines))
        return '\n'.join(lines[start:end])

    def test_git_guard_bullet_names_verdicts_and_hosts(self):
        sec = self.section('### 4.4 ', '### 4.5 ')
        self.assertIn('git-guard.py', sec)
        bullet = self.git_guard_bullet()
        self.assertGreater(len(bullet.splitlines()), 8)
        for word in ('git-guard.py', '`deny`', '`ask`', 'bypassPermissions', 'force_ask', 'exit 2',
                     '`onFailure: block`', 'ma_bash', '`+` refspec', '`--mirror`', '`--force-with-lease`',
                     'cannot parse the command', 'subagent', 'auto', 'Codex', 'Antigravity',
                     'GIT_CONFIG_KEY_<n>', '`$VAR`', 'core.hooksPath', 'permission guard',
                     'no output', 'depth 3', 'never a deny from heredoc text'):
            self.assertIn(word, bullet, word)

    def test_git_guard_stays_in_the_g2_panel(self):
        # tools/build-docs.py cut_bold('actions G2 asks about') stops at the next bold-only line
        a = self.text.index('**actions G2 asks about**')
        panel = self.text[a:self.text.index('**Storing the deliverable after G3', a)]
        self.assertIn('- **Git guard (2026-11-22, plugin 0.24.0):**', panel)
        # no bold-only line from the panel title through the end of the Git guard bullet
        upto = panel[:panel.index('- **Git guard')] + self.git_guard_bullet()
        self.assertFalse(any(re.match(r'^\*\*[^*]+\*\*$', l) for l in upto.splitlines()[1:]))

    def test_permission_modes_say_the_git_guard_ignores_the_mode(self):
        a = self.text.index('**Permission modes (decision Q11)**')
        sec = self.text[a:self.text.index('**Workflow run approval prompt**', a)]
        self.assertIn('git guard', sec)
        self.assertIn('`bypassPermissions`', sec)

    def test_cd_rule_lifetime_is_stated(self):
        s44 = self.section('- **When the hooks and the permission rules apply', '- **`deny` rules (2026-11-23')
        self.assertIn('added at the start of Execute', s44)
        self.assertIn('removed on every path that deletes `.active`', s44)
        self.assertIn('cd-guard.json', s44)
        s46 = self.section('### 4.6 ', '### 4.7 ')
        self.assertIn('--remove', s46)
        self.assertIn('--task', s46)
        self.assertIn('cd-guard.json', s46)
        self.assertNotIn('rule stays', s46)

    def test_cd_warning_is_recorded_as_harmless(self):
        sec = self.section('### 4.6 ', '### 4.7 ')
        self.assertIn('matches no tool', sec)
        self.assertIn('2026-11-22', sec)
        self.assertIn('harmless', sec)
        self.assertIn('`set_cwd`', sec)

    def test_security_section_states_the_subprocess_limit(self):
        sec = self.section('### 4.12 ', '## 5. ')
        self.assertIn('sh -c', sec)
        self.assertIn('sandbox', sec)
        self.assertIn('Keynote', sec)
        self.assertNotIn('`Read(//**/.env.*)`', sec)
        self.assertIn('Read(//**/*.p12)', sec)

    def test_host_sections_name_the_git_guard(self):
        codex = self.section('### 4.14 ', '### 4.15 ')
        self.assertIn('git-guard.py', codex)
        self.assertIn('git-guard', codex[codex.index('**Hook trust.**'):codex.index('**How Codex finds the skills.**')])
        agy = self.section('### 4.15 ', '## 5. ')
        self.assertIn('git-guard.py', agy)
        self.assertIn('`conversationId`', agy[agy.index('**Not verified**'):])

    def test_g1b_section_says_ask_for_writes_and_deny_for_delegation(self):
        a = self.text.index('**G1-B hard gate**')
        sec = self.text[a:self.text.index('- **Block when the hook fails:**', a)]
        self.assertNotIn('blocks **regardless of phase**', sec)
        self.assertNotIn('pre-approval write block', sec)
        self.assertIn('`permissionDecision: ask`', sec)
        self.assertIn('`permissionDecision: deny`', sec)

    def test_delegated_approval_covers_g3_with_a_cap_of_three(self):
        sec = self.section('**Delegated approval (2026-10-29, Q22)**', '**G1-B hard gate**')
        always = next(l for l in sec.splitlines() if l.startswith('- Always to the person:'))
        self.assertIn('**G2 and E**', always)
        self.assertNotIn('G3', always)
        for word in ('**G3 under delegated approval (2026-11-20, Q39):**', '`Rework: fix all open items`',
                     'after 3 G3 fix rounds it goes to E', 'whatever the round count', 'do not stop the take',
                     'in the dev profile the commit still holds only the files this task changed',
                     'The G3 fix loop has its own cap of 3 rounds', '`Severity | Found | Fixed | Open`',
                     '`BLOCKER · <n> / SHOULD-FIX · <n> / NITPICK · <n>`', 'No gate starts the monitor'):
            self.assertIn(word, sec, word)

    def test_monitor_autostart_is_off_by_default(self):
        sec = self.section('**When it starts: when the Router starts a task**', '- `"report_open": true`')
        for word in ('Autostart is off by default', '`"autostart": true`',
                     '`monitor: not started (autostart off by default; start it with /my-agent:monitor)`',
                     '`--open` always starts and opens the monitor'):
            self.assertIn(word, sec, word)
        self.assertNotIn('default true)', sec)
        self.assertIn("`timeline.wait.by = 'L1'`", self.text)

    def test_researcher_notes_keep_two_forms_and_say_how_sources_are_checked(self):
        bullet = next(l for l in self.text.splitlines() if l.startswith('- **Researcher notes: primary sources and disagreement (2026-11-21):**'))
        for word in ('keeps its two forms', '`- Not found: a primary source for <claim>`', 'one search and one fetch for each secondary-sourced item',
                     'each claim attributed to its own source', 'picks none silently', 'not from a search snippet', "In the research profile's 3B Merge the writer keeps both"):
            self.assertIn(word, bullet, word)

    def test_decision_log_has_q39_and_q40_once_after_q38(self):
        rows = re.findall(r'^\| (Q\d+) \|', self.text, re.M)
        self.assertEqual(len(rows), len(set(rows)), rows)
        self.assertEqual(rows[-8:], ['Q41', 'Q42', 'Q43', 'Q44', 'Q45', 'Q46', 'Q47', 'Q48'])
        q39 = next(l for l in self.text.splitlines() if l.startswith('| Q39 |'))
        q40 = next(l for l in self.text.splitlines() if l.startswith('| Q40 |'))
        self.assertIn('capped at 3 rounds', q39)
        self.assertIn('`"autostart": true`', q40)

    def test_background_research_is_decision_q45(self):
        lines = self.text.splitlines()
        q45 = next(l for l in lines if l.startswith('| Q45 |'))
        self.assertIn('Background research', q45)
        q6 = next(l for l in lines if l.startswith('| Q6 |'))
        self.assertIn('researcher for confirmed `b<n>` since Q45', q6)
        step = self.bullet('### 4.3 ', '### 4.4 ', '- **Background research before the plan (2026-11-24, Q45):**')
        self.assert_words(step, ('`## Background research`', '`Background question: b<n> <slug>`',
                                 '`(background b<n>)`', 'reopens G1-A with `Revise`', 'none on Codex'))
        self.assertIn('step n=1B name=Background-research', self.section('### 4.3 ', '### 4.4 '))
        gate = self.section('**G1-B hard gate**', '- **Block when the hook fails:**')
        self.assert_words(gate, ('profile is not research', 'scope is confirmed',
                                 '`## Background research` section', '`Background question: b<n>`'))
        self.assertIn('(background b<n>)', self.section('**Plan gaps', '### 4.5 '))
        self.assertIn('unit=b<n>', self.section('### 4.7.2 ', '### 4.7.3 '))
        tree = self.section('### 4.7 ', '### 4.7.1 ')
        self.assertIn('background/', tree)
        self.assertIn('<slug>.md', tree)

    def test_no_line_says_web_research_waits_for_approval_without_the_exception(self):
        after = re.compile(r'(web research|researcher)[^.\n]*only after (the )?(plan is approved|plan approval|G1-B)', re.I)
        for line in self.text.splitlines():
            if after.search(line):
                self.assertIn('Background research', line, line)

    def test_report_tab_names_return_marks(self):
        self.assertIn('timeline.backs[].row', self.text)
        self.assertIn('timeline.chart_end', self.text)
        self.assertIn('went back to an earlier step', self.text)

    def test_verify_review_scope_names_the_findings_rejudge_rules(self):
        para = re.search(r'^- \*\*Verify and Review scope .*$', self.text, re.M).group(0)
        for token in ('[criterion <n>]', '[criterion none]', '--review', '--rework-criterion',
                      '--rework-finding', '## Findings', 'same evidence as the previous run',
                      '`Re-judge: all`', 'Applied after review', 'Verdict: FAIL', 'plugin 0.29.0'):
            self.assertIn(token, para)

    def line_of(self, marker):
        found = [l for l in self.text.splitlines() if marker in l]
        self.assertEqual(len(found), 1, marker)
        return found[0]

    def test_explanation_lines_in_design(self):
        line = self.line_of('**Explanation lines (2026-11-24, plugin 0.29.1)')
        for word in ('SHOULD-FIX', '`Rework: fix all open items`', 'judged again', '`Re-judge: all`',
                     'no new popup, gate or choice'):
            self.assertIn(word, line)

    def test_remote_take_not_offered_in_remote_session(self):
        text = self.text[self.text.index('- **Remote take at G3 (2026-11-21, Q41)'):]
        text = text[:text.index('- **Verify and Review scope')]
        for word in ('printenv CLAUDE_CODE_REMOTE`', 'is `true`', 'is unset or has any other value'):
            self.assertIn(word, text)

    def test_worktree_removal_refused_in_design(self):
        line = self.line_of('- **Worktree removal after the compare for a leftover harness worktree (#83):**')
        for word in ('refused', 'one attempt', 'keeps that worktree and its branch', '"Open risks"',
                     'no popup', 'no `git worktree unlock`'):
            self.assertIn(word, line)
        self.assertIn('Unit-copy removal after the compare', self.text)

    def test_check_command_form_in_design(self):
        line = self.line_of('**Check command form (2026-11-24, plugin 0.29.1)')
        for word in ('`python3 -m unittest discover -s tests -p <file>`', 'architect', 'plan-reviewer',
                     'SHOULD-FIX', '`explore.md`'):
            self.assertIn(word, line)

    def test_q48_docs_only_rounds_row(self):
        row = self.line_of('| Q48 |')
        self.assert_words(row, ('Docs-only rounds', '`docs` folder segment', '`tests`', '`check-commands.py`', '`-p`',
                                '`carried from`', '`rest carried from`', '`checks/kept/`', '`docs-only (run due; ',
                                '`docs-only (checked; ', '`Re-judge:`', 'Q47 (3)', 'Q47 (4)', 'Q47 (7)',
                                'effort is not lowered', 'SHOULD-FIX', 'picked by the person at G3',
                                'checks-docs-only', 'checks-docs-and-code', 'checks-readme-only',
                                'tests do not pin the wording of record documents', '15,000',
                                'documents are decided by path', 'only unittest discover commands',
                                'is not run', 'Not taken', '261127-accept-speedup', '617 s'))

    def test_docs_only_places_in_design(self):
        self.assert_words(self.line_of('| **④ Accept** |'), ('docs-only round', 'carried'))
        self.assert_words(self.line_of('- **Verify and Review scope'), ('docs-only', '`Re-judge:`'))
        tree = self.section('### 4.7 ', '### 4.7.1 ')
        self.assert_words(tree, ('ma_readers', '`checks/kept/`'))

    def test_status_line_starts_with_the_newest_entry(self):
        line = re.search(r'^- Status: .*$', self.text, re.M).group(0)
        self.assertTrue(line.startswith('- Status: design draft v0.87 (2026-11-28, plugin 0.37.1:'), line[:110])
        self.assertIn('v0.86 (2026-11-27, plugin 0.37.0:', line)
        self.assertNotIn('design draft v0.86', line)
        self.assertIn('v0.84 (2026-11-26, plugin 0.35.0:', line)
        self.assertNotIn('design draft v0.84', line)
        self.assertIn('v0.83 (2026-11-26, plugin 0.34.0:', line)
        self.assertNotIn('design draft v0.83', line)
        self.assertIn('v0.82 (2026-11-26, plugin 0.33.0:', line)
        self.assertNotIn('design draft v0.82', line)
        self.assertIn('v0.80 (2026-11-25, plugin 0.31.0:', line)
        self.assertNotIn('design draft v0.80', line)
        self.assertIn('v0.79 (2026-11-24, plugin 0.30.0:', line)
        self.assertNotIn('design draft v0.79', line)
        self.assertIn('v0.78 (2026-11-24, plugin 0.29.1: three fixes from task retrospectives', line)
        self.assertNotIn('design draft v0.78', line)
        self.assertIn('v0.77 (2026-11-24, plugin 0.29.0: review findings re-judge', line)
        self.assertIn('v0.76 (2026-11-24, plugin 0.28.1: the monitor\'s Report tab shows Background research', line)
        self.assertIn('v0.75 (2026-11-24, plugin 0.28.0: Background research (Q45)', line)
        self.assertIn('v0.74 (2026-11-23, plugin 0.27.0:', line)
        self.assertIn('v0.72 (2026-11-23, plugin 0.25.2:', line)
        self.assertIn('v0.70 (2026-11-22, plugin 0.25.0:', line)
        self.assertIn('v0.69 (2026-11-22, plugin 0.24.0:', line)
        self.assertIn('v0.68 (2026-11-22, plugin 0.23.2:', line)
        self.assertIn('v0.67 (2026-11-22, plugin 0.23.1: Phase timeline return marks and the duration fix', line)
        self.assertIn('v0.66 (2026-11-21, plugin 0.23.0: Antigravity as a third host', line)
        self.assertIn('v0.65 (2026-11-21, plugin 0.22.1: researcher notes and the findings table', line)
        self.assertIn('v0.64 (2026-11-21, plugin 0.22.0: remote take at G3 and fixes from task retrospectives', line)
        self.assertIn('v0.63 (2026-11-21, plugin 0.21.2: session folder guard', line)
        self.assertIn('v0.62 (2026-11-20, plugin 0.21.1: a session moved into a coder worktree', line)
        self.assertIn('v0.61 (2026-11-20, plugin 0.21.0: the chat report of every gate approval', line)
        self.assertIn('v0.60 (2026-11-20, plugin 0.20.0: step letters', line)
        self.assertIn('v0.59 (2026-11-20, plugin 0.19.0: plan-reviewer judges', line)
        self.assertIn('v0.58 (2026-11-19, plugin 0.18.1: fixes from', line)
        self.assertIn('v0.57 (2026-11-18, plugin 0.18.0: coder notes', line)
        self.assertIn('v0.56 (2026-11-17, plugin 0.17.0: Scope Review', line)
        self.assertIn('v0.55 (2026-11-17, plugin 0.16.0: project blueprint', line)
        self.assertIn('v0.54 (2026-11-16, plugin 0.15.0: Intake script', line)
        self.assertIn('v0.53 (2026-11-16, plugin 0.14.3:', line)
        self.assertIn('v0.52 (2026-11-15, plugin 0.14.2:', line)
        self.assertIn('plugin 0.14.1: Intake order.', line)
        self.assertIn('v0.51 (2026-11-11, plugin 0.14.0:', line)
        self.assertIn('v0.50 (2026-11-10, plugin 0.13.0:', line)
        self.assertIn('v0.49 (2026-11-06, plugin 0.12.0:', line)
        self.assertIn('`changed-files.md`', line[:line.index('v0.48 (')])
        self.assertIn('`report-ko.json`', line[:line.index('v0.48 (')])
        self.assertIn('v0.48 (2026-11-05, plugin 0.11.3:', line)
        self.assertIn('plugin 0.11.3:', line[:line.index('v0.47 (')])
        self.assertIn('plugin 0.11.2:', line[:line.index('v0.47 (')])
        self.assertIn('v0.47 (2026-11-04, plugin 0.11.1:', line)
        self.assertIn('v0.46 (2026-11-04, plugin 0.11.0:', line)
        self.assertIn('v0.45 (2026-11-03, plugin 0.10.0:', line)
        self.assertIn('v0.44 (2026-11-03, plugin 0.9.0:', line)
        self.assertIn('v0.43 (', line)
        self.assertIn('plugin 0.8.0', line)
        self.assertIn('plugin 0.9.0', line)

    def test_plan_findings_route_described(self):
        """Criterion 9: the mark, the popup, the choices, the order, delegated approval and the architect input."""
        block = self.section('**Plan findings (Review) (2026-11-26', '**What the files look like after a revision**')
        self.assert_words(block, (
            '`[plan]`', 'plan-finding popup', 'marked-finding popup', '`Adjust within approved scope`',
            '`Revise this task`', '`Fix within current plan`', 'before the small fix', 'light path',
            'right before `[criterion', 'reads as unmarked', 'not sent back', 'unmarked findings',
            'never recommended', 'approved request does not stand', 'the largest need decides',
            'SHOULD-FIX is', '`[4B] Review → Deliver · Q`', '`ask gate=Q', '`answer gate=Q', '`Scope change:`',
            'to the files to change in each later rerun call of that unit', 'writes `plan finding`',
            'counts as a target file', '(item 3 above)',
            'delegated approval', 'Review BLOCKER loop', 'G3 fix loop', 'no new cap',
            'settled-popup rule', 'same severity and location', 'question back', '4th revision',
            'archive/<time>-rev<new rev>/review.md` as the change request', 'architect',
            'locations (severity and `path:line`, no explanation)', 'in their own words', '`## Revisions`',
            'no `back-execute.py`', 'four-choice'))
        change = self.section('### 4.8.1 ', '### 4.8.2 ')
        for prefix in ('This is for going back to ③ Build', '- **Small fix with only Review rerun',
                       '- **Light path after G3 Rework'):
            self.assertIn('`[plan]`', self.line_of(prefix), prefix)
        reviewer = self.line_of('  - **reviewer:** each NITPICK')
        self.assert_words(reviewer, ('`[plan]`', 'A file added by a `Scope change:` line under `## Approval` of '
                                     '`plan.md` counts as a target file'))
        self.assert_words(self.line_of('- If the WHAT/WHY changes ('),
                          ('purpose, completion criteria, non-goals, constraints or exception cases', '① Define'))
        popup_line = self.line_of('- **Plan-finding popup at G3 (2026-11-26')
        self.assert_words(popup_line, ('comes last of the explanation lines, before the open item lines',
                                       'right before `[criterion …]` or `(new)`/`(carried)`'))
        self.assertIn('`[plan]`', self.bullet('### 4.3 ', '### 4.4 ', '- **Plan mark on a review finding'))
        self.assertIn('plan-finding popup', self.line_of('6. **The number of questions to the person'))
        self.assertIn('plan-finding popup', self.line_of('| **G3 Final acceptance**'))
        self.assertIn('plan-finding popup', self.bullet('### 4.4 ', '### 4.5 ', '- **Plan-finding popup at G3'))
        self.assertIn('`[plan]`', self.line_of('- **Verify and Review scope (2026-11-06'))
        # later reruns of a unit still get the files a `Scope change:` line added (build.md 3A item 3)
        self.assert_words(self.line_of('4. Each rerun of a work unit goes to a new worker'), (
            'files to change include those a `Scope change:` line under `## Approval` of `plan.md` adds for that unit',
            'as their source', '`build.md` step 3A item 3', 'every coder call'))
        self.assertIn('plan-finding popup', self.line_of('| `Rework` in the G3 popup |'))
        self.assertIn('plan-finding popup', self.line_of('- **G3 under delegated approval (2026-11-20, Q39):**'))
        self.assertIn('`[plan]` review finding', self.line_of('- **Core rule in SKILL.md (review B6):**'))
        archive = next(l for l in change.splitlines() if l.startswith('- **The archive folder is only a record.**'))
        self.assert_words(archive, ('previous `verify.md`', 'previous `review.md`', '`archive/<ts>-run<N>/`',
                                    'architect', '`archive/<time>-rev<N>/review.md` path as the change request'))
        self.assertNotIn('never in the paths passed to judges', self.text)
        self.assertNotIn('judges (L2) do not read it', self.text)

    def test_codex_ask_bullet_names_the_asking_hooks(self):
        bullet = next(l for l in self.text.splitlines() if l.startswith('- **On Codex (plugin 0.11.0):**'))
        self.assertIn('plan-approved-check.py', bullet)
        self.assertIn('verdict-fresh-check.py', bullet)
        self.assertIn('git-guard.py', bullet)
        self.assertNotIn('scope-guard.py', bullet)   # scope-guard never asks

    def test_inline_text_says_first_non_empty_line(self):
        self.assertIn('first non-empty line of the result file', self.text)

    def test_host_layer_notes_grant_share_and_paths_only_key(self):
        sec = self.section('### 4.14 Host layer', '### 4.15 ')
        self.assertIn('one share per asking hook', sec)
        self.assertIn('paths only', sec)
        self.assertIn('not the patch text', sec)

    def test_skill_layout_and_manifest_have_no_skills_key(self):
        manifest = self.section('**Plugin manifest (`.claude-plugin/plugin.json`)**', '**Marketplace file')
        self.assertNotIn('"skills"', manifest)
        self.assertIn('`skills/` folder scan', manifest)
        self.assertIn('tools/claude-skill-check.py', self.section('### 4.13 ', '### 4.14 '))
        sec = self.section('### 4.7.1 ', '### 4.7.2 ')
        self.assertIn('skills/my-agent/SKILL.md', sec)
        self.assertIn('two levels above the folder of this `SKILL.md`', sec)
        self.assertNotIn('${CLAUDE_SKILL_DIR}', sec)

    def test_run_log_section_names_inline_and_release_lines(self):
        sec = self.section('### 4.7.2 ', '### 4.7.3 ')
        self.assertIn('inline: agent=', sec)
        self.assertIn('release: gate=G2', sec)
        self.assertIn('answer: gate=G2 tool=', sec)
        self.assertIn('(inline k)', sec)

    def test_agent_section_describes_inline_roles(self):
        sec = self.section('### 4.5 ', '### 4.5.1 ')
        self.assertIn('**Inline roles', sec)
        self.assertIn('"model": "inline"', sec)
        self.assertIn('scope-guard', sec[sec.index('**Inline roles'):])

    def test_host_section_has_g2_row_and_listed_main_skill(self):
        sec = self.section('### 4.14 ', '### 4.15 ')
        row = [l for l in sec.splitlines() if l.startswith('| G2 permission dialog')]
        self.assertEqual(len(row), 1)
        self.assertIn('exit 2', row[0])
        self.assertIn('`release`', row[0])
        self.assertIn('`my-agent:my-agent`', sec)
        self.assertNotIn('The main skill is not listed', sec)
        self.assertNotIn('no G2 dialog', sec)
        self.assertIn('my-agent on Codex: plugin folder', sec)

    def test_monitor_section_names_gate_view(self):
        section = self.section('### 4.7.4 ', '### 4.8 ')
        for word in ('gate', '/api/tasks/<key>/prototype', '--report'):
            self.assertIn(word, section, word)

    def test_prototype_uses_mock_up_skill(self):
        a = self.text.index('**What G1-B shows: mock-up and prototype**')
        section = self.text[a:self.text.index('**What a prototype is**')]
        self.assertIn('skills/mock-up', section)
        self.assertIn('capture.sh', section)

    def test_preset_mechanism_is_described(self):
        section = self.section('### 4.5 ', '### 4.5.1 ')
        for word in ('`agent-models.json`', 'agent-models.py', 'agent-models.example.json',
                     'pass=', 'CLAUDE_CODE_EFFORT_LEVEL', 'beats'):
            self.assertIn(word, section, word)
        self.assertNotIn('does not pass an `effort` argument in calls', section)
        f13 = [l for l in self.text.splitlines() if l.startswith('| F13 |')][0]
        self.assertIn('preset', f13)
        self.assertIn('retry', f13)

    def test_preset_rules_in_intake_and_plan(self):
        for word in ('`Models:`', '`## Models`', 'presets --profile', '`Models` row'):
            self.assertIn(word, self.text, word)
        profile = [l for l in self.text.splitlines() if l.startswith('- **Profile change at the first gate')][0]
        self.assertIn('`Models:`', profile)
        self.assertIn('preset', profile)

    def test_run_log_section_names_the_models_line(self):
        section = self.section('### 4.7.2 ', '### 4.7.3 ')
        self.assertIn('`models:`', section)
        self.assertIn('preset=', section)
        self.assertIn('source=file', section)

    def test_retry_beats_the_preset(self):
        section = self.section('### 4.8 ', '### 4.8.1 ')
        self.assertIn('beats the preset', section)

    def test_monitor_section_names_report_tab_and_open_html(self):
        section = self.section('### 4.7.4 ', '### 4.8 ')
        for word in ('Report', '/api/tasks/<key>/report', 'open-html.py', 'monitor-up.py'):
            self.assertIn(word, section, word)

    def test_gate_reports_open_with_overview_and_takeaway(self):
        self.assertIn('### Overview', self.text)
        self.assertIn('### Takeaway', self.text)

    def test_prototype_is_a_local_file_opened_by_open_html(self):
        a = self.text.index('**What G1-B shows: mock-up and prototype**')
        section = self.text[a:self.text.index('**What a prototype is**')]
        self.assertIn('open-html.py', section)
        for stale in ('claude.ai', 'private artifact', 'artifact link', 'publishes it'):
            self.assertNotIn(stale, section, stale)
        self.assertNotIn('prototype link', self.section('### 4.4 ', '### 4.5 '))

    def test_check_before_anything_leaves_has_two_places(self):
        a = self.text.index('**check before anything leaves**')
        section = self.text[a:self.text.index('### 4.13 ')]
        self.assertIn('two places', section)
        self.assertNotIn('three places', section)
        self.assertNotIn('prototype', section)
        self.assertNotIn('artifact', section)

    def test_decision_log_has_q26_to_q28(self):
        for q in ('Q26', 'Q27', 'Q28'):
            rows = [l for l in self.text.splitlines() if l.startswith(f'| {q} |')]
            self.assertEqual(len(rows), 1, q)
        q28 = [l for l in self.text.splitlines() if l.startswith('| Q28 |')][0]
        self.assertIn('open-html.py', q28)

    def test_run_log_kinds_name_the_guard_line(self):
        section = self.section('### 4.7.2 ', '### 4.7.3 ')
        self.assertIn('`guard:`', section)
        for field in ma_schema.GUARD_FIELDS:
            self.assertIn(f'`{field}=`', section, field)

    def test_g1b_section_says_a_sibling_task_folder_write_is_asked(self):
        a = self.text.index('**G1-B hard gate**')
        sec = self.text[a:self.text.index('- **Block when the hook fails:**', a)]
        self.assertIn('sibling task folder', sec)
        self.assertRegex(sec, r'(?s)sibling task folder.{0,200}asked')

    def test_cost_only_texts(self):
        lines = self.text.splitlines()
        g3 = [x for x in lines if x.startswith('| **G3 Final acceptance**')]
        self.assertEqual(len(g3), 1)
        self.assertIn('cost (reference, 4.8)', g3[0])
        self.assertNotIn('tokens and cost', g3[0])
        deliver = [x for x in lines if x.startswith('[Deliver] (chat)')]
        self.assertEqual(len(deliver), 1)
        self.assertNotIn('tokens', deliver[0])
        snap = [x for x in lines if x.startswith('- **Usage snapshot:**')]
        self.assertEqual(len(snap), 1)
        self.assertIn('≈ $', snap[0])
        self.assertIn('ma_prices', self.section('**Price table**', '\n**'))

    def test_status_line_plugin_version_matches_plugin_json(self):
        line = self.text.splitlines()[3]
        found = re.search(r'plugin (\d+\.\d+\.\d+)', line)
        self.assertIsNotNone(found, line[:80])
        manifest = json.loads((REPO / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))
        self.assertEqual(found.group(1), manifest['version'])

    def test_principles_name_the_assumption_principle_and_judge_misses(self):
        section = self.section('### 4.1 Principles', '### 4.1.1 ')
        self.assertIn('assumption about what the model cannot do alone', section)
        self.assertIn('Judge misses', section)
        self.assertIn('removal candidate', section)

    def test_maintenance_section_names_removal_candidate_review(self):
        section = self.section('### 4.11 ', '### 4.12 ')
        self.assertIn('removal candidate', section)
        self.assertIn('feedback review', section)
        self.assertIn('Judge misses', section)

    def test_security_section_names_the_environment_deny(self):
        section = self.section('### 4.12 ', '## 5. ')
        self.assertIn('may not read the environment', section)

    def test_decision_log_has_q23_row(self):
        rows = [l for l in self.text.splitlines() if l.startswith('| Q23 |')]
        self.assertEqual(len(rows), 1, rows)
        self.assertIn('2026-10-30', rows[0])

    def test_security_section_names_the_read_roots_and_git_mv(self):
        section = self.section('### 4.12 ', '## 5. ')
        for word in ('data folder', 'plugin folder', 'scratchpad', 'git mv'):
            self.assertIn(word, section)
        self.assertIn('may be approved without a dialog and without a G2 record', section)

    def test_resume_section_gives_a_non_owner_session_no_notice(self):
        section = self.section('### 4.8.2 ', '### 4.9 ')
        self.assertNotIn('otherwise work as usual', section)
        self.assertIn('gets no text (2026-11-23, plugin 0.26.0, Q44', section)

    def test_hooks_and_rules_apply_only_during_a_task(self):
        # Q44: the policy is stated once in the G2 panel, and the list is applied by a hook, not merged into settings
        panel = self.section('**actions G2 asks about**', '**Storing the deliverable after G3')
        lines = panel.splitlines()
        start = next(i for i, l in enumerate(lines)
                     if l.startswith('- **When the hooks and the permission rules apply (2026-11-23, plugin 0.26.0, Q44):**'))
        end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith('- '))
        policy = '\n'.join(lines[start:end])
        for word in ('only while the skill has been called and is running a task', '`.active`', '`session:`',
                     'no my-agent rule sits in the user settings', 'scope-guard', 'session-notice', 'subagent-log',
                     'permission-log.py', 'Codex and Antigravity', 'removes them'):
            self.assertIn(word, policy, word)
        log = next(l for l in lines[start:end] if l.startswith('  - **subagent-log'))
        for word in ('intended exception', '`call`', '`start`', '`stop`', 'does not compare the session'):
            self.assertIn(word, log, word)
        guard = next(l for l in lines if l.startswith('- **Permission guard (2026-11-23, plugin 0.26.0):**'))
        self.assertIn('permission-guard.py', guard)
        for word in ('`Bash|Read|Grep|Glob|mcp__.*`', '`onFailure: block`', '`bypassPermissions`', 'Claude Code only',
                     'ma_bash.command_texts', 'ma_bash.read_paths', 'F7'):
            self.assertIn(word, panel, word)
        self.assertIn('21 rules, all `Read` rules', panel)
        self.assertNotIn('merges by hand', panel)
        q44 = next(l for l in self.text.splitlines() if l.startswith('| Q44 |'))
        for word in ('only while the skill has been called and is running a task', 'permission-guard.py', 'F7'):
            self.assertIn(word, q44, word)

    def test_arch_steps_remove_cd_rule_before_active(self):
        # criterion 4: the continue, Abort and Accept steps and Q17 name the `Cd(...)` removal before the `.active` deletion
        text = self.text
        cont = text[text.index('**If `Status: done` (the session was cut off'):]
        cont = cont[:cont.index('\n')]
        abort = text[text.index('**Abort**\n\nThe procedure when'):]
        abort = abort[abort.index('\n3. '):abort.index('\n4. ')]
        accept = next(l for l in text.splitlines() if l.strip().startswith('3. Last,') and 'active-index.json' in l)
        q17 = next(l for l in text.splitlines() if l.startswith('| Q17 |'))
        for name, part, mark in (('continue', cont, 'delete only `.active`'), ('abort', abort, 'delete `.active`'),
                                 ('accept', accept, 'delete `.active`'), ('Q17', q17, 'deletes only `.active`')):
            self.assertIn('`Cd(...)` rule', part, name)
            self.assertIn(mark, part, name)
            self.assertLess(part.index('`Cd(...)` rule'), part.index(mark), name)

    def test_task_ending_steps_name_worktree_cleanup_not_cd_guard_remove(self):
        # criterion 16: every task-ending path removes the `Cd(...)` rule through `worktree.py cleanup` (4.6), which runs
        # `cd-guard.py --remove` itself; no step line tells L1 to run `cd-guard.py --remove` directly
        text = self.text
        cont = text[text.index('**If `Status: done` (the session was cut off'):]
        cont = cont[:cont.index('\n')]
        abort = text[text.index('**Abort**\n\nThe procedure when'):]
        abort = abort[abort.index('\n3. '):abort.index('\n4. ')]
        accept = next(l for l in text.splitlines() if l.strip().startswith('3. Last,') and 'active-index.json' in l)
        q17 = next(l for l in text.splitlines() if l.startswith('| Q17 |'))
        s44 = next(l for l in text.splitlines() if 'removed on every path that deletes `.active`' in l)
        for name, part in (('continue', cont), ('abort', abort), ('accept', accept), ('Q17', q17), ('4.4 bullet', s44)):
            self.assertIn('`worktree.py cleanup`', part, name)
            self.assertIn('4.6', part, name)
            self.assertIn('cd-guard.py --remove', part, name)
            self.assertNotIn('rule with `cd-guard.py --remove`', part, name)
            self.assertNotIn('rule (`cd-guard.py --remove`', part, name)
            self.assertNotIn('L1 runs `cd-guard.py --remove', part, name)
        self.assertNotIn('rule with `cd-guard.py --remove`', text)

    def test_gate_section_has_the_ask_texts(self):
        section = self.section('### 4.4 ', '### 4.5 ')
        for text in ('my-agent plan gate: write outside the task folder', 'my-agent verdict gate:',
                     'cannot parse the command'):
            self.assertIn(text, section)

    def test_decision_log_has_q24_row(self):
        rows = [l for l in self.text.splitlines() if l.startswith('| Q24 |')]
        self.assertEqual(len(rows), 1, rows)
        self.assertIn('2026-10-30', rows[0])

    def test_decision_log_has_q25_row(self):
        rows = [l for l in self.text.splitlines() if l.startswith('| Q25 |')]
        self.assertEqual(len(rows), 1, rows)
        self.assertIn('2026-10-31', rows[0])

    def test_host_layer_section(self):
        section = self.section('### 4.14 ', '### 4.15 ')
        self.assertIn('Host layer', section.splitlines()[0])
        for text in ('l1-orchestration/hosts.md', 'ma_host.py'):
            self.assertIn(text, section)
        a = section.index('**Host differences**')
        differences = section[a:].lower()
        for word in ('fallback', 'workaround'):
            self.assertNotIn(word, differences)
        self.assertIn('<codex home>/agents/', differences)
        self.assertIn('`my-agent-<role>`', differences)
        self.assertIn('--install-agents', section)
        self.assertIn('`[a-z0-9_]`', differences)
        self.assertNotIn('my_agent' + '_<role>', section)
        self.assertNotIn('not used: the main session', differences)

    def test_antigravity_host_layer_section(self):
        section = self.section('### 4.15 ', '## 5. ')
        self.assertIn('Host layer (Antigravity) [proposed]', section.splitlines()[0])
        for text in ('l1-orchestration/hosts-antigravity.md', '`rules/AGENTS.md`', 'ma_host.py', 'build-antigravity.py --write',
                     '`.antigravity-plugin/plugin.json`', '`hooks.json` at the plugin root', '--install-agents',
                     '`Antigravity agents: installed 10 (<version>)`', '`{"decision":"force_ask","reason":…}`',
                     'No task has been run in Antigravity from Intake to G3', '`agy plugin validate --strict plugins/my-agent`'):
            self.assertIn(text, section)
        for head in ('**Host differences**', '**Limitations**', '**Not verified**'):
            self.assertIn(head, section)
        self.assertLess(section.index('**Limitations**'), section.index('**Not verified**'))
        limits = section[section.index('**Limitations**'):section.index('**Not verified**')]
        for text in ('No `SubagentStart`, `SubagentStop` or `PermissionRequest` event', 'Usage and cost are not read',
                     '`WebFetch` in an agent\'s `tools` becomes `search_web`'):
            self.assertIn(text, limits)
        for word in ('fallback', 'workaround'):
            self.assertNotIn(word, section.lower())
        self.assertIn('Antigravity CLI (`agy`) as a third host (4.15)', self.text.splitlines()[4])
        q43 = next(l for l in self.text.splitlines() if l.startswith('| Q43 |'))
        self.assertIn('stays `[proposed]` until a task has run end to end in Antigravity', q43)

    def test_host_differences_name_the_question_tool(self):
        section = self.section('### 4.14 ', '### 4.15 ')
        differences = section[section.index('**Host differences**'):]
        self.assertIn('`request_user_input`', differences)
        self.assertIn('`default_mode_request_user_input`', differences)
        self.assertIn('--check-question-tool', section)
        row = next(l for l in differences.splitlines() if l.startswith('| Question to the person |'))
        self.assertNotIn('both with the choices', row)
        part = next(l for l in section.splitlines() if l.startswith('| `l1-orchestration/hosts.md` |'))
        self.assertIn('before `## Core rules`', part)
        self.assertIn('before the first question or command', part)
        variables = next(l for l in differences.splitlines() if l.startswith('| Skill text variables |'))
        self.assertIn('ask the person only with request_user_input', variables)

    def bullet(self, start, end, prefix):
        """The bullet of the section `start`..`end` that begins with `prefix`, with its nested lines."""
        lines = self.section(start, end).splitlines()
        i = next(k for k, l in enumerate(lines) if l.startswith(prefix))
        j = next((k for k in range(i + 1, len(lines)) if lines[k].startswith(('- ', '**', '#'))), len(lines))
        return '\n'.join(lines[i:j])

    def assert_words(self, text, words):
        for word in words:
            self.assertIn(word, text, word)

    def test_popup_layout_and_findings_list_table_in_arch_doc(self):
        """Criteria 8, 9: the layout rule of a multi-part popup and the findings list table rule."""
        start = self.text.index('**Findings table and popup text at the gate approvals')
        section = self.text[start:self.text.index('**G1-B hard gate**', start)]
        self.assert_words(section, ('List markers', '`- Next: …`', 'two sentences', 'blank line',
                                    'findings list table',
                                    '`# | Severity | Location | Finding | Fix L1 would apply | Who decides`',
                                    'not the count table'))
        bullet = self.bullet('**Findings table and popup text at the gate approvals', '**G1-B hard gate**',
                             '- **Findings list table')
        self.assert_words(bullet, (
            'after every Scope Review and Plan Review judgment', 'also with no popup', '`Who decides`',
            '`L1 applies`', '`you decide`', 'no findings', 'one line instead of a table',
            'The popup for the marked findings stays'))
        self.assertNotIn('five-column', bullet)
        marked = self.line_of('- **Marked findings popup (2026-11-24, plugin 0.30.0):**')
        self.assert_words(marked, ('findings list table', 'also when no finding is marked'))

    def test_codex_g2_answer_closes_with_its_result(self):
        line = next(l for l in self.section('### 4.7.2 ', '### 4.7.3 ').splitlines()
                    if l.startswith('- **How the readers class them:**'))
        self.assertIn('with the result of that answer', line)
        self.assertNotIn('as `allowed`', line)
        self.assertNotIn('that `key=` as `allowed`', self.text)

    def test_interpreter_writes_and_their_limit(self):
        self.assertNotIn('For example, writing a file with `python -c`.', self.text)
        risk = self.bullet('### 4.4 ', '### 4.5 ', '- **remaining risk:**')
        self.assert_words(risk, ('interpreter_writes', 'scope-guard', 'plan-approved-check', 'verdict'))
        bullet = self.bullet('### 4.12 ', '### 4.13 ', '- **Inline interpreter code (2026-11-22, plugin 0.25.0; #92):**')
        self.assertGreater(len(bullet.splitlines()), 10)
        self.assert_words(bullet, (
            '`ma_bash.interpreter_writes(cmd, cwd)`', 'next to `write_targets`', 'Only `scope-guard.py` calls it',
            '`plan-approved-check.py` and `verdict-fresh-check.py` keep `write_targets`', 'do not read it',
            'the person decided (2026-11-22)', '`python`, `python3`', '`node`', '`ruby`', '`perl`',
            'heredoc', 'sudo', 'xargs', '`ast`', 'Cannot tell where this command writes',
            'The contents of a script file or module', '`os.system`', '`subprocess`', '`child_process`',
            '`exec`, `eval`, `getattr`, `__import__`', '`<<<`', '`perl -i`', '`ruby -i`',
            'inline code with no visible write is not refused'))

    def test_settled_and_stand_alone_popups_described(self):
        start, end = '### 4.4 ', '### 4.5 '
        head = '**Popups after Intake (2026-11-22, plugin 0.25.0)**'
        self.assertIn(head, self.section(start, end))
        settled = self.bullet(start, end, '- **Settled popup:**')
        self.assert_words(settled, (
            'after Intake', 'request, the files or the person\'s earlier answer', '`ask` line', '`answer … by=L1`',
            '(answered by L1)', 'SKILL.md "Question rules"', 'Always asked:', 'G1-A, G1-B, G3, G2, E',
            'every Intake popup', 'a popup without a recommended choice', 'with a question back',
            'Delegated approval rules stay', 'counted with the L1 answers'))
        alone = self.bullet(start, end, '- **Stand-alone popup:**')
        self.assert_words(alone, ('stands alone', 'one-line plain explanation', 'what it contains',
                                  'what it leads to', 'written at plan time'))
        preset = self.bullet(start, end, '- **Models preset popup:**')
        self.assert_words(preset, ('one line', 'cost or care', '`presets` line'))

    def test_g3_recommendation_follows_the_open_items(self):
        g3 = next(l for l in self.text.splitlines() if l.startswith('| **G3 Final acceptance**'))
        self.assert_words(g3, ('while any SHOULD-FIX or NITPICK is open', 'only with no open item',
                               'cost (reference, 4.8)'))
        self.assertNotIn('while a SHOULD-FIX is open', g3)
        self.assertNotIn('with only NITPICK items open', g3)
        self.assertNotIn('and after a G3 Rework answer Accept (Commit) is, because', g3)
        bullet = self.bullet('### 4.4 ', '### 4.5 ', '- **G3 recommendation')
        self.assert_words(bullet, ('every G3 of the task', 'under delegated approval', 'up to 3 rounds'))
        self.assertNotIn('first G3', bullet)
        self.assertNotIn('after a Rework answer', bullet)
        self.assertNotIn('Accept (Commit) at a G3 after', bullet)

    def test_g3_rework_recommended_like_the_delegated_answer(self):
        """Criteria 1, 8: the popup and the delegated answer agree at every G3."""
        bullet = self.bullet('### 4.4 ', '### 4.5 ', '- **G3 recommendation')
        self.assert_words(bullet, ('2026-11-24, plugin 0.30.0', '`Rework: fix all open items`',
                                   'SHOULD-FIX or NITPICK', 'No open item: Accept (dev: Commit)',
                                   'the same answer', 'gates.md'))

    def test_remote_take_section_agrees_with_g3_recommendation(self):
        """Criteria 1, 8: no place in the document keeps the take as always recommended."""
        for line in self.text.splitlines():
            self.assertNotIn('`Commit` stays the recommended take', line)
            self.assertNotIn('`Commit` stays recommended', line)
        remote = self.text[self.text.index('- **Remote take at G3 (2026-11-21, Q41)'):]
        remote = remote[:remote.index('- **Verify and Review scope')]
        self.assert_words(remote, ('`Rework: fix all open items (Recommended)` / `Commit` / `Rework` / `Abort`',
                                   '`Commit (Recommended)` / `Rework` / `Abort`',
                                   'only with no open review item', 'never recommended'))
        q41 = self.line_of('| Q41 |')
        self.assert_words(q41, ('only with no open review item',))
        self.assertNotIn('`Commit` stays recommended', q41)

    def test_revise_findings_popup_comes_before_the_fix(self):
        """Criteria 6, 8: a REVISE in the Plan Review item does not skip the marked-findings popup."""
        line = self.line_of('- **Plan Review findings, the same in every profile')
        self.assertNotIn('goes back for a fix without asking', line)
        self.assert_words(line, ('popup over the marked findings',))

    def test_rule_locations_named_in_design(self):
        """Criterion 8: the person's-choice mark is `define.md` step 1B item 4, the width pointer item 3."""
        mark = self.line_of("**Person's-choice mark (2026-11-24, plugin 0.30.0)")
        self.assertIn('`define.md` step 1B item 4', mark)
        self.assertNotIn('`define.md` step 1B item 3', mark)
        self.assertIn('`define.md` step 1B item 3 points to it', self.line_of('**Scope-width popup (2026-11-24'))

    def test_persons_choice_mark_in_design(self):
        """Criteria 2, 8: the mark in scope.md and the scope judge's reading of it."""
        line = self.line_of("**Person's-choice mark (2026-11-24, plugin 0.30.0)")
        self.assert_words(line, ('`(the person\'s choice)`', 'Scope interview', 'right before', '`[check:',
                                 'answered by L1', 'scope-reviewer', 'Traceability', 'checkability'))

    def test_measured_duration_in_design(self):
        """Criteria 3, 8: explorer duration, the hand-off with the upper bound and the coder time limit."""
        line = self.line_of('**Measured duration and time limit (2026-11-24, plugin 0.30.0)')
        self.assert_words(line, ('explorer', 'whole seconds', 'rounded up', '`cannot run:`', 'no duration',
                                 '`<command>: <n> s`', 'upper bound', '`no measured duration`', 'coder',
                                 'twice', 'longest', 'foreground', 'build.md'))

    def test_decision_line_matching_in_design(self):
        """Criteria 4, 8: a Decisions line matches by file name and line, with whole components."""
        line = self.line_of('**Decisions-line matching (2026-11-24, plugin 0.30.0)')
        self.assert_words(line, ('`judged_counts`', 'file name', 'whole trailing', '`scope.md:14`',
                                 '`rules/scope.md:14`', '`ope.md:14`', 'severity', 'both', 'findings.py',
                                 'Report tab'))

    def test_ask_person_mark_in_design(self):
        """Criteria 5, 8: the mark, its three kinds and what it leaves unchanged."""
        line = self.line_of('**Finding mark `[ask person]` (2026-11-24, plugin 0.30.0)')
        self.assert_words(line, ('scope-reviewer', 'plan-reviewer', 'completion criterion', 'non-goal',
                                 'constraint', "`(the person's choice)`", "the person's answer",
                                 'any severity', 'NITPICK', 'ma_schema', 'old'))

    def test_marked_findings_popup_in_design(self):
        """Criteria 6, 8: unmarked findings are applied silently, marked ones go in one popup."""
        line = self.line_of('**Marked findings popup (2026-11-24, plugin 0.30.0)')
        self.assert_words(line, ('unmarked', 'without a popup', '`READY', '`REVISE`', 'one popup', 'marked',
                                 '`Apply all (Recommended)`', '`Confirm without applying`',
                                 '`Approve without applying`', '`Pick myself`', 'BLOCKER',
                                 'delegated approval', 'no marked finding'))
        scope = self.bullet('### 4.3 ', '### 4.4 ', '- **Scope Review findings')
        plan = self.bullet('### 4.3 ', '### 4.4 ', '- **Plan Review findings')
        for text in (scope, plan):
            self.assertIn('marked', text)
            self.assertNotIn('with any SHOULD-FIX one popup', text)

    def test_scope_width_popup_in_design(self):
        """Criteria 7, 8: the scope-width popup and the richer second choice."""
        line = self.line_of('**Scope-width popup (2026-11-24, plugin 0.30.0)')
        self.assert_words(line, ('Scope interview', '`Only what was asked (Recommended)`',
                                 '`Related things too`', '`The richer result`', 'second', 'profile',
                                 '`ask gate=Q', 'rec="Only what was asked"', '`answer gate=Q`', 'define.md'))

    def test_procedure_rules_are_described_in_their_sections(self):
        popups = self.section('### 4.4 ', '### 4.5 ')
        self.assert_words(popups, ('Scope change: u<n> <new approach>', '`Give direction`',
                                   'how the person checks it'))
        findings = self.bullet('### 4.4 ', '### 4.5 ', '- **Finding locations')
        self.assert_words(findings, ('`<file>:<a>-<b>`', 'a line inside it', 'the bare file', 'a folder',
                                     'stays unmatched'))
        mapping = self.bullet('### 4.4 ', '### 4.5 ', '- **Verify and Review scope')
        self.assert_words(mapping, ('nested bullets', 'relative to the git root', 'a `./` prefix',
                                    'listed under the work unit that changes its source'))
        self.assertIn('`cp -pR <folder>/.`', self.section('### 4.7.1 ', '### 4.7.2 '))
        self.assert_words(self.section('### 4.7.2 ', '### 4.7.3 '), (
            '`rec=-` gives `none`', 'no `rec=` field', 'ask` plus `answer … by=L1'))
        blueprint = self.section('### 4.7.5 ', '### 4.7.6 ')
        self.assert_words(blueprint, ('relative to the repository root', 'git diff -U0 -- docs/blueprint/',
                                      'as done by L1 after G3'))
        self.assertIn('no Verify run starts while an adjustment', self.section('### 4.8.1 ', '### 4.8.2 '))
        resume = self.section('### 4.8.2 ', '### 4.9 ')
        self.assert_words(resume, ('`behind:`', 'FETCH_TIMEOUT', 'GIT_TERMINAL_PROMPT=0', '`--request-file`',
                                   '`git worktree remove --force <worktree>`', 'git branch -D <branch>', 'its contents'))
        agents = self.bullet('### 4.5 ', '### 4.5.1 ', '- **Rules added 2026-11-22')
        self.assert_words(agents, ('syntax check', 'never retries that write', 'foreground', 'summary lines',
                                   'never invents a task ID', 'nothing to fix', 'Glob or Grep',
                                   'list a generated file under the work unit', 'only L1 can meet after G3'))
        self.assert_words(self.section('### 4.1 Principles', '### 4.1.1 '), (
            'adds no gate and no popup kind', 'behind `origin`'))

    def test_gate_report_calls_in_design(self):
        """Criterion 12: the doc describes the pre-gate call, Back to Execute, the writer report and the other changes."""
        calls = self.section('**Gate report calls (2026-11-25, plugin 0.31.0)**', '**G1-B hard gate**')
        self.assert_words(calls, ('`pre-gate.py`', '`--report-text`', '`Gate report: G1-B`', '`Gate report: G3`',
                                  '`report/G3.md`', '`report-ko.json`', 'not only within one step',
                                  '`BLOCKER · 0 / SHOULD-FIX · 0 / NITPICK · 0`', '`2/0`', '`## Counts`',
                                  '`| Round | BLOCKER | SHOULD-FIX | NITPICK |`', 'first Review call of the task',
                                  'every finding', '`[<step ID>] <step name> · <gate>`', '`[1B] Explore → Scope · Q`',
                                  '`[4B] Review → Deliver · G3`', '`[1A] Intake`'))
        files = self.section('**Gate report files (`report/`)**', '**G1-B hard gate**')
        self.assert_words(files, ('`Gate report: G1-B`', '`plan-review.md`', 'scope-guard', '`report/`'))
        self.assertIn('`Gate report: G1-B`', self.section('**G1-B hard gate**', '- **Block when the hook fails:**'))
        self.assertIn('pre-gate.py', self.line_of('**Fewer main-session calls'))
        self.assertIn('**Gate report:**', self.section('### 4.5 ', '### 4.5.1 '))
        change = self.section('### 4.8.1 ', '### 4.8.2 ')
        back = change[change.index('**Back to Execute'):]
        self.assertIn('back-execute.py', back)
        self.assertNotIn('cp -p', back[:back.index('Small fix with only Review rerun')])
        self.assertNotIn('`cmp`', back[:back.index('Small fix with only Review rerun')])
        self.assert_words(change, ('**Light path after G3 Rework', 'every open item is a NITPICK',
                                   'one G3 Rework round', 'only Review runs again'))
        self.assert_words(change, ('documents-only small fix', '`archive.py --only verify.md review.md changed-files.md`',
                                   'light verifier judgment', 'Back to Execute with the failing test',
                                   'a documents-only small fix takes this route in place of the full rerun'))
        self.assertIn('If every open item is a NITPICK small fix, or every fix is a documents-only small fix, '
                      'L1 fixes them; only Review runs again, or the light verifier judgment too when a fixed '
                      'document maps to a criterion.', self.section('### 4.4 ', '### 4.5 '))
        self.assertNotIn('(open)`', self.text)

    def test_step_ids_in_design(self):
        """Criterion 9: the 4.3 table and the flow text use the step IDs; old numeric lines are still read."""
        sec = self.section('### 4.3 ', '### 4.4 ')
        rows = [l.split('|')[2].strip() for l in sec.splitlines() if l.startswith('| **') or l.startswith('| |')]
        self.assertEqual([r.split(' ')[0] for r in rows], list(ma_schema.STEP_IDS))
        ids = self.section('- **Step IDs (2026-11-25, plugin 0.31.0):**', '### 4.4 ')
        self.assert_words(ids, ('`1A`', '`4B`', '`n=1`…`n=8`', 'still read', 'mixed'))
        for path in (ARCH, ARCH.with_name('my-agent-monitor-design.md')):
            text = path.read_text(encoding='utf-8')
            for pat in (r'\b[1-8]\. (Intake|Explore|Plan|Execute|Merge|Verify|Review)', r'step:? n=[1-8]\b',
                        r'\b[1-8] (Intake|Explore|Execute|Merge|Plan Review|Review →)\b', r'\bstep [1-8] ·'):
                self.assertEqual(re.findall(pat, text), [], (path.name, pat))

    def test_no_old_gate_names_in_design_docs(self):
        """Criterion 15: G1-A and G1-B in the architecture doc, the monitor design doc and the HITL guide."""
        for name in ('my-agent-architecture.md', 'my-agent-monitor-design.md', 'hitl-orchestration-guide.md'):
            text = ARCH.with_name(name).read_text(encoding='utf-8')
            self.assertEqual(re.findall(r'G1[ab]\b', text), [], name)
        self.assertIn('old lowercase gate names', self.section('- **Step IDs (2026-11-25, plugin 0.31.0):**', '### 4.4 '))

    def test_blueprint_popup_recommendation_in_design(self):
        """Criterion 8: the keep-or-change popup lists the judged choice first, one popup per line."""
        sec = self.section('### 4.7.5 ', '### 4.7.6 ')
        found = [l for l in sec.splitlines() if l.startswith('  - **Scope:**')]
        self.assertEqual(len(found), 1, found)
        self.assert_words(found[0], (
            'one popup per line', '`Keep it` / `Change it`', 'listed first with `(Recommended)`',
            'the question gives the reason in one line',
            'recommends `Change it` when the request cannot be met while the line stays', 'judges a change better',
            'otherwise `Keep it`', 'incidental', '`ask gate=Q … rec="<that choice>"`', '`answer gate=Q`',
            'settled popup', 'delegated approval'))
        self.assertNotIn('Keep it (Recommended)', found[0])
        self.assertNotIn('rec="Keep it"', found[0])

    def test_task_location_without_popup_in_design(self):
        """Criteria 5, 8: the location order and its exceptions; no current text names a location popup."""
        bullet = self.bullet('### 4.8.2 ', '### 4.9 ', '- **Task location without a popup (2026-11-26')
        self.assert_words(bullet, (
            'Intake asks no popup', 'what the work is on', 'the first one named when there are several',
            'only as a reference, a comparison or the explanation of a cause', '`--candidate`', '`target:`',
            'then in its repository root', 'installed skill', 'a repository name', 'subfolder',
            'gives the repository root', 'linked worktree', "that worktree's own top folder", 'does not exist',
            'data folder', 'plugin install cache', 'next named target', 'Otherwise the run folder',
            '`Location: <path> (<reason>)`', 'in one line',
            'names it in the request or runs the session from it', 'running-task popup', 'Git check',
            '`--dev`'))
        self.assertLess(bullet.index('what the work is on'), bullet.index('Otherwise the run folder'))
        q10 = self.line_of('| Q10 |')
        self.assertIn('Replaced 2026-11-26', q10)
        for number, line in enumerate(self.text.splitlines(), 1):
            if line.startswith(('- Status:', '| Q10 |')) or 'replaced 2026-11-26' in line.lower():
                continue
            for stale in ('Other path', 'location popup', 'Where should the task location', 'Current folder',
                          'item 2 offers', 'item 2 popup', 'Asking the location'):
                self.assertNotIn(stale, line, f'line {number}')
        self.assertNotIn('task location', self.line_of('6. **The number of questions to the person'))
        # the data folder bullet no longer says its line goes into popups (only the removed popup showed it)
        source = self.line_of('- **Where the data folder comes from:**')
        self.assertNotIn('popup', source)
        self.assertIn('uses its output line as `<data folder>` in file paths and as `--data-dir "<data folder>"`', source)
        # SKILL.md "Data folder" no longer points to the removed popup
        skill = SKILL.read_text(encoding='utf-8')
        self.assertNotIn('Use it for the popup', skill)
        self.assertIn('Use it for `projects.txt`', skill)

    def test_intake_order_checks_the_chosen_location(self):
        """Criterion 8: the Intake order and the facts text describe the picked location and how it is found."""
        order = self.line_of('  - **Intake order (2026-11-15):**')
        self.assert_words(order, ('the location item 2 picks', '`.active`', 'picked location', '`candidate:` block',
                                  'item 1 popup', 'Git check', '`--dev`'))
        facts = self.line_of('    - **`facts` (read-only):**')
        self.assert_words(facts, (
            '`target: <as given> | resolved: <resolved path> | location: <task location> | exists: yes|no | '
            'skip: no|data folder|plugin cache`', 'after the `presets` lines', 'before the first `candidate:` block',
            'in the order given', 'de-duplicated', 'in the run folder, then in `run_git`', 'links followed',
            'a file gives its folder', 'its top folder', 'linked worktree', "the target's own resolved path",
            '`plugins/cache`', '`CLAUDE_CONFIG_DIR`', 'one `--candidate "<target as named>"` per',
            'after `Fix it first`'))

    def test_intake_runs_only_the_named_facts_reruns_in_design(self):
        """Criterion 8: between the facts call and create, the only commands are the named facts reruns."""
        script = self.line_of('  - **Intake script (2026-11-16, plugin 0.15.0):**')
        self.assert_words(script, ('Items 1–5 and the Git check read the facts output',
                                   'the only commands they run are the facts reruns and the `work-branch` call they name'))

    def test_continue_it_continues_only_the_shown_task_in_design(self):
        """Criterion 8: `Continue it` never continues another task than the one the popup showed."""
        bullet = self.bullet('### 4.8.2 ', '### 4.9 ', '- If `.active` already exists at Intake')
        self.assert_words(bullet, (
            '`Continue it` continues only the task the popup showed', '`status` item 1',
            'finds no `.active` or the one of another task', 'L1 continues none',
            '`/my-agent continue` from a session in the folder of the shown task', 'stops, creating nothing'))

    def test_codex_cache_and_unknown_home_target_in_design(self):
        """Criterion 8: the Codex cache folder is skipped on every host; an unknown user's `~` path is missing."""
        facts = self.line_of('    - **`facts` (read-only):**')
        self.assert_words(facts, (
            '`CODEX_HOME` (otherwise under `~/.codex`)', 'on every host',
            'where Antigravity installs plugins is not confirmed',
            'A `~<unknown user>` path is a missing target (`exists: no`', 'below the run folder',
            'does not stop the call'))

    def test_report_reason_names_skipped_targets_in_design(self):
        """Criterion 8: the report reason, and the skipped targets when every named one was passed over."""
        bullet = self.bullet('### 4.8.2 ', '### 4.9 ', '- **Task location without a popup (2026-11-26')
        self.assert_words(bullet, (
            '`repository root of the named target <target>`', '`the folder you ran in`',
            'every `target:` line was skipped',
            '`; skipped <target>: <missing | data folder | plugin cache>` for each'))

    def test_cd_rule_take_over_in_design(self):
        """Criterion 8: a rule already there is taken over, and every copy of the exact string is removed."""
        rule = self.line_of('  - **The `Cd(...)` rule of `cd-guard.py` (2026-11-23):**')
        guard = self.line_of('  - **Session folder guard (2026-11-21):**')
        for line in (rule, guard):
            self.assert_words(line, ('taken over', 'every copy', 'exact', 'neither taken over nor removed',
                                     'byte for byte', 'this task folder already records', 'no longer kept'))
            for stale in ('stays, and so does every other entry', '`present`, no record', 'had before',
                          'prints `present` and writes no record'):
                self.assertNotIn(stale, line, stale)
        self.assert_words(guard, ('cannot write <record>', 'cannot write <file>',
                                  '`added`, `taken over`, `present` or `not added`'))

    def test_unit_copy_removal_in_design(self):
        """Criterion 16: the refused-removal wording covers unit copies and keeps the harness worktree wording."""
        copy = self.line_of('- **Unit-copy removal after the compare (plugin 0.36.0):**')
        self.assert_words(copy, ('`worktree.py merge`', 'one `--force`', 'refused and kept, never unlocked', '"Open risks"',
                                 'ask no popup', '`kept: <path> (<cause>)`'))
        old = self.line_of('- **Worktree removal after the compare for a leftover harness worktree (#83):**')
        self.assert_words(old, ('`git worktree remove --force <worktree>`', 'one attempt per worktree', 'no `git branch -D`',
                                'no popup', 'no `git worktree unlock`', 'dev.md` 3B Merge'))

    def test_unit_copies_in_4_6_and_q46(self):
        """Criteria 3, 15: 4.6 names the tool, the store, the state file, exit 3, the session guard rule and cleanup;
        the decision row records the plan's answers, the inline coder role included."""
        s46 = self.section('### 4.6 ', '### 4.7 ')
        self.assert_words(s46, ('`worktree.py`', '`<task folder>/copy-store`', '`unit-copies.json`', 'exit 3',
                                '`sequential: <reason>`', '`Cd(/<resolved location>/.claude/worktrees/**)`',
                                '`cleanup`', '`cd-guard.py --remove`', 'Outcome table', '`merge` exit 1', '`keep`',
                                'Base compare before the apply', 'a coder group run in a workflow',
                                'Session guard before the first copy, every profile', 'sweep'))
        self.assertNotIn('only the first parallel group', s46)
        self.assertNotIn('isolation: "worktree"` in the Agent call only', s46)
        row = self.line_of('| Q46 | Parallel coders in unit copies')
        self.assert_words(row, ('(1) **Resume and abort:**', '`(running)` copy gets the `Merge` / `Redo` / `Discard` popup',
                                '`(kept)` copy gets one chat line', 'approved `## Existing work` rows',
                                '(2) **Absolute paths in check commands:**', '(3) **A unit\'s change to an ignored file**',
                                '(4) **Ignored files absent from copies:**', '`Not run in copy:`',
                                '(5) **Transcript first line and the fail-closed guard:**', '(6) **A session in a linked worktree',
                                '(7) **No size popup:**', '(8) **A coder group run in a workflow uses copies too:**',
                                '(9) **An inline coder role (`pass=inline`) gets no copies:**', '"Apply all"',
                                "criterion 3", 'Not taken'))
        self.assertIn('Superseded 2026-11-27 (plugin 0.36.0) by Q46', self.line_of('| Q9 | Parallel coders in the dev profile'))

    def test_git_mv_and_read_git_forms_for_a_copy_coder(self):
        """Criterion 12: a coder in its own copy is refused `git mv` and git commands but the read forms; the main-tree
        and F19 coders keep the allowance."""
        mv = self.line_of("- The coder's `git mv <src> <dst>` is allowed when both paths are in its write root")
        self.assert_words(mv, ('main-tree coder and a F19 `agent-<id>` coder', 'unchanged',
                               'A coder in its own unit copy is refused `git mv` and every git command except the read forms',
                               '`write_targets(read_git_only=True)`', '`GIT_READ`', '`stash list`/`show`',
                               'listing `branch` and `tag`', '`config --get`/`--get-all`/`--list`', '`worktree list`',
                               'bare `remote` and `remote -v`', 'no `GIT_*` variable',
                               'read-only git commands stay allowed for it'))
        limits = self.line_of('- **read and write path limits:**')
        self.assert_words(limits, ('refused `git mv` and every git command except the read forms', 'F19 `agent-<id>` coder'))
        copy = self.section('  - **Which copy is the coder\'s own', '  - **Which worktree is the coder\'s own, F19')
        self.assert_words(copy, ('`git mv`, `git add`', 'read-only git commands stay allowed', '`stash list`/`show`',
                                 'listing `branch` and `tag`', 'bare `remote` and `remote -v`', 'A bare `git config <name>`',
                                 'Own copy (row 7)', '| 10 |'))
        self.assertIn('`git mv`', self.section('### 4.12 ', '## 5. '))

    def test_no_first_group_only_wording_and_active_lookup_names_the_copy_step(self):
        """Criterion 16: no line outside the version history says coder worktrees are used only in the first group; the
        `.active` lookup names the store-backed copy step."""
        for line in self.text.splitlines():
            if line.startswith('- Status: '):
                continue
            if 'first parallel group' in line or 'only for the first group' in line:
                # the superseded Q9 row and the 0.36.0 text may name the old rule as history
                self.assertTrue('Superseded' in line or 'replaces' in line or 'earlier rule' in line
                                or 'no longer' in line or 'not needed' in line or '2026-10-25' in line, line[:160])
        self.assertNotIn('Subagents (coder uses a worktree only for the first parallel group)', self.text)
        self.assertNotIn('Parallel coders use worktrees only for the first group', self.text)
        self.assertNotIn('So L1 passes `isolation: "worktree"` in the Agent call only when delegating the first parallel group', self.text)
        self.assertNotIn('Put `worktree.baseRef: "head"` in `~/.claude/settings.json` (approved at install)', self.text)
        order = self.line_of('  1. `<task_dir>/.active` at the root of the git repository the launch folder belongs to.')
        self.assert_words(order, ('`ma_active.find_active`', '`my-agent-*` directly under `<X>/.claude/worktrees/`',
                                  'common git folder lies inside `X`', 'store-backed copy step'))

    def test_file_layout_names_unit_copies(self):
        """Criterion 16: 4.7 "File layout" lists the rule file, the state file, the store and the patch."""
        layout = self.section('### 4.7 ', '### 4.7.1 ')
        self.assert_words(layout, ('unit-copies.md', 'unit-copies.json', 'copy-store/', '<unit>.patch', 'worktree (coder unit copies'))

    def test_q47_accept_speed_up_row(self):
        """Criteria 3, 7, 12: the Q47 row holds each decision of the accept speed-up and what was not taken."""
        row = self.line_of('| Q47 | Accept speed-up: one check run, judges together |')
        self.assert_words(row, (
            '`check-commands.py`', '`checks.md`', '`checks/<nn>.log`', 'in 3B', 'Not taken',
            'the fingerprint', 'git-ignored files are not in it', "the person's choice for the limit",
            '`<task_dir>/<task-id>/` is always left out', 'no fingerprint', 'tree changed by the run',
            'one chat line', 'rerun once', 'stale', 'missing',
            '`(checks.md)`', 'covered by <full suite command>', 'the evidence bar is unchanged',
            'the criteria file', 'only the existing dev check', 'cites `checks.md`',
            'the verifier and the reviewer start together', 'one message', 'sequential fallback',
            'ALL PASS and BLOCKER 0', 'small fix', 'Back to Execute',
            'the review of a Verify FAIL round', 'feeds the next round',
            '`verdict-fresh-check.py`', '`scope-guard.py`', 'Codex starts them together',
            'Antigravity only with a cited source', '15,000 characters',
            '`intake.py work-branch`', '`my-agent-task/<task-id>`', 'no work branch',
            'findings list table after every Scope Review and Plan Review judgment',
            'judge-fixture', 'before', 'after', 'the longest time limit the host accepts',
            'light path', 'twice the measured duration',
            'The gate report and the monitor with 4A and 4B overlapping', "each judge's tokens once, in exactly one stretch",
            'the Verify round count and the judge misses', 'the 4A and 4B timeline rows overlapping',
            "the verifier's agent item on step 4A", 'ending 4A at the 4B start'))
        self.assertNotIn('Antigravity starts them together', row)

    def test_raised_size_limit_in_design(self):
        """Criterion 10: the limit lines say 15,000; the old limit appears only in the version history and as the old value."""
        for number, line in enumerate(self.text.splitlines(), 1):
            if line.startswith('- Status:'):
                continue
            for match in re.finditer(r'12,700', line):
                around = line[max(0, match.start() - 60):match.end() + 40]
                self.assertTrue('from 12,700' in around or 'was 12,700' in around or 'raised' in around,
                                f'line {number}: {around}')
        limits = self.line_of('  - Limits (`test_skill_md`):')
        self.assert_words(limits, ('under 15,000 characters', '6,465 tokens', '2.32 characters per token',
                                   '5,769 tokens', '2.6 characters per token', '2026-11-27', 'from 12,700'))
        question = self.line_of('  - **Question rules (popup clarity;')
        self.assertIn('15,000 characters', question)
        self.assertNotIn('limit is 12,700', question)
        row = next(l for l in self.text.splitlines() if l.startswith('| After compaction, **only the first 5,000 tokens**'))
        self.assert_words(row, ('while it stays under about 13,000 characters', '5,000-token cut',
                                '2.6 characters per token', 'the end is cut', 'near the top'))
        self.assertNotIn('so all of it is attached again', row)
        self.assertNotIn('stays under 12,700 characters', row)

    def test_file_layout_names_the_check_script_and_record(self):
        """Criterion 12: 4.7 "File layout" lists the check rule file, its folder, the script and the module."""
        layout = self.section('### 4.7 ', '### 4.7.1 ')
        self.assert_words(layout, ('checks.md', 'checks/', 'check-commands.py', 'ma_checks.py'))

    def test_verify_review_scope_and_guard_follow_the_check_record(self):
        """Criteria 7, 12: the step row, the scope bullet, the guard text and the host rows follow the new flow."""
        row = self.line_of('| **④ Accept** | 4A Verify (with 4B Review, started together) |')
        self.assert_words(row, ('check record', 'together'))
        scope = self.line_of('- **Verify and Review scope (2026-11-06, plugin 0.12.0):**')
        self.assert_words(scope, (
            '`check-commands.py`', '`checks.md`', '`Checks: current`', 'one message', 'the criteria file',
            '`review not read (Verify FAIL in that run)`', 'not newer than'))
        guard = self.line_of('- **Record deny (2026-11-27, plugin 0.37.0')
        self.assert_words(guard, ('`verdict-fresh-check.py`', '`scope-guard.py`', '`checks.md`', '`checks/`',
                                  'before every other write verdict', 'Only check-commands.py writes'))
        judge = self.line_of('| **judge checks** |')
        self.assert_words(judge, ('five dev fixtures', '`--out`', 'nine in all', 'docs-only'))
        tests = self.section('### 4.13 ', '### 4.14 ')
        self.assert_words(tests, ('tests do not pin the wording of record documents', '`docs/blueprint/`',
                                  '`docs/handoff/`', 'tests that pin the specification', 'stay'))
        codex = self.line_of('| Subagent start | `Agent` with `subagent_type` `my-agent:<role>` | `spawn_agent`')
        self.assert_words(codex, ('the verifier and the reviewer start together',))
        agy = self.line_of('| Subagent start | `Agent` with `subagent_type` `my-agent:<role>` | `invoke_subagent`')
        self.assert_words(agy, ('together only with a cited source', 'one after the other'))

    def test_intake_work_branch_in_design(self):
        """Criterion 13: the Intake text names the work-branch call, the rerun and the no-switch cases."""
        git = self.line_of('  - **Git check at Intake (2026-11-10):**')
        self.assert_words(git, ('`intake.py work-branch`', '`my-agent-task/<task-id>`', 'from the current commit',
                                'uncommitted changes stay in the working tree', 'reruns the Git check right away',
                                'same popup', 'an existing branch', 'a failed create or switch', 'one chat line',
                                '`main`/`master`', 'detached HEAD'))
        script = self.line_of('  - **Intake script (2026-11-16, plugin 0.15.0):**')
        self.assert_words(script, ('`work-branch`', '`--task-id`'))
        section = self.section('### 4.8.2 ', '### 4.9 ')
        self.assert_words(section, ('`intake.py work-branch`', 'my-agent-task/<task-id>'))

    def test_reference_articles_list_both_local_copies(self):
        ref = (REPO / 'docs' / 'reference.md').read_text(encoding='utf-8')
        articles = ref[ref.index('## Articles'):]
        for name in ('harness-design-long-running-apps.md', 'managed-agents.md'):
            self.assertIn(f'`{name}`', articles)


if __name__ == '__main__':
    unittest.main()
