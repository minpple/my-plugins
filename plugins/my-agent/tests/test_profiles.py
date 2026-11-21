"""Profiles under l1-orchestration/profiles/ and the Router's choice (architecture 4.3, 4.13 "judge checks")."""
import json
import re
import unittest

from helpers import REPO

PROFILES = REPO / 'l1-orchestration' / 'profiles'
SKILL = REPO / 'skills' / 'my-agent' / 'SKILL.md'
NEW_TASK = REPO / 'l1-orchestration' / 'new-task.md'   # Flags and Intake (SKILL.md "Procedure files")
FIXTURES = REPO / 'tests' / 'judge-fixtures'


class ProfilesTest(unittest.TestCase):
    def test_profiles_exist(self):
        for name in ('general', 'research', 'dev'):
            self.assertTrue((PROFILES / f'{name}.md').is_file(), name)

    def test_derived_files_and_absolute_paths(self):
        for name in ('build', 'dev'):
            path = (REPO / 'l1-orchestration' / 'phases' / 'build.md') if name == 'build' else PROFILES / 'dev.md'
            self.assertIn('derived files', path.read_text(encoding='utf-8'), name)
        for name, phrase in (('general', 'absolute path'), ('research', 'absolute path')):
            self.assertIn(phrase, (PROFILES / f'{name}.md').read_text(encoding='utf-8'), name)

    def test_router_names_every_profile(self):
        text = SKILL.read_text(encoding='utf-8')
        for name in ('general', 'research', 'dev'):
            self.assertIn(f'${{CLAUDE_PLUGIN_ROOT}}/l1-orchestration/profiles/{name}.md', text)
            self.assertRegex(NEW_TASK.read_text(encoding='utf-8'), rf'`{name}`')
        self.assertIn('Profile: <', NEW_TASK.read_text(encoding='utf-8'))

    def test_build_passes_result_path_only_to_writer_and_researcher(self):
        build = (REPO / 'l1-orchestration' / 'phases' / 'build.md').read_text(encoding='utf-8')
        self.assertIn('for a writer or researcher unit the result path', build)
        self.assertIn('A coder unit gets the files to change, not a result path', build)
        self.assertIn('`end=ok`', build)

    def test_build_workflow_result_rules_limit_result_files_to_writer_and_researcher(self):
        build = (REPO / 'l1-orchestration' / 'phases' / 'build.md').read_text(encoding='utf-8')
        rules = build.split('## Workflow rules')[1].split('## 6. Merge')[0]
        self.assertIn('Result files (writer and researcher units only) go to `work/`', rules)
        self.assertIn('a coder unit has no result file', rules)
        self.assertIn('missing result files of writer and researcher units', rules)
        self.assertIn('`end=ok`', rules)

    def test_research_rules_present(self):
        text = (PROFILES / 'research.md').read_text(encoding='utf-8')
        for word in ('Questions', 'Scope', 'Source criteria', 'Deliverable format', 'G1a', 'claim · source URL · quote', 'sub-questions',
                     'synthesis structure', 'sample paragraph', 'source bias', 'scope gaps', 'my-agent:researcher', 'my-agent:writer',
                     'deliverable/'):
            self.assertIn(word, text, word)
        self.assertRegex(text, r'Plan Review \| not skipped')

    def test_dev_rules_present(self):
        text = (PROFILES / 'dev.md').read_text(encoding='utf-8')
        for word in ('purpose and users', 'Completion criteria', 'hard constraints', 'exception cases', 'data', 'non-goals', 'UX preferences', 'G1a',
                     'small task', '3 files', 'SKIPPED small task', '`isolation: "worktree"`', 'first parallel group', 'base commit=',
                     'User cleans up first (Recommended)', 'Proceed as is', '`Run:`', 'git diff', 'git status',
                     'Commit (Recommended)', 'Rework', 'completion criterion number', '## Decisions', 'git apply'):
            self.assertIn(word, text, word)
        build = (REPO / 'l1-orchestration' / 'phases' / 'build.md').read_text(encoding='utf-8')
        self.assertIn('User cleans up first (Recommended)', build)
        self.assertIn('Popup: `Commit (Recommended)` / `Rework` / `Abort`', text)
        self.assertIn('deliver path=commit:', text)

    def test_dev_g3_points_to_delegated_approval_details(self):
        """Under delegated approval L1 answers G3 by gates.md; without it the Commit popup is unchanged."""
        text = (PROFILES / 'dev.md').read_text(encoding='utf-8')
        g3 = text[text.index('## G3 in the dev profile'):]
        self.assertNotIn('G3 always goes to the person', g3)
        self.assertIn('L1 answers per gates.md "Delegated approval details"', g3)
        self.assertIn('Popup: `Commit (Recommended)` / `Rework` / `Abort`', g3)

    def test_remote_take(self):
        """Q41: the dev G3 popup offers a take that brings the remote default branch up to the commit."""
        dev = (PROFILES / 'dev.md').read_text(encoding='utf-8')
        g3 = dev[dev.index('## G3 in the dev profile'):dev.index('## Upstream check')]
        self.assertIn('Remote take: read retro.md "Remote update" before this popup', g3)
        self.assertIn('On a remote take do retro.md "Remote update" now', g3)
        self.assertNotIn('any push is a separate action', dev)
        retro = (REPO / 'l1-orchestration' / 'retro.md').read_text(encoding='utf-8')
        self.assertLess(retro.index('## Remote update'), retro.index('## Retrospective'))
        remote = retro[retro.index('## Remote update'):retro.index('## Retrospective')]
        for text in ('git symbolic-ref --short refs/remotes/origin/HEAD', '`Commit and push`',
                     '`Commit and merge into <default branch>`', '`Commit` stays the recommended take',
                     'under delegated approval L1 never answers with a remote take',
                     '`Commit` / `<remote take>` / `Rework: fix all open items` / `Abort`', 'choice=Rework other=1',
                     'git rev-list --count HEAD..origin/<default branch>', '`git push origin HEAD:<default branch>`',
                     'Count above 0: do not push', 'Never force a push', 'does not undo the commit', 'merge unit=remote'):
            self.assertIn(text, remote, text)
        skill = (REPO / 'skills' / 'my-agent' / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn('| `retro.md` | before the dev G3 popup; after G3 `Accept` or `Commit`, before the retrospective | '
                      'Remote update, Retrospective |', skill)
        gates = (REPO / 'l1-orchestration' / 'gates.md').read_text(encoding='utf-8')
        self.assertIn('dev also: retro.md "Remote update"', gates)

    def test_retro_fixes_2026_11_21(self):
        """From task retrospectives: the review file check, the Rework reason, projects of a check command,
        coder files outside the task records."""
        read = lambda *parts: REPO.joinpath(*parts).read_text(encoding='utf-8')  # noqa: E731
        accept = read('l1-orchestration', 'phases', 'accept.md')
        self.assertIn('Then run the findings command (gates.md "Gate reports"); on `findings: FAIL` (no `review.md`, or one '
                      'older than this call) call a new reviewer once.', accept)
        self.assertIn('G3 Rework: the shortfalls named, with criterion numbers>"', accept)
        self.assertIn('After the Write, Read `review.md` once', read('l2-design-judge', 'agents', 'reviewer.md'))
        self.assertIn('never under `<task_dir>/`', read('l2-design-judge', 'agents', 'architect.md'))
        self.assertIn('none under `<task_dir>/`', read('l2-design-judge', 'agents', 'plan-reviewer.md'))
        explorer = read('l3-workers', 'agents', 'explorer.md')
        self.assertIn('  - <project or target>: pass | fail: <failing tests> | cannot run: <reason>', explorer)
        self.assertIn('several named projects or targets', explorer)
        define = read('l1-orchestration', 'phases', 'define.md')
        self.assertIn('`Run only the projects that run here (Recommended)` / `I fix the environment first` / '
                      '`Judge without this command`', define)
        self.assertIn('every project or target it names, no fewer and no more', read('l2-design-judge', 'agents', 'verifier.md'))
        self.assertIn('Back to Execute reasons', read('l2-design-judge', 'agents', 'gate-analyst.md'))
        self.assertIn('direct-<yymmdd>-<slug>', read('l3-workers', 'blueprint-format.md'))

    def test_retrospective_files_judge_miss_item(self):
        retro = (REPO / 'l1-orchestration' / 'retro.md').read_text(encoding='utf-8').split('## Retrospective', 1)[1]
        for text in ('Judge misses', 'add L2', 'not named'):
            self.assertIn(text, retro)

    def test_judge_fixtures(self):
        expected = json.loads((FIXTURES / 'expected.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(expected.values()).count('FAIL'), 3)
        self.assertIn('PASS', expected.values())
        for note in expected:
            self.assertTrue((FIXTURES / note).is_file(), note)
        self.assertTrue((FIXTURES / 'scope.md').is_file())
        script = (FIXTURES / 'run-judge-check.sh').read_text(encoding='utf-8')
        self.assertIn('my-agent:verifier', script)
        self.assertIn('--max-budget-usd', script)
        self.assertIn('JUDGE OK', script)

    def test_fixture_notes_use_the_note_format(self):
        line = re.compile(r'^- .+ · https?://\S+ · ".+"$|^- Not found: .+$')
        for note in ('note-good.md', 'note-criterion-miss.md', 'note-broken-citation.md'):
            items = [ln for ln in (FIXTURES / note).read_text(encoding='utf-8').splitlines() if ln.startswith('- ')]
            self.assertTrue(items, note)
            for ln in items:
                self.assertRegex(ln, line, note)


    def test_result_location_line_format(self):
        """plan-approved-check reads `- Deliverable location: `<path>`` / `- Save path: `<path>`` to let the deliver write through."""
        general = (PROFILES / 'general.md').read_text(encoding='utf-8')
        research = (PROFILES / 'research.md').read_text(encoding='utf-8')
        self.assertIn('`- Deliverable location: `', general)
        self.assertIn('`- Save path: `', research)

    def test_argument_hint_matches_profiles_and_phases(self):
        text = SKILL.read_text(encoding='utf-8')
        m = re.search(r'^argument-hint: (.+)$', text, re.M)
        self.assertIsNotNone(m)
        hint = m.group(1).strip().strip('\'"')
        flags = set(re.findall(r'--([a-z]+)', hint))
        self.assertEqual(flags, {p.stem for p in PROFILES.glob('*.md')} | {'auto'})
        for phase in (p.stem for p in (REPO / 'l1-orchestration' / 'phases').glob('*.md')):
            self.assertIn(phase, hint)
        self.assertIn('continue', hint)
        self.assertIn('status [all]', hint)

    def test_arguments_table_names_every_flag(self):
        text = SKILL.read_text(encoding='utf-8')
        new_task = NEW_TASK.read_text(encoding='utf-8')
        args = text[text.index('## Arguments'):]
        flags = new_task[new_task.index('## Flags'):new_task.index('## Intake')]
        for p in PROFILES.glob('*.md'):
            self.assertIn(f'--{p.stem}', args)
            self.assertIn(f'--{p.stem}', flags)
        self.assertIn('"Flags" in `new-task.md`', args)
        self.assertIn('Let the Router pick (Recommended)', flags)
        self.assertIn('`Let the Router pick (Recommended)` / `Abort`', flags)
        self.assertIn('`Type the request in Other (Recommended)` / `Abort`', flags)
        intake = new_task[new_task.index('## Intake'):]
        self.assertIn('`Proceed as general (Recommended)` / `Abort`', intake)
        self.assertIn('the flag is ignored', intake)
        self.assertIn('keeps `--dev` as its first word', intake)

    def test_findings_popup_lives_in_plan_phase(self):
        """Plan Review findings are handled the same in every profile: the popup text is in phases/plan.md, not only dev.md."""
        plan = (REPO / 'l1-orchestration' / 'phases' / 'plan.md').read_text(encoding='utf-8')
        self.assertIn('`Apply all (Recommended)` / `Approve without applying` / `Pick myself`', plan)
        dev = (PROFILES / 'dev.md').read_text(encoding='utf-8')
        self.assertNotIn('Apply all (Recommended)', dev)
        for name in ('dev', 'general', 'research'):
            row = next(l for l in (PROFILES / f'{name}.md').read_text(encoding='utf-8').splitlines() if l.startswith('| 4 Plan Review'))
            if name == 'dev':
                self.assertIn('Not skipped (except for a small task)', row)
            else:
                self.assertIn('`plan.md` step 4', row)


    def test_scope_review_before_g1a(self):
        """scope-reviewer judges scope.md in the profiles with G1a, before the Person-check and G1a popups."""
        define = (REPO / 'l1-orchestration' / 'phases' / 'define.md').read_text(encoding='utf-8')
        section = define.split('## Scope Review')[1]
        self.assertIn('`my-agent:scope-reviewer`', section)
        self.assertIn('before the Person-check popups and the G1a popup', section)
        self.assertIn('Not when the profile skips the interview and G1a', section)
        self.assertIn('`Apply all (Recommended)` / `Confirm without applying` / `Pick myself`', section)
        self.assertIn('third `REVISE`', section)
        self.assertIn('do "Scope Review" below', define.split('4. **Confirm the scope:**')[1])
        for name in ('dev', 'research'):
            text = (PROFILES / f'{name}.md').read_text(encoding='utf-8')
            self.assertIn('`define.md` "Scope Review"', text, name)
            self.assertIn('| `my-agent:scope-reviewer` | 2 (before G1a', text, name)
        self.assertIn('skip the Scope interview, Scope Review and G1a', (PROFILES / 'dev.md').read_text(encoding='utf-8'))
        general = (PROFILES / 'general.md').read_text(encoding='utf-8')
        self.assertIn('`define.md` "Scope Review"', general)
        self.assertIn('| `my-agent:scope-reviewer` | 2 (before G1a)', general)
        self.assertNotIn('no Scope Review', general)
        # the small-task exception is shared with dev (Q38)
        self.assertIn('| Small task exception |', general)
        self.assertIn('skip the Scope interview, Scope Review and G1a', general)
        self.assertIn('`SKIPPED small task`', general)
        self.assertIn('2 times: G1b, G3', general)

    def test_merge_copies_new_files_before_apply(self):
        """Criterion 15: new files are copied before `git apply`, then the worktree is removed."""
        dev = (PROFILES / 'dev.md').read_text(encoding='utf-8')
        row = next(l for l in dev.splitlines() if l.startswith('| 6 Merge'))
        a = row.index('ls-files --others --exclude-standard')
        b = row.index('git apply')
        c = row.index('git worktree remove')
        self.assertLess(a, b)
        self.assertLess(b, c)

    def test_check_tags_in_scope_rules(self):
        """Criterion 4: every criterion line gets one check tag; four tag values are named."""
        tags = ('[check: command]', '[check: file]', '[check: URL]', '[check: person]')
        define = (REPO / 'l1-orchestration' / 'phases' / 'define.md').read_text(encoding='utf-8')
        for t in tags:
            self.assertIn(t, define)
        self.assertIn('one check tag', define)
        for name in ('dev', 'general', 'research'):
            row = next(l for l in (PROFILES / f'{name}.md').read_text(encoding='utf-8').splitlines() if l.startswith('| 2 Explore'))
            for t in tags:
                self.assertIn(t, row, name)
            self.assertIn('one check tag', row, name)
        plan = (REPO / 'l1-orchestration' / 'phases' / 'plan.md').read_text(encoding='utf-8')
        line = next(l for l in plan.splitlines() if '`## Completion criteria`' in l)
        self.assertIn('check tag', line)

    def test_person_check_popup(self):
        """Criterion 5: one popup per [check: person] criterion; Scope change lines; G3 lists later ones."""
        phases = REPO / 'l1-orchestration' / 'phases'
        define = (phases / 'define.md').read_text(encoding='utf-8')
        self.assertIn('I check it before G3 and tell you', define)
        self.assertIn('[check: person]', define)
        self.assertIn('How criterion <n> is checked', define)
        accept = (phases / 'accept.md').read_text(encoding='utf-8')
        verify = accept[accept.index('## 7. Verify'):accept.index('## Back to Execute')]
        self.assertIn('Scope change: criterion <n> checked by the person', verify)
        self.assertIn('checked by the user later', verify)
        review = accept[accept.index('## 8. Review'):]
        devp = (REPO / 'l1-orchestration' / 'profiles' / 'dev.md').read_text(encoding='utf-8')
        dev = devp[devp.index('## G3 in the dev profile'):devp.index('## Agents used')]
        for sec in (review, dev):
            self.assertIn('checked by the user later', sec)

    def test_rerun_is_a_new_worker_call_never_a_resume(self):
        """Criterion 6: where units are handed out and sent back, a rerun is a new call, never a resume."""
        phases = REPO / 'l1-orchestration' / 'phases'
        build = (phases / 'build.md').read_text(encoding='utf-8')
        item = build.split('## 5. Execute')[1].split('## Workflow rules')[0]
        self.assertIn('new worker call, never a resume', item)
        self.assertIn('archive/<ts>-run<N>/verify.md', item)
        self.assertIn('failed criterion numbers', item)
        merge = build.split('## 6. Merge')[1]
        self.assertIn('new worker call', merge)
        accept = (phases / 'accept.md').read_text(encoding='utf-8')
        sec = accept.split('## Back to Execute')[1].split('\n## ')[0]
        self.assertIn('new worker call, never a resume', sec)
        self.assertIn('archive folder', sec)
        self.assertIn('failed criterion numbers', sec)

    def test_define_plan_gate_reports_and_prototype(self):
        phases = REPO / 'l1-orchestration' / 'phases'
        define = (phases / 'define.md').read_text(encoding='utf-8')
        plan = (phases / 'plan.md').read_text(encoding='utf-8')
        g1a = define.split('4. **Confirm the scope:**')[1]
        self.assertIn('Gate reports', g1a)
        self.assertNotIn('### Details', g1a)
        interview = define.split('3. **Scope interview:**')[1].split('4. **Confirm the scope:**')[0]
        self.assertIn('Question rules', interview)
        self.assertIn('screen behavior', interview)
        self.assertIn('Prototype before G1a', interview)
        self.assertIn('Prototype: requested', define)
        self.assertIn('`## Prototype`', define)
        g1b = plan.split('## G1b plan approval')[1].split('2. If `## Prototype`')[0]
        self.assertIn('Gate reports', g1b)
        self.assertNotIn('### Details', g1b)
        self.assertIn('remake it only if the mock-up changed', plan)
        step4 = plan.split('## 4. Plan Review')[1].split('## G1b plan approval')[0]
        self.assertIn('L1 writes the `## Decisions` lines in `plan-review.md`; architect does not write that file', step4)
        self.assertGreaterEqual(plan.count('Tool choice'), 3)
        # prototype: opened locally by the plugin script, not published
        stale = ('publishes it', 'private artifact', 'artifact link', 'claude.ai')
        proto3 = define.split('**G1a prototype:**')[1].split('4. **Confirm the scope:**')[0]
        item2 = plan.split('2. If `## Prototype`')[1].split('3. **Hosts:**')[0]
        for sec in (proto3, item2):
            self.assertIn('open-html.py', sec)
            self.assertIn('local path', sec)
            self.assertIn('skills/mock-up', sec)
            self.assertIn('capture.sh', sec)
            for phrase in stale:
                self.assertNotIn(phrase, sec)
        for word in ('templates/canvas.html', 'references', 'index.png'):
            self.assertIn(word, item2)
        self.assertNotIn('artifact-design', item2)
        self.assertIn('failed:', item2)
        self.assertIn('--data-dir', item2)
        self.assertNotIn('Check before anything leaves', item2)
        self.assertIn('Nothing is published', item2)
        # G1a / G1b chat reports open with Overview and Takeaway; the Report tab opens before the popup
        self.assertIn('### Overview', g1a)
        self.assertIn('### Takeaway', g1a)
        self.assertIn('scope summary', g1a.split('### Takeaway')[1].split('###')[0] + g1a)
        self.assertIn('`Prototype` row', g1a)
        g1b_item1 = g1b
        self.assertIn('### Overview', g1b_item1)
        self.assertIn('### Takeaway', g1b_item1)
        self.assertIn('`Models` row', g1b_item1)
        self.assertIn('`Prototype` row', g1b_item1)
        item3 = plan.split('4. Record before and after')[1].split('5. **Approve:**')[0]
        for gate, sec in (('G1a', g1a), ('G1b', item3)):
            for word in ('--report', '--pointer', 'pointer line', 'Gate reports'):
                self.assertIn(word, sec)
            self.assertNotIn('--url', sec)   # one `--pointer` call prints the pointer line (2026-11-16)
            self.assertLess(sec.index('ask gate=%s' % gate), sec.index('--report'))
            self.assertLess(sec.index('--report'), sec.index('answer gate=%s' % gate))

    def test_plan_lead_paragraph_required(self):
        plan = (REPO / 'l1-orchestration' / 'phases' / 'plan.md').read_text(encoding='utf-8')
        sec = plan.split('3. Sections `plan.md` must have')[1].split('4. If work units in the same parallel group')[0]
        for word in ('lead paragraph', '# Plan:', 'Profile:'):
            self.assertIn(word, sec)
        self.assertLess(sec.index('lead paragraph'), sec.index('## Scope summary'))
        arch = (REPO / 'l2-design-judge' / 'agents' / 'architect.md').read_text(encoding='utf-8')
        head = arch.split('## `plan.md` sections')[1].split('\n1. ')[0]
        for word in ('lead paragraph', 'plan summary'):
            self.assertIn(word, head)

    def test_scope_purpose_labels(self):
        for name in ('dev', 'research'):
            text = (REPO / 'l1-orchestration' / 'profiles' / ('%s.md' % name)).read_text(encoding='utf-8')
            self.assertIn('## Purpose and users', text)
            self.assertIn('Background:', text)
            self.assertIn('Purpose:', text)

    def test_plan_models_section_and_approval(self):
        phases = REPO / 'l1-orchestration' / 'phases'
        plan = (phases / 'plan.md').read_text(encoding='utf-8')
        step3 = plan.split('## 3. Plan')[1].split('## 4. Plan Review')[0]
        self.assertIn('agent-models.py', step3.split('2. Hand it')[1].split('3. Sections')[0])
        self.assertIn('`## Models`', step3.split('3. Sections')[1])
        step4 = plan.split('## 4. Plan Review')[1].split('## G1b plan approval')[0]
        self.assertIn('agent-models.py', step4.split('3. Hand it')[1].split('4. Handle')[0])
        approve = plan.split('5. **Approve:**')[1].split('6. **Request changes:**')[0]
        self.assertIn('`## Models`', approve)
        self.assertIn('Request changes', approve)
        self.assertIn('refuses', approve)

    def test_build_preset_rule(self):
        build = (REPO / 'l1-orchestration' / 'phases' / 'build.md').read_text(encoding='utf-8')
        self.assertNotIn('never pass `effort`', build)
        self.assertNotIn('The model follows the definition file', build)
        item3 = build.split('3. Hand out')[1].split('4. When a result')[0]
        self.assertIn('show --plan', item3)
        self.assertIn('pass=', item3)
        self.assertIn('Models:', item3)
        self.assertIn('model: "opus"', item3)
        rules = build.split('## Workflow rules')[1].split('## 6. Merge')[0]
        self.assertIn('definition values', rules)

    def test_general_g1b_shows_the_scope_confirmed_at_g1a(self):
        g = (REPO / 'l1-orchestration' / 'profiles' / 'general.md').read_text(encoding='utf-8')
        row = [l for l in g.splitlines() if l.startswith('| G1b')][0]
        self.assertIn('confirmed at G1a, so do not ask again', row)


    def test_verify_and_review_scope(self):
        """261106 criteria 1-3: L1 writes the changed-file map, the verifier gets it (and the previous verify.md on a rerun),
        the archive keeps it, and the reviewer gets verify.md instead of running the suites again."""
        phases = REPO / 'l1-orchestration' / 'phases'
        accept = (phases / 'accept.md').read_text(encoding='utf-8')
        self.assertIn('Verify and Review are never skipped', accept)
        verify = accept[accept.index('## 7. Verify'):accept.index('## Back to Execute')]
        self.assertIn('l4-tools-guards/scripts/changed-files.py" --task', verify)
        self.assertIn('--previous', verify)
        self.assertIn('the previous `verify.md` path', verify)
        self.assertIn('PASS (carried from Run <m>)', verify)
        self.assertIn('\n3. Hand it to `my-agent:verifier`. Pass:', verify)   # the handoff is its own item
        self.assertIn('When only Review is redone, without Verify, do both:', accept)
        self.assertIn('(on a rerun, a carried criterion is `- <n>. PASS (carried from Run <m>) <evidence>`, read as PASS)', verify)   # item 4 names the carried form
        back = accept.split('## Back to Execute')[1].split('\n## ')[0]
        self.assertIn('archive.py" --task "<absolute task folder>" --name run<Run: value of verify.md> '
                      '--only verify.md review.md changed-files.md', back)
        self.assertNotIn('cp -p', back)
        review = accept[accept.index('## 8. Review'):]
        self.assertIn('the `verify.md` and `changed-files.md` paths', review)
        self.assertIn('instead of running the suites again', review)
        self.assertIn('the list of files L1 fixed', review)
        profiles = REPO / 'l1-orchestration' / 'profiles'
        dev = (profiles / 'dev.md').read_text(encoding='utf-8')
        self.assertIn('changed-file map', dev)
        self.assertIn('instead of running the suites again', dev)
        for name in ('general.md', 'research.md'):
            self.assertIn('changed-file map', (profiles / name).read_text(encoding='utf-8'), name)

class CoderNotesRulesTest(unittest.TestCase):
    """Execute rules for coder-notes.md: save, cut and pass (criteria 2, 3, 4, 6, 7, 13)."""

    def setUp(self):
        self.build = (REPO / 'l1-orchestration' / 'phases' / 'build.md').read_text(encoding='utf-8')

    def test_item4_saves_notes_with_label_and_cut_line(self):
        item4 = self.build.split('4. When a result')[1].split('5. If a worker')[0]
        for text in ('coder-notes.md', 'Notes for later units:', '## rev<current rev> u<n> <name>',
                     '(cut: <k> more lines not saved)', 'first 10', 'without blank lines', '`PARTIAL <reason>`'):
            self.assertIn(text, item4, text)

    def test_item3_passes_notes_file_to_later_coder_calls_only(self):
        item3 = self.build.split('3. Hand out')[1].split('4. When a result')[0]
        for text in ('coder-notes.md', 'later parallel groups', 'retry of a stopped unit', '6 Merge', 'Back to Execute',
                     "each other's notes", 'Only coder calls get it', 'scope-reviewer', 'verifier',
                     'nothing is passed or created'):
            self.assertIn(text, item3, text)

    def test_other_units_results_rule_is_reworded(self):
        self.assertNotIn("Do not pass other units' results", self.build)
        item3 = self.build.split('3. Hand out')[1].split('4. When a result')[0]
        self.assertIn('only through the notes file', item3)

    def test_merge_rerun_passes_notes_file(self):
        merge = self.build.split('## 6. Merge')[1]
        self.assertIn('notes file path', merge)

    def test_workflow_return_value_holds_notes_part(self):
        rules = self.build.split('## Workflow rules')[1].split('## 6. Merge')[0]
        self.assertIn('notes part', rules)
        self.assertIn('Notes for later units:', rules)
        self.assertIn('definition values', rules)

    def test_only_coder_names_the_notes_file(self):
        for path in sorted((REPO / 'l2-design-judge' / 'agents').glob('*.md')):
            self.assertNotIn('coder-notes.md', path.read_text(encoding='utf-8'), path.name)
        for name in ('explorer.md', 'researcher.md', 'writer.md'):
            self.assertNotIn('coder-notes.md', (REPO / 'l3-workers' / 'agents' / name).read_text(encoding='utf-8'), name)
        self.assertIn('coder-notes.md', (REPO / 'l3-workers' / 'agents' / 'coder.md').read_text(encoding='utf-8'))


class EnvironmentAndUpstreamRulesTest(unittest.TestCase):
    """Environment check before the gates (Q36) and the upstream check in 6 Merge (Q37)."""

    def read(self, *parts):
        return REPO.joinpath(*parts).read_text(encoding='utf-8')

    def test_explorer_runs_check_commands_once(self):
        explorer = self.read('l3-workers', 'agents', 'explorer.md')
        self.assertIn('→ pass | fail: <failing tests> | cannot run: <reason>', explorer)
        self.assertIn('Run each check command once', explorer)
        self.assertIn('install nothing', explorer)

    def test_scope_interview_asks_about_environment_lines(self):
        define = self.read('l1-orchestration', 'phases', 'define.md')
        for phrase in ('**Environment:**', '`I fix the environment first (Recommended)` / `Judge without this command`',
                       '`Failures from before this task do not count (Recommended)` / `Fix them in this task`',
                       '`- Environment: <command> — '):
            self.assertIn(phrase, define)
        verifier = self.read('l2-design-judge', 'agents', 'verifier.md')
        for phrase in ('`- Environment:` lines', 'not run (scope: Environment)', '`replaced by`'):
            self.assertIn(phrase, verifier)

    def test_hosts_are_checked_before_g1b(self):
        self.assertIn('`- Needs host: <host name>`', self.read('l2-design-judge', 'agents', 'architect.md'))
        plan = self.read('l1-orchestration', 'phases', 'plan.md')
        self.assertIn('3. **Hosts:** for each `- Needs host: <name>` line', plan)
        self.assertIn('`I allow the hosts first (Recommended)` / `Plan change` / `Go on as is`', plan)
        self.assertLess(plan.index('**Hosts:**'), plan.index('Popup: `Approve (Recommended)`'))
        self.assertIn('`Plan change` is the same as item 6, Request changes', plan)
        self.assertIn('6. **Request changes:**', plan)

    def test_dev_merge_checks_upstream_before_verify(self):
        dev = self.read('l1-orchestration', 'profiles', 'dev.md')
        for phrase in ('## Upstream check (6 Merge)', 'git rev-list --count HEAD..<ref>', 'git merge --autostash <ref>',
                       '`Bring them in now (Recommended)` / `Go on without them`', '`git merge --abort`',
                       'merge unit=upstream'):
            self.assertIn(phrase, dev)
        self.assertIn('do "Upstream check" below, then run the check commands', dev)
        self.assertIn('"Upstream check" comes before the check commands',
                      self.read('l1-orchestration', 'phases', 'build.md'))
        for name in ('general.md', 'research.md'):
            self.assertNotIn('Upstream check', self.read('l1-orchestration', 'profiles', name))


class SessionFolderCheck(unittest.TestCase):
    """L1 checks the session's folder before a main-tree hand-out; the person answers, also under delegation."""

    def test_build_names_the_check_and_the_popup(self):
        build = (REPO / 'l1-orchestration' / 'phases' / 'build.md').read_text(encoding='utf-8')
        line = next(l for l in build.splitlines() if l.lstrip().startswith('- Session folder check'))
        for part in ('`git rev-parse --show-toplevel`', 'without `isolation: "worktree"`', 'start of 6 Merge',
                     'also under delegated approval', '`I moved the session back (Recommended)` / `Abort`',
                     '`/cd <task location>`', '`/my-agent continue`', 'run the check again'):
            self.assertIn(part, line)

    def test_build_adds_the_cd_rule_before_the_first_group(self):
        build = (REPO / 'l1-orchestration' / 'phases' / 'build.md').read_text(encoding='utf-8')
        lines = build.splitlines()
        i = next(k for k, l in enumerate(lines) if 'l4-tools-guards/scripts/cd-guard.py" --location "<task location>"' in l)
        self.assertIn('`.claude/settings.local.json`', lines[i])
        self.assertIn('`added` or `not added`', lines[i])
        self.assertIn('info/exclude', lines[i - 1])
        self.assertLess(i, next(k for k, l in enumerate(lines) if l.startswith('3. Hand out the work units')))
        self.assertTrue((REPO / 'l4-tools-guards' / 'scripts' / 'cd-guard.py').is_file())


if __name__ == '__main__':
    unittest.main()
