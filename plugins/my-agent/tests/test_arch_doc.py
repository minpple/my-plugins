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
                                ('git-guard.py', 'Bash')):
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
                     'GIT_CONFIG_KEY_<n>', '`$VAR`', 'core.hooksPath', 'Claude Code only', 'hand-merged',
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
        a = self.text.index('**G1b hard gate**')
        sec = self.text[a:self.text.index('- **Block when the hook fails:**', a)]
        self.assertNotIn('blocks **regardless of phase**', sec)
        self.assertNotIn('pre-approval write block', sec)
        self.assertIn('`permissionDecision: ask`', sec)
        self.assertIn('`permissionDecision: deny`', sec)

    def test_delegated_approval_covers_g3_with_a_cap_of_three(self):
        sec = self.section('**Delegated approval (2026-10-29, Q22)**', '**G1b hard gate**')
        always = next(l for l in sec.splitlines() if l.startswith('- Always to the person:'))
        self.assertIn('**G2 and E**', always)
        self.assertNotIn('G3', always)
        for word in ('**G3 under delegated approval (2026-11-20, Q39):**', '`Rework: fix all open items`',
                     'after 3 G3 fix rounds it goes to E', 'whatever the round count', 'do not stop the take',
                     'in the dev profile the commit still holds only the files this task changed',
                     'The G3 fix loop has its own cap of 3 rounds', '`Severity | Found | Fixed | Open`',
                     '`BLOCKER <n> · SHOULD-FIX <n> · NITPICK <n> (open)`', 'No gate starts the monitor'):
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
                     'each claim attributed to its own source', 'picks none silently', 'not from a search snippet', "In the research profile's 6 Merge the writer keeps both"):
            self.assertIn(word, bullet, word)

    def test_decision_log_has_q39_and_q40_once_after_q38(self):
        rows = re.findall(r'^\| (Q\d+) \|', self.text, re.M)
        self.assertEqual(len(rows), len(set(rows)), rows)
        self.assertEqual(rows[-5:], ['Q39', 'Q40', 'Q41', 'Q42', 'Q43'])
        q39 = next(l for l in self.text.splitlines() if l.startswith('| Q39 |'))
        q40 = next(l for l in self.text.splitlines() if l.startswith('| Q40 |'))
        self.assertIn('capped at 3 rounds', q39)
        self.assertIn('`"autostart": true`', q40)

    def test_report_tab_names_return_marks(self):
        self.assertIn('timeline.backs[].row', self.text)
        self.assertIn('timeline.chart_end', self.text)
        self.assertIn('went back to an earlier step', self.text)

    def test_status_line_starts_with_the_newest_entry(self):
        line = re.search(r'^- Status: .*$', self.text, re.M).group(0)
        self.assertTrue(line.startswith('- Status: design draft v0.71 (2026-11-22, plugin 0.25.1:'), line[:90])
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
        a = self.text.index('**What G1b shows: mock-up and prototype**')
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
        a = self.text.index('**What G1b shows: mock-up and prototype**')
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
        a = self.text.index('**G1b hard gate**')
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

    def test_resume_section_has_the_non_owner_notice(self):
        section = self.section('### 4.8.2 ', '### 4.9 ')
        self.assertIn('The original session is running my-agent task <id> (phase <n>). '
                      'To take it over in this session, run /my-agent continue; otherwise work as usual.', section)

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
            '(answered by L1)', 'SKILL.md "Question rules"', 'Always asked:', 'G1a, G1b, G3, G2, E',
            'every Intake popup', 'a popup without a recommended choice', 'with a question back',
            'Delegated approval rules stay', 'counted with the L1 answers'))
        alone = self.bullet(start, end, '- **Stand-alone popup:**')
        self.assert_words(alone, ('stands alone', 'one-line plain explanation', 'what it contains',
                                  'what it leads to', 'written at plan time'))
        preset = self.bullet(start, end, '- **Models preset popup:**')
        self.assert_words(preset, ('one line', 'cost or care', '`presets` line'))

    def test_g3_recommendation_follows_the_open_items(self):
        g3 = next(l for l in self.text.splitlines() if l.startswith('| **G3 Final acceptance**'))
        self.assert_words(g3, ('while a SHOULD-FIX is open', 'with only NITPICK items open',
                               'cost (reference, 4.8)'))
        self.assertNotIn('and after a G3 Rework answer Accept (Commit) is, because', g3)
        bullet = self.bullet('### 4.4 ', '### 4.5 ', '- **G3 recommendation')
        self.assert_words(bullet, ('every G3 of the task', 'first G3', 'after a Rework answer',
                                   'under delegated approval', 'unchanged', 'up to 3 rounds'))

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

    def test_reference_articles_list_both_local_copies(self):
        ref = (REPO / 'docs' / 'reference.md').read_text(encoding='utf-8')
        articles = ref[ref.index('## Articles'):]
        for name in ('harness-design-long-running-apps.md', 'managed-agents.md'):
            self.assertIn(f'`{name}`', articles)


if __name__ == '__main__':
    unittest.main()
