#!/usr/bin/env python3
"""Changed-file map for Verify and Review (accept.md step 4A): each changed file with its work units, criteria and fingerprint.

usage: changed-files.py --task TASK_FOLDER [--previous EARLIER_CHANGED_FILES_MD] [--review ARCHIVED_REVIEW_MD]
                        [--rework-criterion "<n>: <shortfall>"]... [--rework-finding "<path>:<line>"]...

Writes <task folder>/changed-files.md and prints one line
`changed-files: <N> files, <M> unmapped[, <K> changed since Run <r>][, <F> criteria from findings][, <k> finding(s) without a valid criterion tag (Re-judge: all)][, review not read (Verify FAIL in that run)]`
and a second line `checks: <status>`, which is also the `Checks:` header line of the map, right after `Re-judge:`.
The status compares <task folder>/checks.md (written by check-commands.py, see ma_checks.py) with the current working tree:
`current` (head and files fingerprint equal), `stale (HEAD moved)`, `stale (<n> paths differ: <up to 5 paths>)`, `missing`
(no or unreadable record while check commands exist), `no fingerprint` (the record says `Fingerprint: none`: not a git location,
or the run changed the tree), `not needed (no check commands)`. In a docs-only round (architecture Q48; `ma_checks.docs_round`)
it is also `docs-only (run due; <d> paths differ: <up to 5 paths>; test files: <names | none>)` (the record passed and only
documents differ: the check script will narrow its run) or `docs-only (checked; <d> document paths since <oldest kept id>: <up to
5 paths>)` (a record with narrowed or carried lines equals the tree and every kept record it names differs from the tree only in
documents; never `current`), or `stale (kept record <id> missing)`. A checks problem never changes the exit code.
Files: in the dev profile with a git task location, `git diff --name-only HEAD` plus the untracked files, without the
task records folder; otherwise the files under <task folder>/work/ and deliverable/, plus each file a unit lists under
`Files to change` that exists in the task location (code a coder changed in place where git cannot list it).
A file maps to every plan unit that names it (`Files to change`, or any backticked path of the unit outside git; in git a path
is made relative to the git root first: an absolute path, a `./` prefix and a task location below the root); a file
no unit names is `unmapped`, a shared test helper or `ma_schema.py` is `shared`; both have the criteria `all`.
The criteria come from the units that name the file only: a criterion that also leans on a file of another unit is
re-judged when that file's own criteria are listed (or `all`).
With --previous, `Since previous` is `changed` or `same`, a file of the previous map that is no longer changed is a
`reverted` row (once: a row already `reverted` there is left out, so later maps do not keep it), and `Re-judge:` is the union of the criteria of the changed rows (`all` when one of them is unmapped or
shared, `none` when nothing changed). Without it, `Re-judge: all`.
Findings (a rerun after Back to Execute): the criteria of every `- BLOCKER` line under `## Findings` of --review (`## Applied after review`
is not read), of each --rework-criterion and of the SHOULD-FIX lines whose location --rework-finding names are added to `Re-judge:`
(`all` stays `all`; a line without a valid `[criterion <n>[, <m>…]]` tag makes it `all`; `[criterion none]` adds nothing). Those lines
are copied to a `## Findings` section after the table, with one `- Criterion <n> (G3 Rework): <shortfall>` line per --rework-criterion.
A --review whose sibling verify.md says `Verdict: FAIL` is a copy from an earlier run and is not read, unless it is newer than
the sibling changed-files.md (a round with a check record runs both judges, and the map is written before them: that review is fresh).
exit: 0 written, 1 intake.md or plan.md missing (or the map could not be written), 2 bad arguments, --previous or --review names no file,
a --rework-criterion that is no completion criterion or has no shortfall, a --rework-finding without --review or matching no SHOULD-FIX line.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import ma_checks  # noqa: E402
import ma_schema  # noqa: E402
from ma_checks import file_fp  # noqa: E402

PLUGIN_PREFIX = re.compile(r'^plugins/[^/]+/')
BACKTICKED = re.compile(r'`([^`\s]+)`')


def say(text: str, code: int) -> int:
    print(f'changed-files: {text}')
    return code


def field(text: str, name: str):
    m = re.search(rf'(?m)^{name}:\s*(.*\S)\s*$', text or '')
    return m.group(1) if m else None


def git(root: Path, *args):
    """stdout lines of a git command in `root`, or None when git fails."""
    try:
        res = subprocess.run(['git', '-C', str(root), '-c', 'core.quotepath=false', *args],   # real non-ASCII names
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout.splitlines() if res.returncode == 0 else None


def unit_paths(plan: str) -> list:
    """[(id, criteria, files to change, every backticked path of the unit)] of the plan's work units."""
    details = {u['id']: u for u in ma_schema.unit_details(plan)}
    paths, current = {}, None
    for line in ma_schema.section_lines(plan, 'Work units') or []:
        head = ma_schema.UNIT_HEAD.match(line)
        if head:
            current = head.group(1)
            paths[current] = []
        elif current:
            paths[current] += BACKTICKED.findall(line)
    return [(uid, u['criteria'], u['files'], paths.get(uid, [])) for uid, u in details.items()]


def shared(path: str) -> bool:
    """A file many criteria lean on: a test helper, a test fixture or the shared format module."""
    name, in_tests = path.rsplit('/', 1)[-1], '/tests/' in f'/{path}'
    return name in ('conftest.py', 'ma_schema.py') or in_tests and (name == 'helpers.py' or '/fixtures/' in f'/{path}')


REWORK_CRITERION = re.compile(r'^\s*(\d+)\s*:\s*(\S.*?)\s*$')


def review_lines(text: str):
    """[(severity, location, line as written, tag value or None)] of the `## Findings` bullets of a review.md."""
    out = []
    for raw in ma_schema.section_lines(text, 'Findings') or []:
        line = raw.strip()
        m = ma_schema.FINDING_LINE.match(line)
        if m:
            out.append((m.group(1), m.group(2), line, ma_schema.split_finding_criterion(m.group(3))[1]))
    return out


def review_is_fresh(review: Path) -> bool:
    """A review written after the sibling changed-files.md of its round: that round ran both judges."""
    try:
        return review.stat().st_mtime > review.with_name(ma_schema.CHANGED_FILES).stat().st_mtime
    except OSError:
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('--task', required=True)
    ap.add_argument('--previous')
    ap.add_argument('--review')
    ap.add_argument('--rework-criterion', action='append', default=[])
    ap.add_argument('--rework-finding', action='append', default=[])
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    task = Path(args.task).resolve()
    intake, plan = task / 'intake.md', task / 'plan.md'
    if not intake.is_file() or not plan.is_file():
        return say(f'{"intake.md" if not intake.is_file() else "plan.md"} missing in {task}', 1)
    previous = Path(args.previous).resolve() if args.previous else None
    if previous is not None and not previous.is_file():
        return say(f'no such previous map: {previous}', 2)
    review = Path(args.review).resolve() if args.review else None
    if review is not None and not review.is_file():
        return say(f'no such review: {review}', 2)
    if args.rework_finding and review is None:
        return say('--rework-finding needs --review', 2)
    itext, ptext = intake.read_text(encoding='utf-8'), plan.read_text(encoding='utf-8')
    location = Path(field(itext, 'Location') or task.parent.parent)
    top = git(location, 'rev-parse', '--show-toplevel') if field(itext, 'Profile') == 'dev' else None
    units = unit_paths(ptext)

    scope = task / 'scope.md'
    valid = {n for n, _t, _c in ma_schema.criteria(scope.read_text(encoding='utf-8') if scope.is_file() else ptext)}
    if not valid:
        valid = {n for n, _t, _c in ma_schema.criteria(ptext)}
    rework = []   # [(n, shortfall)]
    for value in args.rework_criterion:
        m = REWORK_CRITERION.match(value)
        if not m:
            return say(f'--rework-criterion needs "<n>: <shortfall>": {value}', 2)
        if int(m.group(1)) not in valid:
            return say(f'--rework-criterion {int(m.group(1))} is not a completion criterion of the task', 2)
        rework.append((int(m.group(1)), m.group(2)))
    found, review_skipped = [], False   # found: (line as written, tag numbers, or None when the tag is invalid)
    if review is not None:
        sibling = review.with_name('verify.md')
        verify_text = ''
        if sibling.is_file():
            try:
                verify_text = sibling.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError) as exc:
                return say(f'cannot read {sibling}: {exc}', 2)
        if re.search(r'(?m)^Verdict:\s*FAIL\b', verify_text) and not review_is_fresh(review):
            review_skipped = True   # a copy left over from an earlier run: no Review ran in this one
        else:
            try:
                lines = review_lines(review.read_text(encoding='utf-8'))
            except (OSError, UnicodeDecodeError) as exc:
                return say(f'cannot read review {review}: {exc}', 2)
            picked = set(args.rework_finding)
            unmatched = sorted(picked - {loc for sev, loc, _line, _tag in lines if sev == 'SHOULD-FIX'})
            if unmatched:
                return say(f'--rework-finding {unmatched[0]} matches no SHOULD-FIX line of {review}', 2)
            for sev, loc, line, tag in lines:
                if sev == 'BLOCKER' or sev == 'SHOULD-FIX' and loc in picked:
                    nums = ma_schema.finding_tag_numbers(tag)
                    if nums == 'none':
                        continue
                    found.append((line, nums if nums and all(n in valid for n in nums) else None))
    if review_skipped and args.rework_finding:
        return say(f'--rework-finding {args.rework_finding[0]} matches no SHOULD-FIX line: the review is not read '
                   '(Verify FAIL in that run)', 2)
    in_place = {}

    if top:
        root = Path(top[0])
        try:
            records = task.parent.relative_to(root).as_posix() + '/'
        except ValueError:
            records = None
        names = (git(root, 'diff', '--name-only', 'HEAD') or []) + \
            (git(root, 'ls-files', '--others', '--exclude-standard', '--full-name') or [])
        files = sorted({n for n in names if n and not (records and n.startswith(records))})
        base = (git(root, 'rev-parse', '--short', 'HEAD') or ['-'])[0]

        try:
            below = location.resolve().relative_to(root.resolve()).as_posix()   # task location below the git root
        except ValueError:
            below = '.'

        def relative(n):
            """The plan's path as git lists it: without `./`, an absolute path or a location-relative path made root-relative."""
            n = n[2:] if n.startswith('./') else n
            if n.startswith('/'):
                try:
                    return Path(n).resolve().relative_to(root.resolve()).as_posix()
                except ValueError:
                    return n
            return n if below == '.' else f'{below}/{n}'

        def owners(f):
            return [(uid, crit) for uid, crit, named, _all in units
                    if any(f == r or PLUGIN_PREFIX.sub('', f) == r or PLUGIN_PREFIX.sub('', f) == n
                           for n in named for r in (relative(n), n))]
    else:
        root = task
        files = sorted(p.relative_to(task).as_posix() for d in ('work', 'deliverable') if (task / d).is_dir()
                       for p in (task / d).rglob('*') if p.is_file())
        base = '-'
        for _uid, _crit, named, _every in units:   # code changed in place: no git to list it, so the plan names it
            for n in named:
                p = (location / n).resolve()
                if n not in files and p.is_file() and task not in p.parents:
                    files.append(n)
                    in_place[n] = p
        files.sort()

        def owners(f):
            return [(uid, crit) for uid, crit, _named, every in units if any(p == f or p.endswith('/' + f) for p in every)]

    prev_rows = {}
    run = None
    if previous is not None:
        prev_rows = {r['file']: r for r in ma_schema.changed_files_rows(previous.read_text(encoding='utf-8'))[0]}
        verify = previous.with_name('verify.md')
        run = ma_schema.run_number(verify.read_text(encoding='utf-8')) if verify.is_file() else None

    rows = []
    gone = {f for f in set(prev_rows) - set(files) if prev_rows[f]['fingerprint'] != 'reverted'}
    for f in files + sorted(gone):
        own = owners(f)
        if shared(f):
            unit_cell, crit_cell = 'shared', ma_schema.ALL_CRITERIA
        elif not own:
            unit_cell, crit_cell = 'unmapped', ma_schema.ALL_CRITERIA
        else:
            unit_cell = ', '.join(uid for uid, _c in own)
            nums = sorted({n for _u, crit in own for n in crit})
            crit_cell = ', '.join(map(str, nums)) or '-'
        fp = file_fp(in_place.get(f, root / f)) if f in files else 'reverted'
        if previous is None:
            since = '-'
        else:
            since = 'same' if f in prev_rows and prev_rows[f]['fingerprint'] == fp else 'changed'
        rows.append((f, unit_cell, crit_cell, fp, since))

    changed = [r for r in rows if r[4] == 'changed']
    if previous is None:
        rejudge = ma_schema.ALL_CRITERIA
    elif any(r[2] == ma_schema.ALL_CRITERIA for r in changed):
        rejudge = ma_schema.ALL_CRITERIA
    else:
        nums = sorted({int(n) for r in changed for n in re.findall(r'\d+', r[2])})
        rejudge = ', '.join(map(str, nums)) or 'none'
    from_findings = {n for _l, nums in found if nums for n in nums} | {n for n, _s in rework}
    invalid = sum(1 for _l, nums in found if nums is None)
    if rejudge != ma_schema.ALL_CRITERIA:
        if invalid:
            rejudge = ma_schema.ALL_CRITERIA
        elif from_findings:
            have = {int(n) for n in re.findall(r'\d+', rejudge)}
            rejudge = ', '.join(map(str, sorted(have | from_findings)))

    run_text = '?' if run is None else str(run)
    checks = ma_checks.status(task, location, field(itext, 'Profile'), ptext)
    lines = [f'# Changed files: {task.name}', f'Base: {base}',
             f'Previous: {previous} (Run {run_text})' if previous else 'Previous: none',
             f'Re-judge: {rejudge}', f'Checks: {checks}', '',
             '| File | Units | Criteria | Fingerprint | Since previous |', '|---|---|---|---|---|']
    lines += [f'| {" | ".join(r)} |' for r in rows]
    copied = [line for line, _n in found] + [f'- Criterion {n} (G3 Rework): {s}' for n, s in rework]
    if copied:
        lines += ['', '## Findings'] + copied
    try:
        (task / ma_schema.CHANGED_FILES).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    except OSError as exc:
        return say(f'cannot write {task / ma_schema.CHANGED_FILES}: {exc}', 1)
    unmapped = sum(1 for r in rows if r[1] == 'unmapped')
    tail = f', {len(changed)} changed since Run {run_text}' if previous else ''
    if from_findings:
        tail += f', {len(from_findings)} criteri{"on" if len(from_findings) == 1 else "a"} from findings'
    if invalid:
        tail += f', {invalid} finding{"" if invalid == 1 else "s"} without a valid criterion tag (Re-judge: all)'
    if review_skipped:
        tail += ', review not read (Verify FAIL in that run)'
    print(f'changed-files: {len(rows)} files, {unmapped} unmapped{tail}')
    print(f'checks: {checks}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
