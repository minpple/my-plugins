"""Judge fixtures for the check record (architecture 4.13 "judge checks"): a stale record and a record that
disagrees with its log, both with an expected verifier FAIL (scope criterion 11). Free: no paid run here."""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO

FIXTURES = REPO / 'tests' / 'judge-fixtures'
PROJECT = FIXTURES / 'checks-project'
CASES = ('checks-stale', 'checks-log-mismatch')
COMMAND = "python3 -m unittest discover -s tests -p 'check_*.py'"
PROJECT_FILES = ('base/calc.py', 'base/tests/check_calc.py', 'change/calc.py', 'change/tests/check_calc.py',
                 'task/scope.md', 'task/plan.md', 'task/explore.md')
CASE_FILES = ('checks.md', 'checks/01.log', 'changed-files.md')
RECORD_LINE = re.compile(r'^- (\d\d) `(.+)` \((.+)\) → exit (\d+) \| (.+) \| (\d+) s \| (checks/\d\d\.log)$')


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8') if path.is_file() else ''


def record_lines(case: str) -> list:
    return [m for m in (RECORD_LINE.match(ln) for ln in read(FIXTURES / case / 'checks.md').splitlines()) if m]


def log_tail(case: str) -> list:
    return [ln for ln in read(FIXTURES / case / 'checks' / '01.log').splitlines() if ln.strip()]


def run_suite(*layers: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:   # never run the suite in the fixture folder (no __pycache__ there)
        for layer in layers:
            shutil.copytree(PROJECT / layer, tmp, dirs_exist_ok=True)
        return subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'check_*.py'],
                              cwd=tmp, capture_output=True, text=True, timeout=60)


class JudgeFixturesTest(unittest.TestCase):
    def test_expected_checks_and_their_files(self):
        """Two folder fixtures, each an expected FAIL of criterion 1 with a `ran` text (criterion 11)."""
        path = FIXTURES / 'expected-checks.json'
        self.assertTrue(path.is_file(), path)
        expected = json.loads(read(path) or '{}')
        self.assertEqual(sorted(expected), sorted(CASES))
        for case, want in expected.items():
            self.assertEqual(want.get('verdict'), 'FAIL', case)
            self.assertEqual(want.get('criterion'), 1, case)
            self.assertTrue(COMMAND.startswith(want.get('ran') or '-'), case)
            for name in CASE_FILES:
                self.assertTrue((FIXTURES / case / name).is_file(), f'{case}/{name}')
        for name in PROJECT_FILES:
            self.assertTrue((PROJECT / name).is_file(), name)
        self.assertFalse((PROJECT / 'base' / 'tests' / '__init__.py').exists())   # discover never collects check_*.py
        notes = json.loads(read(FIXTURES / 'expected.json'))
        self.assertEqual(sorted(notes), ['note-broken-citation.md', 'note-criterion-miss.md', 'note-good.md',
                                         'note-injected.md'])

    def test_task_files_name_the_check_command(self):
        task = PROJECT / 'task'
        self.assertIn('[check: command]', read(task / 'scope.md'))
        plan = read(task / 'plan.md')
        self.assertIn('### u1 ', plan)
        self.assertIn(f'- Check commands: `{COMMAND}` (criterion 1)', plan)
        self.assertRegex(plan, r'- Approved \d{4}-\d\d-\d\d \d\d:\d\d G1-B')
        explore = read(task / 'explore.md')
        self.assertIn(f'## Check commands\n\n- `{COMMAND}`', explore)

    def test_base_passes_and_change_fails(self):
        """The record was true for base/; the change makes the suite fail (exception: tree changed after the record)."""
        for name in PROJECT_FILES[:4]:
            self.assertTrue((PROJECT / name).is_file(), name)
        base = run_suite('base')
        self.assertEqual(base.returncode, 0, base.stderr)
        self.assertRegex(base.stderr, r'Ran \d+ tests in ')
        changed = run_suite('base', 'change')
        self.assertNotEqual(changed.returncode, 0, changed.stderr)
        self.assertIn('FAILED (failures=1)', changed.stderr)

    def test_records_use_the_contract_format(self):
        for case in CASES:
            lines = read(FIXTURES / case / 'checks.md').splitlines()
            self.assertGreater(len(lines), 5, case)
            self.assertRegex(lines[0], r'^# Check record: \S+$', case)
            self.assertRegex(lines[1], r'^Fingerprint: head=[0-9a-f]{40} files=[0-9a-f]{12} paths=\d+$', case)
            self.assertRegex(lines[2], r'^Taken: \d{4}-\d\d-\d\d \d\d:\d\d:\d\d$', case)
            self.assertEqual(lines[3], 'Result: 1 run, 0 failed, 0 not run', case)
            self.assertIn('## Fingerprint paths', lines, case)
            [m] = record_lines(case)
            self.assertEqual((m.group(1), m.group(2), m.group(3), m.group(4), m.group(7)),
                             ('01', COMMAND, 'explore, u1', '0', 'checks/01.log'), case)
            self.assertRegex(m.group(5), r'^Ran \d+ tests in [0-9.]+s, OK$', case)
            log = read(FIXTURES / case / 'checks' / '01.log').splitlines()
            self.assertEqual(log[0], f'$ {COMMAND}', case)
            self.assertTrue(log[1].startswith('cwd: /'), case)
            self.assertRegex(log[2], r'^time limit: \d+ s$', case)

    def test_stale_record_agrees_with_its_log(self):
        [m] = record_lines('checks-stale')
        tail = log_tail('checks-stale')
        self.assertEqual(tail[-1], f'exit 0 after {m.group(6)} s')
        self.assertEqual(tail[-2], 'OK')
        self.assertIn(m.group(5).split(', ')[0], tail)
        self.assertIn('paths=0', read(FIXTURES / 'checks-stale' / 'checks.md'))   # taken on the clean base/ tree

    def test_log_mismatch_record_says_ok_while_its_log_says_failed(self):
        """Exception: log summary does not match the record (criterion 11 (b))."""
        [m] = record_lines('checks-log-mismatch')
        self.assertEqual(m.group(4), '0')
        self.assertTrue(m.group(5).endswith(', OK'))
        tail = log_tail('checks-log-mismatch')
        self.assertEqual(tail[-1], 'exit 1 after 1 s')
        self.assertEqual(tail[-2], 'FAILED (failures=1)')
        self.assertNotIn('OK', tail)
        self.assertIn(m.group(5).split(', ')[0], tail)   # same run, only the result is wrong

    def test_log_mismatch_fingerprint_matches_the_changed_tree(self):
        """Only the log disagrees: the fingerprint is the one of base/ plus change/ (contract hash)."""
        text = read(FIXTURES / 'checks-log-mismatch' / 'checks.md')
        paths = text.split('## Fingerprint paths', 1)[-1].strip().splitlines()
        want = {}
        for rel in ('calc.py', 'tests/check_calc.py'):
            data = (PROJECT / 'change' / rel).read_bytes() if (PROJECT / 'change' / rel).is_file() else b''
            want[rel] = hashlib.sha1(data).hexdigest()[:12]
        self.assertEqual(paths, [f'- {p} {fp}' for p, fp in sorted(want.items())])
        files = hashlib.sha1(''.join(f'{p}\t{fp}\n' for p, fp in sorted(want.items())).encode()).hexdigest()[:12]
        self.assertIn(f' files={files} paths=2', text)

    def test_changed_files_status_lines(self):
        stale = read(FIXTURES / 'checks-stale' / 'changed-files.md')
        self.assertRegex(stale, r'(?m)^Checks: stale \(\d+ paths differ: .*calc\.py.*\)$')
        self.assertIn('| calc.py |', stale)
        mismatch = read(FIXTURES / 'checks-log-mismatch' / 'changed-files.md')
        self.assertRegex(mismatch, r'(?m)^Checks: current$')
        for text in (stale, mismatch):
            self.assertRegex(text, r'(?m)^Re-judge: .+\nChecks: ')

    def test_script_runs_folder_fixtures(self):
        script_path = FIXTURES / 'run-judge-check.sh'
        self.assertEqual(subprocess.run(['bash', '-n', str(script_path)]).returncode, 0)
        script = read(script_path)
        for text in ('--out', 'expected-checks.json', '--max-budget-usd 2', '--model haiku', '(checks.md)',
                     'JUDGE OK', 'my-agent:verifier', '## Commands run', 'changed-files.md', 'checks.md'):
            self.assertIn(text, script)
        note_tools = re.search(r'(?m)^NOTE_TOOLS="([^"]*)"', script)
        folder_tools = re.search(r'(?m)^FOLDER_TOOLS="([^"]*)"', script)
        self.assertTrue(note_tools and folder_tools)
        self.assertNotIn('Bash', note_tools.group(1).split())   # Bash for folder fixtures only
        self.assertIn('Bash', folder_tools.group(1).split())
        self.assertEqual(script.count('--allowedTools $NOTE_TOOLS'), 1)
        self.assertEqual(script.count('--allowedTools $FOLDER_TOOLS'), 1)
        self.assertEqual(script.count('--allowedTools'), 2)
        out_lines = [ln for ln in script.splitlines() if '"$OUT"' in ln and '>' in ln]
        self.assertTrue(out_lines)
        for ln in out_lines:   # --out appends
            self.assertIn('>> "$OUT"', ln)
            self.assertNotRegex(ln, r'(^|[^>])> *"\$OUT"')


if __name__ == '__main__':
    unittest.main()
