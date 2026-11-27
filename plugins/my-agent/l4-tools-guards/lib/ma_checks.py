"""Check commands, working-tree fingerprint and check-record status (shared by check-commands.py and changed-files.py).

The check record `<task folder>/checks.md` is written only by `check-commands.py`:

    # Check record: <task-id>
    Fingerprint: head=<40 hex | none> files=<12 hex> paths=<n>
    Taken: <YYYY-MM-DD HH:MM:SS>
    Result: <n> run, <f> failed, <k> not run

    - 01 `<command>` (<source>) → exit <code> | <summary> | <secs> s | checks/01.log
    - 02 `<command>` (<source>) → timeout after <n> s | <summary> | <n> s | checks/02.log
    - 03 `<command>` (<source>) → not run (scope: Environment: <reason>)

    ## Fingerprint paths
    - <path relative to the git root> <12 hex | deleted>

The second line is `Fingerprint: none (not a git location)`, `Fingerprint: none (tree changed by the run: <n> paths)` or
`Fingerprint: none (git status failed after the run)` when there is no fingerprint; then there is no `## Fingerprint paths`
section.

The fingerprint is taken from `git status --porcelain=v1 -z -uall` (every changed, deleted or untracked file, both paths of a
rename), without the task records folder; each path is hashed with `file_fp`; `files=` is the first 12 hex characters of sha1
over the sorted lines `<path>\\t<fp>\\n`; `head=` is `git rev-parse HEAD` or `none`. Git-ignored files are not in it.

`status` compares the record with the current tree: `current`, `stale (HEAD moved)`, `stale (<n> paths differ: <paths>)`,
`missing`, `no fingerprint`, or `not needed (no check commands)`; and, in a docs-only round (architecture Q48),
`docs-only (run due; <d> paths differ: <up to 5 paths>; test files: <names | none>)`,
`docs-only (checked; <d> document paths since <oldest kept id>: <up to 5 paths>)` and `stale (kept record <id> missing)`.

Docs-only round. A round is docs-only when the current record is a base (it parses, has a fingerprint and passed: `0 failed`
and no line with a nonzero exit or a timeout), its `head` is the current HEAD, at least one path differs between its
`## Fingerprint paths` and the tree, every differing path is a document (`ma_readers.is_document`), and every kept record the
base names (below) is readable, has the same head and differs from the tree only in documents. `docs_round` decides this for the
script and the map. Then `check-commands.py` narrows each unittest discover command to the test files that read a changed
document (`ma_readers`), carries a command no test file reads, and runs every other command in full. A first run, a failed or
fingerprint-less base, a moved HEAD or any non-document path gives the full run.
A narrowed or carried record adds these line forms; the backticked text is always the unnarrowed run text, and `Result:` gets a
`, <c> carried` suffix:

    - 01 `<command>` (<source>) → narrowed to <file>, <file>: exit 0 | <summary> | <secs> s | checks/01.log; rest carried from <id>/<nn>
    - 02 `<command>` (<source>) → carried from <id>/<nn>: exit 0 | <summary> | <secs> s | checks/kept/<id>/<nn>.log

`<id>` is `<yymmdd-HHMMSS>` from the `Taken:` line of the kept record (`record_id`; a second record with the same id gets `-2`).
The script keeps the base under `<task folder>/checks/kept/<id>/` (`checks.md` as written, and its `<nn>.log` files; inside a kept
record `checks/<nn>.log` means `checks/kept/<id>/<nn>.log`). A reference always names a line where the command ran (full or
narrowed), never a carried line: a carried base line passes its own reference on. `kept_closure` follows the references through
the kept records. A narrowed line's summary joins one `Ran <n> tests in <t>s, OK|FAILED …` part per `Ran` line with `; `.
"""
import hashlib
import math
import re
import subprocess
import sys
from pathlib import Path

import ma_readers
import ma_schema

MIN_LIMIT = 60        # seconds: the floor of a command's time limit
DEFAULT_LIMIT = 600   # seconds: the limit when `explore.md` gives no duration

BACKTICK = re.compile(r'`([^`]+)`')
DURATION = re.compile(r'\((\d+(?:\.\d+)?)\s*s\)')
ENVIRONMENT = re.compile(r'(?m)^\s*-\s*Environment:\s*(.+?)\s*$')
NOT_RUN_HERE = re.compile(r'^not run here\s*\((.*)\)$')
REPLACED_BY = re.compile(r'^replaced by\s+(.+)$')
FAILS_BEFORE = re.compile(r'^fails before the task\s*\((.*)\)$')
FP_LINE = re.compile(r'^Fingerprint: head=(none|[0-9a-f]{40}) files=([0-9a-f]{12}) paths=(\d+)$')
FP_NONE = re.compile(r'^Fingerprint: none \((.*)\)$')
RAN_LINE = re.compile(r'^Ran \d+ tests? in [\d.]+s')
REF = r'\d{6}-\d{6}(?:-\d+)?/\d{2,}'     # `<record id>/<line nn>`
LOG_PATH = r'checks/(?:kept/[\w.-]+/)?\d+\.log'
RECORD_LINE = re.compile(
    r'^- (?P<n>\d{2,}) `(?P<command>.+?)` \((?P<source>.+?)\) → (?:'
    r'(?:narrowed to (?P<files>.+?): |carried from (?P<cref>' + REF + r'): )?'
    r'(?:exit (?P<code>-?\d+)|timeout after (?P<limit>\d+) s) \| (?P<summary>.*) \| (?P<secs>\d+) s \| '
    r'(?P<log>' + LOG_PATH + r')(?:; rest carried from (?P<rest>' + REF + r'))?'
    r'|not run \(scope: Environment: (?P<reason>.*)\))$')
TAKEN = re.compile(r'^\d\d(\d\d)-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)$')
PATH_LINE = re.compile(r'^- (.+) ([0-9a-f]{12}|deleted)$')


# --- fingerprint ---

def file_fp(path: Path) -> str:
    """First 12 hex characters of sha1 of the file's bytes; `deleted` when it cannot be read."""
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()[:12]
    except OSError:
        return 'deleted'


def _git(root, *args):
    """Raw stdout of a git command in `root`, or None when git fails."""
    try:
        res = subprocess.run(['git', '-C', str(root), '-c', 'core.quotepath=false', *args],
                             capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout if res.returncode == 0 else None


def git_root(location):
    """The git top-level folder of `location`, or None when it is not a git location."""
    out = _git(location, 'rev-parse', '--show-toplevel')
    return Path(out.decode('utf-8', 'surrogateescape').strip()) if out and out.strip() else None


def fingerprint(location, records_folder):
    """{'head', 'files', 'paths': {path: fp}} of the working tree at `location`, or None when it is not a git location.
    Paths under `records_folder` (the task's own records folder) are left out."""
    root = git_root(location)
    if root is None:
        return None
    out = _git(root, 'status', '--porcelain=v1', '-z', '-uall')
    if out is None:
        return None
    try:
        skip = Path(records_folder).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        skip = None
    tokens = out.decode('utf-8', 'surrogateescape').split('\0')
    paths, i = [], 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if len(tok) < 4:
            continue
        paths.append(tok[3:])
        if 'R' in tok[:2] or 'C' in tok[:2]:   # a rename or copy lists its source path next
            if i < len(tokens) and tokens[i]:
                paths.append(tokens[i])
            i += 1
    paths = {p: file_fp(root / p) for p in paths if not (skip and (p == skip or p.startswith(skip + '/')))}
    head = _git(root, 'rev-parse', 'HEAD')
    head = head.decode().strip() if head and head.strip() else 'none'
    lines = ''.join(f'{p}\t{paths[p]}\n' for p in sorted(paths))
    return {'head': head, 'files': hashlib.sha1(lines.encode('utf-8', 'surrogateescape')).hexdigest()[:12],
            'paths': paths}


def differing_paths(before: dict, after: dict) -> list:
    """Sorted paths whose hash differs between two `paths` dicts (a path missing on one side counts)."""
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


# --- check commands ---

def applies(profile, plan_text) -> bool:
    """True in the dev profile, and in the general profile when the plan has a `my-agent:coder` unit."""
    if profile == 'dev':
        return True
    if profile != 'general':
        return False
    in_units = False
    for line in ma_schema.section_lines(plan_text, 'Work units') or []:
        if ma_schema.UNIT_HEAD.match(line):
            in_units = True
        elif in_units and re.match(r'^\s*-\s*Agent:.*my-agent:coder', line):
            return True
    return False


def unit_commands(plan_text) -> list:
    """[(unit id, [command])]: the backticked spans on a unit's `- Check commands:` line, plus the first span of each
    nested `  - ` bullet under it."""
    out, in_check = [], False
    for line in ma_schema.section_lines(plan_text, 'Work units') or []:
        head = ma_schema.UNIT_HEAD.match(line)
        if head:
            out.append((head.group(1), []))
            in_check = False
            continue
        if not out:
            continue
        key = None if line[:1].isspace() else ma_schema.UNIT_KEY.match(line)
        if key:
            in_check = key.group(1) == 'Check commands'
            if in_check:
                out[-1][1].extend(c.strip() for c in BACKTICK.findall(key.group(2)))
        elif in_check and re.match(r'\s+-\s', line):
            first = BACKTICK.search(line)
            if first:
                out[-1][1].append(first.group(1).strip())
    return out


def explore_commands(explore_text) -> list:
    """[(command, seconds or None)]: the first backticked span of each `- ` line under `## Check commands`, with the
    first `(<n> s)` duration after it."""
    out = []
    for line in ma_schema.section_lines(explore_text, 'Check commands') or []:
        if not line.startswith('- '):
            continue
        m = BACKTICK.search(line)
        if m:
            d = DURATION.search(line, m.end())
            out.append((m.group(1).strip(), float(d.group(1)) if d else None))
    return out


def environment(text) -> dict:
    """{command: (kind, value)} from the `- Environment:` lines: kind `not run` (value: reason), `replaced` (value: the
    replacement command) or `fails before` (value: the tests). Backticks are stripped."""
    out = {}
    for raw in ENVIRONMENT.findall(text or ''):
        raw = re.sub(r"\s*\(the person's choice\)\s*$", '', raw.replace('`', ''))   # the mark of a settled line
        parts = re.split(r'\s[—–]\s', raw, maxsplit=1)
        if len(parts) != 2:
            continue
        command, rest = parts[0].strip(), parts[1].strip()
        for pattern, kind in ((NOT_RUN_HERE, 'not run'), (REPLACED_BY, 'replaced'), (FAILS_BEFORE, 'fails before')):
            m = pattern.match(rest)
            if m:
                out[command] = (kind, m.group(1).strip())
                break
    return out


def time_limit(command, durations) -> int:
    """Twice the duration of the matching explore line, or twice the longest duration for another command; at least
    MIN_LIMIT; DEFAULT_LIMIT when no duration is given."""
    known = {c: d for c, d in durations if d is not None}
    if not known:
        return DEFAULT_LIMIT
    d = known.get(command)
    d = 2 * (d if d is not None else max(known.values()))
    return max(MIN_LIMIT, math.ceil(d))


def command_list(plan_text, explore_text, env_text) -> list:
    """The commands to run, in order, duplicates removed: [{command (as listed), run (as run), source, not_run (reason or
    None), limit}]. Unit commands come first in plan order, then the explore commands."""
    order, sources = [], {}
    for uid, cmds in unit_commands(plan_text):
        for c in cmds:
            if c not in sources:
                order.append(c)
            sources.setdefault(c, []).append(uid)
    durations = explore_commands(explore_text)
    for c, _d in durations:
        if c not in sources:
            order.append(c)
        if 'explore' not in sources.setdefault(c, []):
            sources[c].append('explore')
    env = environment(env_text)
    out = []
    for c in order:
        label = ', '.join(sorted(sources[c], key=lambda s: s != 'explore'))
        entry = {'command': c, 'run': c, 'source': label, 'not_run': None}
        kind, value = env.get(c, (None, None))
        if kind == 'not run':
            entry['not_run'] = value
        elif kind == 'replaced':
            entry['run'], entry['source'] = value, f'{label}; replaces `{c}`'
        elif kind == 'fails before':
            entry['source'] = f'{label}; fails before the task: {value}'
        entry['limit'] = time_limit(entry['run'], durations)
        out.append(entry)
    return out


def _read(path: Path, strict: bool) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return ''
    except (OSError, UnicodeDecodeError):
        if strict:
            raise
        return ''


def commands_for(task: Path, profile, plan_text, strict=False) -> list:
    """The command list of a task folder; [] when the script does not apply. `strict`: an unreadable explore.md or
    scope.md raises instead of counting as empty."""
    if not applies(profile, plan_text):
        return []
    explore = _read(task / 'explore.md', strict)
    scope = task / 'scope.md'
    env = _read(scope, strict) if scope.is_file() else plan_text
    return command_list(plan_text, explore, env)


# --- record ---

def summary_of(output: str) -> str:
    """One `Ran <n> tests in <t>s, OK|FAILED …` part per unittest `Ran` line (the first OK/FAILED line after it), joined with
    `; `; else the last non-blank line (200 characters), else `(no output)`."""
    lines = [l.rstrip() for l in output.splitlines()]
    ran = [i for i, line in enumerate(lines) if RAN_LINE.match(line)]
    parts = []
    for k, i in enumerate(ran):
        end = ran[k + 1] if k + 1 < len(ran) else len(lines)
        tail = [l for l in lines[i + 1:end] if l.startswith('OK') or l.startswith('FAILED')]
        if tail:
            parts.append(f'{RAN_LINE.match(lines[i]).group(0)}, {tail[-1]}')
    if parts:
        return '; '.join(parts)
    spoken = [l for l in lines if l.strip()]
    return spoken[-1].strip()[:200] if spoken else '(no output)'


def parse_record(text):
    """{task, head, files, count, none_reason, taken, result, lines, paths} of a checks.md, or None when it does not
    parse. `lines` holds {n, command, source, kind (`exit`, `timeout`, `not run`, `narrowed`, `carried`), outcome (`exit` or
    `timeout`; None for a not-run line), code (exit lines), limit (timeout lines), summary, secs, log, reason (not-run lines),
    files (narrowed lines: the test file names), ref (`<id>/<nn>`: a carried line's source, a narrowed line's `rest carried
    from`, else None)}."""
    rows = (text or '').splitlines()
    if len(rows) < 4 or not rows[0].startswith('# Check record: '):
        return None
    rec = {'task': rows[0][len('# Check record: '):].strip(), 'head': None, 'files': None, 'count': None,
           'none_reason': None, 'lines': [], 'paths': {}}
    m = FP_LINE.match(rows[1])
    if m:
        rec['head'], rec['files'], rec['count'] = m.group(1), m.group(2), int(m.group(3))
    else:
        m = FP_NONE.match(rows[1])
        if not m:
            return None
        rec['none_reason'] = m.group(1)
    if not rows[2].startswith('Taken: ') or not rows[3].startswith('Result: '):
        return None
    rec['taken'], rec['result'] = rows[2][len('Taken: '):].strip(), rows[3][len('Result: '):].strip()
    in_paths = False
    for line in rows[4:]:
        if line.startswith('## '):
            in_paths = line.strip() == '## Fingerprint paths'
            continue
        if not line.strip():
            continue
        if in_paths:
            m = PATH_LINE.match(line)
            if not m:
                return None
            rec['paths'][m.group(1)] = m.group(2)
            continue
        m = RECORD_LINE.match(line)
        if not m:
            return None
        g = m.groupdict()
        item = {'n': g['n'], 'command': g['command'], 'source': g['source'], 'code': None, 'limit': None,
                'summary': None, 'secs': None, 'log': None, 'reason': None, 'outcome': None, 'files': None, 'ref': None}
        if g['code'] is None and g['limit'] is None:
            item.update(kind='not run', reason=g['reason'])
        else:
            if g['code'] is not None:
                item.update(outcome='exit', code=int(g['code']))
            else:
                item.update(outcome='timeout', limit=int(g['limit']))
            item.update(kind=item['outcome'], summary=g['summary'], secs=int(g['secs']), log=g['log'])
            if g['files'] is not None:
                item.update(kind='narrowed', files=g['files'].split(', '), ref=g['rest'])
            elif g['cref'] is not None:
                item.update(kind='carried', ref=g['cref'])
        rec['lines'].append(item)
    return rec


def passed(rec) -> bool:
    """A record counts as a base only when it has a fingerprint, says `0 failed` and no line failed (a nonzero exit or a timeout)."""
    if not rec or rec.get('head') is None:
        return False
    m = re.search(r'(\d+) failed', rec['result'])
    if not m or int(m.group(1)):
        return False
    return all(l['kind'] == 'not run' or (l['outcome'] == 'exit' and l['code'] == 0) for l in rec['lines'])


def record_id(rec):
    """`<yymmdd-HHMMSS>` from the record's `Taken:` line, or None."""
    m = TAKEN.match(rec.get('taken') or '') if rec else None
    return f'{m.group(1)}{m.group(2)}{m.group(3)}-{m.group(4)}{m.group(5)}{m.group(6)}' if m else None


def _kept_record(task: Path, kid: str):
    try:
        return parse_record((task / ma_schema.CHECKS_LOGS / ma_schema.CHECKS_KEPT / kid / ma_schema.CHECKS)
                            .read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError):
        return None


def kept_closure(task: Path, rec) -> dict:
    """{kept id: its parsed record, or None when missing or unreadable} for every kept record that `rec` names, followed
    through the lines the references name, in the order found."""
    out, todo = {}, [(l['ref'], l) for l in rec['lines'] if l.get('ref')]
    seen = set()
    while todo:
        ref, _line = todo.pop(0)
        kid, nn = ref.split('/')
        if (kid, nn) in seen:
            continue
        seen.add((kid, nn))
        if kid not in out:
            out[kid] = _kept_record(task, kid)
        for l in (out[kid] or {}).get('lines', []):
            if l['n'] == nn and l.get('ref'):
                todo.append((l['ref'], l))
    return out


def _only_documents(kept, now):
    """The non-document paths in which a kept record differs from the tree, plus `HEAD` when its head differs; [] when the
    kept record is a usable base (a fingerprint, the same head, only documents differ)."""
    if kept is None or kept['head'] is None:
        return ['no fingerprint']
    bad = ['HEAD'] if kept['head'] != now['head'] else []
    return bad + [p for p in differing_paths(kept['paths'], now['paths']) if not ma_readers.is_document(p)]


def _base_line(base, run):
    """The passing full or narrowed or carried line of `base` for the command text `run`, or None."""
    for l in base['lines']:
        if l['command'] == run and l['kind'] != 'not run' and l['outcome'] == 'exit' and l['code'] == 0:
            return l
    return None


def _narrowing_plan(entries, base, docs, location):
    """[{entry, action (`not run`, `full`, `carried`, `narrowed`), base (the base line, or None), files (narrowed: test file
    names sorted), run (narrowed: the command text of the && chain)}] in the order of `entries`."""
    plan = []
    for entry in entries:
        item = {'entry': entry, 'action': 'full', 'base': None, 'files': [], 'run': entry['run']}
        plan.append(item)
        if entry['not_run'] is not None:
            item['action'] = 'not run'
            continue
        line = _base_line(base, entry['run'])
        covered = ma_readers.covered_files(entry['run'], location) if line else None
        if line is None or covered is None:
            continue
        item['base'] = line
        readers = ma_readers.reading_tests(covered, docs, location)
        if not readers:
            item['action'] = 'carried'
            continue
        item['action'] = 'narrowed'
        item['files'] = sorted({Path(f).name for f in readers})
        item['run'] = ma_readers.narrowed_command(entry['run'], item['files'])
    return plan


def docs_round(task: Path, location, profile, plan_text, entries=None) -> dict:
    """The decision of the check record against the tree, for `check-commands.py` and the map: {kind, status, ...}.
    `kind` is `full` (a full run is due or not needed: `status` is the 0.37.0 value), `run due` (a docs-only round: also
    `docs` (the differing documents), `plan` (see `_narrowing_plan`), `base` (the parsed base record), `files` (the narrowed
    test file names)) or `checked` (a narrowed or carried record equal to the tree whose kept records differ from it only in
    documents). Never raises: a failure falls back to the 0.37.0 `stale (…)` value."""
    try:
        return _decide(task, location, profile, plan_text, entries)
    except Exception as e:   # the map and the script must keep working; a failure means no docs-only round
        print(f'docs_round failed, a full run is due: {type(e).__name__}: {e}', file=sys.stderr)
        return {'kind': 'full', 'status': 'stale (0 paths differ: none)'}


def _decide(task, location, profile, plan_text, entries):
    if entries is None:
        entries = commands_for(task, profile, plan_text)
    if not entries:
        return {'kind': 'full', 'status': 'not needed (no check commands)'}
    try:
        rec = parse_record((task / ma_schema.CHECKS).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError):
        rec = None
    if rec is None:
        return {'kind': 'full', 'status': 'missing'}
    if rec['head'] is None:
        return {'kind': 'full', 'status': 'no fingerprint'}
    now = fingerprint(location, task)
    if now is None:
        return {'kind': 'full', 'status': 'no fingerprint'}
    if now['head'] != rec['head']:
        return {'kind': 'full', 'status': 'stale (HEAD moved)'}
    closure = kept_closure(task, rec)
    for kid, kept in closure.items():
        if kept is None:
            return {'kind': 'full', 'status': f'stale (kept record {kid} missing)'}
    narrowed_record = any(l['kind'] in ('narrowed', 'carried') for l in rec['lines'])
    if now['files'] == rec['files']:
        if not narrowed_record:
            return {'kind': 'full', 'status': 'current'}
        for kid in sorted(closure):
            bad = _only_documents(closure[kid], now)
            if bad:
                return {'kind': 'full', 'status': f'stale (kept record {kid} differs: {", ".join(bad[:5])})'}
        oldest = min(closure) if closure else None
        diff = differing_paths(closure[oldest]['paths'], now['paths']) if oldest else []
        return {'kind': 'checked', 'status': f'docs-only (checked; {len(diff)} document paths since {oldest}: '
                                             f'{", ".join(diff[:5]) or "none"})'}
    diff = differing_paths(rec['paths'], now['paths'])
    if not diff:
        return {'kind': 'full', 'status': 'stale (0 paths differ: none)'}   # the hash differs but no path is listed
    stale = {'kind': 'full', 'status': f'stale ({len(diff)} paths differ: {", ".join(diff[:5])})'}
    root = git_root(location)
    if (not passed(rec) or not all(ma_readers.is_document(p) for p in diff) or root is None
            or root.resolve() != Path(location).resolve()
            or any(_only_documents(kept, now) for kept in closure.values())):
        return stale
    plan = _narrowing_plan(entries, rec, diff, location)
    files = sorted({f for item in plan for f in item['files']})
    return {'kind': 'run due', 'docs': diff, 'plan': plan, 'base': rec, 'files': files,
            'status': f'docs-only (run due; {len(diff)} paths differ: {", ".join(diff[:5])}; '
                      f'test files: {", ".join(files) or "none"})'}


def status(task: Path, location, profile, plan_text) -> str:
    """The check-record status of a task folder (see the module docstring); `location` is the task location."""
    return docs_round(task, location, profile, plan_text)['status']
