"""Reader finder: which unittest files read a changed document (docs-only check rounds).

A document is a repo-relative path with a `docs` folder segment and no `tests` segment (`is_document`).
`parse_discover` reads a `[cd <dir> && ]python3 -m unittest discover ...` command, `covered_files` lists the test
files discover would load, `reading_tests` says which of them read a document, and `narrowed_command` writes the
command that runs only some files. The test sources are read with `ast`; nothing is run or imported.

A test file reads a document D when one of these holds (all paths are compared resolved, against `location`):
1. Roots. A name is bound to `Path(__file__).resolve().parents[k]`, `Path(__file__).parent...` or a `.parent` chain
   of these. So is a name imported with `from <module> import <name>` (or used as `<module>.<name>`) from a
   module in the test file's own folder that binds it so. A name bound to `<root> / 'a' / 'b'` (module level or
   function local) is a derived root. A root built from anything else (a temp folder, `self.L`, a parameter, a loaded
   module's attribute) never resolves. A name that is rebound or is a parameter or loop variable is dropped.
2. Concrete path. A `/` chain or a `.joinpath(...)` (also `.with_name('x')`) from a resolved root, whose other parts
   are all string constants (split on `/`), is D.
3. Variable tail. A `/` chain or `.joinpath` from a resolved folder F ends in a non-constant (a name, a parameter,
   `*parts`). D lies under F, and D's path relative to F is in the file as one string constant or as consecutive
   string-constant positional arguments of one call (the arguments joined with `/`).
4. Generator hop, one level. A concrete path (rule 2) names an existing `.py` file that is not a test file covered by
   the command. Rules 1-3 then apply to that file's source with its own roots, and what it reads counts for the
   test file.
5. Not counted. A string constant never joined to a resolved root, an attribute of a loaded module, and paths under
   unresolved roots. A file that does not parse reads nothing.

Refinements of the rules above, found with the real sources:
- Constants in `..` parts are normalised (`os.path.normpath`) when a chain is joined.
- A concrete path that is a folder is only a root: documents are files, so it equals no document.
- `.resolve()`, `.absolute()` and `.expanduser()` pass a path through unchanged.

Accepted limit: a test file that reads a document in a way these rules do not see (a glob over a folder, a path
from a string variable, `os.path`, a path passed through an object attribute) is not selected, so it is not run
in a docs-only round.
"""
import ast
import fnmatch
import os
import re
import shlex
from pathlib import Path, PurePosixPath

DEFAULT_PATTERN = 'test*.py'
_MODULE_NAME = re.compile(r'[_a-z]\w*\.py$', re.I)    # what unittest discover loads
_PASS = ('resolve', 'absolute', 'expanduser')
_FLAG_TOKENS = {'-v': 'verbose', '--verbose': 'verbose', '-q': 'quiet', '--quiet': 'quiet', '-b': 'buffer',
                '--buffer': 'buffer', '-f': 'failfast', '--failfast': 'failfast', '-c': 'catch', '--catch': 'catch'}
_VALUE_OPTS = {'-s': 'start', '--start-directory': 'start', '-p': 'pattern', '--pattern': 'pattern',
               '-t': 'top', '--top-level-directory': 'top', '-k': 'k'}
_RUN_CAP = 12     # longest run of constant arguments joined when looking for a relative path


def is_document(rel_path) -> bool:
    """True when a folder segment (every segment but the last) is `docs` and none is `tests`."""
    parts = PurePosixPath(str(rel_path).replace('\\', '/')).parts
    dirs = parts[:-1]
    return 'docs' in dirs and 'tests' not in dirs


# ---------------------------------------------------------------- discover commands

def _parse(command):
    """Parse a discover command into (cd, python, opts, flags-and-options in order) or None."""
    if not isinstance(command, str):
        return None
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        return None
    cd = None
    if toks[:1] == ['cd']:
        if len(toks) < 4 or toks[2] != '&&':
            return None
        cd, toks = toks[1], toks[3:]
    if len(toks) < 4 or toks[0] not in ('python3', 'python') or toks[1:4] != ['-m', 'unittest', 'discover']:
        return None
    python, args = toks[0], toks[4:]
    items = []          # ('opt', name, value) | ('flag', token) | ('pos', value), in order
    positional = []
    i = 0
    while i < len(args):
        t = args[i]
        if t in _FLAG_TOKENS:
            items.append(('flag', t))
        elif t in _VALUE_OPTS:
            if i + 1 >= len(args) or args[i + 1].startswith('-'):
                return None
            items.append(('opt', t, args[i + 1]))
            i += 1
        elif t.startswith('--') and '=' in t and t.split('=', 1)[0] in _VALUE_OPTS:
            name, value = t.split('=', 1)
            items.append(('opt', name, value))
        elif t.startswith('-') or any(c in t for c in '&|;<>()'):
            return None
        else:
            positional.append(len(items))
            items.append(('pos', t))
        i += 1
    if len(positional) > 3:
        return None
    return cd, python, items, positional


def parse_discover(command):
    """`{'cd', 'start', 'pattern', 'tokens'}` for a unittest discover command, else None.

    `tokens` are the arguments after `discover`. Any other token or a shell operator gives None.
    """
    parsed = _parse(command)
    if parsed is None:
        return None
    cd, _python, items, positional = parsed
    start, pattern = '.', DEFAULT_PATTERN
    names = ('start', 'pattern')
    for n, idx in enumerate(positional[:2]):
        if n < len(names):
            if names[n] == 'start':
                start = items[idx][1]
            else:
                pattern = items[idx][1]
    for item in items:
        if item[0] == 'opt' and _VALUE_OPTS[item[1]] == 'start':
            start = item[2]
        elif item[0] == 'opt' and _VALUE_OPTS[item[1]] == 'pattern':
            pattern = item[2]
    tokens = []
    for item in items:
        tokens.extend(item[1:])
    return {'cd': cd, 'start': start, 'pattern': pattern, 'tokens': tokens}


def covered_files(command, location):
    """The test files discover would load, sorted, or None for an unrecognised command or a missing start folder."""
    p = parse_discover(command)
    if p is None:
        return None
    base = Path(location)
    if p['cd']:
        base = base / p['cd']
    base = base / p['start']
    if not base.is_dir():
        return None
    out = []

    def scan(folder):
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            return
        for e in entries:
            if e.is_file():
                if _MODULE_NAME.match(e.name) and fnmatch.fnmatch(e.name, p['pattern']):
                    out.append(e)
            elif e.is_dir() and (e / '__init__.py').is_file():
                scan(e)

    scan(base)
    return sorted(out)


def narrowed_command(command, files) -> str:
    """The command run once per file in `files` (`-p <file>`), joined with ` && `, with the `cd` prefix once in front."""
    parsed = _parse(command)
    if parsed is None:
        return command
    cd, python, items, positional = parsed
    runs = []
    for f in files:
        name = shlex.quote(Path(str(f)).name)
        args = []
        replaced = False
        pos_seen = 0
        for item in items:
            if item[0] == 'flag':
                args.append(item[1])
            elif item[0] == 'opt':
                if _VALUE_OPTS[item[1]] == 'pattern':
                    args += ['-p', name]
                    replaced = True
                else:
                    args += [item[1], shlex.quote(item[2])]
            else:
                pos_seen += 1
                if pos_seen == 1:
                    args.append(shlex.quote(item[1]))
                elif pos_seen == 2:
                    continue            # the positional pattern; `-p` follows below
                else:
                    args += ['-t', shlex.quote(item[1])]
        if not replaced:
            args += ['-p', name]
        runs.append(' '.join([python, '-m', 'unittest', 'discover'] + args))
    body = ' && '.join(runs)
    return ('cd %s && %s' % (shlex.quote(cd), body)) if cd else body


# ---------------------------------------------------------------- reading a source

class _Tail:
    """A chain from a resolved folder that ends in a non-constant part."""
    def __init__(self, base):
        self.base = base


def _norm(path):
    return Path(os.path.normpath(str(path)))


class _Analysis:
    """What one source file binds and refers to: concrete paths, variable tails and its string constants."""

    def __init__(self, path, loader):
        self.path = path
        self.loader = loader
        self.env = {}
        self.modules = {}
        self.concrete = set()
        self.tails = set()
        self.joined = set()
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (OSError, SyntaxError, ValueError, RecursionError):
            return
        try:
            self._constants(tree)
            queue = []
            self._stmts(tree.body, self.env, queue)
            while queue:
                fn, env = queue.pop(0)
                local = dict(env)
                a = fn.args
                for arg in a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x]:
                    local.pop(arg.arg, None)
                self._stmts(fn.body, local, queue)
        except RecursionError:
            pass

    # constants
    def _constants(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.joined.add(node.value)
            elif isinstance(node, ast.Call):
                run = []
                for arg in list(node.args) + [None]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        run.append(arg.value)
                        continue
                    for i in range(len(run)):
                        for j in range(i + 2, min(len(run), i + _RUN_CAP) + 1):
                            self.joined.add('/'.join(s.strip('/') for s in run[i:j]))
                    run = []

    # statements, in source order
    def _stmts(self, stmts, env, queue):
        for s in stmts:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                env.pop(s.name, None)
                queue.append((s, dict(env)))
                continue
            if isinstance(s, ast.ClassDef):
                self._stmts(s.body, env, queue)
                env.pop(s.name, None)
                continue
            for child in ast.iter_child_nodes(s):
                if isinstance(child, (ast.stmt, ast.ExceptHandler)) or type(child).__name__ == 'match_case':
                    continue
                for node in ast.walk(child):
                    self._see(node, env)
            if isinstance(s, (ast.Assign, ast.AnnAssign)):
                value = self._ev(s.value, env) if s.value is not None else None
                targets = s.targets if isinstance(s, ast.Assign) else [s.target]
                for t in targets:
                    if isinstance(t, ast.Name) and isinstance(value, Path):
                        env[t.id] = value
                    else:
                        self._drop(t, env)
            elif isinstance(s, (ast.For, ast.AsyncFor)):
                self._drop(s.target, env)
            elif isinstance(s, ast.AugAssign):
                self._drop(s.target, env)
            elif isinstance(s, (ast.With, ast.AsyncWith)):
                for item in s.items:
                    if item.optional_vars is not None:
                        self._drop(item.optional_vars, env)
            elif isinstance(s, (ast.Import, ast.ImportFrom)):
                self._import(s, env)
            for field in ('body', 'orelse', 'finalbody'):
                sub = getattr(s, field, None)
                if isinstance(sub, list) and sub and isinstance(sub[0], ast.stmt):
                    self._stmts(sub, env, queue)
            for h in getattr(s, 'handlers', []) or []:
                if h.name:
                    env.pop(h.name, None)
                self._stmts(h.body, env, queue)
            for case in getattr(s, 'cases', []) or []:
                self._stmts(case.body, env, queue)

    def _drop(self, target, env):
        for node in ast.walk(target):
            if isinstance(node, ast.Name):
                env.pop(node.id, None)

    def _import(self, s, env):
        if isinstance(s, ast.ImportFrom):
            if s.level or not s.module or '.' in s.module:
                for a in s.names:
                    env.pop(a.asname or a.name, None)
                return
            other = self._sibling(s.module)
            for a in s.names:
                name = a.asname or a.name
                if other is not None and isinstance(other.env.get(a.name), Path):
                    env[name] = other.env[a.name]
                else:
                    env.pop(name, None)
        else:
            for a in s.names:
                if '.' in a.name:
                    continue
                other = self._sibling(a.name)
                if other is not None:
                    self.modules[a.asname or a.name] = other.env

    def _sibling(self, module):
        f = self.path.parent / (module + '.py')
        if f == self.path or not f.is_file():
            return None
        return self.loader.get(f)

    # expressions
    def _see(self, node, env):
        if isinstance(node, ast.NamedExpr):
            self._drop(node.target, env)
            return
        if not isinstance(node, (ast.BinOp, ast.Call, ast.Name, ast.Attribute, ast.Subscript)):
            return
        v = self._ev(node, env)
        if isinstance(v, Path):
            self.concrete.add(v)
        elif isinstance(v, _Tail):
            self.tails.add(v.base)

    def _ev(self, node, env):
        """A Path (resolved), a _Tail (resolved folder, non-constant end) or None."""
        if isinstance(node, ast.Name):
            return env.get(node.id)
        if isinstance(node, ast.Attribute):
            if node.attr == 'parent':
                base = self._ev(node.value, env)
                return base.parent if isinstance(base, Path) else None
            if isinstance(node.value, ast.Name) and node.value.id in self.modules and node.value.id not in env:
                v = self.modules[node.value.id].get(node.attr)
                return v if isinstance(v, Path) else None
            return None
        if isinstance(node, ast.Subscript):
            v = node.value
            k = node.slice
            if (isinstance(v, ast.Attribute) and v.attr == 'parents' and isinstance(k, ast.Constant)
                    and isinstance(k.value, int) and k.value >= 0):
                base = self._ev(v.value, env)
                if isinstance(base, Path):
                    parents = base.parents
                    return parents[k.value] if k.value < len(parents) else None
            return None
        if isinstance(node, ast.Call):
            f = node.func
            if (isinstance(f, ast.Name) and f.id == 'Path') or (isinstance(f, ast.Attribute) and f.attr == 'Path'
                                                                  and isinstance(f.value, ast.Name)):
                if (len(node.args) == 1 and isinstance(node.args[0], ast.Name) and node.args[0].id == '__file__'
                        and not node.keywords):
                    return self.path
                return None
            if isinstance(f, ast.Attribute):
                if f.attr in _PASS and not node.args and not node.keywords:
                    base = self._ev(f.value, env)
                    return base if isinstance(base, Path) else None
                if f.attr == 'with_name' and len(node.args) == 1 and _const(node.args[0]) is not None:
                    base = self._ev(f.value, env)
                    return base.with_name(_const(node.args[0])) if isinstance(base, Path) and base.name else None
                if f.attr == 'joinpath' and not node.keywords:
                    base = self._ev(f.value, env)
                    if not isinstance(base, Path):
                        return None
                    return self._join(base, node.args)
            return None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            base = self._ev(node.left, env)
            if not isinstance(base, Path):
                return None
            return self._join(base, [node.right])
        return None

    def _join(self, base, args):
        for n, arg in enumerate(args):
            c = _const(arg)
            if c is None:
                return _Tail(base) if n == len(args) - 1 else None
            base = _norm(base.joinpath(*[p for p in c.split('/') if p]))
        return base

    def reads(self, doc):
        """True when this source refers to the absolute path `doc` by rules 1-3."""
        if doc in self.concrete:
            return True
        for base in self.tails:
            if base in doc.parents:
                rel = doc.relative_to(base).as_posix()
                if rel in self.joined:
                    return True
        return False


def _const(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


class _Loader:
    def __init__(self):
        self.cache = {}

    def get(self, path):
        path = Path(path)
        if path not in self.cache:
            self.cache[path] = None          # a cycle sees an empty module
            self.cache[path] = _Analysis(path, self)
        return self.cache[path] or _Empty


class _EmptyAnalysis:
    env = {}


_Empty = _EmptyAnalysis()


def reading_tests(test_files, documents, location):
    """Map each test file that reads at least one of the repo-relative `documents` to the documents it reads."""
    loc = Path(location).resolve()
    docs = {d: _norm(loc / d) for d in documents}
    tests = {Path(f).resolve() for f in test_files}
    loader = _Loader()
    out = {}
    for f in test_files:
        real = Path(f).resolve()
        main = loader.get(real)
        hops = []
        for p in sorted(getattr(main, 'concrete', ())):
            if p.suffix == '.py' and p != real and p not in tests and p.is_file():
                hops.append(loader.get(p))
        found = {d for d, a in docs.items() if any(x.reads(a) for x in [main] + hops if isinstance(x, _Analysis))}
        if found:
            out[Path(f)] = found
    return out
