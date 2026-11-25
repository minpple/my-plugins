"""SKILL.md, the L1 procedure files and the phase/profile files (architecture 4.7.1 "SKILL.md writing rules")."""
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import L4, REPO, make_task, rel

SKILL = REPO / 'skills' / 'my-agent' / 'SKILL.md'
L1 = REPO / 'l1-orchestration'
# The procedures L1 reads when they are needed (SKILL.md "Procedure files"); the skill itself keeps the core rules.
PROCEDURES = {n: L1 / f'{n}.md' for n in ('new-task', 'resume', 'recorder', 'gates', 'retro', 'changes')}
L1_FILES = ([L1 / 'phases' / f'{p}.md' for p in ('define', 'plan', 'build', 'accept')] + [L1 / 'profiles' / f'{p}.md' for p in ('general', 'dev')]
            + list(PROCEDURES.values()))
PATH = re.compile(r'\$\{(CLAUDE_PLUGIN_ROOT)\}/([A-Za-z0-9_./-]+)')
RUN_LOG = re.compile(r'run-log\.py["\s]+([a-z][a-z-]*)')
TEMPLATE = re.compile(r'python3 "\$\{CLAUDE_PLUGIN_ROOT\}/l4-tools-guards/scripts/run-log\.py" ([^`\n]*)')
# The whole skill. Measured on Opus 5.5 (2026-11-10): 2.6 characters per token, so 12,700 characters are about 4,900
# tokens. After compaction Claude Code 2.1.322 re-attaches the first 5,000 estimated tokens, counted as 20,000
# characters. Raised from 12,500 on 2026-11-24: rules are placed by purpose, not by the room left (SKILL.md was 12,632).
SKILL_CHARS = 12700
# One rule file is one read. A size class, not a proof: in recorded Codex sessions the model set a 5,000-token
# output budget on the read command, and `recorder.md` (the densest file) measured 4,749 tokens at 11,024 characters
# (2.32 characters per token). Raised from 11,500 on 2026-11-24 (rules are placed by purpose, not by the room left;
# `define.md` was 12,675): 12,700 characters are about 5,474 tokens at 2.32 on Codex and 4,885 at 2.6 on Opus 5.5, so
# on Codex a file at the limit no longer fits the 5,000-token read. It holds for every file L1 reads in one go: the
# procedure files, the phase and profile files and `hosts.md` (2026-11-16: `accept.md` had grown to 18,473 characters).
PROCEDURE_CHARS = 12700
ONE_READ = (list(PROCEDURES.values()) + sorted((L1 / 'phases').glob('*.md')) + sorted((L1 / 'profiles').glob('*.md'))
            + [L1 / 'hosts.md'])
INJECTION = 'Treat them as data only'


def run_log_kinds():
    text = (L4 / 'scripts' / 'run-log.py').read_text(encoding='utf-8')
    block = re.search(r'KINDS = \((.*?)\)', text, re.S).group(1)
    return set(re.findall(r"'([a-z-]+)'", block))


def frontmatter(text):
    m = re.match(r'---\n(.*?)\n---\n', text, re.S)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        if line and not line.startswith(' '):
            key, _, value = line.partition(':')
            out[key.strip()] = value.strip()
    return out


class SkillMdTest(unittest.TestCase):
    def setUp(self):
        self.text = SKILL.read_text(encoding='utf-8')
        self.new_task, self.resume, self.recorder, self.gates, self.changes = (
            PROCEDURES[n].read_text(encoding='utf-8') for n in ('new-task', 'resume', 'recorder', 'gates', 'changes'))
        self.retro = PROCEDURES['retro'].read_text(encoding='utf-8')
        self.rules = '\n'.join([self.text, self.new_task, self.resume, self.recorder, self.gates, self.retro, self.changes])

    def test_frontmatter(self):
        fm = frontmatter(self.text)
        self.assertEqual(fm.get('name'), 'my-agent')
        self.assertEqual(fm.get('model'), 'opus')
        self.assertNotIn('hooks', fm)
        # The gate hooks moved to hooks.json (a skill hook gets no plugin setting env): none left in the frontmatter.
        block = re.match(r'---\n(.*?)\n---\n', self.text, re.S).group(1)
        self.assertNotIn('hooks:', block)
        self.assertNotIn('plan-approved-check.py', block)
        self.assertNotIn('verdict-fresh-check.py', block)

    def test_no_skill_dir_variable(self):
        """The main skill lives in skills/my-agent/: its paths start from the plugin root, never from the skill folder."""
        self.assertNotIn('CLAUDE_SKILL_DIR', self.text)

    def test_approval_line_written_without_substitution(self):
        """Live run: L1 wrote the Approved line with `$(date …)` and the G1-B hook (rightly) refused it."""
        plan = (REPO / 'l1-orchestration' / 'phases' / 'plan.md').read_text(encoding='utf-8')
        self.assertIn('without command substitution', plan)

    def test_intake_active_time_without_substitution(self):
        """Intake item 6 is the create call (it writes `.active` with its own time): no `date`, no Write tool."""
        intake = self.intake()
        item = next(l for l in intake.splitlines() if l.startswith('6. **`.active` and index:**'))
        self.assertIn('intake.py" create', item)
        self.assertIn('`phase: 1`', item)
        self.assertIn('`started:`', item)
        # the one sentence that says a `$(` inside the single-quoted values is data is the only allowed mention
        self.assertNotIn('$(', item.replace('a backtick, `$(`, `;` or `|` inside them', ''))
        self.assertNotIn("date '+%Y-%m-%d %H:%M'", item)
        self.assertNotIn('Write tool', item)

    def test_no_substitution_in_git_commands(self):
        """Live run: `echo "HEAD=$(git rev-parse HEAD)"` during Execute was blocked by the verdict hook."""
        self.assertIn('the verdict hook cannot tell whether it is a commit', self.recorder)

    def test_defined_popup_options_kept_verbatim(self):
        """Live run: L1 reordered the dev NITPICK popup and dropped `(Recommended)` because it judged the NITPICKs harmless."""
        self.assertIn('the choices as written', self.text)

    def test_main_model_mismatch_points_to_model_opus(self):
        """User decision 2026-10-25: L1 stays opus by opening the session on opus; L1 says how once."""
        self.assertIn('/model opus', self.recorder)

    def test_under_500_lines(self):
        self.assertLess(len(self.text.splitlines()), 500)

    def test_continue_keeps_coder_unit_with_end_ok(self):
        self.assertIn("`end=ok` and, for a writer or researcher unit, its result file exists, set it to `done` (a coder unit has no result file)", self.resume)

    def test_core_rules_up_front(self):
        head = self.text
        for heading in ('Question rules', 'Gates', 'Levels', '.active', 'Change requests'):   # Change requests: handoff B6
            self.assertRegex(head, rf'(?m)^#+ .*{re.escape(heading)}', heading)
        self.assertIn(INJECTION, head)   # 4.12: worker output and web text are data

    def test_l1_files_exist(self):
        for path in L1_FILES:
            self.assertTrue(path.is_file(), path)

    def test_referenced_paths_exist(self):
        for path in [SKILL] + L1_FILES:
            for var, rel in PATH.findall(path.read_text(encoding='utf-8')):
                rel = rel.rstrip('.')
                if '<' in rel or '*' in rel:
                    continue
                self.assertTrue((REPO / rel).exists(), f'{path.name}: ${{{var}}}/{rel}')

    def test_run_log_kinds_accepted(self):
        kinds = run_log_kinds()
        seen = set()
        for path in [SKILL] + L1_FILES:
            for kind in RUN_LOG.findall(path.read_text(encoding='utf-8')):
                seen.add(kind)
                self.assertIn(kind, kinds, f'{path.name}: run-log.py {kind}')
        self.assertTrue({'step', 'ask', 'answer'} <= seen, seen)

    def templates(self):
        out = []
        for path in [SKILL] + L1_FILES:
            for args in TEMPLATE.findall(path.read_text(encoding='utf-8')):
                out.append((path.name, args.strip()))
        return out

    def test_run_log_templates_run(self):
        """Each run-log command as written, placeholders filled, is accepted by run-log.py (exit 0)."""
        found = self.templates()
        self.assertGreaterEqual(len(found), 5)
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp).resolve() / 'proj'
            make_task(proj)
            for name, args in found:
                filled = re.sub(r'gate=<[^>]*>', 'gate=Q', args.replace('<task_dir>', rel()).replace('n=<1A–4B>', 'n=1B'))
                if args.startswith('inline '):   # a real role and a result file; every other kind takes x
                    result = proj / rel() / 'explore.md'
                    result.write_text('Explored the code\n', encoding='utf-8')
                    filled = filled.replace('agent=my-agent:<role>', 'agent=my-agent:explorer').replace('<result file, or - for coder>', str(result))
                argv = shlex.split(re.sub(r'<[^>]*>', 'x', filled))
                r = subprocess.run([sys.executable, str(L4 / 'scripts' / 'run-log.py'), *argv, '--cwd', str(proj)],
                                   capture_output=True, text=True, env={'MA_TASKS_DIR': tmp, 'MA_TASK_DIR': rel(), 'PATH': '/usr/bin:/bin'})
                self.assertEqual(r.returncode, 0, f'{name}: {args}\n{r.stdout}{r.stderr}')

    def test_gate_answers_use_choice(self):
        for name, args in self.templates():
            if args.startswith('answer') and re.search(r'gate=(G1a|G1b|G1-A|G1-B|G3|E|Q)\b', args):
                self.assertIn('choice=', args, f'{name}: {args}')

    def test_every_ask_carries_rec(self):
        """Each `ask gate=` in SKILL.md and the L1 files (template or backticked prose) records rec=."""
        seen = 0
        for path in [SKILL] + L1_FILES:
            for m in re.finditer(r'ask gate=[^`\n]*', path.read_text(encoding='utf-8')):
                seen += 1
                self.assertIn('rec=', m.group(0), f'{path.name}: {m.group(0)}')
        self.assertGreaterEqual(seen, 8)

    def test_other_marker_rule(self):
        self.assertIn('if the answer was typed in (Other), add `other=1` at the end', self.recorder)
        self.assertIn('rec=-', self.recorder)
        for marker in ('prose=1', 'pre=1', 'qn=1'):
            self.assertIn(marker, self.recorder)

    def test_cost_row_takes_no_value(self):
        self.assertIn('run-log.py" cost --data-dir "<data folder>"', self.recorder)
        self.assertNotIn('usd=<cost_usd>', self.rules)

    def test_rec_template_runs_as_written(self):
        found = [a for n, a in self.templates() if a.startswith('ask') and 'rec=' in a]
        self.assertGreaterEqual(len(found), 3)   # the gate popups ask through pre-gate.py; these are the rest
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp).resolve() / 'proj'
            make_task(proj)
            argv = ['ask', 'gate=G3', 'q=x', 'rec=x', '--task-dir', rel()]
            r = subprocess.run([sys.executable, str(L4 / 'scripts' / 'run-log.py'), *argv, '--cwd', str(proj)],
                               capture_output=True, text=True, env={'MA_TASKS_DIR': tmp, 'MA_TASK_DIR': rel(), 'PATH': '/usr/bin:/bin'})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_revision_edits_use_headings_and_edit_tool(self):
        """Sections are found by a line-start heading and edited with Edit, never cut by offset or overwritten."""
        section = self.section('## In-flight revision', '## Abort', self.changes)
        self.assertIn('headings that start at the beginning of a line (`## Revisions`, `## Approval`)', section)
        self.assertIn('edit only that section with the Edit tool', section)
        self.assertIn('do not overwrite the whole file with Write', section)

    def test_defer_manual_check_scope_change(self):
        """A scope change defers a manual check to the user."""
        self.assertIn('Scope change: criterion <n> is checked by the user later', self.changes)

    def test_continue_cleans_active_when_done(self):
        """A retrospective cut short leaves Status: done; continue only clears .active."""
        section = self.section('## continue', None, self.resume)
        self.assertIn('Status: done', section)
        self.assertIn('only `.active` and the `Cd(...)` rule cleared', section)
        self.assertIn('cd-guard.py" --remove', section)
        self.assertIn('`<data folder>/active-index.json`', section)

    def test_l2_row_lists_manifest_agents(self):
        import json
        manifest = json.loads((REPO / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))
        names = [Path(a).stem for a in manifest['agents'] if '/l2-design-judge/' in a]
        row = next(l for l in self.text.splitlines() if l.startswith('| L2 |'))
        for name in names:
            self.assertIn(name, row)

    def test_retrospective_order(self):
        """Tally -> gate-analyst -> copy -> chat -> feedback add L1; before the .active cleanup on both accept paths."""
        accept = (L1 / 'phases' / 'accept.md').read_text(encoding='utf-8')
        devp = (L1 / 'profiles' / 'dev.md').read_text(encoding='utf-8')
        retro = self.retro[self.retro.index('## Retrospective'):]
        marks = ['gate-report.py" tally', 'my-agent:gate-analyst', 'gate-report.py" copy', 'two paths', 'feedback.py" add L1',
                 'gate-report.py" check']
        pos = [retro.index(m) for m in marks]
        self.assertEqual(pos, sorted(pos))
        self.assertIn('Summary', retro[pos[3]:pos[4]])
        self.assertIn('missing start:', retro[pos[5]:])
        self.assertIn('mode not auto:', retro[pos[5]:])
        self.assertIn('Profile:', retro)
        self.assertIn('PARTIAL', retro)
        general = accept[accept.index('6. **Accept:**'):accept.index('7. **Rework:**')]
        dev = devp[devp.index('4. **Commit:**'):devp.index('5. **Rework**')]
        for part in (general, dev):
            self.assertLess(part.index('Status: done'), part.index('"Retrospective"'))
            self.assertLess(part.index('"Retrospective"'), part.index('`.active` and'))

    def test_usage_snapshot_before_active_cleanup(self):
        """4.8.2 "Task records over time": the snapshot runs while `.active` still names the task, on accept and abort."""
        cmd = 'l4-tools-guards/scripts/usage-snapshot.py"'
        retro = self.retro[self.retro.index('## Retrospective'):]
        self.assertGreater(retro.index(cmd), retro.index('mode='))
        abort = self.section('## Abort', None, self.changes)
        self.assertLess(abort.index('run-log.py" abort'), abort.index(cmd))
        self.assertLess(abort.index(cmd), abort.index('Delete `.active`'))

    def test_plugin_version_scoped_to_plugin_folder(self):
        # the plugin lives in a multi-plugin repo (~/dev/my-plugins): another plugin's commit must not look like a rules change
        self.assertNotIn('"${CLAUDE_PLUGIN_ROOT}" rev-parse', self.rules)
        version = 'git -C "${CLAUDE_PLUGIN_ROOT}" log -1 --format=%h -- .'
        for text in (self.resume,):   # continue item 2 compares it; the Intake script writes it (its test checks the value)
            self.assertIn(version, text)
            self.assertIn('git -C "${CLAUDE_PLUGIN_ROOT}" status --porcelain -- .', text)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git = lambda *a: subprocess.run(['git', '-C', str(repo), *a], check=True, capture_output=True, text=True).stdout
            git('init', '-q')
            for name in ('mine', 'other'):
                (repo / name).mkdir()
                (repo / name / 'f').write_text(name)
                git('add', name)
                git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', name)
            cmd = version.replace('"${CLAUDE_PLUGIN_ROOT}"', shlex.quote(str(repo / 'mine')))
            run = lambda: subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True).stdout.strip()
            before = run()
            (repo / 'other' / 'f').write_text('changed')
            git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qam', 'other again')
            self.assertEqual(run(), before)

    # --- Plan Review rounds, L1 plan edits, profile change ---
    PLAN = L1 / 'phases' / 'plan.md'

    def plan_step4(self):
        plan = self.PLAN.read_text(encoding='utf-8')
        return plan[plan.index('## 2B Plan Review'):plan.index('## G1-B plan approval')]

    def test_nitpick_only_applied_without_popup(self):
        """NITPICK only -> applied without a popup, one `## Decisions` line each, then G1-B."""
        step = self.plan_step4()
        self.assertIn('Unmarked SHOULD-FIX and NITPICK, `READY` and `REVISE` alike: apply them without a popup', step)
        self.assertIn('- <severity> <path>:<line> <summary> → applied by L1 | applied by architect | declined', step)

    def test_no_plan_review_round_after_ready(self):
        """READY FOR APPROVAL never leads to another Plan Review round; only REVISE is judged again."""
        step = self.plan_step4()
        self.assertIn('never another Plan Review round', step)
        self.assertIn('third `REVISE`', step)
        self.assertIn('Apply all (Recommended)', step)
        self.assertNotIn('whole list (NITPICKs included)', step)

    def test_l1_plan_edit_rules(self):
        """Small plan.md edits by L1 before G1-B, recorded as `fix ... before=G1-B` with an archive."""
        step = self.plan_step4()
        self.assertIn('before=G1-B archive=', step)
        plan = self.PLAN.read_text(encoding='utf-8')
        g1b = plan[plan.index('## G1-B plan approval'):]
        self.assertIn('Applied after Plan Review', g1b)
        self.assertIn('small', g1b[g1b.index('**Request changes:**'):])
        row = next(l for l in self.text.splitlines() if l.startswith('| L1 |'))
        self.assertIn('plan.md', row)
        section = plan[plan.index('## Rewrite before approval'):]
        self.assertIn('L1 edit', section)
        self.assertIn('Plan Review again only after a BLOCKER fix', section)
        self.assertIn('| Plan edit by L1 before approval', self.recorder)

    def test_profile_label_from_profile_line(self):
        """The label is (set by you) also when the run-log has a `profile` line."""
        intake = self.intake()
        self.assertIn('the run-log has a `profile` line', intake)
        self.assertIn('keeps `--dev` as its first word', intake)
        self.assertIn('Profile change at the first gate', intake)

    def test_intake_profile_popup_without_flag(self):
        """Without a profile flag the Router recommends a profile and the person confirms it in a popup."""
        three = self.intake_item(3)
        self.assertNotIn('does not ask', three)
        for text in ('Without a flag, the Router picks one from the request by the rules below and asks',
                     '`<profile> (Recommended)`', 'no `dev` outside a git repository',
                     'the reason for the pick in one line', 'item 10 writes a `profile` line'):
            self.assertIn(text, three, text)
        ten = self.intake_item(10)
        self.assertIn("picked another profile than the Router's (item 3)", ten)
        self.assertIn("from=<Router's pick> to=<choice> back=- archive=-", ten)
        row = next(l for l in self.recorder.splitlines() if l.startswith('| Profile change at the first gate'))
        self.assertIn("at Intake, a profile other than the Router's pick (`back=- archive=-`)", row)
        self.assertIn('run-log.py" profile from=<old> to=<new>', row)

    def test_profile_change_procedure(self):
        section = self.section('## In-flight revision', '## Abort', self.changes)
        bullet = section[section.index('**Profile change at the first gate'):]
        for word in ('-profile/', '`Request:` is left as written', '`## Scope summary`', 'back=', '`phase:`',
                     'Keep <current profile> (Recommended)', 'new task (`Follows:`)',
                     'Split into a new task (Recommended)'):
            self.assertIn(word, bullet, word)
        for path in (L1 / 'phases' / 'define.md', self.PLAN):
            self.assertIn('Profile change at the first gate', path.read_text(encoding='utf-8'), path.name)

    def test_profile_templates_use_known_kinds(self):
        kinds = run_log_kinds()
        found = [a for n, a in self.templates() if a.startswith(('profile ', 'fix '))]
        self.assertTrue(any(a.startswith('profile from=') for a in found))
        self.assertTrue(any('before=G1-B' in a for a in found))
        self.assertLessEqual({'profile', 'fix'}, kinds)

    def test_auto_flag_rules(self):
        """`--auto` rules in ## Arguments, Flags and Intake."""
        self.assertIn('--auto', self.section('## Arguments', None))
        args = self.section('## Flags', '## Intake', self.new_task)
        for word in ('--auto', '`--Auto`', 'twice', 'either order', 'drops every flag, `--auto` included',
                     'among the leading flags', 'keeps the leading flags'):
            self.assertIn(word, args, word)
        intake = self.intake()
        self.assertIn('delegate state=on how=flag', intake)
        self.assertIn('Delegated approval: on (--auto)', intake)
        self.assertIn('7 lines or fewer', intake)
        self.assertNotIn('6 lines or fewer', intake)
        self.assertIn('item 1–5', intake[intake.index('Delegation covers'):])

    def test_delegated_approval_core_rules(self):
        """Never G2, E, the third-REVISE G1-B popup or a popup without a recommendation (G3 is answered per gates.md); state from the last line."""
        head = self.text[:self.text.index('## Arguments')]
        sec = head[head.index('### Delegated approval'):]
        sec = sec[:sec.index('\n### ', 5)] if '\n### ' in sec[5:] else sec
        self.assertNotIn('read `gates.md` "Delegated approval details"', sec)   # the Procedure files row says it
        row = next(l for l in self.text.splitlines() if l.startswith('| `gates.md` |'))
        self.assertIn('when delegated approval is asked for or turns on', row)
        self.assertIn('Delegated approval details', row)
        for word in ('G2', 'G3', 'E', 'third `REVISE`', 'without a recommended choice', 'by=L1',
                     '(answered by L1)', 'last `delegate` line', 'Turn on (Recommended)', 'Keep asking me',
                     'delegate state=off how=person', 'delegate state=off how=end'):
            self.assertIn(word, sec, word)
        self.assertLess(self.text.index('### Delegated approval'), self.text.index('## Arguments'))
        never = next(l for l in sec.splitlines() if l.startswith('- Never answered by L1:'))
        self.assertNotIn('G3', never)
        for word in ('G2', ' E,'):
            self.assertIn(word, never, word)

    def delegated(self):
        return self.section('## Delegated approval details', '## Check before anything leaves', self.gates)

    def test_delegated_g3_fix_all_open_items(self):
        """With open SHOULD-FIX or NITPICK items L1 answers G3 `Rework: fix all open items`, without a popup."""
        sec = self.delegated()
        g3 = sec[sec.index('**G3 under delegated approval:**'):]
        for word in ('answer gate=G3 choice="Rework: fix all open items" … by=L1', 'rec="Rework: fix all open items"',
                     '→ Rework: fix all open items (answered by L1)', 'open SHOULD-FIX or NITPICK items', 'show no popup',
                     'is the choice L1 gives',
                     'New findings of a fix round are open items of the next G3',
                     'A Verify FAIL or a BLOCKER in a round follows the existing rules and caps',
                     'After `delegate state=off how=person` the next G3 goes to the person',
                     'On `findings: FAIL` show the cause; G3 goes to the person'):
            self.assertIn(word, g3, word)
        self.assertIn('3 Verify FAILs', sec)
        self.assertNotIn('is for the popup shown to the person', sec)   # moved into the G3 recommendation rule

    def test_g3_recommends_rework_while_any_item_open(self):
        """Criterion 1: the popup recommends the rework at every G3 while a SHOULD-FIX or NITPICK is open, the take only with none; the delegated answer is the same."""
        sec = self.section('- **G3 with open review items.**', '## E escalation', self.gates)
        line = next(l for l in sec.splitlines() if l.startswith('  - Open items:'))
        for word in ('`Rework: fix all open items (Recommended)` / `<Take>` / `Rework` / `Abort`',
                     'at every G3 while a SHOULD-FIX or NITPICK is open, also after an earlier Rework answer',
                     '`<Take>` only with no open item',
                     'L1 gives the same answer under delegated approval ("G3 under delegated approval" above)',
                     'The `rec=` of the `ask` line is the recommended label'):
            self.assertIn(word, line, word)
        self.assertNotIn('after a G3 Rework answer (either kind) with only NITPICK items open, `<Take>` is', sec)
        self.assertNotIn('at the first G3 of the task', sec)
        retro = (L1 / 'retro.md').read_text(encoding='utf-8')
        self.assertIn('`Commit` is the recommended take only with no open review item', retro)
        self.assertIn('the remote take is never recommended', retro)
        self.assertIn('`Rework: fix all open items (Recommended)` / `Commit` / `<remote take>` / `Abort`', retro)
        self.assertIn('with open items `Rework: fix all open items (Recommended)` / `Commit` / `Rework` / `Abort`', retro)
        # the delegated G3 steps stay as they are
        g3 = self.delegated()
        g3 = g3[g3.index('**G3 under delegated approval:**'):]
        self.assertIn('4. Otherwise (open SHOULD-FIX or NITPICK items): show no popup;', g3)
        self.assertIn('2. No open item (BLOCKER 0, SHOULD-FIX 0 and NITPICK 0 open): answer `<Take>`', g3)

    def test_e_give_direction_is_recorded_in_plan(self):
        """Criterion 6: after `Give direction` that changes a unit's approach, the plan records it as a Scope change."""
        sec = self.section('## E escalation', None, self.gates)
        bullet = sec.rstrip().splitlines()[-1]
        for word in ('After `Give direction` that changes a unit\'s approach', '`Scope change: u<n> <new approach>`',
                     'under `plan.md` `## Approval`', '`fix … files=plan.md` line', 'plan and deliverable agree'):
            self.assertIn(word, bullet, word)
        self.assertTrue(bullet.startswith('  - After `Give direction`'))   # a new last bullet of "E escalation"

    def test_blueprint_update_shows_deleted_lines(self):
        """Criterion 6: after the writer's update L1 shows the lines it deleted (or says none)."""
        sec = self.section('## Blueprint update', None, self.phase('accept'))
        item = next(l for l in sec.splitlines() if l.startswith('4. '))
        for word in ('`ok:` line', 'per-file lines', '`git diff -U0 -- docs/blueprint/`', 'shows as deleted',
                     '(none: say so)'):
            self.assertIn(word, item, word)

    def test_no_verify_while_adjustment_is_built(self):
        """Criterion 6: no Verify run starts while an adjustment within approved scope is still being built."""
        sec = self.section('- **Adjust within approved scope:**', '- **Revise this task:**', self.changes)
        sub = next(l for l in sec.splitlines() if l.startswith('  - Start no Verify run'))
        for word in ('while an adjustment is still being built', 'coder call has not returned and been merged'):
            self.assertIn(word, sub, word)

    def test_person_check_how_to_first(self):
        """Criterion 6: before the person-check popup L1 says in the chat how the person checks it."""
        sec = self.section('**Person-check popup:**', '5. If `scope.md` has a `## Background research`', self.phase('define'))
        first = sec.splitlines()[1]
        self.assertTrue(first.startswith('     - Before it, say in the chat how the person checks it'), first)
        for word in ('the steps and where', 'then ask'):
            self.assertIn(word, first, word)

    def test_delegated_g3_take_when_nothing_is_open(self):
        """Nothing open, so L1 takes, whatever the round count; open risks are listed, not a stop."""
        sec = self.delegated()
        g3 = sec[sec.index('**G3 under delegated approval:**'):]
        for word in ('BLOCKER 0, SHOULD-FIX 0 and NITPICK 0 open', '`Accept`; dev `Commit`', 'whatever the round count',
                     'rec="<Take>"', '→ <Take> (answered by L1)', 'Open risks do not stop the take',
                     'an unexpected changed path', '`checked by the user later`', 'G2 dialog still goes to the person'):
            self.assertIn(word, g3, word)
        self.assertLess(g3.index('whatever the round count'), g3.index('3 G3 fix rounds reached'))
        self.assertIn('Commit only the files this task changed', self.dev_g3())

    def test_delegated_g3_cap_of_three_rounds(self):
        """3 G3 fix rounds, then E; the count starts at the latest `delegate state=on` line or E answer."""
        sec = self.delegated()
        g3 = sec[sec.index('**G3 under delegated approval:**'):]
        self.assertIn('ask gate=E q="Delegated approval: 3 G3 fix rounds reached" rec="Give direction"', g3)
        self.assertIn('A round is one G3 that L1 answered `Rework: fix all open items`, counted since the latest '
                      '`delegate state=on` line or E answer', g3)
        self.assertNotIn('NITPICK fix rounds', sec)
        self.assertIn('The G3 fix loop has its own cap of 3', sec)

    def test_g3_choices_unchanged_without_delegation(self):
        """Delegation off, so the G3 popup, its choices and the recommended one are as before."""
        sec = self.section('## Gate reports', '## E escalation', self.gates)
        for word in ('`<Take> (Recommended)` / `Rework` / `Abort`, `rec="<Take>"`',
                     '`Rework: fix all open items (Recommended)` / `<Take>` / `Rework` / `Abort`',
                     '`Rework: fix all open items` is recommended at every G3 while a SHOULD-FIX or NITPICK is open',
                     '`<Take>` only with no open item'):
            self.assertIn(word, sec, word)
        accept = self.phase('accept')
        self.assertIn('Popup: `Accept (Recommended)` / `Rework` / `Abort`', accept)
        self.assertIn('`verdict-fresh-check.py`', accept)
        for text in (accept, self.dev_g3()):
            self.assertIn('L1 answers per gates.md "Delegated approval details"', text)
            self.assertNotIn('even while delegated approval is on', text)

    def test_loop_cap_section(self):
        """A 5-round cap per loop (the G3 fix loop has its own cap of 3); the lower caps stay."""
        self.assertNotIn('## Delegated approval details', self.text)
        sec = self.section('## Delegated approval details', '## Check before anything leaves', self.gates)
        for word in ('a round is', '6th round', 'E answer', 'third `REVISE`', '3 Verify FAILs',
                     'Plan Review `REVISE`', 'Review BLOCKER', 'NITPICK'):
            self.assertIn(word, sec, word)
        self.assertIn('## Failure handling', self.recorder)

    def test_pointers_in_phase_files(self):
        plan = self.PLAN.read_text(encoding='utf-8')
        self.assertIn('Delegated approval', plan[plan.index('third `REVISE`'):][:400])
        accept = (L1 / 'phases' / 'accept.md').read_text(encoding='utf-8')
        self.assertIn('delegate state=off how=end', accept)
        self.assertIn('gates.md "Delegated approval details"', accept)
        self.assertNotIn('always to the person', accept)
        abort = self.section('## Abort', None, self.changes)
        self.assertIn('delegate state=off how=end', abort)

    def test_delegate_templates_run(self):
        """Recorder rows for `delegate` and `answer ... by=L1` exist and run (test_run_log_templates_run executes them)."""
        found = [a for n, a in self.templates()]
        self.assertTrue(any(a.startswith('delegate state=on') for a in found))
        self.assertTrue(any(a.startswith('delegate state=off') for a in found))
        self.assertTrue(any(a.startswith('answer') and 'by=L1' in a for a in found))
        self.assertIn('delegate', run_log_kinds())

    def test_skill_within_limit(self):
        """The skill holds the core rules and the arguments only, so all of it stays in context after compaction."""
        self.assertLess(len(self.text), SKILL_CHARS)
        self.assertLess(self.text.index('### Phase files'), self.text.index('### Procedure files'))
        self.assertLess(self.text.index('### Procedure files'), self.text.index('## Arguments'))
        self.assertEqual(re.findall(r'^## (.+)$', self.text, re.M), ['Core rules', 'Arguments'])

    def test_every_one_read_file_fits_the_budget(self):
        self.assertEqual(len(ONE_READ), 14)   # 6 procedure, 4 phase, 3 profile files and hosts.md
        for path in ONE_READ:
            self.assertLess(len(path.read_text(encoding='utf-8')), PROCEDURE_CHARS, path.name)

    def test_fewer_main_session_calls(self):
        """2026-11-16: an archive is one script call, the approval time comes from the answer line, independent calls
        go in one message, and the profile file is read only when it is not in context."""
        rec = self.section('## Revision records and archive', '## Failure handling', self.recorder)
        self.assertIn('scripts/archive.py" --task "<absolute task folder>" --name', rec)
        self.assertIn('prints that folder, which is the `archive=` value', rec)
        for gone in ('cp -pR', '`cmp`', 'date +%y%m%d-%H%M%S'):
            self.assertNotIn(gone, rec)
        self.assertTrue((L4 / 'scripts' / 'archive.py').is_file())
        approve = next(l for l in self.phase('plan').splitlines() if l.startswith('5. **Approve:**'))
        self.assertIn('from the line the `answer` command printed (no `date` call)', approve)
        self.assertIn('the date and minute the `answer` line printed', self.phase('define'))
        tools = self.section('### Tool choice', '### Change requests')
        self.assertIn("that do not need each other's result in one message", tools)
        phase = self.section('### Phase files', '### Procedure files')
        self.assertIn('Read the profile file the same way, but only when its text is not in context', phase)
        self.assertIn('read the profile file when its text is not in context', self.resume)

    def test_accept_split(self):
        """2026-11-16: dev G3 is in profiles/dev.md, E escalation in gates.md, the retrospective in retro.md."""
        accept = self.phase('accept')
        for gone in ('## G3 in the dev profile', '## E escalation', '## Retrospective'):
            self.assertNotIn(gone, accept)
        self.assertIn('"G3 in the dev profile" in `profiles/dev.md` replaces items 4–6', accept)
        self.assertIn('read `retro.md` and do its "Retrospective"', accept)
        self.assertIn('go to E (gates.md "E escalation")', accept)
        self.assertIn('do this instead of `accept.md` step 4B items 4–6', self.dev_g3())
        self.assertIn('read `retro.md` and do its "Retrospective"', self.dev_g3().replace('Read `retro.md`', 'read `retro.md`'))
        self.assertTrue(self.gates.rstrip().endswith(self.section('## E escalation', None, self.gates).rstrip()))
        self.assertIn('## Retrospective', self.retro)

    def test_procedure_files_listed_sized_and_complete(self):
        """Each procedure file has a row in "Procedure files" naming its sections, and fits one read."""
        table = self.section('### Procedure files', '## Arguments')
        rows = {c[0].strip('`'): c for c in ([x.strip() for x in l.strip('|').split('|')] for l in table.splitlines()
                                             if l.startswith('| `'))}
        self.assertEqual(sorted(rows), sorted(f'{n}.md' for n in PROCEDURES))
        self.assertIn('${CLAUDE_PLUGIN_ROOT}/l1-orchestration/', table)
        for name, path in PROCEDURES.items():
            text = path.read_text(encoding='utf-8')
            self.assertLess(len(text), PROCEDURE_CHARS, name)
            self.assertIn('SKILL.md "Procedure files"', text.split('\n## ')[0], name)
            sections = re.split(r', (?![^(]*\))', rows[f'{name}.md'][2])   # "Intake (step 1A, Router)" is one name
            for section in sections:
                self.assertTrue(f'\n## {section}' in text or f'\n**{section}:**' in text, f'{name}: {section}')
            heads, listed = re.findall(r'^## (.+)$', text, re.M), [s for s in sections if f'\n## {s}' in text]
            self.assertEqual(len(heads), len(listed), name)   # every heading of the file is in its row, in order
            for head, section in zip(heads, listed):
                self.assertTrue(head.startswith(section), f'{name}: {head}')

    def test_recorder_read_before_the_first_run_log_command(self):
        """The Recorder rules are outside the skill: Intake (before the create call) and continue item 4 name the file to read first."""
        path = '`${CLAUDE_PLUGIN_ROOT}/l1-orchestration/recorder.md`'
        intake = self.intake()
        self.assertLess(intake.index(path), intake.index('intake.py" create'))
        four = next(l for l in self.section('## continue', None, self.resume).splitlines() if l.startswith('4. '))
        self.assertIn(path, four)
        self.assertIn('monitor-up.py" --data-dir "<data folder>" --task-dir "<task_dir>"', four)

    def test_inline_role_rule(self):
        """The Inline role bullet sits in the core rules and names the folders, the line and the no-run case."""
        i = self.text.index('- **Inline role:**')
        bullet = self.text[i:self.text.index('\n', i)]
        self.assertLess(i + len(bullet), self.text.index('## Arguments'))
        for word in ('l2-design-judge/agents/', 'l3-workers/agents/', '`inline`', 'Skipped:', 'pass=inline'):
            self.assertIn(word, bullet, word)
        self.assertNotIn('Codex', bullet)
        self.assertIn('inline', run_log_kinds())
        self.assertIn('run-log.py" inline agent=my-agent:<role>', self.recorder)

    def test_working_files_in_english(self):
        """Working files in English; the person sees their own language (L1 translates when it shows one)."""
        rules = self.text[self.text.index('### Question rules'):self.text.index('## Arguments')]
        for word in ('`scope.md`', '`## Decisions`', 'in English', 'translates a working file when it shows it'):
            self.assertIn(word, rules, word)

    # --- data folder ---
    DATA_SCRIPTS = ('run-log', 'usage-snapshot', 'gate-report', 'feedback', 'monitor-up', 'open-html', 'intake', 'pre-gate')
    MONITOR_SKILL = REPO / 'skills' / 'monitor' / 'SKILL.md'

    def command_spans(self, path):
        """Each backticked `python3 ".../<script>.py" ...` span in the file, with the script name."""
        text = path.read_text(encoding='utf-8')
        for m in re.finditer(r'`(python3 "\$\{CLAUDE_PLUGIN_ROOT\}/[^"`]*/(%s)\.py"[^`\n]*)`' % '|'.join(self.DATA_SCRIPTS), text):
            yield m.group(2), m.group(1)

    def test_data_scripts_carry_data_dir(self):
        seen = 0
        for path in [SKILL, self.MONITOR_SKILL] + L1_FILES:
            for script, cmd in self.command_spans(path):
                seen += 1
                self.assertIn('--data-dir', cmd, f'{path.name}: {cmd}')
        self.assertGreaterEqual(seen, 30)

    def test_phase_files_rule_runs_data_dir_script(self):
        rule = self.text[self.text.index('### Phase files'):self.text.index('## Arguments')]
        self.assertIn('data-dir.py', rule)

    def test_placeholder_single_quoted_where_substituted(self):
        for path in (SKILL, self.MONITOR_SKILL):
            text = path.read_text(encoding='utf-8')
            self.assertIn('${user_config.data_dir}', text, path.name)
            for m in re.finditer(r'.{0,1}\$\{user_config\.data_dir\}.{0,1}', text):
                self.assertEqual(m.group(0), "'${user_config.data_dir}'", path.name)

    def test_phase_files_have_no_substitution_slot(self):
        for path in list((L1 / 'phases').glob('*.md')) + list(PROCEDURES.values()):
            self.assertNotIn('${user_config', path.read_text(encoding='utf-8'), path.name)

    def test_active_index_always_under_data_folder(self):
        for path in [SKILL] + L1_FILES:
            for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                for m in re.finditer(r'active-index\.json', line):
                    self.assertEqual(line[:m.start()][-14:], '<data folder>/', f'{path.name}:{n}')

    def test_autostart_off_in_intake_and_monitor_skill(self):
        item = self.intake_item(9)
        self.assertTrue(item.startswith('9. **Monitor:**'))
        self.assertIn('autostart off', item)
        self.assertIn('<data folder>/monitor-config.json', item)
        self.assertIn('autostart off', self.MONITOR_SKILL.read_text(encoding='utf-8'))

    def test_autostart_true_needed_for_intake_start(self):
        item = self.intake_item(9)
        self.assertIn('`"autostart": true`', item)
        self.assertIn('not started', item)
        self.assertIn('start by hand', item)
        text = self.MONITOR_SKILL.read_text(encoding='utf-8')
        self.assertIn('starts the monitor whatever the `autostart` value', text)
        self.assertIn('autostart off by default; start it with /my-agent:monitor', text)

    def test_intake_popup_recommends_current_folder(self):
        self.assertIn('`Current folder (Recommended)` / `<data folder>` / `Other path`', self.new_task)
        self.assertNotIn('`<data folder> (Recommended)`', self.new_task)
        self.assertIn('Popup every time, also inside a git repository', self.intake_item(2))
        self.assertNotIn('do not ask', self.intake_item(2))
        self.assertIn('"Commit the task log? The essential information goes into docs/blueprint, so committing it is not recommended."',
                      self.intake_item(5))

    # --- apply open feedback ---
    def section(self, start, end, text=None):
        """`text` (the skill by default) from `start` up to `end`, or to the end of the file when `end` is None."""
        text = self.text if text is None else text
        i = text.index(start)
        return text[i:] if end is None else text[i:text.index(end, i + 1)]

    def intake(self):
        return self.section('## Intake', None, self.new_task)

    def intake_item(self, n):
        i = self.new_task.index(f'\n{n}. **') + 1
        return self.new_task[i:self.new_task.index(f'\n{n + 1}. ', i)]

    # --- codex review fixes ---
    def test_intake_items_in_order(self):
        section = self.section('## Intake (step 1A, Router)', None, self.new_task)
        self.assertEqual(re.findall(r'^(\d+)\. \*\*', section, re.M), [str(n) for n in range(1, 12)])
        self.assertIsNone(re.search(r'\.\d+\. \*\*', section))

    def test_intake_uses_two_calls(self):
        """Intake is the facts call, the popups and one create call: no step the script does is left as an L1 command."""
        intake = self.intake()
        for gone in ('run-log.py', 'monitor-up.py', 'agent-models.py', 'git -C', 'date +%y%m%d', "date '+"):
            self.assertNotIn(gone, intake, gone)
        self.assertEqual(intake.count('intake.py" create'), 1)
        self.assertIn("--request='", self.intake_item(6))
        self.assertIn('hold no quote characters', self.intake_item(6))   # the script refuses a `'` or `"` in them
        self.assertIn('intake.py" facts', self.section('- Data folder:', None))

    def test_intake_md_follows_active(self):
        """`intake.md` is written right after `.active`, before the project list and the monitor (a task with
        `.active` and no `intake.md` can be neither continued nor aborted)."""
        for n, head in ((6, '**`.active` and index:**'), (7, '**`intake.md`:**'), (8, '**Project list:**'),
                        (9, '**Monitor:**')):
            self.assertTrue(self.intake_item(n).startswith(f'{n}. {head}'), n)

    def test_intake_running_task_candidates(self):
        """Item 1 names where it looks for `.active`; item 2 checks a location typed as `Other path`."""
        one = self.intake_item(1)
        self.assertIn('the folder you ran in (its git root, if any), the location `<data folder>/active-index.json` gives for it', one)
        self.assertIn('the folders the item 2 popup offers', one)
        self.assertIn('If `<task_dir>/.active` exists in one, popup:', one)
        self.assertIn('(an `Other path`) and has `<task_dir>/.active`, show the item 1 popup', self.intake_item(2))

    def test_record_popups_bullet_is_its_own_line(self):
        lines = self.new_task.splitlines()
        self.assertTrue(any(l.startswith('- Record these popups only when a new task starts') for l in lines))
        self.assertNotIn('.- Record these popups', self.new_task)

    def test_e_choices_match_accept(self):
        accept = self.section('## E escalation', None, self.gates)
        rows = [l for l in self.rules.splitlines() if l.startswith('| E Escalation |') or l.startswith('| Verify FAIL 3 times in a row |')]
        self.assertEqual(len(rows), 2)
        for row in rows:
            for choice in ('Give direction', 'Change scope', 'Abort'):
                self.assertIn(choice, row)
        self.assertIn('`Give direction` / `Change scope` / `Abort`', accept)
        for text in rows + [accept]:
            self.assertNotIn('Keep fixing', text)
        self.assertNotIn('Keep fixing', self.rules)

    def test_chosen_cuts_applied(self):
        for gone in ('- The monitor and the Claude Code permission dialog (G2) are outside the levels.',
                     'The baseline line makes the stretch holding',
                     '(scope-guard blocks writes that delete or change those lines)',
                     'the G1-B hook asks for a relative path after `cd`',
                     'An aborted task is not resumed with `continue`',
                     'separators inside quotes',
                     'A command with the word `git` but no such shape'):
            self.assertNotIn(gone, self.rules)
        for kept in ('write `Follows:`', 'the verdict hook cannot tell whether it is a commit',
                     'run `git rev-parse HEAD` first', 'follow "Tool choice"'):
            self.assertIn(kept, self.rules)
        row = next(l for l in self.text.splitlines() if l.startswith('| L4 |'))
        self.assertNotIn('monitor', row)   # the note stands on its own line under the table, not in the L4 cell
        self.assertIn('\nThe monitor and the G2 dialog are outside the levels.\n', self.text)

    def test_tool_choice_rule(self):
        self.assertLess(self.text.index('### Tool choice'), self.text.index('## Arguments'))
        rule = self.section('### Tool choice', '### Change requests')
        for word in ('Read', 'Grep', 'Glob', 'Edit', 'Write', 'one command per call', '`sed -i`', '`$(`',
                     'unittest discover -s'):
            self.assertIn(word, rule, word)
        self.assertNotIn('plan-approved-check.py', rule)

    def test_question_rules_popup_topics(self):
        rules = self.section('### Question rules', '### Gates')
        for word in ('one popup per topic', 'plain explanation', 'multi-select', 'stands alone'):
            self.assertIn(word, rules, word)

    def test_settled_popup_rule_in_one_place(self):
        """Criterion 3: the settled-popup bullet is in "Question rules"; the three "do not ask" sentences it replaces are gone."""
        rules = self.section('### Question rules', '### Gates')
        bullet = next(l for l in rules.splitlines() if l.startswith('- **Settled popup:**'))
        for word in ('after Intake', 'request, the files', 'earlier answer', '`answer … by=L1`',
                     '(answered by L1)', 'G1-A, G1-B, G3, G2, E, Intake popups', 'without a recommended choice',
                     'with another choice or a question back'):
            self.assertIn(word, bullet, word)
        self.assertEqual(self.text.count('**Settled popup:**'), 1)
        define = self.phase('define')
        research = (L1 / 'profiles' / 'research.md').read_text(encoding='utf-8')
        for gone, text in (('Do not ask about items the request already answers.', define),
                           ('In the Scope interview, do not ask what a line there already answers.', define),
                           ('Do not ask about items the request already answers.', research)):
            self.assertNotIn(gone, text)

    def test_settled_popup_keeps_delegation_and_records(self):
        """Under delegated approval the existing rules go on; a settled popup is recorded with its `ask` and `answer` lines."""
        rules = self.section('### Question rules', '### Gates')
        bullet = next(l for l in rules.splitlines() if l.startswith('- **Settled popup:**'))
        self.assertIn('Delegated approval rules stay', bullet)
        self.assertIn('write the `ask` line', bullet)
        self.assertIn('by=L1', bullet)
        sec = self.section('### Delegated approval', '### Levels')
        self.assertIn('answers G1-A, G1-B, findings popups and other non-gate popups with the recommended choice', sec)
        never = next(l for l in sec.splitlines() if l.startswith('- Never answered by L1:'))
        for word in ('G2', ' E,', 'third `REVISE`', 'without a recommended choice', 'Intake item 1–5'):
            self.assertIn(word, never, word)
        row = next(l for l in self.recorder.splitlines() if l.startswith('| Popup answered by L1'))
        self.assertIn('(delegated approval or a settled popup)', row)
        self.assertIn('by=L1', row)

    def test_question_rules_popup_layout(self):
        """Criterion 9: "Question rules" gives the layout of a popup question with more than one part."""
        rules = self.section('### Question rules', '### Gates')
        bullet = next(l for l in rules.splitlines() if '- Next:' in l)
        for word in ('first line', 'short question', '`- `', '`- Next: …`', 'two sentences', 'blank line', 'line break'):
            self.assertIn(word, bullet, word)

    def test_findings_list_table_before_findings_popup(self):
        """Criterion 8: Scope Review and Plan Review show a findings list table before the findings popup."""
        define = (REPO / 'l1-orchestration' / 'phases' / 'define.md').read_text(encoding='utf-8')
        plan = (REPO / 'l1-orchestration' / 'phases' / 'plan.md').read_text(encoding='utf-8')
        parts = (self.section('## Scope Review', None, define), self.section('## 2B Plan Review', '## G1-B plan approval', plan))
        for part in parts:
            self.assertIn('findings list table', part)
            self.assertIn('`# | Severity | Location | Finding | Fix L1 would apply`', part)
            self.assertIn('not the count table', part)

    def test_popup_stands_alone(self):
        """Criterion 4: a popup is understood without the chat text."""
        rules = self.section('### Question rules', '### Gates')
        bullet = next(l for l in rules.splitlines() if 'stands alone' in l)
        for word in ('plain explanation', 'what it contains', 'what it leads to'):
            self.assertIn(word, bullet, word)
        self.assertNotIn('For a technical matter, start the question', rules)

    def test_folder_copy_copies_contents(self):
        """Criterion 6: a folder copy takes the folder's contents, so a rerun does not nest."""
        rule = self.section('### Tool choice', '### Change requests')
        self.assertIn('`cp -pR <folder>/.`', rule)
        self.assertIn('does not nest', rule)

    def test_intake_worktree_and_gitignore_rules(self):
        self.assertIn('`New task in a worktree`', self.intake_item(1))
        self.assertIn('gitignore:', self.intake_item(5))
        self.assertIn('("Task worktree" in `changes.md`)', self.intake_item(1))
        section = self.section('## Task worktree', None, self.changes)
        for word in ('my-agent-task/', 'git worktree add', 'task ID'):
            self.assertIn(word, section, word)
        self.assertIn('`New task in a worktree` (Intake item 1)', self.changes.split('\n## ')[0])
        self.assertLess(len(self.new_task), PROCEDURE_CHARS)
        self.assertIn('my-agent-task/', self.section('## continue', None, self.resume))
        self.assertIn('baseline', self.intake_item(10))

    def test_intake_git_check_any_profile(self):
        self.assertIn('**Git check**', self.intake_item(2))
        self.assertLess(self.new_task.index('**Git check**'), self.new_task.index('\n3. **Profile:**'))
        section = self.section('**Git check (item 2)**', '**Models preset (item 3)**', self.new_task)
        for word in ('every profile', '`git:`', 'skip the whole check', '`uncommitted:`', '`branch:`', 'detached HEAD',
                     '`main` or `master`', 'Fix it first (Recommended)', 'Proceed as is', 'item 1 already asked'):
            self.assertIn(word, section, word)
        self.assertNotIn('$(', section)
        self.assertNotIn('rev-parse --is-inside-work-tree', self.new_task)
        report = self.section('\n11. **Report:**', '**Git check (item 2)**', self.new_task)
        self.assertIn('Git: <branch>, clean', report)
        for word in ('`behind:`', 'above 0', 'also when it is the only one', '`origin/<default>`', 'pull or merge',
                     '`not counted (<case>)`'):
            self.assertIn(word, section, word)
        self.assertIn(', <n> behind origin/<b>', report)
        self.assertIn(', behind not counted (<case>)', report)

    def test_new_task_request_file_rule(self):
        item = self.intake_item(6)
        for word in ('denied', 'deny list refuses', 'Write', '`<data folder>/request.txt`', '--request-file "<that path>"',
                     'in place of `--request=`'):
            self.assertIn(word, item, word)
        self.assertIn('--request-file', self.new_task)
        self.assertLess(len(self.new_task), PROCEDURE_CHARS)

    def test_models_preset_popup_describes_each_preset(self):
        item = self.section('**Models preset (item 3)**', None, self.new_task)
        for word in ('one line on what its preset changes in cost or care', '`presets` line'):
            self.assertIn(word, item, word)

    def test_flags_em_dash(self):
        for flags in (self.section('**Flags:**', None), self.section('## Flags', '## Intake', self.new_task)):
            self.assertIn('em dash', flags)
            self.assertIn('`—dev`', flags)

    def test_cost_row_baseline_and_moments(self):
        row = next(l for l in self.recorder.splitlines() if l.startswith('|') and 'run-log.py" cost' in l)
        for word in ('baseline=1', '`pre-gate.py --gate G3` writes it before the G3 popup', '`n=2A`',
                     '`n=3A` (also Back to Execute)', '`n=4A`', 'L1 runs no separate `cost` command'):
            self.assertIn(word, row, word)
        self.assertNotIn('Right before the G3 popup', row)

    def test_no_rule_tells_l1_to_run_cost_before_g3(self):
        self.assertNotIn('run-log.py" cost', self.gates)
        self.assertNotIn('Right before the G3 popup', self.recorder)
        self.assertNotIn('--file review', self.gates.split('G3 under delegated approval')[1].split('\n')[2])

    def test_failure_row_structural_argument(self):
        row = next(l for l in self.recorder.splitlines() if l.startswith('| Verify FAIL 1–2 times'))
        self.assertIn('structural argument', row)

    def test_gate_reports_section(self):
        section = self.section('## Gate reports', None, self.gates)
        for word in ('### Details', 'first two rows', 'G1-A', 'G1-B', 'G3', 'E', 'pre-gate.py', 'pointer line',
                     'task folder', 'no harness tool'):
            self.assertIn(word, section, word)
        self.assertLess(self.gates.index('## Check before anything leaves'), self.gates.index('## Gate reports'))

    def phase(self, name):
        return (L1 / 'phases' / f'{name}.md').read_text(encoding='utf-8')

    def dev_g3(self):
        dev = (L1 / 'profiles' / 'dev.md').read_text(encoding='utf-8')
        return dev[dev.index('## G3 in the dev profile'):dev.index('## Agents used')]

    def test_korean_copy_before_each_gate(self):
        """For a Korean request L1 refreshes report-ko.json before G1-A, G1-B and G3."""
        section = self.section('## Gate reports', None, self.gates)
        for word in ('**Korean copy.**', 'report-ko.py" --task "<absolute task folder>" todo', '`<task folder>/report-ko.json`',
                     'In another request language, skip this bullet.', 'the source the judges read'):
            self.assertIn(word, section, word)
        self.assertNotIn('**Korean copy.**', self.text)   # outside the skill
        self.assertIn('the Korean copy (gates.md "Gate reports"', self.phase('define'))
        self.assertIn('the Korean copy (gates.md "Gate reports"', self.phase('plan'))
        self.assertEqual(self.phase('accept').count('the Korean copy (gates.md "Gate reports"'), 1)
        self.assertEqual(self.dev_g3().count('the Korean copy (gates.md "Gate reports"'), 1)
        self.assertTrue((L4 / 'scripts' / 'report-ko.py').is_file())

    def test_accept_gate_reports_overview_first(self):
        accept = self.phase('accept')
        general = accept[accept.index('4. **G3 report (chat):**'):accept.index('5. **G3 popup:**')]
        dev = self.dev_g3()
        esc = self.section('## E escalation', None, self.gates)
        for part in (general, dev):
            for word in ('Gate reports', '### Overview', '### Takeaway', 'pointer line'):
                self.assertIn(word, part)
            self.assertNotIn('--url', part)
            self.assertNotIn('### Details', part)
        self.assertIn('pre-gate.py', dev)   # one call replaces the separate `open-html.py --report` and `cost` commands
        for word in ('Commit message', 'Diff', '+<a>/-<b>'):
            self.assertIn(word, dev)
        self.assertNotIn('the main diffs', dev)
        self.assertIn('Gate reports', esc)
        self.assertIn('### Details', esc)
        self.assertIn('scripts/archive.py" --task', accept)   # Back to Execute archives with the script, not cp and cmp

    def test_accept_g3_order_and_back_execute_scripts(self):
        """Criteria 1, 2, 4, 10: G3 in general/research is the writer call and one pre-gate.py call; Back to Execute is one script call."""
        accept = self.phase('accept')
        item4 = accept[accept.index('4. **G3 report (chat):**'):accept.index('5. **G3 popup:**')]
        item5 = accept[accept.index('5. **G3 popup:**'):accept.index('6. **Accept:**')]
        g3 = item4 + item5
        self.assertIn('`Gate report: G3`', item4)
        self.assertIn('--report-text "<absolute task folder>/report/G3.md"', item5)
        self.assertLess(item4.index('`Gate report: G3`'), item4.index('`pre-gate.py`'))
        for gone in ('open-html.py', 'findings.py', 'run-log.py" cost', '--file review', 'run-log.py" ask'):
            self.assertNotIn(gone, g3)
        self.assertIn('`Save path` row', item4)
        back = accept.split('## Back to Execute')[1].split('\n## ')[0]
        self.assertIn('back-execute.py" --task', back)
        self.assertIn('On a non-zero exit, stop and report its line', back)
        self.assertLess(back.index('back-execute.py'), back.index('`build.md`'))
        for gone in ('step n=', 'Change `phase:`', 'run-log.py'):
            self.assertNotIn(gone, back)
        self.assertIn('new worker call, never a resume', back)
        row = next(l for l in self.recorder.splitlines() if l.startswith('| Back to Execute'))
        self.assertIn('back-execute.py', row)
        self.assertNotIn('step n=', row)
        build = (L1 / 'phases' / 'build.md').read_text(encoding='utf-8')
        self.assertIn('back-execute.py', build)
        for name in ('accept', 'build'):
            self.assertLess(len(self.phase(name)), 12700)
        for name in ('recorder', 'changes', 'retro', 'resume'):
            self.assertLess(len(PROCEDURES[name].read_text(encoding='utf-8')), 12700, name)

    def test_accept_popup_bodies(self):
        accept = self.phase('accept')
        dev = self.dev_g3()
        for part in (accept, dev):
            self.assertIn('SHOULD-FIX and NITPICK items of `review.md`', part)
        self.assertIn('Verify FAIL x<n>: criterion <n> <one-line reason>', self.section('## E escalation', None, self.gates))
        self.assertIn('then the retrospective', dev)
        self.assertIn('Remote take: read retro.md "Remote update" before this popup', dev)   # Q41: the push is a G3 choice

    def test_accept_loop_and_scope_rules(self):
        accept = self.phase('accept')
        self.assertIn('structural argument', accept)
        self.assertIn('Change scope', accept)
        self.assertIn('one `Scope change:` round', accept)
        for part in (accept, self.dev_g3()):
            self.assertIn('git status --porcelain', part)
            self.assertIn('Open risks', part)
        self.assertIn('the previous `review.md` path, if any', accept)

    def test_accept_cost_calls(self):
        accept = self.phase('accept')
        cmd = 'run-log.py" cost'
        verify = accept[accept.index('## 4A Verify'):accept.index('## Back to Execute')]
        self.assertNotIn(cmd, verify)   # the step line that opens the phase writes the cost line itself (2026-11-16)
        self.assertIn('the script writes the `cost` line of the moment itself', verify)
        general = accept[accept.index('5. **G3 popup:**'):accept.index('6. **Accept:**')]
        devp = self.dev_g3()
        dev = devp[devp.index('3. Record before and after the popup.'):devp.index('4. **Commit:**')]
        self.assertIn('right before the G3 popup', general)
        self.assertNotIn(cmd, general)   # the `pre-gate.py` call writes the `cost` and `ask` lines itself
        self.assertIn('pre-gate.py" --gate G3', general)
        self.assertIn('(it writes the `cost` and `ask` lines)', general)
        self.assertNotIn(cmd, dev)   # the dev `pre-gate.py` call writes the `cost` and `ask` lines itself
        self.assertIn('pre-gate.py" --gate G3', dev)
        self.assertIn('(it writes the `cost` and `ask` lines)', dev)

    def test_build_prototype_and_worktree_session(self):
        build = self.phase('build')
        self.assertIn('prototype/index.html', build)
        self.assertIn('--git-common-dir', build)
        self.assertIn('every unit in sequence', build)

    def test_dev_merge_row_output_and_copy_fallback(self):
        dev = (L1 / 'profiles' / 'dev.md').read_text(encoding='utf-8')
        merge = next(l for l in dev.splitlines() if l.startswith('| 3B Merge'))
        self.assertIn('--output=', merge)
        self.assertIn('cp -p', merge)
        self.assertIn('cmp', merge)
        self.assertNotIn('\\|', merge)
        execute = next(l for l in dev.splitlines() if l.startswith('| 3A Execute'))
        self.assertIn('--git-common-dir', execute)

    def test_l1_row_popup_first_and_syntax_check(self):
        row = next(l for l in self.text.splitlines() if l.startswith('| L1 |'))
        self.assertIn('popup first', row)
        self.assertIn('syntax check', row)

    def test_no_author_machine_paths(self):
        for path in [SKILL, self.MONITOR_SKILL] + L1_FILES:
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('~/dev/agent-tasks', text, path.name)
            self.assertNotIn('my-surrogate', text, path.name)


    # --- agent model presets and report-style gate reports ---
    def test_intake_models_preset(self):
        """Intake item 3 asks the preset only with 2 or more presets; item 7 and 10 carry it."""
        self.assertIn('"Models preset" below item 11', self.intake_item(3))
        item = self.section('**Models preset (item 3)**', None, self.new_task)
        for word in ('Models preset', 'presets <profile>:', '2 or more presets', '`standard` is used',
                     'Use definition values (Recommended)', 'Abort', '(Recommended)', 'item 10'):
            self.assertIn(word, item, word)
        self.assertIn('Models: <preset>', self.intake_item(7))
        ten = self.intake_item(10)
        self.assertIn('models preset=<name> source=file', ten)
        self.assertIn('only when `Models:` was written', ten)

    def test_profile_change_models_preset(self):
        """A profile change at the first gate asks the preset again with the Intake popup rule."""
        section = self.section('## In-flight revision', 'When a message that looks like a revision', self.changes)
        bullet = section[section.index('**Profile change at the first gate'):]
        for word in ('presets --profile <new profile>', 'same popup rule as Intake item 3', '`Models:` in `intake.md`',
                     'run-log.py" models preset=<name> source=file'):
            self.assertIn(word, bullet, word)

    def test_continue_checks_models_preset(self):
        """Continue shows the preset again; a preset that is gone falls back to the definition values."""
        sec = self.section('## continue', None, self.resume)
        for word in ('`Models:`', 'show --profile <p> --preset <name>', 'exits 1', 'definition values'):
            self.assertIn(word, sec, word)

    def test_delegation_passes_only_differing_fields(self):
        """Model/effort come from the preset; only the pass= fields are passed; the opus retry beats it."""
        sec = self.section('## Failure handling', None, self.recorder)
        for word in ('show --profile', 'show --plan', '`## Models`', 'pass=', 'no `Models:` line', 'pass none',
                     '`model: "opus"`', 'beats the preset'):
            self.assertIn(word, sec, word)
        row = next(l for l in self.recorder.splitlines() if l.startswith('| Worker stopped once'))
        self.assertIn('beats the preset', row)
        self.assertIn('model: "opus"', row)

    def test_recorder_models_row(self):
        row = next(l for l in self.recorder.splitlines() if l.startswith('| ') and 'run-log.py" models ' in l)
        self.assertIn('--data-dir "<data folder>" --task-dir "<task_dir>"', row)
        self.assertIn('models', run_log_kinds())

    def test_gate_reports_overview_and_takeaway(self):
        """G1-A and G1-B open with Overview and Takeaway before the table; G1-B has a Models row."""
        sec = self.section('## Gate reports', None, self.gates)
        for word in ('### Overview', '### Takeaway', 'G1-A', 'G1-B', 'scope summary', 'plan summary', '`Models` row',
                     '`Request changes`', '`Approve`'):
            self.assertIn(word, sec, word)
        self.assertLess(sec.index('### Overview'), sec.index('### Takeaway'))
        self.assertLess(sec.index('### Takeaway'), sec.index('`| Item | Value |`'))

    def test_gate_reports_prototype_opened_locally(self):
        """The prototype is a local file opened by open-html.py; the line replaces the full mock-up at G1-B."""
        plan = self.phase('plan')
        sec = self.section('2. If `## Prototype`', '3. **Hosts:**', plan)
        for word in ('open-html.py', 'prototype/index.html', '--data-dir', 'opened in the browser', 'not opened',
                     '`failed:`', 'remake it only if the mock-up changed', 'Nothing is published',
                     'skills/mock-up', 'capture.sh'):
            self.assertIn(word, sec, word)
        self.assertNotIn('**Prototype**', self.gates)   # the rule lives in define.md and plan.md

    def test_gate_reports_open_report_tab(self):
        """The gate report is read on the Report tab; the chat keeps the pointer line `pre-gate.py` prints."""
        sec = self.section('## Gate reports', None, self.gates)
        for word in ('`ask` line', 'Commit message', 'Diff', '+<a>/-<b>', 'Save path', 'the full diff is not printed',
                     'report_open', 'the line the `pre-gate.py` call printed, as it is'):
            self.assertIn(word, sec, word)
        self.assertNotIn('Opening the Report tab', sec)
        # one call: the script writes the lines, opens the tab and prints the pointer line (criterion 1)
        self.assertIn('**Pre-gate call.**', sec)
        self.assertIn('pre-gate.py" --gate <G1-A|G1-B|G3> --task "<absolute task folder>" q="<question>" rec="<recommended choice>"', sec)
        self.assertIn('--report-text "<absolute task folder>/report/<gate>.md"', sec)
        self.assertIn('--data-dir "<data folder>" --task-dir "<task_dir>"', sec)
        self.assertNotIn('open-html.py" --report', sec)
        self.assertNotIn('--url', sec)

    def test_g1b_row_opens_report_tab(self):
        row = next(l for l in self.text.splitlines() if l.startswith('| G1-B Plan approval'))
        self.assertNotIn('full mock-up', row)
        self.assertIn("after opening the task's Report tab", row)

    def test_open_html_spans_carry_data_dir_only(self):
        spans = [c for name in ('plan', 'define') for s, c in self.command_spans(L1 / 'phases' / f'{name}.md') if s == 'open-html']
        self.assertTrue(spans)
        for cmd in spans:
            self.assertIn('--data-dir', cmd)
            self.assertNotIn('--task-dir', cmd)
            self.assertNotIn('--report', cmd)

    def test_no_artifact_publishing(self):
        """No stale publishing wording in the gate reports or the leave check."""
        gate = self.section('## Gate reports', None, self.gates)
        leave = self.section('## Check before anything leaves', '## Gate reports', self.gates)
        for part in (gate, leave):
            for phrase in ('private artifact', 'artifact link', 'publishes it', 'publishing a prototype', 'claude.ai'):
                self.assertNotIn(phrase, part, phrase)
        self.assertNotIn('prototype', leave)
        self.assertNotIn('artifact', leave)
        self.assertIn('copying the deliverable after G3', leave)
        self.assertIn('committing', leave)

    def test_gate_reports_findings_table(self):
        """Each gate report holds the findings table printed by findings.py."""
        sec = self.section('## Gate reports', None, self.gates)
        for word in ('The `pre-gate.py` call prints it (`findings.py`)', '### Scope Review findings', '### Plan Review findings',
                     '### Review findings', 'Severity | Found | Fixed | Open', 'also when every count is 0',
                     'per-round values joined by `/`', 'a single round shows one number',
                     '`findings: skipped (', 'judgment was skipped', '`findings: FAIL`', 'G1-A or G1-B',
                     'general', 'research', 'dev'):
            self.assertIn(word, sec, word)
        self.assertNotIn('Right before the chat report run', sec)
        for path in (self.phase('define'), self.phase('plan'), self.phase('accept'), self.dev_g3()):
            self.assertIn('findings table (gates.md "Gate reports")', path)

    def test_gate_popup_text_layout(self):
        """The popup text has line breaks: question, counts line, one line per open item, next."""
        sec = self.section('## Gate reports', None, self.gates)
        for word in ('counts line', '`BLOCKER \u00b7 <n> / SHOULD-FIX \u00b7 <n> / NITPICK \u00b7 <n>`', 'in capitals also in another language',
                     'No open items',
                     'more than 10', 'first 10', '`\u2026 and <k> more`', 'line breaks as written'):
            self.assertIn(word, sec, word)
        self.assertLess(sec.index('The short question'), sec.index('counts line'))
        self.assertLess(sec.index('counts line'), sec.index('what happens next'))
        block = re.search(r'```text\n(.*?)```', sec, re.S).group(1).splitlines()
        block = [l.strip() for l in block][1:]   # the first line is the label line (u9)
        while block and not block[-1]:
            block.pop()
        self.assertGreaterEqual(len(block), 4)
        self.assertNotIn('', block)
        self.assertFalse(block[0].startswith('- '))
        self.assertTrue(all(l.startswith('- ') for l in block[1:]), block)
        self.assertTrue(block[-1].startswith('- Next:'), block[-1])
        self.assertTrue(any(l.startswith('- BLOCKER \u00b7 0 / SHOULD-FIX \u00b7 ') for l in block))   # criterion 14
        self.assertNotIn('(open)', '\n'.join(block))
        self.assertNotIn('monitor-up.py', sec)

    def test_pre_gate_call_replaces_separate_commands(self):
        """Criterion 1: G1-A, G1-B and the dev G3 each make one `pre-gate.py` call; no separate report, findings or cost command."""
        define, plan, dev = self.phase('define'), self.phase('plan'), self.dev_g3()
        for gate, part in (('G1-A', define), ('G1-B', plan), ('G3', dev)):
            self.assertIn('pre-gate.py" --gate %s --task "<absolute task folder>" q="' % gate, part, gate)
            self.assertIn('--data-dir "<data folder>" --task-dir "<task_dir>"', part[part.index('pre-gate.py'):])
            self.assertNotIn('open-html.py" --report', part, gate)
            self.assertNotIn('open-html.py --report', part, gate)
            self.assertNotIn('scripts/findings.py', part, gate)
            self.assertNotIn('run-log.py" cost', part, gate)
        order = 'the `pre-gate.py` call'
        self.assertIn(order, define[define.index('- Order:'):])
        self.assertIn(order, plan[plan.index('4. Record before and after'):])
        self.assertIn(order, dev[dev.index('3. Record before and after'):])

    def test_gate_report_writer_at_g1b_and_dev_g3(self):
        """Criterion 4: G1-B and the dev G3 call the writer first (`Gate report:`); L1 adds only the commit, diff and cost rows."""
        plan, dev = self.phase('plan'), self.dev_g3()
        step4 = plan[plan.index('4. Record before and after'):plan.index('5. **Approve:**')]
        step3 = dev[dev.index('3. Record before and after'):dev.index('4. **Commit:**')]
        self.assertIn('the writer call (`Gate report: G1-B`)', step4)
        self.assertIn('--report-text "<absolute task folder>/report/G1-B.md"', step4)
        self.assertLess(step4.index('the writer call'), step4.index('the `pre-gate.py` call'))
        self.assertIn('the writer call (`Gate report: G3`, with `git diff --stat` in the same message)', step3)
        self.assertIn('--report-text "<absolute task folder>/report/G3.md"', step3)
        self.assertLess(step3.index('the writer call'), step3.index('the `pre-gate.py` call'))
        self.assertIn('written by `my-agent:writer`', dev)
        self.assertIn('L1 adds only a `Commit message` row', dev)
        self.assertIn('a `Diff` row', dev)
        self.assertIn('and the cost (reference), as one short table after the printed output, before the popup', dev)
        self.assertIn('the reviewer check (`review.md` exists and is newer than the latest reviewer call', step3)
        self.assertIn('`findings.py --file review`', step3)
        self.assertIn('on `findings: FAIL` one new reviewer call', step3)
        self.assertLess(step3.index('the reviewer check'), step3.index('the writer call'))
        gates = self.section('- **Writer** (G1-B, G3):', '- **Korean copy.**', self.gates)
        self.assertIn('as a short table after the printed output, before the popup', gates)
        for word in ('`Gate report: <G1-B|G3>`', '<task folder>/report/<gate>.md', 'L1 adds only the dev `Commit message` and `Diff` rows and the cost',
                     'recorder.md "Failure handling"'):
            self.assertIn(word, gates, word)
        korean = self.section('- **Korean copy.**', '- **Chat report**', self.gates)
        self.assertIn('for G1-B and G3 put the printed output in the writer prompt', korean)
        # G1-A keeps L1's own report: no writer, no --report-text
        self.assertNotIn('Gate report: G1-A', self.gates + self.phase('define'))
        self.assertNotIn('--report-text', self.phase('define'))

    def test_parallel_calls_at_every_point_of_a_task(self):
        """Criterion 3: tool calls that need no result of each other go in one message at every point, not only within one step."""
        sec = self.section('### Tool choice', '### Change requests')
        line = next(l for l in sec.splitlines() if 'one message' in l)
        for word in ('At every point of a task', 'do not need each other\'s result', 'record lines', 'Reads', 'script calls',
                     'not only within one step'):
            self.assertIn(word, line, word)
        self.assertNotIn('of one step', line)

    def test_light_path_sentences_and_delegated_cap(self):
        """Criterion 5: both Rework lines keep the re-judge scope and add the light path; the delegated cap counts a light-path round."""
        sec = self.section('## Gate reports', '## E escalation', self.gates)
        example = next(l for l in sec.splitlines() if l.startswith('  - Rework: fix all open items fixes them'))
        rule = next(l for l in sec.splitlines() if l.startswith('  - With open items the question has one plain line'))
        for line in (example, rule):
            self.assertIn('only the criteria', line)
            self.assertIn('every open item is a NITPICK', line)
            self.assertIn('only Review runs again', line)
        delegated = self.delegated()
        self.assertIn('each light-path round (accept.md) counts as one G3 Rework round', delegated)
        self.assertIn('own cap of 3', delegated)
        self.assertIn('Open items after 3 G3 fix rounds: go to E', delegated)

    def test_findings_cells_and_counts_line_form(self):
        """Criteria 14 and 16: the chat report table cells join the per-round values with `/`; the counts line has the new form."""
        sec = self.section('## Gate reports', '## E escalation', self.gates)
        self.assertIn('Each cell holds the per-round values joined by `/`', sec)
        self.assertIn('`BLOCKER · <n> / SHOULD-FIX · <n> / NITPICK · <n>`', sec)
        self.assertNotIn('NITPICK <n> (open)', sec)
        self.assertNotIn('NITPICK <n> (open)', self.dev_g3())

    def test_unit_files_fit_the_size_limits_with_room_left(self):
        """Criterion 10: each file of the gate-report unit is at most 12,700 characters; the files u8 and u9 still edit keep room."""
        room = {SKILL: 200, PROCEDURES['gates']: 150, L1 / 'phases' / 'define.md': 250, L1 / 'profiles' / 'dev.md': 250}
        for path in [SKILL, PROCEDURES['gates'], L1 / 'phases' / 'define.md', L1 / 'phases' / 'plan.md'] + \
                [L1 / 'profiles' / f'{n}.md' for n in ('dev', 'general', 'research')]:
            size = len(path.read_text(encoding='utf-8'))
            self.assertLessEqual(size + room.get(path, 0), 12700, f'{path.name}: {size}')

    def test_popup_label_rule(self):
        """Criterion 8: every popup but G2 starts with the label line; the rule is in the Question rules, the detail in gates.md."""
        q = self.section('### Question rules', '### Gates')
        for text in ('Every popup but G2 starts with `[<step ID>] <step name> · <gate>`', '`G1-A`, `G1-B`, `G3`, `E`, `Q`',
                     'the question on the next line', 'short English', 'also in another language', 'recorder.md` “Popup label”'):
            self.assertIn(text, q)
        rec = PROCEDURES['recorder'].read_text(encoding='utf-8')
        label = self.section('## Popup label', '## Revision records', rec)
        self.assertIn('recorder.md "Popup label"', self.gates)
        for text in ('not the G2 permission dialog', 'first line `[<step ID>] <step name> · <gate>`',
                     '`G1-A`, `G1-B`, `G3`, `E` or `Q`', 'the question is on the next line', '`Explore → Scope`', '`Plan Review`',
                     '`Merge`', 'without the gate or other words the monitor adds', 'also in a popup in another language',
                     'outside a step\'s own procedure', 'task start, resume, retrospective, change request',
                     'the step the task is in (retrospective `[4B]`)', 'before the task exists uses `[1A] Intake`'):
            self.assertIn(text, label, text)

    def test_popup_example_blocks_start_with_the_label_line(self):
        """Criterion 8: the gates.md popup example (and any popup example in the host files) opens with a label line."""
        pattern = re.compile(r'^\[[1-4][AB]\] (Intake|Explore → Scope|Plan|Plan Review|Execute|Merge|Verify|Review → Deliver)'
                             r' · (G1-A|G1-B|G3|E|Q)$')
        sec = self.section('## Gate reports', '## E escalation', self.gates)
        blocks = [('gates.md', sec[sec.index('- **Popup text.**'):sec.index('- **G3 with open review items.**')])]
        for name in ('hosts.md', 'hosts-antigravity.md'):
            blocks.append((name, (L1 / name).read_text(encoding='utf-8')))
        for name, text in blocks:
            for block in re.findall(r'```text\n(.*?)```', text, re.S):
                first = block.splitlines()[0].lstrip()
                self.assertRegex(first, pattern, name)
        self.assertEqual(len(re.findall(r'```text\n', blocks[0][1])), 1)

    def popup_text(self):
        sec = self.section('## Gate reports', '## E escalation', self.gates)
        return sec[sec.index('- **Popup text.**'):sec.index('- **G3 with open review items.**')]

    def g3_open_items(self):
        sec = self.section('## Gate reports', '## E escalation', self.gates)
        return sec[sec.index('- **G3 with open review items.**'):]

    def plan_step4_should_fix(self):
        return next(l for l in self.phase('plan').splitlines() if 'Marked findings (`[ask person]`' in l)

    def test_popup_should_fix_explanation_line(self):
        """A popup with open SHOULD-FIX items carries one line saying what a SHOULD-FIX item is."""
        text = self.popup_text()
        for word in ('a problem worth fixing', 'does not block', 'G1-A, G1-B and G3'):
            self.assertIn(word, text, word)
        line = self.plan_step4_should_fix()
        for word in ('Question rules', 'a problem worth fixing', 'does not block', '`- Next:` last'):
            self.assertIn(word, line, word)

    def test_g3_rework_and_rejudge_line(self):
        """The G3 question says what Rework: fix all open items does and what is judged again."""
        sec = self.g3_open_items()
        for word in ('Verify and Review run again', 'the criteria the fix touches or the open items name',
                     '`[criterion <n>]`', 'keep their earlier verdict', 'remote take'):
            self.assertIn(word, sec, word)

    def test_g3_rework_line_says_all_when_rejudge_is_all(self):
        sec = self.g3_open_items()
        for word in ('no valid `[criterion <n>]` tag', 'no `changed-files.md`', 'every criterion is judged again',
                     'Re-judge: all'):
            self.assertIn(word, sec, word)

    def test_explanation_lines_keep_popup_layout(self):
        text = self.popup_text()
        self.assertLess(text.index('counts line'), text.index('a problem worth fixing'))
        self.assertLess(text.index('a problem worth fixing'), text.index('`- Next: `'))
        block = re.search(r'```text\n(.*?)```', text, re.S).group(1).splitlines()
        block = [l.strip() for l in block][1:]   # the first line is the label line (u9)
        while block and not block[-1]:
            block.pop()
        self.assertNotIn('', block)
        self.assertFalse(block[0].startswith('- '))
        self.assertTrue(all(l.startswith('- ') for l in block[1:]), block)
        self.assertTrue(block[-1].startswith('- Next:'), block[-1])
        self.assertTrue(any('problem worth fixing' in l for l in block), block)
        self.assertTrue(any('Rework: fix all open items' in l for l in block), block)
        self.assertTrue(any('Rework: fix all open items' in l and 'judged again' in l for l in block), block)
        self.assertIn('`Rework: fix all open items (Recommended)` / `<Take>` / `Rework` / `Abort`', self.g3_open_items())
        self.assertIn('`Apply all (Recommended)` / `Approve without applying` / `Pick myself`',
                      self.plan_step4_should_fix())
        sec = self.section('## Scope Review', None, self.phase('define'))
        self.assertIn('`Apply all (Recommended)` / `Confirm without applying` / `Pick myself`', sec)
        self.assertIn('`plan.md` step 2B', sec)
        self.assertIn('SHOULD-FIX line', sec)

    def test_rework_line_only_at_g3(self):
        self.assertIn('at G3 with open items', self.popup_text())
        step4 = self.plan_step4_should_fix()
        self.assertNotIn('re-judge', step4.lower())
        self.assertNotIn('judged again', step4)
        sec = self.section('## Scope Review', None, self.phase('define'))
        self.assertNotIn('re-judge', sec.lower())
        self.assertNotIn('judged again', sec)

    def test_no_explanation_line_without_open_items(self):
        text = self.popup_text()
        self.assertIn('with no open item at G3, neither line is shown', text)
        self.assertIn('needs an open SHOULD-FIX', text)

    def test_nitpick_only_findings_have_no_popup(self):
        self.assertIn('apply them without a popup', self.phase('plan'))
        self.assertIn('unmarked findings are applied without a popup', self.phase('define'))
        self.assertNotIn('NITPICK only: apply them without a popup', self.phase('plan'))

    def test_marked_findings_popup(self):
        """Criterion 6: unmarked findings are applied without a popup (READY and REVISE); marked ones, any severity, go in one popup before the fix."""
        line = self.plan_step4_should_fix()
        for word in ('`[ask person]`, any severity', 'findings list table', 'one popup that lists them',
                     'ask gate=Q … rec="Apply all"', 'with the SHOULD-FIX line', 'these findings change the scope or need your answer',
                     '`- Next:` last', '`Apply all (Recommended)` / `Approve without applying` / `Pick myself`',
                     'They skip only SHOULD-FIX and NITPICK items; a BLOCKER is always fixed',
                     'No marked finding: no popup', 'Delegated approval answers `Apply all`'):
            self.assertIn(word, line, word)
        step4 = self.plan_step4()
        self.assertIn('the marked-findings popup below comes first, so the fix holds the answers', step4)
        self.assertIn('third `REVISE`', step4)
        self.assertIn('G1-B popup', step4)
        sec = self.section('## Scope Review', None, self.phase('define'))
        self.assertIn('unmarked findings are applied without a popup', sec)
        self.assertIn('the popup first, then fix', sec)
        self.assertNotIn('A fix that needs the person\'s answer', sec)
        self.assertNotIn('NITPICK only', sec)

    def test_scope_width_popup_and_richer_option(self):
        """Criterion 7: the interview opens with the width popup; later popups offer the richer option second, first after `The richer result`."""
        rule = ('opens with one scope-width popup (`ask gate=Q … rec="Only what was asked"`/`answer gate=Q` lines): '
                '`Only what was asked (Recommended)` / `Related things too` / `The richer result`')
        for name in ('dev', 'general', 'research'):
            text = (L1 / 'profiles' / f'{name}.md').read_text(encoding='utf-8')
            self.assertIn(rule, text, name)
            self.assertIn('Every later scope or design popup offers the richer option second, and first with '
                          '`(Recommended)` after `The richer result`', text, name)
            self.assertIn('related items in the same task, plus documents, screens and tests', text, name)
        step3 = self.section('3. **Scope interview:**', '4. **Confirm the scope:**', self.phase('define'))
        self.assertIn("Open with the profile file's scope-width popup", step3)
        self.assertLess(step3.index('Open with'), step3.index('Scope questions follow'))
        self.assertLess(len("Open with the profile file's scope-width popup."), 60)
        dev = (L1 / 'profiles' / 'dev.md').read_text(encoding='utf-8')
        small = next(l for l in dev.splitlines() if l.startswith('| Small task exception'))
        self.assertIn('skip the Scope interview', small)

    def test_person_choice_marks(self):
        """Criterion 2: interview decisions carry `(the person's choice)`; L1's reading and answers carry none."""
        step4 = self.section('4. **Confirm the scope:**', '5. If `scope.md`', self.phase('define'))
        line = next(l for l in step4.splitlines() if 'Mark each line the person settled' in l)
        for word in ("` (the person's choice)`", 'on a criterion right before its check tag', '`- Environment:` line',
                     '`Keep it`/`Change it`', 'Person-check answer', "L1's reading and answers get no mark"):
            self.assertIn(word, line, word)
        self.assertLess(step4.index('Write `scope.md`'), step4.index('Mark each line'))

    def test_build_hands_check_durations_to_coder(self):
        """Criterion 3: the coder hand-off carries the measured duration of each check command, an upper bound for a narrowed one."""
        pass_line = next(l for l in self.phase('build').splitlines() if l.lstrip().startswith('- Pass:'))
        for word in ('`explore.md` `## Check commands`', '`<command>: <n> s`', 'carries the duration of the explorer command it is derived from',
                     '`<n> s (upper bound, from <explorer command>)`', '`no measured duration`', '`Skipped:`', '`cannot run:`',
                     'no Explore'):
            self.assertIn(word, pass_line, word)


class BackgroundResearchRulesTest(unittest.TestCase):
    """Background research (Q45): the L1 rule files carry the step, its limits and where it does not exist."""

    def read(self, *parts):
        return L1.joinpath(*parts).read_text(encoding='utf-8')

    def setUp(self):
        self.define = self.read('phases', 'define.md')

    def step(self):
        i = self.define.index('\n## Background research')
        return self.define[i:self.define.index('\n## Scope Review')]

    def test_background_research_conditions_and_limit(self):
        for word in ('changes a plan choice', 'the project cannot answer', 'not the content of the deliverable', 'at most 4'):
            self.assertIn(word, self.define)

    def test_background_research_section_format_and_no_questions(self):
        text = self.define
        self.assertIn('- b<n>: <question> — <what it decides in the plan>', text)
        self.assertIn('`b1`–`b4`', text)
        self.assertIn('no `## Background research` section', text)
        self.assertIn('never an empty section or `none`', text)

    def test_background_research_more_than_four_candidates(self):
        text = self.define
        self.assertIn('keep the 4 that change the plan most', text)
        self.assertIn('candidates that were not researched', text)
        self.assertIn('`To confirm`', text)

    def test_background_research_call_and_log(self):
        step = self.step()
        for word in ('Background question: b<n> <slug>', 'background/<slug>.md', 'step n=1B name=Background-research',
                     'my-agent:researcher', 'in one message', 'official docs and primary sources'):
            self.assertIn(word, step)
        self.assertLess(self.define.index('On Confirm, write `Confirmed'), self.define.index('\n## Background research'))
        self.assertIn('Background research: <n> questions', self.define)
        self.assertIn('no popup of their own', self.define)

    def test_background_research_done_but_note_missing(self):
        step = self.step()
        self.assertIn('`DONE` whose note is missing or fails the form check', step)
        self.assertIn('worker that stopped once', step)
        self.assertIn('recorder.md "Failure handling"', step)

    def test_background_research_note_contradicts_scope(self):
        step = self.step()
        self.assertIn('contradicts the scope', step)
        self.assertIn('reopens G1-A with `Revise`', step)
        self.assertIn('changes.md "Profile change at the first gate"', step)

    def test_background_research_researcher_stops_twice(self):
        gates = self.read('gates.md')
        self.assertIn('the same work unit (`u<n>` or `b<n>`) stopped twice', gates)
        self.assertIn('`Background research` row', gates)
        rec = self.read('recorder.md')
        self.assertIn('unit=<u…|b…>', rec)
        self.assertIn('Background research', rec[rec.index('## Failure handling'):])
        plan = self.read('phases', 'plan.md')
        self.assertIn('Background research', plan)
        self.assertIn('background/*.md', plan)

    def test_background_research_resume_runs_only_missing_notes(self):
        text = self.read('resume.md')
        self.assertIn('Background research', text)
        self.assertIn('no note', text)

    def test_background_research_skill_names_researcher_exception(self):
        text = SKILL.read_text(encoding='utf-8')
        i = text.index('- Before G1-B approval, delegate only to')
        self.assertIn('my-agent:researcher', text[i:text.index('\n', i)])
        self.assertIn('`my-agent:writer` for the G1-B report', text[i:text.index('\n', i)])
        self.assertIn('1B Explore → Scope → Background research', text)

    def test_background_research_general_profile_rows(self):
        text = self.read('profiles', 'general.md')
        self.assertNotIn('Start web research only after G1-B approval.', text)
        row = next(l for l in text.splitlines() if l.startswith('| 3A Execute'))
        self.assertIn('Background research', row)
        row = next(l for l in text.splitlines() if l.startswith('| `my-agent:researcher`'))
        self.assertIn('Background research', row)

    def test_background_research_absent_places(self):
        research = self.read('profiles', 'research.md')
        self.assertIn('No Background research', research)
        self.assertIn('`To confirm`', research)
        for name in ('dev.md', 'general.md'):
            self.assertIn('no Background research for a small task', self.read('profiles', name), name)
        row = next(l for l in self.read('hosts.md').splitlines() if l.startswith('| `WebFetch`'))
        self.assertIn('Background research', row)
        self.assertIn('To confirm', row)


class PlanFindingRouteTest(unittest.TestCase):
    """2026-11-26: a round that sends back a `[plan]` review finding gets the plan-finding popup before any fix."""

    LABELS = '`Adjust within approved scope` / `Revise this task` / `Fix within current plan`'

    def setUp(self):
        self.changes = PROCEDURES['changes'].read_text(encoding='utf-8')
        self.gates = PROCEDURES['gates'].read_text(encoding='utf-8')
        self.accept = (L1 / 'phases' / 'accept.md').read_text(encoding='utf-8')
        self.plan = (L1 / 'phases' / 'plan.md').read_text(encoding='utf-8')

    def block(self):
        start = self.changes.index('\n### Plan findings (Review)\n')
        return self.changes[start:self.changes.index('\n## Abort')]

    def item(self, title):
        """One numbered item of the block, with its sub-bullets."""
        m = re.search(r'^\d+\. \*\*%s:\*\*.*?(?=^\d+\. \*\*|\Z)' % re.escape(title), self.block(), re.M | re.S)
        self.assertIsNotNone(m, title)
        return m.group(0)

    def has(self, text, *words):
        for word in words:
            self.assertIn(word, text, word)

    def test_accept_points_to_plan_findings_before_any_fix(self):
        """Criterion 3."""
        review = self.accept[self.accept.index('## 4B Review → Deliver'):self.accept.index('1. Record', self.accept.index('## 4B'))]
        line = next(l for l in review.splitlines() if '[plan]' in l)
        self.has(line, 'sends back a `[plan]` finding', 'changes.md', '"Plan findings (Review)"',
                 'no fix starts before its answer')
        self.has(self.item('When'), 'before any fix', '`accept.md` step 4B item 3', 'item 7', 'light path',
                 '"Back to Execute"', 'also when the marked fix is small')
        item7 = self.accept[self.accept.index('7. **Rework:**'):self.accept.index('8. **Abort:**')]
        self.assertNotIn('[plan]', item7)
        self.has(self.changes.split('\n## ')[0], 'SKILL.md "Procedure files"', '`[plan]` review finding',
                 '`accept.md` step 4B')

    def test_plan_findings_popup_three_choices(self):
        """Criteria 4 and 11."""
        popup = self.item('The popup')
        line = next(l for l in popup.splitlines() if 'exactly three choices' in l)
        self.has(line, 'exactly three choices: ' + self.LABELS)
        self.assertNotIn('Split into a new task', self.block())
        self.assertNotIn('`Cancel`', self.block())
        self.has(popup, 'one per round', '`[4B] Review → Deliver · Q`', '"Popup label"', '"Question rules"',
                 'a short question', 'each `[plan]` finding', 'what it contains', 'one `- ` line per choice',
                 'what it leads to', '`- Next:` last', 'ask gate=Q … rec="<recommended>"',
                 'answer gate=Q choice="<choice>"', '`by=L1`', '`(Recommended)`')
        self.has(popup, 'a SHOULD-FIX is listed', 'a problem worth fixing that does not block the gate')
        changes = self.changes
        self.assertLess(changes.index('\n- **A request after G3 acceptance**'), changes.index('\n### Plan findings (Review)\n'))
        self.assertLess(changes.index('\n### Plan findings (Review)\n'), changes.index('\n## Abort'))
        self.assertEqual(re.findall(r'^## (.+)$', changes, re.M),
                         ['In-flight revision (before G3 acceptance)', 'Abort', 'Task worktree'])
        self.assertIn('first ask its kind in a popup: `Revise this task` / `Adjust within approved scope` / '
                      '`Split into a new task` / `Cancel` (put the one that fits first, with `(Recommended)`).', changes)

    def test_plan_findings_recommendation(self):
        """Criterion 4."""
        rec = self.item('Recommendation')
        revise = next(l for l in rec.splitlines() if l.startswith('   - `Revise this task`'))
        self.has(revise, 'the approach or the set of work units must change', 'the approved request does not stand')
        adjust = next(l for l in rec.splitlines() if l.startswith('   - Otherwise `Adjust within approved scope`'))
        self.has(adjust, 'the approved request stands', 'planned units', 'one more target file, behavior or dependency')
        self.has(rec, '`Fix within current plan` is never recommended and is always listed last',
                 'the largest need decides')

    def test_plan_findings_mark_position(self):
        """Criteria 1 and 3."""
        self.has(self.item('When'), 'the exact lower-case token `[plan]` stands right before `[criterion …]`',
                 'right before `(new)`/`(carried)`', 'anywhere else', 'reads as unmarked')

    def test_plan_findings_adjust(self):
        """Criterion 5."""
        self.has(self.item('`Adjust within approved scope`'), '"Adjust within approved scope" above',
                 '`Scope change:` line', 'fix what="Scope change: …" files=plan.md', 'The approval is kept',
                 'item 3: small fix or "Back to Execute"', 'item 7: light path or "Back to Execute"',
                 'to every worker of the round', 'names the unit and each added file',
                 'to the files to change in each later rerun call of that unit', 'as their source')
        # the coder's file list is built in build.md, which every later rerun reads (changes.md may no longer be in context)
        build = (L1 / 'phases' / 'build.md').read_text(encoding='utf-8')
        step = build[build.index('## 3A Execute'):build.index('## Workflow rules')]
        passed = next(l for l in step.splitlines() if l.startswith('   - Pass:'))
        self.has(passed, 'The files to change include those a `Scope change:` line under `## Approval` of `plan.md` adds for that unit',
                 'name that line as their source')
        self.assertLess(len(build), 12700)

    def test_plan_findings_revise(self):
        """Criterion 6."""
        revise = self.item('`Revise this task`')
        self.has(revise, '"Revise this task" above, items 1–7', '② Plan', '① Define', 'every gate again',
                 '`archive/<time>-rev<new rev>/review.md`', 'as the change request',
                 'severity and `path:line`, no explanation', 'all open items for `Rework: fix all open items`',
                 'the shortfalls the person named in their own words', 'as written', '`## Revisions` line',
                 '`<what changed>`', 'No `back-execute.py`')
        # phases/plan.md recognizes the case by these words, also after compaction or `continue`
        self.has(revise, 'Write `plan finding`, the sent-back locations and those shortfalls')
        step = self.plan[self.plan.index('## 2A Plan'):self.plan.index('3. Sections `plan.md` must have')]
        line = next(l for l in step.splitlines() if l.startswith('2. Hand it to `my-agent:architect`'))
        rest = step[step.index(line):]
        self.has(rest, 'plan-finding `Revise this task`', 'as the change request',
                 'archived `review.md` path', 'finding locations (locations only)',
                 'shortfalls the person named in their own words', "`## Revisions` line",
                 'changes.md "Plan findings (Review)"')

    def test_plan_findings_fix_within_plan(self):
        """Criterion 7."""
        self.has(self.item('`Fix within current plan`'), 'as a round without a `[plan]` finding',
                 'small fix (item 3)', 'light path (item 7)', '"Back to Execute"')

    def test_gates_plan_item_line_and_rework_line(self):
        """Criterion 8."""
        sec = self.gates[self.gates.index('- **G3 with open review items.**'):self.gates.index('## E escalation')]
        lines = sec.splitlines()
        line = next(l for l in lines if l.startswith('  - ') and '[plan]' in l)
        self.has(line, 'open `[plan]` item', 'keeps the mark', 'plain line', 'Rework sending it back',
                 'first gets the plan-finding popup', 'before any fix', 'changes.md "Plan findings (Review)"')
        previous = lines[lines.index(line) - 1]
        self.assertTrue(previous.startswith('  - On `Rework: fix all open items`'), previous)
        # the ordered "Popup text" list places the line last among the explanation lines, after the Rework line
        order = next(l for l in self.gates.splitlines() if l.startswith('  3. Explanation lines'))
        self.has(order, 'The plan-finding line (below) comes last.')
        self.assertLess(order.index('`Rework: fix all open items` line'), order.index('plan-finding line'))

    def test_trimmed_sentences_keep_their_meaning(self):
        """Criterion 11: shortening for the size limits keeps what a sentence says and why."""
        self.has(self.gates, 'At G3 show it too (see delegated approval).',
                 "The Report tab's 한국어 mode shows the copy (English where not current).")
        self.has(self.accept, '`Run:` is not that count: it also goes up after a PASS.',
                 'items 1 and 2 (the step line is written; base point, uncommitted-changes popup)')

    def test_plan_findings_mixed_round(self):
        """Exception: marked and unmarked findings in one round."""
        self.has(self.item('The popup'), 'one per round')
        self.has(self.item('Scope of the answer'), 'the whole round', 'unmarked findings included')
        self.has(self.item('`Revise this task`'), 'the unmarked ones included')

    def test_plan_findings_not_sent_back(self):
        """Exception: a marked item that is not sent back."""
        self.has(self.item('When'), 'not sent back (taken, or not picked) gets no popup and stays an open item',
                 'in their own words carries no mark')

    def test_plan_findings_define_route(self):
        """Exception: the fix changes WHAT/WHY."""
        line = next(l for l in self.item('`Revise this task`').splitlines() if '① Define when' in l)
        self.has(line, 'purpose, completion criteria, non-goals, constraints or exception cases change')

    def test_plan_findings_fourth_revision(self):
        """Exception: a 4th revision."""
        self.assertIn('  7. If this is the 4th revision of the same task, popup before starting it: '
                      '`Keep revising (Recommended)` / `Restart as a new task` / `Abort`.', self.changes)
        self.has(self.item('4th revision'), 'before a 4th revision (Revise item 7) still applies')

    def test_plan_findings_delegated_on(self):
        """Exception: delegated approval on."""
        sec = self.item('Delegated approval')
        self.has(sec, 'L1 answers with the recommended choice, `Revise this task` included',
                 'one round of the loop it came from', 'Review BLOCKER loop', 'G3 fix loop',
                 'L1 answered `Rework: fix all open items`', '`Revise this task` restarts neither count',
                 'no new cap')

    def test_plan_findings_delegated_off(self):
        """Exception: delegated approval off."""
        self.has(self.item('Delegated approval'), 'When it is off, the settled-popup rule')

    def test_plan_findings_same_finding_back(self):
        """Exception: the same marked finding comes back."""
        self.has(self.item('The same finding comes back'), 'same severity and location',
                 '`Fix within current plan` or `Adjust within approved scope`', 'the popup is asked again',
                 'not settled', 'the person is asked unless delegated approval is on')

    def test_plan_findings_choice_cannot_add_unit(self):
        """Exception: the earlier choice could not add the unit or the approach."""
        self.has(self.item('The same finding comes back'),
                 'could not add the unit or the approach', 'recommend `Revise this task`')

    def test_plan_findings_other_answer(self):
        """Exception: an Other-field answer or a question back."""
        self.has(self.item('Other answers'), 'Other field', 'question back', '"Question rules"')

    def test_l1_files_within_limit_after_route(self):
        """Criterion 11."""
        for text in (self.accept, (L1 / 'profiles' / 'dev.md').read_text(encoding='utf-8'), self.changes, self.plan):
            self.assertLess(len(text), 12700)
        self.assertLessEqual(len(self.gates), 12550)
        self.assertLessEqual(len(SKILL.read_text(encoding='utf-8')), SKILL_CHARS)


class TaskDirRulesTest(unittest.TestCase):
    """The rule texts say <task_dir>, resolved once at Intake, never the literal records folder."""
    MONITOR_SKILL = REPO / 'skills' / 'monitor' / 'SKILL.md'
    AGENTS = [REPO / 'l2-design-judge' / 'agents' / 'architect.md'] + [REPO / 'l3-workers' / 'agents' / f'{n}.md' for n in ('coder', 'researcher', 'writer')]
    TASK_SCRIPTS = ('run-log', 'usage-snapshot', 'gate-report', 'monitor-up')

    def spans(self, path, scripts):
        text = path.read_text(encoding='utf-8')
        for m in re.finditer(r'`(python3 "\$\{CLAUDE_PLUGIN_ROOT\}/[^"`]*/(%s)\.py"[^`\n]*)`' % '|'.join(scripts), text):
            yield m.group(2), m.group(1)

    def test_task_scripts_carry_task_dir(self):
        seen = 0
        for path in [SKILL, self.MONITOR_SKILL] + L1_FILES:
            for script, cmd in self.spans(path, self.TASK_SCRIPTS):
                seen += 1
                self.assertIn('--task-dir', cmd, f'{path.name}: {cmd}')
                self.assertLess(cmd.index('--data-dir'), cmd.index('--task-dir'), f'{path.name}: {cmd}')
            for script, cmd in self.spans(path, ('feedback',)):
                self.assertNotIn('--task-dir', cmd, f'{path.name}: {cmd}')
        self.assertGreaterEqual(seen, 30)

    def test_task_dir_placeholder_single_quoted(self):
        for path in (SKILL, self.MONITOR_SKILL):
            text = path.read_text(encoding='utf-8')
            self.assertIn('${user_config.task_dir}', text, path.name)
            for m in re.finditer(r'.{0,1}\$\{user_config\.task_dir\}.{0,1}', text):
                self.assertEqual(m.group(0), "'${user_config.task_dir}'", path.name)

    def test_no_fixed_records_folder(self):
        for path in [SKILL, self.MONITOR_SKILL] + L1_FILES + self.AGENTS:
            self.assertNotIn('docs/agent', path.read_text(encoding='utf-8'), path.name)
        text = PROCEDURES['new-task'].read_text(encoding='utf-8')
        i = text.index('11. **Report:**')
        self.assertIn('Task folder: <task_dir>', text[i:text.index('\n', i)])

    def test_monitor_skill_names_mismatch_case(self):
        self.assertIn('(task folder mismatch', self.MONITOR_SKILL.read_text(encoding='utf-8'))


class StepIdRulesTest(unittest.TestCase):
    """2026-11-25: the rules name the steps by their IDs (1A-4B) and the gates G1-A/G1-B."""
    FILES = [SKILL] + ONE_READ + [L1 / 'hosts-antigravity.md']
    NAMES = r'(Intake|Explore|Background research|Plan|Execute|Merge|Verify|Review)'
    NUMERIC = [re.compile(r'^#+ [1-8][a-z]?\. ', re.M), re.compile(r'\b[Ss]teps? [1-8]\b(?![AB])'),
               re.compile(r'(?<![\w.–-])[1-8][ab]? ' + NAMES + r'\b(?! FAIL)'), re.compile(r'(?<![a-z])n=<?[1-8](?![0-9AB])'),
               re.compile(r'\b2b\b'), re.compile(r'[Ss]tep names?: [1-8]\b'),
               re.compile(r'(?<![\w.–-])[1-8] `' + NAMES)]

    def test_no_old_gate_names(self):
        for path in self.FILES:
            self.assertIsNone(re.search(r'\bG1[ab]\b', path.read_text(encoding='utf-8')), path.name)

    def test_no_numeric_step_headings_or_references(self):
        for path in self.FILES:
            text = path.read_text(encoding='utf-8')
            for pattern in self.NUMERIC:
                m = pattern.search(text)
                self.assertIsNone(m, '%s: %r' % (path.name, m and text[max(0, m.start() - 30):m.end() + 10]))

    def test_run_log_step_templates_are_lettered(self):
        found = 0
        for path in self.FILES:
            for args in TEMPLATE.findall(path.read_text(encoding='utf-8')):
                if args.startswith('step '):
                    found += 1
                    self.assertRegex(args, r'^step n=([1-4][AB]|<1A–4B>) ', path.name)
        self.assertGreaterEqual(found, 8)

    def test_step_id_headings(self):
        heads = {p: re.findall(r'^#{1,2} .+$', (L1 / 'phases' / f'{p}.md').read_text(encoding='utf-8'), re.M)
                 for p in ('define', 'plan', 'build', 'accept')}
        self.assertEqual(heads['accept'][:2], ['# ④ Accept: 4A Verify · 4B Review → G3', '## 4A Verify'])
        self.assertIn('## 4B Review → Deliver', heads['accept'])
        self.assertIn('## 3A Execute', heads['build'])
        self.assertIn('## 3B Merge', heads['build'])
        self.assertIn('## 2A Plan', heads['plan'])
        self.assertIn('## 2B Plan Review', heads['plan'])
        self.assertIn('## G1-B plan approval', heads['plan'])
        self.assertIn('## 1B Explore → Scope', heads['define'])
        self.assertIn('## Background research', heads['define'])

    def test_sizes(self):
        self.assertLessEqual(len(SKILL.read_text(encoding='utf-8')), SKILL_CHARS)
        for path in ONE_READ + [L1 / 'hosts-antigravity.md']:
            self.assertLessEqual(len(path.read_text(encoding='utf-8')), PROCEDURE_CHARS, path.name)


if __name__ == '__main__':
    unittest.main()
