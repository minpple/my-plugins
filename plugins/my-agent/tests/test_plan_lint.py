"""Plan gaps (architecture 4.4 "Plan gaps", Q33): `ma_schema.plan_gaps`, `plan-lint.py` and the G1b hook on the approval write."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import CLAUDE_HOOK_ENV, L4, REPO, make_task, run_hook
import ma_schema

TASK = '261119-plan-gaps'
SCOPE = '''# Scope

## Completion criteria
1. The command prints the total [check: command]
2. The README names the flag [check: file]
3. The person likes the wording [check: person]
'''
PLAN = '''# Plan: totals

## Work units
### u1 total
- Agent: my-agent:coder
- Files to change: `src/total.py`, `tests/test_total.py`
- Tests to add: `tests/test_total.py` prints the total for three rows (criterion 1); empty input prints 0 (exception: empty input)
- Check commands: `python3 -m unittest`
- Parallel group: group 1
- Completion criteria: 1, 2
- Status: pending

## Approval
'''
APPROVED = '- Approved 2026-11-19 10:00 G1b\n'


class PlanGapsTest(unittest.TestCase):
    def test_no_gap(self):
        self.assertEqual(ma_schema.plan_gaps(SCOPE, PLAN, 'dev'), [])

    def test_missing_and_unknown_check_tag(self):
        scope = SCOPE.replace(' [check: file]', '').replace('[check: person]', '[check: eyes]')
        gaps = ma_schema.plan_gaps(scope, PLAN, 'research')
        self.assertEqual(len(gaps), 2)
        self.assertIn('criterion 2: no check tag', gaps[0])
        self.assertIn('criterion 3: check tag `eyes`', gaps[1])

    def test_no_tag_at_all_is_a_gap(self):
        gaps = ma_schema.plan_gaps(ma_schema.CHECK_TAG.sub('', SCOPE), PLAN, 'general')
        self.assertEqual(ma_schema.plan_gaps('1. x\n', PLAN, 'general'), ['no numbered completion criteria'])
        self.assertTrue(gaps)

    def test_criteria_from_plan_without_scope(self):
        plan = '## Completion criteria\n1. It prints the total [check: command]\n\n' + PLAN.split('\n', 2)[2]
        self.assertEqual(ma_schema.plan_gaps('', plan, 'dev'), [])
        self.assertEqual(len(ma_schema.plan_gaps('', plan.replace(' (criterion 1)', ''), 'dev')), 1)

    def test_dev_command_criterion_needs_a_mark(self):
        gaps = ma_schema.plan_gaps(SCOPE, PLAN.replace(' (criterion 1)', ''), 'dev')
        self.assertEqual(gaps, ['criterion 1: no test to add or check command marked `(criterion 1)` in a work unit that lists it'])
        self.assertEqual(ma_schema.plan_gaps(SCOPE, PLAN.replace(' (criterion 1)', ''), 'research'), [])

    def test_mark_in_a_unit_that_does_not_list_the_criterion(self):
        self.assertEqual(len(ma_schema.plan_gaps(SCOPE, PLAN.replace('criteria: 1, 2', 'criteria: 2'), 'dev')), 1)

    def test_mark_on_a_check_command_and_several_numbers(self):
        plan = PLAN.replace(' (criterion 1)', '').replace('`python3 -m unittest`', '`make build` (criteria 1, 2)')
        self.assertEqual(ma_schema.plan_gaps(SCOPE, plan, 'dev'), [])
        self.assertEqual(ma_schema.unit_covers(plan), {'u1': {1, 2}})


class PlanLintScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.task = Path(self.tmp.name) / TASK
        self.task.mkdir()
        (self.task / 'intake.md').write_text('Status: active\nProfile: dev\n', encoding='utf-8')
        (self.task / 'scope.md').write_text(SCOPE, encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def run_lint(self, *argv):
        return subprocess.run([sys.executable, str(L4 / 'scripts' / 'plan-lint.py'), *argv], capture_output=True, text=True)

    def test_ok(self):
        (self.task / 'plan.md').write_text(PLAN, encoding='utf-8')
        r = self.run_lint('--task', str(self.task))
        self.assertEqual((r.returncode, r.stdout), (0, 'plan-lint: ok\n'), r.stderr)

    def test_fail_lines(self):
        (self.task / 'plan.md').write_text(PLAN.replace(' (criterion 1)', ''), encoding='utf-8')
        r = self.run_lint('--task', str(self.task))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.splitlines(), ['plan-lint: FAIL criterion 1: no test to add or check command marked '
                                                 '`(criterion 1)` in a work unit that lists it'])

    def test_missing_plan_and_bad_arguments(self):
        r = self.run_lint('--task', str(self.task))
        self.assertEqual(r.returncode, 1)
        self.assertIn('plan-lint: FAIL', r.stdout)
        self.assertEqual(self.run_lint().returncode, 2)


class ApprovalWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.proj = self.root / 'proj'
        self.task = make_task(self.proj, task=TASK)
        (self.root / 'agent-tasks').mkdir()
        self.env = dict(CLAUDE_HOOK_ENV, MA_TASKS_DIR=str(self.root / 'agent-tasks'))
        (self.task / 'intake.md').write_text('Status: active\nProfile: dev\n', encoding='utf-8')
        (self.task / 'scope.md').write_text(SCOPE, encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, tool, **ti):
        payload = {'hook_event_name': 'PreToolUse', 'tool_name': tool, 'session_id': 's-test',
                   'tool_input': dict(ti, file_path=str(self.task / 'plan.md'))}
        r = run_hook('plan-approved-check.py', None, payload, self.proj, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)['hookSpecificOutput'] if r.stdout else None

    def approve(self):
        return self.hook('Edit', old_string='## Approval\n', new_string='## Approval\n' + APPROVED)

    def test_approval_edit_passes_without_gaps(self):
        (self.task / 'plan.md').write_text(PLAN, encoding='utf-8')
        self.assertIsNone(self.approve())

    def test_approval_edit_denied_with_gaps(self):
        (self.task / 'plan.md').write_text(PLAN.replace(' (criterion 1)', ''), encoding='utf-8')
        out = self.approve()
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertIn('plan.md cannot be approved yet (G1b, plan gaps): criterion 1: no test to add', out['permissionDecisionReason'])
        self.assertIn(' guard: ', (self.task / 'run-log.md').read_text(encoding='utf-8'))

    def test_approval_write_denied_with_gaps(self):
        (self.task / 'scope.md').write_text(SCOPE.replace(' [check: file]', ''), encoding='utf-8')
        out = self.hook('Write', content=PLAN + APPROVED)
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertIn('criterion 2: no check tag', out['permissionDecisionReason'])

    def test_other_plan_edits_pass_with_gaps(self):
        (self.task / 'plan.md').write_text(PLAN.replace(' (criterion 1)', ''), encoding='utf-8')
        self.assertIsNone(self.hook('Edit', old_string='- Status: pending', new_string='- Status: pending\n- Note: x'))
        self.assertIsNone(self.hook('Write', content=PLAN.replace(' (criterion 1)', '')))

    def test_approved_plan_is_not_read_again(self):
        (self.task / 'plan.md').write_text(PLAN.replace(' (criterion 1)', '') + APPROVED, encoding='utf-8')
        self.assertIsNone(self.hook('Edit', old_string='- Status: pending', new_string='- Status: done'))


class RulesTest(unittest.TestCase):
    def test_l1_runs_the_lint_and_architect_writes_the_marks(self):
        plan = (REPO / 'l1-orchestration' / 'phases' / 'plan.md').read_text(encoding='utf-8')
        self.assertIn('scripts/plan-lint.py" --task "<absolute task folder>"', plan)
        self.assertIn('also when Plan Review is skipped', plan)
        self.assertLess(plan.index('**Plan gaps:**'), plan.index('Hand it to `my-agent:plan-reviewer`'))
        arch = (REPO / 'l2-design-judge' / 'agents' / 'architect.md').read_text(encoding='utf-8')
        self.assertIn('the same `(criterion <n>)` mark on its check command', arch)


if __name__ == '__main__':
    unittest.main()
