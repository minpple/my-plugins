"""Judge fixtures for the check record (architecture 4.13 "judge checks"): a stale record and a record that
disagrees with its log, both with an expected verifier FAIL (scope criterion 11), and three fixtures on a project
with a document (docs-only round: PASS from carried lines; document and code together: FAIL; README only: FAIL).
Free: no paid run here."""
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
DOCS_PROJECT = FIXTURES / 'checks-docs-project'
OLD_CASES = ('checks-stale', 'checks-log-mismatch')
DOCS_CASES = ('checks-docs-only', 'checks-docs-and-code', 'checks-readme-only')
CASES = OLD_CASES + DOCS_CASES
COMMAND = "python3 -m unittest discover -s tests -p 'check_*.py'"
PROJECT_FILES = ('base/calc.py', 'base/tests/check_calc.py', 'change/calc.py', 'change/tests/check_calc.py',
                 'task/scope.md', 'task/plan.md', 'task/explore.md')
DOCS_PROJECT_FILES = ('base/calc.py', 'base/README.md', 'base/docs/guide.md', 'base/tests/check_calc.py',
                      'base/tests/check_guide.py', 'base/tests/check_readme.py', 'task/scope.md', 'task/plan.md',
                      'task/explore.md')
CASE_FILES = ('checks.md', 'checks/01.log', 'changed-files.md')
CASE_OWN_FILES = {
    'checks-docs-only': ('change/docs/guide.md', 'checks/kept/261120-100000/checks.md',
                         'checks/kept/261120-100000/01.log', 'verify-previous.md'),
    'checks-docs-and-code': ('change/calc.py', 'change/docs/guide.md'),
    'checks-readme-only': ('change/README.md',),
}
# a full line, or a narrowed one: `→ narrowed to <files>: exit …` and `; rest carried from <id>/<nn>` after the log
RECORD_LINE = re.compile(r'^- (?P<nn>\d\d) `(?P<cmd>.+)` \((?P<src>.+)\) → (?:narrowed to (?P<files>.+?): )?'
                         r'exit (?P<code>\d+) \| (?P<summary>.+) \| (?P<secs>\d+) s \| (?P<log>checks/\d\d\.log)'
                         r'(?:; rest carried from (?P<rest>\S+))?$')
FULL_RESULT = 'Result: 1 run, 0 failed, 0 not run'
NARROWED_RESULT = 'Result: 1 run, 0 failed, 0 not run, 0 carried'


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8') if path.is_file() else ''


def record_lines(case: str, name: str = 'checks.md') -> list:
    return [m for m in (RECORD_LINE.match(ln) for ln in read(FIXTURES / case / name).splitlines()) if m]


def log_tail(case: str) -> list:
    return [ln for ln in read(FIXTURES / case / 'checks' / '01.log').splitlines() if ln.strip()]


def run_suite(*layers: Path, project: Path = PROJECT) -> subprocess.CompletedProcess:
    """The check command on `project/<layer>` copied over each other into a temp folder (never in the fixture
    folder: no __pycache__ there). A layer is a name under the project or an absolute folder."""
    with tempfile.TemporaryDirectory() as tmp:
        for layer in layers:
            src = Path(layer) if Path(layer).is_absolute() else project / layer
            shutil.copytree(src, tmp, dirs_exist_ok=True)
        return subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'check_*.py'],
                              cwd=tmp, capture_output=True, text=True, timeout=60)


def fingerprint(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:12]


def files_hash(items: dict) -> str:
    return hashlib.sha1(''.join(f'{p}\t{fp}\n' for p, fp in sorted(items.items())).encode()).hexdigest()[:12]


class JudgeFixturesTest(unittest.TestCase):
    def test_runner_header_names_a_real_model_run(self):
        """Criterion 3: the runner header says a fixture run calls a real model, not "Paid"; caps and model stay."""
        script = read(FIXTURES / 'run-judge-check.sh')
        head = script.split('\n', 1)[1].split('set -uo pipefail')[0]
        header = ' '.join(re.sub(r'^# ?', '', l) for l in head.splitlines())
        header = re.sub(r'\s+', ' ', header)
        self.assertNotIn('Paid', header)
        self.assertIn('starts a session that calls a real model', header)
        self.assertIn('--max-budget-usd', header)
        self.assertEqual(script.count('--max-budget-usd 2'), 2)
        self.assertEqual(script.count('--model haiku'), 2)

    def test_expected_checks_and_their_files(self):
        """Five folder fixtures; the two old ones are an expected FAIL of criterion 1 with a `ran` text (criterion 11);
        the three new ones carry their own keys (criterion 8)."""
        path = FIXTURES / 'expected-checks.json'
        self.assertTrue(path.is_file(), path)
        expected = json.loads(read(path) or '{}')
        self.assertEqual(sorted(expected), sorted(CASES))
        for case in OLD_CASES:
            self.assertEqual(expected[case], {'verdict': 'FAIL', 'criterion': 1,
                                              'ran': 'python3 -m unittest discover -s tests -p'}, case)
        self.assertEqual(expected['checks-docs-only'],
                         {'project': 'checks-docs-project', 'verdict': 'PASS', 'criterion': 2, 'line': 'PASS',
                          'reused': COMMAND, 'previous': 'verify-previous.md'})
        self.assertEqual(expected['checks-docs-and-code'],
                         {'project': 'checks-docs-project', 'verdict': 'FAIL', 'criterion': 1,
                          'ran': 'python3 -m unittest discover -s tests -p'})
        self.assertEqual(expected['checks-readme-only'],
                         {'project': 'checks-docs-project', 'verdict': 'FAIL', 'criterion': 3,
                          'ran': 'python3 -m unittest discover -s tests -p'})
        for case, want in expected.items():
            if 'ran' in want:
                self.assertTrue(COMMAND.startswith(want['ran']), case)
            for name in CASE_FILES:
                self.assertTrue((FIXTURES / case / name).is_file(), f'{case}/{name}')
            for name in CASE_OWN_FILES.get(case, ()):
                self.assertTrue((FIXTURES / case / name).is_file(), f'{case}/{name}')
        for name in PROJECT_FILES:
            self.assertTrue((PROJECT / name).is_file(), name)
        for name in DOCS_PROJECT_FILES:
            self.assertTrue((DOCS_PROJECT / name).is_file(), name)
        self.assertFalse((PROJECT / 'base' / 'tests' / '__init__.py').exists())   # discover never collects check_*.py
        self.assertFalse((DOCS_PROJECT / 'base' / 'tests' / '__init__.py').exists())
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

    def test_docs_project_task_files(self):
        task = DOCS_PROJECT / 'task'
        scope = read(task / 'scope.md')
        for n in (1, 2, 3):
            self.assertRegex(scope, rf'(?m)^{n}\. .+\[check: (command|file)\]$')
        self.assertRegex(scope, r'(?m)^1\. .*\[check: command\]$')
        self.assertRegex(scope, r'(?m)^2\. .*`docs/guide\.md`.*\[check: file\]$')
        self.assertRegex(scope, r'(?m)^3\. .*`README\.md`.*\[check: command\]$')
        plan = read(task / 'plan.md')
        self.assertIn('### u1 ', plan)
        self.assertIn(f'- Check commands: `{COMMAND}` (criteria 1, 3)', plan)
        self.assertRegex(plan, r'- Approved \d{4}-\d\d-\d\d \d\d:\d\d G1-B')
        self.assertIn(f'## Check commands\n\n- `{COMMAND}`', read(task / 'explore.md'))
        guide = DOCS_PROJECT / 'base' / 'tests' / 'check_guide.py'   # reads the guide through a resolved root
        self.assertIn("Path(__file__).resolve().parents[1] / 'docs' / 'guide.md'", read(guide))
        self.assertIn('docs/guide.md', read(DOCS_PROJECT / 'base' / 'README.md'))

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

    def test_docs_project_base_and_changes(self):
        """base/ passes; a docs-only change keeps it green; the mixed and README changes fail in their own test
        (exception: a document and another file changed)."""
        base = run_suite('base', project=DOCS_PROJECT)
        self.assertEqual(base.returncode, 0, base.stderr)
        self.assertIn('Ran 4 tests in ', base.stderr)
        docs_only = run_suite('base', FIXTURES / 'checks-docs-only' / 'change', project=DOCS_PROJECT)
        self.assertEqual(docs_only.returncode, 0, docs_only.stderr)
        mixed = run_suite('base', FIXTURES / 'checks-docs-and-code' / 'change', project=DOCS_PROJECT)
        self.assertNotEqual(mixed.returncode, 0, mixed.stderr)
        self.assertIn('FAIL: test_add (check_calc.CalcTest', mixed.stderr)
        self.assertNotIn('check_guide', mixed.stderr.split('Ran ')[0])   # the reworded guide still names add
        readme = run_suite('base', FIXTURES / 'checks-readme-only' / 'change', project=DOCS_PROJECT)
        self.assertNotEqual(readme.returncode, 0, readme.stderr)
        self.assertIn('FAIL: test_readme_names_the_guide (check_readme.ReadmeTest', readme.stderr)
        self.assertIn('FAILED (failures=1)', readme.stderr)

    def test_records_use_the_contract_format(self):
        for case in OLD_CASES:
            lines = read(FIXTURES / case / 'checks.md').splitlines()
            self.assertGreater(len(lines), 5, case)
            self.assertRegex(lines[0], r'^# Check record: \S+$', case)
            self.assertRegex(lines[1], r'^Fingerprint: head=[0-9a-f]{40} files=[0-9a-f]{12} paths=\d+$', case)
            self.assertRegex(lines[2], r'^Taken: \d{4}-\d\d-\d\d \d\d:\d\d:\d\d$', case)
            self.assertEqual(lines[3], FULL_RESULT, case)
            self.assertIn('## Fingerprint paths', lines, case)
            [m] = record_lines(case)
            self.assertEqual((m['nn'], m['cmd'], m['src'], m['code'], m['log'], m['files'], m['rest']),
                             ('01', COMMAND, 'explore, u1', '0', 'checks/01.log', None, None), case)
            self.assertRegex(m['summary'], r'^Ran \d+ tests in [0-9.]+s, OK$', case)
            log = read(FIXTURES / case / 'checks' / '01.log').splitlines()
            self.assertEqual(log[0], f'$ {COMMAND}', case)
            self.assertTrue(log[1].startswith('cwd: /'), case)
            self.assertRegex(log[2], r'^time limit: \d+ s$', case)

    def test_new_full_records_are_the_passing_record_of_base(self):
        """The mixed and README records are full 0.37.0 records of the clean base/ tree."""
        for case in ('checks-docs-and-code', 'checks-readme-only'):
            text = read(FIXTURES / case / 'checks.md')
            lines = text.splitlines()
            self.assertRegex(lines[0], r'^# Check record: \S+$', case)
            self.assertRegex(lines[1], r'^Fingerprint: head=[0-9a-f]{40} files=da39a3ee5e6b paths=0$', case)
            self.assertRegex(lines[2], r'^Taken: \d{4}-\d\d-\d\d \d\d:\d\d:\d\d$', case)
            self.assertEqual(lines[3], FULL_RESULT, case)
            self.assertNotIn('carried', text, case)
            self.assertNotIn('narrowed', text, case)
            [m] = record_lines(case)
            self.assertEqual((m['nn'], m['cmd'], m['src'], m['code'], m['log']),
                             ('01', COMMAND, 'explore, u1', '0', 'checks/01.log'), case)
            self.assertEqual(m['summary'], 'Ran 4 tests in 0.001s, OK', case)
            log = read(FIXTURES / case / 'checks' / '01.log').splitlines()
            self.assertEqual(log[0], f'$ {COMMAND}', case)
            self.assertIn('Ran 4 tests in 0.001s', log, case)

    def test_docs_only_record_is_narrowed_and_keeps_its_base(self):
        case = FIXTURES / 'checks-docs-only'
        text = read(case / 'checks.md')
        lines = text.splitlines()
        self.assertRegex(lines[0], r'^# Check record: \S+$')
        self.assertRegex(lines[1], r'^Fingerprint: head=[0-9a-f]{40} files=[0-9a-f]{12} paths=1$')
        self.assertEqual(lines[3], NARROWED_RESULT)
        self.assertIn('## Fingerprint paths', lines)
        [m] = record_lines('checks-docs-only')
        self.assertEqual((m['nn'], m['cmd'], m['src'], m['files'], m['code'], m['log'], m['rest']),
                         ('01', COMMAND, 'explore, u1', 'check_guide.py', '0', 'checks/01.log',
                          '261120-100000/01'))
        self.assertRegex(m['summary'], r'^Ran \d+ tests? in [0-9.]+s, OK$')
        log = read(case / 'checks' / '01.log').splitlines()
        self.assertEqual(log[0], '$ python3 -m unittest discover -s tests -p check_guide.py')   # the narrowed command
        self.assertIn(m['summary'].split(', ')[0], log)   # the summary part is in the log
        # the fingerprint is the tree: base plus change/ (one path, the reworded guide)
        guide = fingerprint(case / 'change' / 'docs' / 'guide.md')
        self.assertIn(f'- docs/guide.md {guide}', text)
        self.assertIn(f' files={files_hash({"docs/guide.md": guide})} paths=1', text)
        # the kept record is the full passing record of base/, its log beside it
        kept = case / 'checks' / 'kept' / '261120-100000'
        kept_lines = read(kept / 'checks.md').splitlines()
        self.assertEqual(kept_lines[3], FULL_RESULT)
        self.assertRegex(kept_lines[1], r'^Fingerprint: head=[0-9a-f]{40} files=da39a3ee5e6b paths=0$')
        self.assertEqual(kept_lines[1].split()[1], lines[1].split()[1])   # the same head
        [km] = record_lines('checks-docs-only', 'checks/kept/261120-100000/checks.md')
        self.assertEqual((km['cmd'], km['files'], km['rest'], km['log']), (COMMAND, None, None, 'checks/01.log'))
        self.assertEqual(km['summary'], 'Ran 4 tests in 0.001s, OK')
        self.assertIn('Ran 4 tests in 0.001s', read(kept / '01.log'))
        self.assertTrue(re.match(r'^Taken: 2026-11-20 10:00:00$', kept_lines[2]))   # the id 261120-100000

    def test_docs_only_previous_verify_passes_all(self):
        text = read(FIXTURES / 'checks-docs-only' / 'verify-previous.md')
        self.assertTrue(text.startswith('Verdict: ALL PASS\n'))
        self.assertRegex(text, r'(?m)^Run: 1$')
        for n in (1, 2, 3):
            self.assertRegex(text, rf'(?m)^- {n}\. PASS')
        self.assertIn('checks/kept/261120-100000/01.log', text)

    def test_stale_record_agrees_with_its_log(self):
        [m] = record_lines('checks-stale')
        tail = log_tail('checks-stale')
        self.assertEqual(tail[-1], f'exit 0 after {m["secs"]} s')
        self.assertEqual(tail[-2], 'OK')
        self.assertIn(m['summary'].split(', ')[0], tail)
        self.assertIn('paths=0', read(FIXTURES / 'checks-stale' / 'checks.md'))   # taken on the clean base/ tree

    def test_log_mismatch_record_says_ok_while_its_log_says_failed(self):
        """Exception: log summary does not match the record (criterion 11 (b))."""
        [m] = record_lines('checks-log-mismatch')
        self.assertEqual(m['code'], '0')
        self.assertTrue(m['summary'].endswith(', OK'))
        tail = log_tail('checks-log-mismatch')
        self.assertEqual(tail[-1], 'exit 1 after 1 s')
        self.assertEqual(tail[-2], 'FAILED (failures=1)')
        self.assertNotIn('OK', tail)
        self.assertIn(m['summary'].split(', ')[0], tail)   # same run, only the result is wrong

    def test_log_mismatch_fingerprint_matches_the_changed_tree(self):
        """Only the log disagrees: the fingerprint is the one of base/ plus change/ (contract hash)."""
        text = read(FIXTURES / 'checks-log-mismatch' / 'checks.md')
        paths = text.split('## Fingerprint paths', 1)[-1].strip().splitlines()
        want = {}
        for rel in ('calc.py', 'tests/check_calc.py'):
            data = (PROJECT / 'change' / rel).read_bytes() if (PROJECT / 'change' / rel).is_file() else b''
            want[rel] = hashlib.sha1(data).hexdigest()[:12]
        self.assertEqual(paths, [f'- {p} {fp}' for p, fp in sorted(want.items())])
        self.assertIn(f' files={files_hash(want)} paths=2', text)

    def test_changed_files_status_lines(self):
        stale = read(FIXTURES / 'checks-stale' / 'changed-files.md')
        self.assertRegex(stale, r'(?m)^Checks: stale \(\d+ paths differ: .*calc\.py.*\)$')
        self.assertIn('| calc.py |', stale)
        mismatch = read(FIXTURES / 'checks-log-mismatch' / 'changed-files.md')
        self.assertRegex(mismatch, r'(?m)^Checks: current$')
        for text in (stale, mismatch):
            self.assertRegex(text, r'(?m)^Re-judge: .+\nChecks: ')

    def test_docs_fixture_changed_files_status_lines(self):
        docs_only = read(FIXTURES / 'checks-docs-only' / 'changed-files.md')
        self.assertRegex(docs_only, r'(?m)^Re-judge: 2\nChecks: docs-only \(checked; 1 document paths since '
                                    r'261120-100000: docs/guide\.md\)$')
        self.assertRegex(docs_only, r'(?m)^\| docs/guide\.md \| u1 \| 2 \| ')
        mixed = read(FIXTURES / 'checks-docs-and-code' / 'changed-files.md')
        self.assertRegex(mixed, r'(?m)^Re-judge: all\nChecks: stale \(2 paths differ: calc\.py, docs/guide\.md\)$')
        readme = read(FIXTURES / 'checks-readme-only' / 'changed-files.md')
        self.assertRegex(readme, r'(?m)^Re-judge: all\nChecks: stale \(1 paths differ: README\.md\)$')
        for case, paths in (('checks-docs-only', {'docs/guide.md': 'checks-docs-only'}),
                            ('checks-docs-and-code', {'calc.py': 'checks-docs-and-code',
                                                      'docs/guide.md': 'checks-docs-and-code'}),
                            ('checks-readme-only', {'README.md': 'checks-readme-only'})):
            text = read(FIXTURES / case / 'changed-files.md')
            for rel in paths:   # the row's fingerprint is the file's in change/
                self.assertIn(f'| {rel} | u1 | ', text, case)
                self.assertIn(f'| {fingerprint(FIXTURES / case / "change" / rel)} |', text, case)

    def test_script_runs_folder_fixtures(self):
        script_path = FIXTURES / 'run-judge-check.sh'
        self.assertEqual(subprocess.run(['bash', '-n', str(script_path)]).returncode, 0)
        script = read(script_path)
        for text in ('--out', 'expected-checks.json', '--max-budget-usd 2', '--model haiku', '(checks.md)',
                     'JUDGE OK', 'my-agent:verifier', '## Commands run', 'changed-files.md', 'checks.md',
                     'project', 'previous', 'reused', 'Previous verify:', '(checks.md'):
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

    def test_script_reads_the_new_keys(self):
        """`project` (default checks-project), `line` (default FAIL), `reused`, `previous`, and a fixture's own change/."""
        script = read(FIXTURES / 'run-judge-check.sh')
        self.assertIn('project checks-project)', script)
        self.assertIn('line FAIL)', script)
        self.assertIn('"$HERE/$project/base/."', script)
        self.assertIn('"$HERE/$name/change"', script)
        self.assertIn('"$HERE/$project/change/."', script)
        self.assertIn('"$HERE/$project/task/"', script)
        self.assertIn('archive/261120-100000-run1/verify.md', script)
        self.assertIn('Previous verify: $T/archive/261120-100000-run1/verify.md', script)
        self.assertIn('reused the record', script)
        self.assertIn('ran the suite itself', script)


if __name__ == '__main__':
    unittest.main()
