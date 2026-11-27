#!/usr/bin/env python3
"""Coder copies of a task (architecture 4.6 "Parallel coders in copies"): one copy of the task location per coder unit.

usage: worktree.py create  --location LOC --task TASK_FOLDER --unit u<n> [--unit u<m> ...]
       worktree.py merge   --location LOC --task TASK_FOLDER --unit u<n>
       worktree.py keep    --location LOC --task TASK_FOLDER --unit u<n>
       worktree.py remove  --location LOC --task TASK_FOLDER --unit u<n>
       worktree.py list    --location LOC --task TASK_FOLDER
       worktree.py cleanup --location LOC --task TASK_FOLDER

LOC is the task location (a git repository's top folder, or a folder that is not a repository), TASK_FOLDER the
absolute task folder `<location>/<task_dir>/<task-id>`. A unit's copy is
`<location>/.claude/worktrees/my-agent-<task-id>-<unit>`, a detached linked worktree, in both kinds of location.

Git location: the snapshot is a commit no ref names (a temporary index seeded from the real one gets `add -A`, the
records folder is taken out of it, then `write-tree` and `commit-tree`). No branch is made; the index, the files and HEAD
of the location stay as they are. Non-git location: the copies come from a temporary bare repository, the store
`<task folder>/copy-store`, made by the first `create` and reused by every group. The location stays non-git: every git
call runs with `--git-dir=<store> --work-tree=<location>` (or inside a copy), a fresh empty temporary index, and no global
or system git config and no global excludes file, so only the `.gitignore` files inside the location apply. No `.git`
and no `.gitignore` is created in the location.

create: checks first, each ending in exit 3 with the one line `sequential: <reason>` and no copy: Windows, no git
  program, a location that is not the repository top, a nested repository or submodule, a file list over MAX_BYTES or
  MAX_FILES (the records folder and `.claude/worktrees/` are not counted and not read as nested repositories). Then it runs
  `cd-guard.py` (every create does; its line is printed first), writes the state file once, and makes the copies from one
  snapshot. Prints `worktree: <unit> <path>` per unit, then `base: <short sha>`.
merge: stages the copy (`git add -A`), writes `git diff --cached --binary` to `<task folder>/work/<unit>.patch`, compares
  each path of the diff in the main tree with the copy's base commit (any difference is a conflict, exit 4), applies the
  patch with `git apply` (all or nothing), then compares each file with the copy's (through git, so `.gitattributes`
  conversions do not matter). Prints `merged <unit>: <n> files`, `file: <A|M|D> <path>` lines, an `ignored:` line for
  files the ignore rules exclude (not merged), then `removed: <path>` or `kept: <path> (<cause>)`.
keep: drops the unit from `running` and keeps its copy untouched (`kept: <path> (given up)`).
remove: `git worktree remove --force` (one `--force`: a locked copy is kept) and drops the unit from `running`.
list: `worktree: <unit> <path> (<running|kept>)` lines, `store: <path>` when the store exists, or `worktree: none`.
cleanup: runs `cd-guard.py --remove` first (always, whatever else is wrong) and prints its line. With no copy of this
  task left it deletes the store; it removes what `create` made (the settings file of a non-git location when it holds
  only an empty deny list, `.claude/worktrees`, `.claude`) when it is empty and the state file lists it. A copy left keeps
  the copy and the store (both paths printed). It never deletes the state file. In a git location the
  `.claude/worktrees/` line that `create` adds to `info/exclude` stays after cleanup (local, untracked config).

State file `<task folder>/unit-copies.json`, written only here: `{"running": [...], "created": [...]}`. `running` holds
the units whose copy has not gone through merge, keep or remove; `created` the location-relative paths this tool made
(`.claude`, `.claude/settings.local.json`, `.claude/worktrees`), added once, taken out only by `cleanup` when removed.

exit: 0 done; 1 not done (a git or file error; the cause is printed; `create` removes the copies it made, `merge` applied
nothing); 2 bad arguments (nothing changed); 3 sequential (one `sequential: <reason>` line, no copy); 4 `conflict <unit>:
<cause>` (nothing applied, copy kept); 5 `differs <unit>: <files>` (patch applied, copy kept).
"""
import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from ma_path import same, under  # noqa: E402

WORKTREES = Path('.claude') / 'worktrees'
SETTINGS = '.claude/settings.local.json'
PREFIX = 'my-agent-'
STATE = 'unit-copies.json'
STORE = 'copy-store'
MAX_BYTES = 100_000_000
MAX_FILES = 20_000
SNAPSHOT_ID = {'GIT_AUTHOR_NAME': 'my-agent', 'GIT_AUTHOR_EMAIL': 'my-agent@localhost',
               'GIT_COMMITTER_NAME': 'my-agent', 'GIT_COMMITTER_EMAIL': 'my-agent@localhost'}
GUARD_OK = ('cd-guard: added ', 'cd-guard: taken over ', 'cd-guard: present')


class Fail(Exception):
    def __init__(self, text, code=1):
        super().__init__(text)
        self.text, self.code = text, code


class Sequential(Fail):
    """The copies cannot be used; the one printed line is `sequential: <reason>`."""
    def __init__(self, reason):
        super().__init__(f'sequential: {reason}', 3)


class Ctx:
    """The task location and how to run git in it: plain `git -C <location>` in a git location, the store plus a clean
    environment in a non-git one."""
    def __init__(self, location: Path, task: Path):
        self.location, self.task = location, task
        self.store = task / STORE
        self.nongit = False
        self.records = None   # the records folder relative to the location (posix), or None when outside it
        records = task.parent
        if under(records, location) and not same(records, location):
            self.records = records.relative_to(location).as_posix()

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if k not in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE')}
        if self.nongit:
            env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
        env.update(extra)
        return env

    def cmd(self, *args, copy=None, bare=False):
        cmd = ['git']
        if self.nongit:
            cmd += ['-c', f'core.excludesFile={self.store / "no-global-excludes"}']
        if copy is not None:
            return cmd + ['-C', str(copy), *args]
        if self.nongit:
            cmd += ['--git-dir', str(self.store)] + ([] if bare else ['--work-tree', str(self.location)])
            return cmd + list(args)
        return cmd + ['-C', str(self.location), *args]

    def run(self, *args, copy=None, bare=False, env=None, binary=False, check=True, inp=None):
        """CompletedProcess of one git call; with `check`, Fail with git's first stderr line on a non-zero exit."""
        r = subprocess.run(self.cmd(*args, copy=copy, bare=bare), capture_output=True, input=inp,
                           cwd=None if copy is not None else str(self.location), env=env or self.env())
        if check and r.returncode != 0:
            err = r.stderr.decode('utf-8', 'replace').strip().splitlines()
            raise Fail(f'git {args[0]} failed: {err[0] if err else f"exit {r.returncode}"}')
        if not binary:
            r.stdout = r.stdout.decode('utf-8', 'surrogateescape')
        return r

    def out(self, *args, **kw):
        return self.run(*args, **kw).stdout


def worktree_path(location: Path, task: Path, unit: str) -> Path:
    return location / WORKTREES / f'{PREFIX}{task.name}-{unit}'


def is_copy(path: Path) -> bool:
    return (path / '.git').is_file()


def load_state(task: Path):
    try:
        data = json.loads((task / STATE).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, ValueError):
        raise Fail(f'{task / STATE} cannot be read as the state file')
    if not isinstance(data, dict) or not isinstance(data.get('running', []), list) \
            or not isinstance(data.get('created', []), list):
        raise Fail(f'{task / STATE} is not a state file')
    return {'running': list(data.get('running', [])), 'created': list(data.get('created', []))}


def save_state(task: Path, state: dict) -> None:
    path = task / STATE
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def drop_running(task: Path, unit: str) -> None:
    state = load_state(task)
    if state and unit in state['running']:
        state['running'].remove(unit)
        save_state(task, state)


def skipped(path: str, ctx: Ctx) -> bool:
    """The records folder and the copies folder are never read as the location's files."""
    p = path.rstrip('/')
    for skip in (ctx.records, WORKTREES.as_posix()):
        if skip and (p == skip or p.startswith(skip + '/')):
            return True
    return False


def split_z(text: str) -> list:
    return [p for p in text.split('\0') if p]


# -- checks before anything is hashed or written --------------------------------------------------------------------

def fresh_index(ctx: Ctx) -> dict:
    """Environment with an empty temporary index (never `<store>/index`), for the non-git calls that read an index."""
    return ctx.env(GIT_INDEX_FILE=str(ctx.store / f'my-agent-empty-{os.getpid()}.index'))


def file_list(ctx: Ctx) -> list:
    env = fresh_index(ctx) if ctx.nongit else None
    out = ctx.out('ls-files', '-z', '--cached', '--others', '--exclude-standard', env=env)
    seen, listed = set(), []
    for p in split_z(out):
        if p not in seen and not skipped(p, ctx):
            seen.add(p)
            listed.append(p)
    return listed


def check_nested(ctx: Ctx, listed: list) -> None:
    nested = [p for p in listed if p.endswith('/') and (ctx.location / p / '.git').exists()]
    nested += [p for p in listed if p.rsplit('/', 1)[-1] == '.git']
    if not ctx.nongit:
        for entry in split_z(ctx.out('ls-files', '-s', '-z')):
            mode, _, path = entry.partition('\t')
            if mode.startswith('160000') and not skipped(path, ctx):
                nested.append(path)
    if nested:
        raise Sequential(f'nested repository or submodule: {nested[0]}')


def check_size(ctx: Ctx, listed: list) -> None:
    total = count = 0
    for p in listed:
        if p.endswith('/'):
            continue
        try:
            st = os.lstat(ctx.location / p)
        except OSError:
            continue
        count += 1
        total += st.st_size
    if total > MAX_BYTES or count > MAX_FILES:
        raise Sequential(f'the task location holds {total} bytes in {count} files, over the copy limit of {MAX_BYTES} '
                         f'bytes or {MAX_FILES} files; excluding large folders with an ignore file keeps the parallel run')


def detect(ctx: Ctx) -> None:
    """Set ctx.nongit; a git location must be the repository top."""
    try:
        r = subprocess.run(['git', '-C', str(ctx.location), 'rev-parse', '--show-toplevel'], capture_output=True,
                           text=True, env=ctx.env())
    except OSError as e:
        raise Fail(f'git cannot run: {e}')
    if r.returncode != 0 or not r.stdout.strip():
        ctx.nongit = True
        return
    if not same(Path(r.stdout.strip()).resolve(), ctx.location):
        raise Sequential(f'{ctx.location} is not the top folder of its git repository')


def exclude_lines(ctx: Ctx) -> list:
    lines = [f'/{WORKTREES.as_posix()}/']
    if ctx.records:
        lines.append(f'/{ctx.records}/')
    return lines


def init_store(ctx: Ctx) -> bool:
    """Make the store when it is missing; True when made now. Its info/exclude keeps the copies and the records out."""
    made = not ctx.store.exists()
    if made:
        r = subprocess.run(['git', 'init', '--bare', '-q', str(ctx.store)], capture_output=True, text=True,
                           env=ctx.env())
        if r.returncode != 0:
            shutil.rmtree(ctx.store, ignore_errors=True)
            err = r.stderr.strip().splitlines()
            raise Fail(f'git init failed: {err[0] if err else f"exit {r.returncode}"}')
    path = ctx.store / 'info' / 'exclude'
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding='utf-8') if path.exists() else ''
    add = [line for line in exclude_lines(ctx) if line not in old.splitlines()]
    if add:
        path.write_text(old + ('' if not old or old.endswith('\n') else '\n') + '\n'.join(add) + '\n', encoding='utf-8')
    return made


def exclude_worktrees(ctx: Ctx) -> None:
    if ctx.run('check-ignore', '-q', f'{WORKTREES.as_posix()}/', check=False).returncode == 0:
        return
    path = Path(ctx.out('rev-parse', '--git-path', 'info/exclude').strip())
    path = path if path.is_absolute() else ctx.location / path
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding='utf-8') if path.exists() else ''
    path.write_text(old + ('' if not old or old.endswith('\n') else '\n') + f'{WORKTREES.as_posix()}/\n',
                    encoding='utf-8')


def run_guard(location: Path, task: Path, *flags) -> tuple:
    """(exit code, first line) of cd-guard.py."""
    r = subprocess.run([sys.executable, str(Path(__file__).with_name('cd-guard.py')), *flags, '--location', str(location),
                        '--task', str(task)], capture_output=True, text=True)
    lines = (r.stdout.strip() or r.stderr.strip()).splitlines()
    return r.returncode, lines[0] if lines else 'cd-guard: no output'


# -- snapshot and copies ---------------------------------------------------------------------------------------------

def records_pathspec(ctx: Ctx, copy=None) -> list:
    """`:(exclude)<records>` only when git does not ignore the records folder: git refuses an exclude pathspec that names
    an ignored path (defect 1 of the first version)."""
    if not ctx.records:
        return []
    if ctx.run('check-ignore', '-q', f'{ctx.records}/', copy=copy, check=False).returncode == 1:
        return [f':(exclude){ctx.records}']
    return []


def snapshot(ctx: Ctx, unit: str) -> str:
    """A commit of the location's current files (HEAD as parent in a git location); no ref and no real index change."""
    if ctx.nongit:
        index = ctx.store / f'my-agent-snapshot-{os.getpid()}.index'
        real = None
    else:
        index = Path(ctx.out('rev-parse', '--git-path', f'my-agent-snapshot-{os.getpid()}.index').strip())
        index = index if index.is_absolute() else ctx.location / index
        real = Path(ctx.out('rev-parse', '--git-path', 'index').strip())
        real = real if real.is_absolute() else ctx.location / real
    env = ctx.env(GIT_INDEX_FILE=str(index), **SNAPSHOT_ID)
    try:
        if real is not None and real.exists():
            index.write_bytes(real.read_bytes())
        ctx.run('add', '-A', '--', '.', *records_pathspec(ctx), env=env)
        if ctx.records:
            ctx.run('rm', '-r', '-q', '--cached', '--ignore-unmatch', '--', ctx.records, env=env)
        tree = ctx.out('write-tree', env=env).strip()
    finally:
        index.unlink(missing_ok=True)
    head = ''
    if not ctx.nongit:
        head = ctx.run('rev-parse', '--verify', '-q', 'HEAD', check=False).stdout.strip()
    parent = ['-p', head] if head else []
    return ctx.out('commit-tree', tree, *parent, '-m', f'my-agent snapshot {ctx.task.name} {unit}',
                   env=ctx.env(**SNAPSHOT_ID)).strip()


def remove_line(ctx: Ctx, wt: Path) -> str:
    r = ctx.run('worktree', 'remove', '--force', str(wt), bare=True, check=False)
    if r.returncode == 0:
        return f'removed: {wt}'
    err = r.stderr.decode('utf-8', 'replace').strip().splitlines()
    return f'kept: {wt} ({err[0] if err else f"exit {r.returncode}"})'


def create(ctx: Ctx, units: list) -> int:
    made_store = False
    try:
        if ctx.nongit:
            made_store = init_store(ctx)
        listed = file_list(ctx)
        check_nested(ctx, listed)
        check_size(ctx, listed)
    except Fail:
        if made_store:
            shutil.rmtree(ctx.store, ignore_errors=True)
        raise
    state = load_state(ctx.task)
    first = state is None
    noted = [p for p in ('.claude', SETTINGS) if not (ctx.location / p).exists()] if first else []
    code, line = run_guard(ctx.location, ctx.task)
    if code != 0 or not line.startswith(GUARD_OK):
        if made_store:
            shutil.rmtree(ctx.store, ignore_errors=True)
        cause = line[len('cd-guard: not added: '):] if line.startswith('cd-guard: not added: ') else line
        raise Sequential(f'session guard not added: {cause}')
    print(line)
    if first:
        state = {'running': [], 'created': noted}
        save_state(ctx.task, state)
    made = []
    try:
        if not ctx.nongit:
            exclude_worktrees(ctx)
        sha = snapshot(ctx, ','.join(units))
        for unit in units:
            wt = worktree_path(ctx.location, ctx.task, unit)
            if os.path.lexists(wt):
                raise Fail(f'copy exists: {wt}')
            for folder in (Path('.claude'), WORKTREES):
                if not (ctx.location / folder).exists() and folder.as_posix() not in state['created']:
                    state['created'].append(folder.as_posix())
            ctx.run('worktree', 'add', '--detach', str(wt), sha, bare=True)
            made.append((unit, wt))
    except (Fail, OSError) as e:
        for _, wt in made:
            remove_line(ctx, wt)
            if wt.exists():
                shutil.rmtree(wt, ignore_errors=True)
        ctx.run('worktree', 'prune', bare=True, check=False)
        save_state(ctx.task, state)
        raise e if isinstance(e, Fail) else Fail(str(e))
    state['running'] += [u for u, _ in made if u not in state['running']]
    save_state(ctx.task, state)
    for unit, wt in made:
        print(f'worktree: {unit} {wt}')
    print(f'base: {sha[:12]}')
    return 0


# -- merge -----------------------------------------------------------------------------------------------------------

def blob_state(ctx: Ctx, root: Path, path: str, copy=None):
    """(mode, blob id) of a path as git would record it, from the file under `root`; None when absent. Hashed through
    git (`--path`), so the location's `.gitattributes` conversions apply, as they do when git applies a patch."""
    full = root / path
    try:
        st = os.lstat(full)
    except (FileNotFoundError, NotADirectoryError):
        return None
    if stat.S_ISLNK(st.st_mode):
        blob = ctx.out('hash-object', '--stdin', inp=os.readlink(full).encode('utf-8', 'surrogateescape'),
                       copy=copy, binary=True).decode().strip()
        return ('120000', blob)
    if stat.S_ISREG(st.st_mode):
        blob = ctx.out('hash-object', f'--path={path}', '--', str(full), copy=copy).strip()
        return ('100755' if st.st_mode & stat.S_IXUSR else '100644', blob)
    return ('other', '')


def base_states(ctx: Ctx, wt: Path) -> dict:
    states = {}
    for entry in split_z(ctx.out('ls-tree', '-r', '-z', 'HEAD', copy=wt)):
        meta, _, path = entry.partition('\t')
        mode, _, rest = meta.partition(' ')
        states[path] = (mode, rest.split(' ')[1])
    return states


def ignored_files(ctx: Ctx, wt: Path) -> list:
    return split_z(ctx.out('ls-files', '--others', '--ignored', '--exclude-standard', '--directory', '-z', copy=wt))


def print_ignored(ctx: Ctx, wt: Path) -> None:
    ignored = ignored_files(ctx, wt)
    if ignored:
        print(f'ignored: {len(ignored)} not merged: {", ".join(ignored[:5])}' + (', …' if len(ignored) > 5 else ''))


def merge(ctx: Ctx, unit: str) -> int:
    wt = worktree_path(ctx.location, ctx.task, unit)
    state = load_state(ctx.task)
    if not is_copy(wt) or not state or unit not in state['running']:
        raise Fail(f'no running copy for {unit}: {wt}', 2)
    try:
        return do_merge(ctx, unit, wt)
    except Fail as e:
        drop_running(ctx.task, unit)
        print(e.text if e.code == 4 else f'worktree: not done: {e.text}')
        print(f'kept: {wt} (not merged)')
        return e.code
    except OSError as e:
        drop_running(ctx.task, unit)
        print(f'worktree: not done: {e}')
        print(f'kept: {wt} (not merged)')
        return 1


def do_merge(ctx: Ctx, unit: str, wt: Path) -> int:
    ctx.run('add', '-A', '--', '.', *records_pathspec(ctx, copy=wt), copy=wt)
    parts = split_z(ctx.out('diff', '--cached', '--name-status', '--no-renames', '-z', 'HEAD', copy=wt))
    changes = list(zip(parts[0::2], parts[1::2]))
    if not changes:
        drop_running(ctx.task, unit)
        print(f'merged {unit}: 0 files')
        print_ignored(ctx, wt)
        print(remove_line(ctx, wt))
        return 0
    patch = ctx.task / 'work' / f'{unit}.patch'
    patch.parent.mkdir(parents=True, exist_ok=True)
    patch.write_bytes(ctx.out('diff', '--cached', '--binary', '--no-renames', 'HEAD', copy=wt, binary=True))
    base = base_states(ctx, wt)
    changed = [path for _, path in changes if blob_state(ctx, ctx.location, path) != base.get(path)]
    if changed:
        raise Fail(f'conflict {unit}: changed in the main tree since the copy was made: {", ".join(changed)}', 4)
    env = ctx.env()
    r = subprocess.run(ctx.cmd('apply', '--whitespace=nowarn', str(patch)), capture_output=True, text=True,
                       cwd=str(ctx.location), env=env)
    if r.returncode != 0:
        lines = r.stderr.strip().splitlines()[:3]
        raise Fail(f'conflict {unit}: {" / ".join(lines) or f"exit {r.returncode}"}', 4)
    drop_running(ctx.task, unit)
    differ = []
    for status, path in changes:
        if status == 'D':
            if os.path.lexists(ctx.location / path):
                differ.append(path)
        elif blob_state(ctx, ctx.location, path) != blob_state(ctx, wt, path, copy=wt):
            differ.append(path)
    print(f'merged {unit}: {len(changes)} files')
    for status, path in changes:
        print(f'file: {status} {path}')
    print_ignored(ctx, wt)
    if differ:
        print(f'differs {unit}: {", ".join(differ)}')
        print(f'kept: {wt} (differs)')
        return 5
    print(remove_line(ctx, wt))
    return 0


def keep(ctx: Ctx, unit: str) -> int:
    wt = worktree_path(ctx.location, ctx.task, unit)
    if not is_copy(wt):
        raise Fail(f'no copy for {unit}: {wt}')
    drop_running(ctx.task, unit)
    print(f'kept: {wt} (given up)')
    return 0


def remove(ctx: Ctx, unit: str) -> int:
    wt = worktree_path(ctx.location, ctx.task, unit)
    if not is_copy(wt):
        raise Fail(f'no copy for {unit}: {wt}')
    line = remove_line(ctx, wt)
    drop_running(ctx.task, unit)
    print(line)
    return 0


# -- list and cleanup ------------------------------------------------------------------------------------------------

def find_copies(ctx: Ctx) -> list:
    """[(unit, path)] of this task's copies: git's worktree list, plus a scan of the copies folder."""
    prefix = f'{PREFIX}{ctx.task.name}-'
    folder = ctx.location / WORKTREES
    found = {}
    if not ctx.nongit or ctx.store.exists():
        r = ctx.run('worktree', 'list', '--porcelain', bare=True, check=False)
        for line in r.stdout.splitlines() if r.returncode == 0 else []:
            if line.startswith('worktree '):
                path = Path(line[len('worktree '):])
                if path.name.startswith(prefix) and same(path.parent, folder) and path.exists():
                    found[path.name[len(prefix):]] = path
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            if path.name.startswith(prefix) and path.name[len(prefix):] not in found:
                found[path.name[len(prefix):]] = path
    return sorted(found.items(), key=lambda kv: (len(kv[0]), kv[0]))


def listing(ctx: Ctx) -> int:
    state = load_state(ctx.task)
    running = state['running'] if state else []
    found = find_copies(ctx)
    for unit, path in found:
        print(f'worktree: {unit} {path} ({"running" if unit in running else "kept"})')
    if not found:
        print('worktree: none')
    if ctx.store.exists():
        print(f'store: {ctx.store}')
    return 0


def cleanup(location: Path, task: Path) -> int:
    ctx = Ctx(location, task)
    state = load_state(task) or {'running': [], 'created': []}
    prefix = f'{PREFIX}{task.name}-'
    folder = location / WORKTREES
    copies = sorted(p for p in folder.iterdir() if p.name.startswith(prefix)) if folder.is_dir() else []
    for path in copies:
        print(f'cleanup: kept copy {path}')
    if copies:
        if ctx.store.exists():
            print(f'cleanup: store kept: {ctx.store}')
    elif ctx.store.exists():
        shutil.rmtree(ctx.store)
        print(f'cleanup: store removed: {ctx.store}')
    removed = []
    created = state['created']
    settings = location / SETTINGS
    if SETTINGS in created and settings.is_file():
        try:
            empty = json.loads(settings.read_text(encoding='utf-8')) == {'permissions': {'deny': []}}
        except (OSError, UnicodeDecodeError, ValueError):
            empty = False
        if empty and not (location / '.git').exists():   # a git location keeps its settings file
            settings.unlink()
            removed.append(SETTINGS)
    for rel in (WORKTREES.as_posix(), '.claude'):
        path = location / rel
        if rel in created and path.is_dir() and not any(path.iterdir()):
            path.rmdir()
            removed.append(rel)
    if removed:
        print(f'cleanup: removed empty: {", ".join(removed)}')
        state['created'] = [p for p in created if p not in removed]
        if (task / STATE).exists():
            save_state(task, state)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='Coder copies of a my-agent task.')
    p.add_argument('action', choices=['create', 'merge', 'keep', 'remove', 'list', 'cleanup'])
    p.add_argument('--location', required=True)
    p.add_argument('--task', required=True)
    p.add_argument('--unit', action='append')
    a = p.parse_args(argv)
    location, task = Path(a.location).expanduser().resolve(), Path(a.task).expanduser().resolve()
    if a.action == 'cleanup':
        try:
            print(run_guard(location, task, '--remove')[1])   # first and unconditionally
        except OSError as e:
            print(f'cd-guard: not removed: {e}')
    units = a.unit or []
    if a.action == 'create':
        if not units:
            p.error('--unit u<n> is required')
    elif a.action in ('merge', 'keep', 'remove'):
        if len(units) != 1:
            p.error('exactly one --unit u<n> is required')
    elif units:
        p.error(f'{a.action} takes no --unit')
    if any(not (u[:1] == 'u' and u[1:].isdigit()) for u in units) or len(set(units)) != len(units):
        p.error('--unit must be u<n>, each once')
    if not location.is_dir():
        p.error(f'--location is not a folder: {location}')
    if a.action != 'cleanup' and not under(task, location):
        p.error('--task must be inside --location')
    try:
        if a.action == 'cleanup':
            return cleanup(location, task)
        if a.action == 'create':
            if os.name == 'nt':
                raise Sequential('Windows: the session guard does not work there')
            if shutil.which('git') is None:
                raise Sequential('no git program')
        ctx = Ctx(location, task)
        detect(ctx)
        if a.action == 'create':
            return create(ctx, units)
        if a.action == 'merge':
            return merge(ctx, units[0])
        if a.action == 'keep':
            return keep(ctx, units[0])
        if a.action == 'remove':
            return remove(ctx, units[0])
        return listing(ctx)
    except Fail as e:
        print(e.text if e.code == 3 else f'worktree: not done: {e.text}')
        return e.code
    except OSError as e:
        print(f'worktree: not done: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
