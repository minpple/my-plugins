#!/usr/bin/env python3
"""The Intake script of the my-agent skill (step 1): `facts` collects what Intake needs, `create` writes its records.

usage: intake.py facts  [--candidate PATH]... [--cwd DIR] [--data-dir X] [--task-dir Y]
       intake.py create --loc DIR --profile general|research|dev (--slug SLUG | --task-id ID) --request=LINE
                        --model MODEL [--preset NAME] [--gitignore ignore|commit] [--follows TASK-ID] [--auto]
                        [--router-pick PROFILE] [--ask 'FIELDS']... [--answer 'FIELDS']...
                        [--cwd DIR] [--data-dir X] [--task-dir Y]

`--data-dir` and `--task-dir` are the `data_dir` and `task_dir` settings (the raw values or the resolved ones, as
`data-dir.py`); `--cwd` is the run folder (default: the process folder).

facts: writes nothing (no file, no folder, no run-log line). On Codex it first runs the hook-health check of
`data-dir.py` (a problem is named on stderr, nothing is printed, exit 1). Output is `key: value` lines, in this order:
  data:, task_dir:, run: (the run folder), run_git: (its git root, or none), index: (the location
  `<data folder>/active-index.json` gives for the run folder outside git, else none), session: (or none),
  plugin: (`git log -1 --format=%h -- .` of the plugin folder, plus `-dirty` when `git status --porcelain -- .`
  prints a line; none without a commit or outside git), date: (%y%m%d, local time),
  `presets <profile>: <line>` (the lines of `agent-models.py presets` for general, research and dev; a rejected
  file gives one line `presets <profile>: error: <its stderr line>`),
  then one block per candidate task location: `candidate: <path> (<kind>)` and indented lines
    active: none | <task> phase <n> session <s> started <t> | broken (<path of .active>)
    git: true|false
    and only when true: branch: (`(detached)` when empty), uncommitted: <n> followed by up to 10 `path: <porcelain
    line>` lines and `path: ... <k> more` (paths under `<task_dir>/`, `*.pyc` and `__pycache__/` are not counted),
    gitignore: ignored | file | ask (`<task_dir>/` is git-ignored | has a `.gitignore` | neither)
    ids: (folders of `<task_dir>/` that start with `<date>-`, comma-separated, or none)
    listed: yes|no (the location is in `projects.txt`)
  Candidates: inside git, the git root of the run folder (repo); outside git, the index location (index), the data
  folder (data) and the run folder (current); plus every `--candidate PATH` (given). Exit 0; 2 bad arguments.

create: makes every Intake record in a fixed order and starts the monitor. Arguments:
  --loc DIR          the task location (an absolute, existing folder)
  --profile P        general, research or dev (dev needs a git work tree at the location)
  --slug SLUG | --task-id ID   exactly one. SLUG is lowercase letters, digits and hyphens, 30 characters or fewer; the
                     ID is `<date>-<slug>`, then `-b`, `-c` ... when that folder exists. --task-id is exact.
  --request=LINE     the request as the person wrote it: always the `=` form, one line, not empty, kept as is
  --model MODEL      the main session model ID (the `step` line; MISMATCH check)
  --preset NAME      a preset of `agent-models.py presets --profile P`; adds `Models:` and the `models` line
  --gitignore ignore|commit   writes `<task_dir>/.gitignore` (`*` or `# my-agent: commit`); refused when that file
                     exists or the location is not a git work tree
  --follows ID       adds `Follows:` to intake.md
  --auto             writes `delegate state=on how=flag`
  --router-pick P    the Router's profile when the person chose another: writes the `profile` line (not equal to --profile)
  --ask 'FIELDS' / --answer 'FIELDS'   repeatable, kept in the order given; each value is split like a shell line into
                     run-log fields. An ask needs gate=, q= (not starting with --) and rec=; an answer gate= and choice=.
  --loc is the run folder's git root, or (outside git) the run folder, when no index line is needed; otherwise the line
  {"<run folder>": "<location>"} is added to `<data folder>/active-index.json` (other entries are kept).
Order: validate and check the refusals (nothing written), then write: `.gitignore`, the task folder, `.active` (task,
phase 1, session, started), the index line, `intake.md`, the `projects.txt` line (when not listed), start the monitor
(`monitor-up.py`; a failure is only reported), then the run-log lines through `run-log.py`: `step n=1` (with the
baseline `cost` line when a statusline value exists), the asks and answers, `delegate`, `models`, `profile`.
Output: `task:`, `folder:`, the monitor line, every `MISMATCH:` and `PARTIAL:` line of run-log.py, `written:` (what was
written). Exit 0 done; 1 the location has `<task_dir>/.active` or the task folder exists; 2 an invalid argument (both
nothing written); 3 a failure after the first write (stderr `intake: stopped at <what>: <cause>; written: <list>`,
nothing is undone).
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import ma_active  # noqa: E402
import ma_data  # noqa: E402
import ma_host  # noqa: E402

PROFILES = ('general', 'research', 'dev')
SLUG = re.compile(r'[a-z0-9][a-z0-9-]*')
TASK_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')
FIELD_KEY = re.compile(r'[a-z][a-z0-9_-]*')
STAMPED = re.compile(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ')
SLUG_MAX = 30
MAX_PATHS = 10
SCRIPTS = Path(__file__).resolve().parent


def run(cmd, cwd=None):
    """(returncode, stdout, stderr) of a command; (127, '', cause) when it cannot run."""
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, '', str(exc)
    return r.returncode, r.stdout, r.stderr


def git(folder, *args):
    return run(['git', '--no-optional-locks', '-C', str(folder), *args])


def git_root(folder):
    code, out, _ = git(folder, 'rev-parse', '--show-toplevel')
    return out.strip() if code == 0 and out.strip() else None


def resolved(raw):
    try:
        return Path(raw).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def index_location(data, run_folder):
    """The task location `<data>/active-index.json` gives for the run folder (or its nearest ancestor), else None."""
    try:
        index = json.loads((data / 'active-index.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(index, dict):
        return None
    keys = {}
    for k, v in index.items():
        p = resolved(k)
        if p is not None and isinstance(v, str) and v.strip():
            keys[p] = v
    for d in (run_folder, *run_folder.parents):
        if d in keys:
            found = resolved(keys[d])
            return found
    return None


def plugin_value():
    root = ma_host.plugin_root(Path(__file__).resolve().parents[2])
    code, out, _ = git(root, 'log', '-1', '--format=%h', '--', '.')
    value = out.strip() if code == 0 else ''
    if not value:
        return 'none'
    code, out, _ = git(root, 'status', '--porcelain', '--', '.')
    return value + ('-dirty' if code == 0 and out.strip() else '')


def preset_lines(profile, data):
    code, out, err = run([sys.executable, str(SCRIPTS / 'agent-models.py'), 'presets', '--profile', profile,
                          '--data-dir', str(data)])
    if code == 0:
        return [f'presets {profile}: {line}' for line in out.splitlines() if line.strip()] or [f'presets {profile}: none']
    cause = (err.strip().splitlines() or [f'exit {code}'])[0]
    return [f'presets {profile}: error: {cause}']


def derived(path):
    parts = path.split('/')
    return '__pycache__' in parts or path.endswith('.pyc')


def uncommitted(loc, task_dir):
    """(count, porcelain lines) of the changes outside `<task_dir>/`, without derived files."""
    code, out, _ = git(loc, 'status', '--porcelain', '-uall')
    top = git_root(loc)
    prefix = ''
    if top:
        try:
            prefix = (Path(loc).resolve() / task_dir).relative_to(Path(top).resolve()).as_posix() + '/'
        except ValueError:
            prefix = ''
    lines = []
    for line in out.splitlines() if code == 0 else []:
        path = line[3:].rpartition(' -> ')[2].strip('"')
        if (prefix and (path + '/' == prefix or path.startswith(prefix))) or derived(path):
            continue
        lines.append(line)
    return len(lines), lines


def listed_paths(data):
    out = set()
    try:
        lines = ma_data.projects_file(str(data)).read_text(encoding='utf-8').splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            p = resolved(line)
            if p is not None:
                out.add(p)
    return out


def block(loc, kind, args, task_dir, date, listed):
    out = [f'candidate: {loc} ({kind})']
    broken = []
    active = ma_active.read_active(Path(loc), broken, args.task_dir)
    if active:
        out.append(f'  active: {active.task} phase {active.phase} session {active.session} started {active.started}')
    elif broken:
        out.append(f'  active: broken ({broken[0]})')
    else:
        out.append('  active: none')
    code, text, _ = git(loc, 'rev-parse', '--is-inside-work-tree') if Path(loc).is_dir() else (1, '', '')
    inside = code == 0 and text.strip() == 'true'
    out.append(f'  git: {"true" if inside else "false"}')
    if inside:
        _, branch, _ = git(loc, 'branch', '--show-current')
        out.append(f'  branch: {branch.strip() or "(detached)"}')
        count, lines = uncommitted(loc, task_dir)
        out.append(f'  uncommitted: {count}')
        out.extend(f'  path: {line}' for line in lines[:MAX_PATHS])
        if count > MAX_PATHS:
            out.append(f'  path: … {count - MAX_PATHS} more')
        folder = Path(loc) / task_dir
        if git(loc, 'check-ignore', '-q', f'{folder}/')[0] == 0:
            out.append('  gitignore: ignored')
        elif (folder / '.gitignore').exists():
            out.append('  gitignore: file')
        else:
            out.append('  gitignore: ask')
    try:
        ids = sorted(p.name for p in (Path(loc) / task_dir).iterdir() if p.is_dir() and p.name.startswith(date + '-'))
    except OSError:
        ids = []
    out.append(f'  ids: {", ".join(ids) or "none"}')
    out.append(f'  listed: {"yes" if resolved(loc) in listed else "no"}')
    return out


def facts(args) -> int:
    if ma_host.env_host() == 'codex':
        problems = ma_host.hook_health(ma_host.session_id())
        if problems:
            print(ma_host.health_message(problems), file=sys.stderr)
            return 1
    data = ma_data.data_dir(args.data_dir)
    task_dir = ma_data.task_dir(args.task_dir)
    run_folder = resolved(args.cwd or os.getcwd()) or Path(os.getcwd())
    root = git_root(run_folder)
    index = None if root else index_location(data, run_folder)
    date = datetime.now().strftime('%y%m%d')
    out = [f'data: {data}', f'task_dir: {task_dir}', f'run: {run_folder}', f'run_git: {root or "none"}',
           f'index: {index or "none"}', f'session: {ma_host.session_id() or "none"}', f'plugin: {plugin_value()}',
           f'date: {date}']
    for profile in PROFILES:
        out.extend(preset_lines(profile, data))
    if root:
        candidates = [(root, 'repo')]
    else:
        candidates = [(index, 'index')] if index else []
        candidates += [(data, 'data'), (run_folder, 'current')]
    candidates += [(Path(c).expanduser(), 'given') for c in args.candidate]
    listed = listed_paths(data)
    seen = []
    for loc, kind in candidates:
        key = resolved(loc)
        if key in seen:
            continue
        seen.append(key)
        out.extend(block(loc, kind, args, task_dir, date, listed))
    print('\n'.join(out))
    return 0


class Refuse(Exception):
    def __init__(self, code, text):
        super().__init__(text)
        self.code = code


class Stop(Exception):
    def __init__(self, what, cause, written=()):
        super().__init__(f'{what}: {cause}')
        self.what, self.cause, self.written = what, cause, list(written)


class Pairs(argparse.Action):
    """`--ask` and `--answer` share one list, so their order is the order given."""
    def __call__(self, parser, namespace, values, option_string=None):
        items = list(getattr(namespace, self.dest) or [])
        items.append((self.const, values))
        setattr(namespace, self.dest, items)


def popup_fields(kind, text):
    """The run-log fields of one `--ask` / `--answer` value, or a Refuse."""
    try:
        fields = shlex.split(text)
    except ValueError as exc:
        raise Refuse(2, f'--{kind} {text!r} is not a quoted field list ({exc})')
    got = {}
    for item in fields:
        key, sep, value = item.partition('=')
        if not sep or not FIELD_KEY.fullmatch(key):
            raise Refuse(2, f'--{kind} field {item!r} is not key=value')
        got[key] = value
    need = ('gate', 'q', 'rec') if kind == 'ask' else ('gate', 'choice')
    missing = [k for k in need if not got.get(k)]
    if missing:
        raise Refuse(2, f'--{kind} needs {", ".join(k + "=" for k in need)} (missing {", ".join(k + "=" for k in missing)})')
    if kind == 'ask':
        if got['q'].startswith('--'):
            raise Refuse(2, '--ask q= must not start with --')
        bad = sorted(set(got) & {'prose', 'other', 'pre'})
        if bad:
            raise Refuse(2, f'--ask takes no {", ".join(k + "=" for k in bad)} (they belong on the answer)')
    return fields


def preset_names(profile, data):
    """The preset names of `agent-models.py presets`, or a Refuse when the file is rejected."""
    code, out, err = run([sys.executable, str(SCRIPTS / 'agent-models.py'), 'presets', '--profile', profile,
                          '--data-dir', str(data)])
    if code != 0:
        cause = (err.strip().splitlines() or [f'exit {code}'])[0]
        raise Refuse(2, f'--preset cannot be checked: {cause}')
    return [line.partition(':')[0].strip() for line in out.splitlines() if line.strip()]


def inside_work_tree(loc):
    code, out, _ = git(loc, 'rev-parse', '--is-inside-work-tree')
    return code == 0 and out.strip() == 'true'


def read_index(data):
    """(dict, None) of `<data>/active-index.json` ({} when missing), or (None, cause) when it cannot be used."""
    path = data / 'active-index.json'
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return {}, None
    except (OSError, UnicodeDecodeError) as exc:
        return None, f'{path} is unreadable: {type(exc).__name__}'
    try:
        index = json.loads(text)
    except ValueError:
        return None, f'{path} is not JSON'
    return (index, None) if isinstance(index, dict) else (None, f'{path} is not a JSON object')


def plan(args):
    """Validate every argument and check the refusals; returns the plan dict. Writes nothing."""
    data = ma_data.data_dir(args.data_dir)
    task_dir = ma_data.task_dir(args.task_dir)
    date = datetime.now().strftime('%y%m%d')
    if not args.loc or not Path(args.loc).is_absolute() or not Path(args.loc).is_dir():
        raise Refuse(2, '--loc must be an absolute path of an existing folder')
    loc = Path(args.loc)
    if args.profile not in PROFILES:
        raise Refuse(2, '--profile must be general, research or dev')
    if (args.slug is None) == (args.task_id is None):
        raise Refuse(2, 'give exactly one of --slug and --task-id')
    if args.slug is not None and not (SLUG.fullmatch(args.slug) and len(args.slug) <= SLUG_MAX):
        raise Refuse(2, f'--slug must be lowercase letters, digits and hyphens, {SLUG_MAX} characters or fewer')
    if args.task_id is not None and not TASK_ID.fullmatch(args.task_id):
        raise Refuse(2, '--task-id must be a folder name (letters, digits, . _ -)')
    request = args.request
    if request is None or not request.strip():
        raise Refuse(2, '--request=<line> is needed and must not be empty')
    if ''.join(request.splitlines()) != request:
        raise Refuse(2, '--request must be one line')
    if not args.model or not args.model.strip() or len(args.model.split()) != 1:
        raise Refuse(2, '--model needs the main session model ID')
    if args.follows is not None and not TASK_ID.fullmatch(args.follows):
        raise Refuse(2, '--follows must be a task ID')
    if args.gitignore not in (None, 'ignore', 'commit'):
        raise Refuse(2, '--gitignore must be ignore or commit')
    if args.router_pick is not None and (args.router_pick not in PROFILES or args.router_pick == args.profile):
        raise Refuse(2, '--router-pick must be a profile other than --profile')
    in_git = inside_work_tree(loc)
    if args.profile == 'dev' and not in_git:
        raise Refuse(2, '--profile dev needs a git work tree at the location')
    root = ma_data.task_root(loc, args.task_dir)
    if args.gitignore and not in_git:
        raise Refuse(2, '--gitignore needs a git work tree at the location')
    if args.gitignore and (root / '.gitignore').exists():
        raise Refuse(2, f'--gitignore: {root / ".gitignore"} exists')
    if args.preset is not None and args.preset not in preset_names(args.profile, data):
        raise Refuse(2, f'--preset {args.preset!r} is not a preset of the {args.profile} profile')
    popups = [(kind, popup_fields(kind, text)) for kind, text in args.popups or []]
    broken = []
    active = ma_active.read_active(loc, broken, args.task_dir)
    if active or broken or (root / '.active').exists():
        which = f'task {active.task}' if active else 'unreadable'
        raise Refuse(1, f'{root / ".active"} exists ({which})')
    if args.task_id is not None:
        task = args.task_id
    else:
        task = f'{date}-{args.slug}'
        for suffix in [''] + [f'-{chr(c)}' for c in range(ord('b'), ord('z') + 1)]:
            if not (root / (task + suffix)).exists():
                task += suffix
                break
        else:
            raise Refuse(1, f'task folders {task}, {task}-b ... all exist')
    if (root / task).exists():
        raise Refuse(1, f'task folder {root / task} exists')
    run_folder = resolved(args.cwd or os.getcwd()) or Path(os.getcwd())
    top = git_root(run_folder)
    home = resolved(top) if top else run_folder
    index_key = None if resolved(loc) == home else str(top or run_folder)
    index = None
    if index_key:
        index, cause = read_index(data)
        if index is None:
            raise Refuse(2, cause)
    return {'data': data, 'task_dir': task_dir, 'loc': loc, 'root': root, 'task': task, 'folder': root / task,
            'popups': popups, 'index_key': index_key, 'index': index, 'request': request}


def monitor_line(data, task_dir):
    code, out, err = run([sys.executable, str(SCRIPTS.parents[1] / 'monitor' / 'monitor-up.py'), '--data-dir', str(data),
                          '--task-dir', task_dir])
    lines = [x for x in out.splitlines() if x.startswith('monitor:')]
    if code == 0 and lines:
        return lines[-1]
    cause = (err.strip().splitlines() or out.strip().splitlines() or [f'exit {code}'])[0]
    return f'monitor: not started ({cause})'


def run_log(p, kind, fields, model=None):
    """One `run-log.py` call; (stdout lines, None), or a Stop on a failure."""
    cmd = [sys.executable, str(SCRIPTS / 'run-log.py'), kind, *fields]
    if model:
        cmd += ['--model', model]
    cmd += ['--cwd', str(p['loc']), '--data-dir', str(p['data']), '--task-dir', p['task_dir']]
    code, out, err = run(cmd)
    if code != 0:
        raise Stop(f'run-log {kind}', (err.strip() or out.strip() or f'exit {code}').splitlines()[0])
    return out.splitlines()


def write(p, args):
    """Write the records in the order of new-task.md items 5-10. Returns (written, monitor, report lines)."""
    written, stage = [], 'start'
    try:
        stage = '.gitignore'
        if args.gitignore:
            p['root'].mkdir(parents=True, exist_ok=True)
            (p['root'] / '.gitignore').write_text('*\n' if args.gitignore == 'ignore' else '# my-agent: commit\n',
                                                  encoding='utf-8')
            written.append('.gitignore')
        stage = 'task folder'
        p['folder'].mkdir(parents=True)
        written.append('task folder')
        stage = '.active'
        sid = ma_host.session_id() or ''
        started = datetime.now().strftime('%Y-%m-%d %H:%M')
        (p['root'] / '.active').write_text(f'task: {p["task"]}\nphase: 1\nsession:{" " + sid if sid else ""}\n'
                                           f'started: {started}\n', encoding='utf-8')
        written.append('.active')
        stage = 'data folder'
        p['data'].mkdir(parents=True, exist_ok=True)
        if p['index_key']:
            stage = 'active-index.json'
            index = dict(p['index'])
            index[p['index_key']] = str(p['loc'])
            (p['data'] / 'active-index.json').write_text(json.dumps(index, indent=2, ensure_ascii=False) + '\n',
                                                         encoding='utf-8')
            written.append('active-index.json line')
        stage = 'intake.md'
        lines = ['Status: active', f'my-agent: {plugin_value()}', f'Location: {p["loc"]}', f'Profile: {args.profile}',
                 f'Task: {p["task"]}', f'Request: {p["request"]}']
        if args.follows:
            lines.append(f'Follows: {args.follows}')
        if args.preset:
            lines.append(f'Models: {args.preset}')
        (p['folder'] / 'intake.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        written.append('intake.md')
        stage = 'projects.txt'
        if resolved(p['loc']) not in listed_paths(p['data']):
            target = ma_data.projects_file(str(p['data']))
            try:
                old = target.read_text(encoding='utf-8')
            except OSError:
                old = ''
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(old + ('\n' if old and not old.endswith('\n') else '') + f'{p["loc"]}\n', encoding='utf-8')
            written.append('projects.txt line')
    except OSError as exc:
        raise Stop(stage, exc, written) from None
    monitor = monitor_line(p['data'], p['task_dir'])
    report, count = [], 0
    calls = [('step', ['n=1', 'name=Intake'], args.model)]
    calls += [(kind, fields, None) for kind, fields in p['popups']]
    if args.auto:
        calls.append(('delegate', ['state=on', 'how=flag'], None))
    if args.preset:
        calls.append(('models', [f'preset={args.preset}', 'source=file'], None))
    if args.router_pick:
        calls.append(('profile', [f'from={args.router_pick}', f'to={args.profile}', 'back=-', 'archive=-'], None))
    try:
        for kind, fields, model in calls:
            out = run_log(p, kind, fields, model)
            count += sum(1 for line in out if STAMPED.match(line))
            report += [line for line in out if line.startswith(('MISMATCH:', 'PARTIAL:'))]
    except Stop as stop:
        raise Stop(stop.what, stop.cause, written + ([f'run-log {count} lines'] if count else [])) from None
    written.append(f'run-log {count} lines')
    return written, monitor, report


def create(args) -> int:
    try:
        p = plan(args)
    except Refuse as refusal:
        print(f'intake: {refusal}; nothing written', file=sys.stderr)
        return refusal.code
    try:
        written, monitor, report = write(p, args)
    except Stop as stop:
        print(f'intake: stopped at {stop.what}: {stop.cause}; written: {", ".join(stop.written) or "nothing"}',
              file=sys.stderr)
        return 3
    print('\n'.join([f'task: {p["task"]}', f'folder: {p["folder"]}', monitor, *report, f'written: {", ".join(written)}']))
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('facts', 'create'):
        p = sub.add_parser(name)
        p.add_argument('--data-dir', default=None)
        p.add_argument('--task-dir', default=None)
        p.add_argument('--cwd', default=None)
    sub.choices['facts'].add_argument('--candidate', action='append', default=[])
    c = sub.choices['create']
    c.add_argument('--loc')   # the values are checked by plan(), so a refusal names its cause and "nothing written"
    c.add_argument('--profile')
    c.add_argument('--slug')
    c.add_argument('--task-id')
    c.add_argument('--request')
    c.add_argument('--model')
    c.add_argument('--preset')
    c.add_argument('--gitignore')
    c.add_argument('--follows')
    c.add_argument('--auto', action='store_true')
    c.add_argument('--router-pick')
    c.add_argument('--ask', action=Pairs, dest='popups', const='ask')
    c.add_argument('--answer', action=Pairs, dest='popups', const='answer')
    return ap


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.cmd == 'facts':
        return facts(args)
    return create(args)


if __name__ == '__main__':
    sys.exit(main())
