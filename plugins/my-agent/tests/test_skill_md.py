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
# The whole skill. Measured on Opus 5.5 (2026-11-10): 2.6 characters per token, so this is about 4,800 tokens. After
# compaction Claude Code 2.1.322 re-attaches the first 5,000 estimated tokens, counted as 20,000 characters.
SKILL_CHARS = 12500
# One rule file is one read. A size class, not a proof: in recorded Codex sessions the model set a 5,000-token
# output budget on the read command, and `recorder.md` (the densest file) measured 4,749 tokens at 11,024 characters
# (2.32 characters per token), so 11,500 characters stay under 5,000 tokens at that density. It holds for every file
# L1 reads in one go: the procedure files, the phase and profile files and `hosts.md` (2026-11-16: `accept.md` had
# grown to 18,473 characters).
PROCEDURE_CHARS = 11500
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

    def test_no_skill_dir_variable(self):
        """The main skill lives in skills/my-agent/: its paths start from the plugin root, never from the skill folder."""
        self.assertNotIn('CLAUDE_SKILL_DIR', self.text)

    def test_no_hooks_in_frontmatter(self):
        """The gate hooks moved to hooks.json (a skill hook gets no plugin setting env): none left in the frontmatter."""
        block = re.match(r'---\n(.*?)\n---\n', self.text, re.S).group(1)
        self.assertNotIn('hooks:', block)
        self.assertNotIn('plan-approved-check.py', block)
        self.assertNotIn('verdict-fresh-check.py', block)

    def test_approval_line_written_without_substitution(self):
        """Live run: L1 wrote the Approved line with `$(date …)` and the G1b hook (rightly) refused it."""
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
                filled = args.replace('<task_dir>', rel())
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
            if args.startswith('answer') and re.search(r'gate=(G1a|G1b|G3|E|Q)\b', args):
                self.assertIn('choice=', args, f'{name}: {args}')

    def test_every_ask_carries_rec(self):
        """Criterion 4: each `ask gate=` in SKILL.md and the L1 files (template or backticked prose) records rec=."""
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
        self.assertGreaterEqual(len(found), 5)
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp).resolve() / 'proj'
            make_task(proj)
            argv = ['ask', 'gate=G3', 'q=x', 'rec=x', '--task-dir', rel()]
            r = subprocess.run([sys.executable, str(L4 / 'scripts' / 'run-log.py'), *argv, '--cwd', str(proj)],
                               capture_output=True, text=True, env={'MA_TASKS_DIR': tmp, 'MA_TASK_DIR': rel(), 'PATH': '/usr/bin:/bin'})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_revision_edits_use_headings_and_edit_tool(self):
        """Criterion 1: sections are found by a line-start heading and edited with Edit, never cut by offset or overwritten."""
        section = self.section('## In-flight revision', '## Abort', self.changes)
        self.assertIn('headings that start at the beginning of a line (`## Revisions`, `## Approval`)', section)
        self.assertIn('edit only that section with the Edit tool', section)
        self.assertIn('do not overwrite the whole file with Write', section)

    def test_defer_manual_check_scope_change(self):
        """Criterion 2."""
        self.assertIn('Scope change: criterion <n> is checked by the user later', self.changes)

    def test_continue_cleans_active_when_done(self):
        """Criteria 3 and 7: a retrospective cut short leaves Status: done; continue only clears .active."""
        section = self.section('## continue', None, self.resume)
        self.assertIn('Status: done', section)
        self.assertIn('only `.active` cleared', section)
        self.assertIn('`<data folder>/active-index.json`', section)

    def test_l2_row_lists_manifest_agents(self):
        import json
        manifest = json.loads((REPO / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))
        names = [Path(a).stem for a in manifest['agents'] if '/l2-design-judge/' in a]
        row = next(l for l in self.text.splitlines() if l.startswith('| L2 |'))
        for name in names:
            self.assertIn(name, row)

    def test_retrospective_order(self):
        """Criterion 7: tally -> gate-analyst -> copy -> chat -> feedback add L1; before the .active cleanup on both accept paths."""
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

    # --- Plan Review rounds, L1 plan edits, profile change (task 261029-review-loop-l1-rules, u4) ---
    PLAN = L1 / 'phases' / 'plan.md'

    def plan_step4(self):
        plan = self.PLAN.read_text(encoding='utf-8')
        return plan[plan.index('## 4. Plan Review'):plan.index('## G1b plan approval')]

    def test_nitpick_only_applied_without_popup(self):
        """Criterion 2: NITPICK only -> applied without a popup, one `## Decisions` line each, then G1b."""
        step = self.plan_step4()
        self.assertIn('NITPICK only', step)
        self.assertIn('without a popup', step)
        self.assertIn('- <severity> <path>:<line> <summary> → applied by L1 | applied by architect | declined', step)

    def test_no_plan_review_round_after_ready(self):
        """Criterion 1: READY FOR APPROVAL never leads to another Plan Review round; only REVISE is judged again."""
        step = self.plan_step4()
        self.assertIn('never another Plan Review round', step)
        self.assertIn('third `REVISE`', step)
        self.assertIn('Apply all (Recommended)', step)
        self.assertIn('whole list (NITPICKs included)', step)

    def test_l1_plan_edit_rules(self):
        """Criterion 3: small plan.md edits by L1 before G1b, recorded as `fix ... before=G1b` with an archive."""
        step = self.plan_step4()
        self.assertIn('before=G1b archive=', step)
        plan = self.PLAN.read_text(encoding='utf-8')
        g1b = plan[plan.index('## G1b plan approval'):]
        self.assertIn('Applied after Plan Review', g1b)
        self.assertIn('small', g1b[g1b.index('**Request changes:**'):])
        row = next(l for l in self.text.splitlines() if l.startswith('| L1 |'))
        self.assertIn('plan.md', row)
        section = plan[plan.index('## Rewrite before approval'):]
        self.assertIn('L1 edit', section)
        self.assertIn('Plan Review again only after a BLOCKER fix', section)
        self.assertIn('| Plan edit by L1 before approval', self.recorder)

    def test_profile_label_from_profile_line(self):
        """Criterion 5: the label is (set by you) also when the run-log has a `profile` line."""
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
        self.assertTrue(any('before=G1b' in a for a in found))
        self.assertLessEqual({'profile', 'fix'}, kinds)

    def test_auto_flag_rules(self):
        """Criterion 6: `--auto` rules in ## Arguments, Flags and Intake."""
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
        """Criterion 6: never G2, G3, E, the third-REVISE G1b popup or a popup without a recommendation; state from the last line."""
        head = self.text[:self.text.index('## Arguments')]
        sec = head[head.index('### Delegated approval'):]
        sec = sec[:sec.index('\n### ', 5)] if '\n### ' in sec[5:] else sec
        self.assertIn('read `gates.md` "Delegated approval details"', sec)   # needed before the first gate too
        for word in ('G2', 'G3', 'E', 'third `REVISE`', 'without a recommended choice', 'by=L1',
                     '(answered by L1)', 'last `delegate` line', 'Turn on (Recommended)', 'Keep asking me',
                     'delegate state=off how=person', 'delegate state=off how=end'):
            self.assertIn(word, sec, word)
        self.assertLess(self.text.index('### Delegated approval'), self.text.index('## Arguments'))

    def test_loop_cap_section(self):
        """Criterion 9: a 5-round cap per loop; the lower caps stay."""
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
        self.assertIn('always to the person', accept)
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
        self.assertIn('each message re-reads the whole conversation', tools)
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
        self.assertIn('do this instead of `accept.md` step 8 items 4–6', self.dev_g3())
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
            sections = re.split(r', (?![^(]*\))', rows[f'{name}.md'][2])   # "Intake (step 1, Router)" is one name
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
        """Criterion 10: the Inline role bullet sits in the core rules and names the folders, the line and the no-run case."""
        i = self.text.index('- **Inline role:**')
        bullet = self.text[i:self.text.index('\n', i)]
        self.assertLess(i + len(bullet), self.text.index('## Arguments'))
        for word in ('l2-design-judge/agents/', 'l3-workers/agents/', '`inline`', 'Skipped:', 'pass=inline'):
            self.assertIn(word, bullet, word)
        self.assertNotIn('Codex', bullet)
        self.assertIn('inline', run_log_kinds())
        self.assertIn('run-log.py" inline agent=my-agent:<role>', self.recorder)

    def test_working_files_in_english(self):
        """Criterion 4: working files in English; the person sees their own language (L1 translates when it shows one)."""
        rules = self.text[self.text.index('### Question rules'):self.text.index('## Arguments')]
        for word in ('`scope.md`', '`## Decisions`', 'in English', 'translates a working file when it shows it'):
            self.assertIn(word, rules, word)

    # --- data folder (task 261028-data-dir-config, u3) ---
    DATA_SCRIPTS = ('run-log', 'usage-snapshot', 'gate-report', 'feedback', 'monitor-up', 'open-html', 'intake')
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

    def test_intake_popup_recommends_current_folder(self):
        self.assertIn('`Current folder (Recommended)` / `<data folder>` / `Other path`', self.new_task)
        self.assertNotIn('`<data folder> (Recommended)`', self.new_task)
        self.assertIn('Popup every time, also inside a git repository', self.intake_item(2))
        self.assertNotIn('do not ask', self.intake_item(2))
        self.assertIn('"Commit the task log? The essential information goes into docs/blueprint, so committing it is not recommended."',
                      self.intake_item(5))

    # --- apply open feedback (task 261101-apply-open-feedback, u1) ---
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

    # --- codex review fixes (task 261104-codex-review-fixes, u6) ---
    def test_intake_items_in_order(self):
        section = self.section('## Intake (step 1, Router)', None, self.new_task)
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
                     'the G1b hook asks for a relative path after `cd`',
                     'An aborted task is not resumed with `continue`',
                     'separators inside quotes',
                     'A command with the word `git` but no such shape'):
            self.assertNotIn(gone, self.rules)
        for kept in ('write `Follows:`', 'the verdict hook cannot tell whether it is a commit',
                     'run `git rev-parse HEAD` first', 'follow "Tool choice"'):
            self.assertIn(kept, self.rules)
        row = next(l for l in self.text.splitlines() if l.startswith('| L4 |'))
        self.assertIn('the monitor and the G2 dialog are outside the levels', row)

    def test_tool_choice_rule(self):
        self.assertLess(self.text.index('### Tool choice'), self.text.index('## Arguments'))
        rule = self.section('### Tool choice', '### Change requests')
        for word in ('Read', 'Grep', 'Glob', 'Edit', 'Write', 'one command per call', '`sed -i`', '`$(`',
                     'unittest discover -s'):
            self.assertIn(word, rule, word)
        self.assertNotIn('plan-approved-check.py', rule)

    def test_question_rules_popup_topics(self):
        rules = self.section('### Question rules', '### Gates')
        for word in ('one popup per topic', 'plain explanation', 'multi-select', 'Popup bodies'):
            self.assertIn(word, rules, word)

    def test_intake_worktree_and_gitignore_rules(self):
        self.assertIn('`New task in a worktree`', self.intake_item(1))
        self.assertIn('gitignore:', self.intake_item(5))
        self.assertIn('("Task worktree" in `changes.md`)', self.intake_item(1))
        self.assertNotIn('## Task worktree', self.new_task)   # moved to changes.md on 2026-11-16
        section = self.section('## Task worktree', None, self.changes)
        for word in ('my-agent-task/', 'git worktree add', 'task ID'):
            self.assertIn(word, section, word)
        self.assertIn('`New task in a worktree` (Intake item 1)', self.changes.split('\n## ')[0])
        self.assertLessEqual(len(self.new_task), 10500)
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

    def test_flags_em_dash(self):
        for flags in (self.section('**Flags:**', None), self.section('## Flags', '## Intake', self.new_task)):
            self.assertIn('em dash', flags)
            self.assertIn('`—dev`', flags)

    def test_cost_row_baseline_and_moments(self):
        row = next(l for l in self.recorder.splitlines() if l.startswith('|') and 'run-log.py" cost' in l)
        for word in ('baseline=1', 'Right before the G3 popup', '`n=3`', '`n=5` (also Back to Execute)', '`n=7`',
                     'L1 runs nothing then'):
            self.assertIn(word, row, word)

    def test_failure_row_structural_argument(self):
        row = next(l for l in self.recorder.splitlines() if l.startswith('| Verify FAIL 1–2 times'))
        self.assertIn('structural argument', row)

    def test_gate_reports_section(self):
        section = self.section('## Gate reports', None, self.gates)
        for word in ('### Details', 'first two rows', 'G1a', 'G1b', 'G3', 'E', '--report', '--pointer', 'Report:',
                     'task folder', 'no harness tool'):
            self.assertIn(word, section, word)
        self.assertLess(self.gates.index('## Check before anything leaves'), self.gates.index('## Gate reports'))

    def phase(self, name):
        return (L1 / 'phases' / f'{name}.md').read_text(encoding='utf-8')

    def dev_g3(self):
        dev = (L1 / 'profiles' / 'dev.md').read_text(encoding='utf-8')
        return dev[dev.index('## G3 in the dev profile'):dev.index('## Agents used')]

    def test_korean_copy_before_each_gate(self):
        """261106 criterion 5: for a Korean request L1 refreshes report-ko.json before G1a, G1b and G3."""
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
            for word in ('Gate reports', '### Overview', '### Takeaway', '--report', '--pointer', 'pointer line'):
                self.assertIn(word, part)
            self.assertNotIn('--url', part)
            self.assertNotIn('### Details', part)
        for word in ('Commit message', 'Diff', '+<a>/-<b>'):
            self.assertIn(word, dev)
        self.assertNotIn('the main diffs', dev)
        self.assertIn('Gate reports', esc)
        self.assertIn('### Details', esc)
        self.assertIn('scripts/archive.py" --task', accept)   # Back to Execute archives with the script, not cp and cmp

    def test_accept_popup_bodies(self):
        accept = self.phase('accept')
        dev = self.dev_g3()
        for part in (accept, dev):
            self.assertIn('SHOULD-FIX and NITPICK items of `review.md`', part)
        self.assertIn('Verify FAIL x<n>: criterion <n> <one-line reason>', self.section('## E escalation', None, self.gates))
        self.assertIn('then the retrospective', dev)
        self.assertIn('separate action', dev)

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
        verify = accept[accept.index('## 7. Verify'):accept.index('## Back to Execute')]
        self.assertNotIn(cmd, verify)   # the step line that opens the phase writes the cost line itself (2026-11-16)
        self.assertIn('the script writes the `cost` line of the moment itself', verify)
        general = accept[accept.index('5. **G3 popup:**'):accept.index('6. **Accept:**')]
        devp = self.dev_g3()
        dev = devp[devp.index('3. Record before and after the popup.'):devp.index('4. **Commit:**')]
        for part in (general, dev):
            self.assertIn('right before the G3 popup', part)
            self.assertLess(part.index(cmd), part.index('ask gate=G3'))

    def test_build_prototype_and_worktree_session(self):
        build = self.phase('build')
        self.assertIn('prototype/index.html', build)
        self.assertIn('--git-common-dir', build)
        self.assertIn('every unit in sequence', build)

    def test_dev_merge_row_output_and_copy_fallback(self):
        dev = (L1 / 'profiles' / 'dev.md').read_text(encoding='utf-8')
        merge = next(l for l in dev.splitlines() if l.startswith('| 6 Merge'))
        self.assertIn('--output=', merge)
        self.assertIn('cp -p', merge)
        self.assertIn('cmp', merge)
        self.assertNotIn('\\|', merge)
        execute = next(l for l in dev.splitlines() if l.startswith('| 5 Execute'))
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


    # --- agent model presets and report-style gate reports (task 261101-agent-model-config-report-b, u5) ---
    def test_intake_models_preset(self):
        """Criterion 3: Intake item 3 asks the preset only with 2 or more presets; item 7 and 10 carry it."""
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
        """Criterion 3: a profile change at the first gate asks the preset again with the Intake popup rule."""
        section = self.section('## In-flight revision', 'When a message that looks like a revision', self.changes)
        bullet = section[section.index('**Profile change at the first gate'):]
        for word in ('presets --profile <new profile>', 'same popup rule as Intake item 3', '`Models:` in `intake.md`',
                     'run-log.py" models preset=<name> source=file'):
            self.assertIn(word, bullet, word)

    def test_continue_checks_models_preset(self):
        """Criterion 3: continue shows the preset again; a preset that is gone falls back to the definition values."""
        sec = self.section('## continue', None, self.resume)
        for word in ('`Models:`', 'show --profile <p> --preset <name>', 'exits 1', 'definition values'):
            self.assertIn(word, sec, word)

    def test_delegation_passes_only_differing_fields(self):
        """Criterion 4: model/effort come from the preset; only the pass= fields are passed; the opus retry beats it."""
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
        """Criterion 13: G1a and G1b open with Overview and Takeaway before the table; G1b has a Models row."""
        sec = self.section('## Gate reports', None, self.gates)
        for word in ('### Overview', '### Takeaway', 'G1a', 'G1b', 'scope summary', 'plan summary', '`Models` row',
                     '`Request changes`', '`Approve`'):
            self.assertIn(word, sec, word)
        self.assertLess(sec.index('### Overview'), sec.index('### Takeaway'))
        self.assertLess(sec.index('### Takeaway'), sec.index('`| Item | Value |`'))

    def test_gate_reports_prototype_opened_locally(self):
        """Criterion 13: the prototype is a local file opened by open-html.py; the line replaces the full mock-up at G1b."""
        sec = self.section('## Gate reports', None, self.gates)
        for word in ('open-html.py', 'prototype/index.html', '--data-dir', 'opened in the browser', 'not opened',
                     '`failed:`', 'remade only when the mock-up changed', 'not published anywhere',
                     'skills/mock-up', 'capture.sh'):
            self.assertIn(word, sec, word)
        self.assertNotIn('--task-dir', ' '.join(c for s, c in self.command_spans(PROCEDURES['gates']) if s == 'open-html'))

    def test_gate_reports_open_report_tab(self):
        """Criterion 7: the gate report is read on the Report tab; the chat keeps a pointer line."""
        sec = self.section('## Gate reports', None, self.gates)
        for word in ('`ask` line', 'Commit message', 'Diff', '+<a>/-<b>', 'Save path',
                     'the full diff is not printed', 'Report: not opened (<reason>); task folder: <absolute task folder>',
                     '(opened in the browser: <window|tab>)', '(not opened: no browser opened; open it yourself)',
                     '(not opened: report_open is off; open it yourself)', 'report_open'):
            self.assertIn(word, sec, word)
        self.assertLess(sec.index('`ask` line'), sec.index('--report'))
        # one call: the script opens the tab and prints the pointer line, so the rule has no cases to tell apart
        self.assertIn('--report "<absolute task folder>" --pointer --data-dir "<data folder>"', sec)
        self.assertIn('the line the `--pointer` call printed, as it is', sec)
        self.assertNotIn('--url', sec)

    def test_g1b_row_opens_report_tab(self):
        row = next(l for l in self.text.splitlines() if l.startswith('| G1b Plan approval'))
        self.assertNotIn('full mock-up', row)
        self.assertIn("after opening the task's Report tab", row)

    def test_open_html_spans_carry_data_dir_only(self):
        spans = [c for s, c in self.command_spans(PROCEDURES['gates']) if s == 'open-html']
        self.assertTrue(spans)
        for cmd in spans:
            self.assertIn('--data-dir', cmd)
            self.assertNotIn('--task-dir', cmd)

    def test_no_artifact_publishing(self):
        """Criterion 13: no stale publishing wording in the gate reports or the leave check."""
        gate = self.section('## Gate reports', None, self.gates)
        leave = self.section('## Check before anything leaves', '## Gate reports', self.gates)
        for part in (gate, leave):
            for phrase in ('private artifact', 'artifact link', 'publishes it', 'publishing a prototype', 'claude.ai'):
                self.assertNotIn(phrase, part, phrase)
        self.assertNotIn('prototype', leave)
        self.assertNotIn('artifact', leave)
        self.assertIn('copying the deliverable after G3', leave)
        self.assertIn('committing', leave)


if __name__ == '__main__':
    unittest.main()


class TaskDirRulesTest(unittest.TestCase):
    """Criterion 5: the rule texts say <task_dir>, resolved once at Intake, never the literal records folder."""
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
