"""What a Bash command line writes, reads, or copies from (architecture 4.4 "what is blocked", 4.5 "Bash for L2 judges",
4.12 "limiting read paths too", "Inline interpreter code"). Best effort by design: the forms it knows are pinned case
by case in tests/test_bash.py. `write_targets` does not read inline interpreter code (`python3 -c`, a heredoc fed to
`node`); `interpreter_writes` reads it, for scope-guard only (the other hooks keep `write_targets` as it is). The
contents of a script file (`python3 tool.py`, `-m mod`) stay outside both: the accepted risk of 4.4 "remaining risk".
What it cannot follow
(command substitution outside single quotes, a heredoc left open, a `cd` to a variable, a symlink made and written
through in one command) fails closed: None. A variable is followed only when `NAME=<literal>` is a bare assignment that
always runs, nothing else sets or names `NAME`, and the line has no command that can set a variable unseen
(`_literal_vars`).
"""
import ast
import os
import re
import shlex
from pathlib import Path
from typing import List, NamedTuple, Optional

OPS = ';&|()<>\n'
HEREDOC = re.compile(r'(?<!<)<<(?!<)-?[ \t]*')
SEP_PIECE = re.compile(r'&&|\|\||\|&|;;|[;&|()\n]')
COMPOUND = {'if', 'then', 'else', 'elif', 'while', 'until', 'do', 'for', 'case', 'select', 'function', '{'}
PIPE = {'|', '|&'}
VAR_PATH_NOT = re.compile(r'://|^[sy]/|[\^\\|()<>"\'`]')
ASSIGN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')
NOT_PATH = re.compile(r'[\^$\\|(){}<>"\'`]|://|^[sy]/')
PREFIX = {'sudo', 'doas', 'env', 'command', 'time', 'nohup', 'nice', 'exec', 'builtin', 'timeout', 'xargs',
          'setsid'}
PREFIX_VALUE = {'sudo': {'-u', '-g', '-h', '-p', '-C', '-D', '-r', '-t', '-U', '-T'}, 'doas': {'-u', '-C'},
                'env': {'-u', '-C', '-S', '--unset', '--chdir', '--split-string'}, 'nice': {'-n', '--adjustment'},
                'timeout': {'-s', '-k', '--signal', '--kill-after'},
                'xargs': {'-I', '-i', '-n', '-P', '-L', '-l', '-s', '-d', '-E', '-e', '-a'}}
SETTERS = {'eval', 'source', '.', 'read', 'mapfile', 'readarray', 'unset', 'export', 'declare', 'typeset', 'readonly',
           'local', 'let', 'getopts'}
RESERVED = {'if', 'then', 'else', 'elif', 'while', 'until', 'do', '!', '{', '}'}
# `git_forms` only (`_simple` with `zsh`): the zsh precommand modifiers, the value options of `exec` and `time`, and the
# headers that come before the command they introduce (`function NAME`, `coproc [NAME]`, zsh `repeat N`)
ZSH_MODIFIERS = {'noglob', 'nocorrect', '-'}
ZSH_PREFIX_VALUE = {'exec': {'-a'}, 'time': {'-f', '-o', '--format', '--output'}}
HEADERS = {'function', 'coproc', 'repeat'}
# `git_forms` only (`_brace_role`): the words after which a lone `{` can start the body of a zsh short form
COND_WORDS = {'if', 'elif', 'while', 'until'}
BODY_WORDS = {'then', 'do', 'else'}
FOR_WORDS = {'for', 'foreach', 'select'}
BRACE_LEAD = 24        # the leading words `_brace_role` reads (a command word comes long before the 24th)
MAX_READINGS = 64      # the other readings of one simple command kept at once; more is a command that does not parse
PROBE = '\x02'         # stands for the next plain word in `_brace_role`
SHELLS = {'bash', 'sh', 'zsh', 'dash', 'ksh'}
CD = {'cd', 'pushd'}
LAST_ARG = {'cp', 'mv', 'rsync', 'install', 'ln'}
ALL_ARGS = {'rm', 'rmdir', 'mkdir', 'touch', 'truncate', 'unlink', 'tee'}
COPY = {'cp', 'mv', 'rsync'}
GIT_READ = {'status', 'diff', 'log', 'show', 'blame', 'annotate', 'ls-files', 'ls-tree', 'rev-parse', 'grep',
            'cat-file', 'describe', 'shortlog', 'rev-list', 'merge-base', 'name-rev', 'show-ref', 'for-each-ref',
            'count-objects', 'check-ignore', 'whatchanged', 'var', 'help', 'version'}
GIT_BRANCH_WRITE = {'-d', '-D', '-m', '-M', '-c', '-C', '-f', '--delete', '--move', '--copy', '--force'}
FIND_WRITE = {'-delete', '-exec', '-execdir', '-ok', '-okdir', '-fprint', '-fprintf', '-fls'}

# set by the shell itself (`cd` rewrites PWD / OLDPWD…), so an assignment in the line does not fix the value
SHELL_VARS = {'PWD', 'OLDPWD', 'SHLVL', 'RANDOM', 'SECONDS', 'LINENO', 'BASHPID', 'PPID', 'UID', 'EUID', 'HOSTNAME',
              'BASH_COMMAND', 'BASH_LINENO', 'BASH_SOURCE', 'FUNCNAME', 'REPLY', 'OPTIND', 'OPTARG', 'EPOCHSECONDS',
              'EPOCHREALTIME', 'SRANDOM', 'PIPESTATUS', 'COMP_LINE', 'COMP_POINT', 'DIRSTACK', 'MATCH', 'BASH_REMATCH'}


class Simple(NamedTuple):
    words: List[str]       # assignments and prefixes (sudo, env, xargs…) removed; words[0] is the command
    xargs: bool            # run through xargs: its arguments come from stdin
    redirects: List[str]   # output redirect targets, /dev/null and fd duplications left out
    inputs: List[str]      # input redirect files
    sep: str = ''          # the top-level separator before it ('' at the start, `&&`, `;`…)
    after: str = ''        # the separator after it
    top: bool = False      # runs at the top level: not in `( )`, a pipeline, the background, a compound command
    orl: bool = False      # a top-level `||` came before it in the same and-or list
    raw: List[str] = []    # the words as written, assignments and prefixes still in (the environment rule)


def _delimiters(line: str) -> List[tuple]:
    """(word, quoted) for every `<<` / `<<-` on `line`, quotes and backslashes removed from the word (any shell word:
    `EOF.txt`, `'EOF-1'`); `quoted` when the body is literal text (any quote or backslash in the delimiter)."""
    out = []
    for m in HEREDOC.finditer(line):
        j, word, quoted = m.end(), [], False
        while j < len(line) and line[j] not in ' \t\n;&|()<>':
            c = line[j]
            quoted = quoted or c in '\'"\\'
            if c in '\'"':
                k = line.find(c, j + 1)
                k = len(line) if k < 0 else k
                word.append(line[j + 1:k])
                j = k + 1
            elif c == '\\' and j + 1 < len(line):
                word.append(line[j + 1])
                j += 2
            else:
                word.append(c)
                j += 1
        if word:
            out.append((''.join(word), quoted))
    return out


def _quote_at(line: str, quote: Optional[str]) -> tuple:
    """(quote state at each `<<` start of `line`, state at its end), given the state at its start."""
    at, i, n = [], 0, len(line)
    marks = {m.start() for m in HEREDOC.finditer(line)}
    while i < n:
        c = line[i]
        if i in marks:
            at.append(quote)
        if quote == "'":
            quote = None if c == "'" else quote
        elif c == '\\':
            i += 1
        elif quote == '"':
            quote = None if c == '"' else quote
        elif c in '\'"':
            quote = c
        i += 1
    return at, quote


def _drop_quoted_bodies(cmd: str, open_ok: bool = False) -> str:
    """`cmd` without the body lines of heredocs whose delimiter is quoted (`<<'EOF'`, `<<"EOF"`, `<<\\EOF`): the shell
    does not expand them, so a backticked word there is text (`env_reads` must not read it as a substitution). The
    opening and closing lines stay. Bodies of unquoted delimiters stay too (real substitutions). A `<<` inside quotes
    (`bash -c "cat <<'EOF' …"`) or a heredoc never closed leaves `cmd` as it is; with `open_ok` the body of a quoted
    heredoc never closed is dropped as well (`git_forms`: its text is a message, not a command)."""
    out, waiting, quote = [], [], None
    for line in cmd.split('\n'):
        if waiting:
            if line.strip() == waiting[0][0]:
                waiting.pop(0)
                out.append(line)
            elif not waiting[0][1]:
                out.append(line)
            continue
        at, quote_after = _quote_at(line, quote)
        if any(q is not None for q in at) or (quote is not None and HEREDOC.search(line)):
            return cmd
        quote = quote_after
        out.append(line)
        waiting = _delimiters(line)
    return '\n'.join(out) if (open_ok or not waiting) else cmd


def _strip_heredocs(cmd: str) -> str:
    """`cmd` without heredoc bodies; ValueError when a heredoc is never closed (`echo "<<EOF"` would hide the rest)
    or when the body of an unquoted heredoc (expanded by the shell) has `$(` or a backtick."""
    out, waiting = [], []
    for line in cmd.split('\n'):
        if waiting:
            if line.strip() == waiting[0][0]:
                waiting.pop(0)
            elif not waiting[0][1] and ('`' in line or '$(' in line):
                raise ValueError('command substitution')
            continue
        out.append(line)
        waiting = _delimiters(line)
    if waiting:
        raise ValueError('heredoc not closed')
    return '\n'.join(out)


def _scan(text: str) -> str:
    """Quote-aware pass over `text` (heredocs already stripped): ValueError('command substitution') for `$(` or a
    backtick outside single quotes (unquoted or inside double quotes; `\\$(` is text). Comments are blanked; quotes and
    escapes are left for shlex."""
    out, i, n, quote = [], 0, len(text), None
    while i < n:
        c = text[i]
        if quote == "'":
            if c == "'":
                quote = None
        elif c == '\\' and i + 1 < n:
            out.append(c)
            i += 1
            c = text[i]
        elif c == '`' or (c == '$' and text[i + 1:i + 2] == '('):
            raise ValueError('command substitution')
        elif quote == '"':
            if c == '"':
                quote = None
        elif c in '\'"':
            quote = c
        elif c == '#' and (i == 0 or text[i - 1] in ' \t\n;&|()<>'):
            j = text.find('\n', i)
            j = n if j < 0 else j
            out.append(' ' * (j - i))        # a comment at a word start; a `#` inside a word (`${#D}`) is plain text
            i = j
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def _tokens(cmd: str, prep=None) -> List[str]:
    """The shlex tokens of `cmd`. `prep` (git_forms: `_prep_inner`) rewrites the text after the heredocs are stripped
    and before the scan, for a string the line itself did not scan (an `sh -c` or `eval` body)."""
    text = _strip_heredocs(cmd)
    lex = shlex.shlex(_scan(prep(text) if prep else text), posix=True, punctuation_chars=OPS)
    lex.whitespace = ' \t\r'
    lex.whitespace_split = True
    lex.commenters = ''
    return list(lex)


def _is_op(tok: str) -> bool:
    return tok != '' and all(c in OPS for c in tok)


SHELL_VALUE = {'-o', '-O', '+o', '+O', '--rcfile', '--init-file'}


def _shell_c(args: List[str]) -> Optional[str]:
    """The command string of a shell run with `-c`: the first word that is not an option or an option's value
    (`bash -o pipefail -c '<s>'`, `bash -co pipefail '<s>'`, `bash -c -- '<s>'`), else None."""
    i, n, has_c = 0, len(args), False
    while i < n:
        a = args[i]
        if a == '--':
            i += 1
            break
        if a in SHELL_VALUE:
            i += 2
        elif a.startswith('--') or (a[:1] in '-+' and len(a) > 1):
            has_c = has_c or (a[0] == '-' and not a.startswith('--') and 'c' in a[1:])
            i += 1 + (not a.startswith('--') and a[-1] in 'oO')       # a cluster ending in o / O takes the next word
        else:
            break
    return args[i] if has_c and i < n else None


def _env_strings(raw: List[str]) -> List[str]:
    """The command strings of `env -S '<s>'` (also `--split-string`, `-S<s>`) in the prefix words of `raw`; `_commands`
    with `prep` follows them. Walks the prefix words like `_simple`."""
    out, rest = [], list(raw)
    while rest:
        if rest[0][:1] == '=' and rest[0][1:]:
            rest[0] = rest[0][1:]
        name = os.path.basename(rest[0])
        if ASSIGN.match(rest[0]) or rest[0] in RESERVED:
            rest.pop(0)
        elif name in PREFIX:
            rest.pop(0)
            while rest and rest[0].startswith('-'):
                opt = rest.pop(0)
                if name == 'env' and opt in ('-S', '--split-string') and rest:
                    out.append(rest[0])
                elif name == 'env' and opt.startswith('--split-string='):
                    out.append(opt.partition('=')[2])
                elif name == 'env' and opt.startswith('-S') and not opt.startswith('--'):
                    out.append(opt[2:])
                if opt in PREFIX_VALUE.get(name, ()) and rest:
                    rest.pop(0)
            if name == 'timeout' and rest:
                rest.pop(0)
        else:
            break
    return out


def _inner(c: 'Simple', strict: bool = False) -> Optional[str]:
    """The command string run by `bash -c '<s>'` or `eval <s>`, else None. `strict` (git_forms) reads the options of
    the shell that take a value (`-o pipefail`) instead of taking the first non-option word, and also takes the
    command of `trap`."""
    if not c.words:
        return None
    name, args = os.path.basename(c.words[0]), c.words[1:]
    if name == 'eval':
        return ' '.join(args)
    if name == 'trap' and strict:
        rest = [a for a in args if a != '--' and not a.startswith('-')]
        return rest[0] if rest else None       # `trap [-p] [--] '<command>' SIGNAL…`: the command runs at the signal
    if name in SHELLS and strict:
        return _shell_c(args)
    if name in SHELLS:
        opts = [a for a in args if a.startswith('-') and not a.startswith('--')]
        rest = [a for a in args if not a.startswith('-')]
        if any('c' in o[1:] for o in opts) and rest:
            return rest[0]
    return None


def _commands(cmd: str, depth: int = 0, prep=None) -> List[Simple]:
    """Simple commands of `cmd`, with `bash -c` and `eval` strings parsed in place; raises ValueError when it
    does not tokenize (an open quote, command substitution, an open heredoc) or nests too deep. Each carries where
    it sits (`sep`, `after`, `top`, `orl`) for the `cd` rule. `prep` (git_forms) is the rewrite of `_tokens` for
    the nested strings and switches `_inner` to `strict`."""
    if depth > 3:
        raise ValueError('nested shells too deep')
    toks, out = _tokens(cmd, prep if depth else None), []
    words, raw, redirects, inputs = [], [], [], []
    paren, sep, orl, compound = 0, '', False, False
    others: List[list] = []        # git_forms: the other readings of the current simple command (`_brace_role`)
    groups, cond_open = 0, False   # git_forms: `{` read as a group start, not yet closed; a zsh `if`/`while` list is open

    def flush(after, alt=None):
        nonlocal compound
        w, r, rd, inp = (words, raw, redirects, inputs) if alt is None else alt
        if not (w or rd or inp):
            return
        s = _simple(w, rd, inp, prep is not None)
        if r and (r[1] if r[0] == '!' and len(r) > 1 else r[0]) in COMPOUND:
            compound = True
        top = (depth == 0 and paren == 0 and not compound and sep not in PIPE
               and after not in PIPE and after != '&')
        s = s._replace(sep=sep, after=after, top=top, orl=orl, raw=list(r))
        inner = _inner(s, prep is not None)
        if prep is not None:
            out.extend(c._replace(sep=sep, after=after, top=False, orl=orl)
                       for text in _env_strings(r) for c in _commands(text, depth + 1, prep))
        if inner is None:
            out.append(s)
        else:
            out.append(s._replace(words=s.words[:1]))
            out.extend(c._replace(sep=sep, after=after, top=False, orl=orl)
                       for c in _commands(inner, depth + 1, prep))

    def flush_all(after):
        nonlocal cond_open
        flush(after)
        for alt in others:
            flush(after, alt)
        for alt in [[words]] + others:
            lead = alt[0][1:2] if alt[0][:1] == ['!'] else alt[0][:1]
            if lead and lead[0] in COND_WORDS:
                cond_open = True
            elif lead and lead[0] in BODY_WORDS:
                cond_open = False
        others.clear()

    def settle(fresh):
        """Keep one empty reading at most (the start of the next command), plus a new one when `fresh`."""
        seen = not (words or redirects or inputs)
        for alt in list(others):
            if not (alt[0] or alt[2] or alt[3]):
                if seen:
                    others.remove(alt)
                seen = True
        if fresh and not seen:
            others.append([[], [], [], []])
        if len(others) > MAX_READINGS:
            raise ValueError('too many readings')

    i = 0
    while i < len(toks):
        t = toks[i]
        if _is_op(t) and ('>' in t or '<' in t):
            target = toks[i + 1] if i + 1 < len(toks) and not _is_op(toks[i + 1]) else None
            i += 2 if target is not None else 1
            for w, r, rd, inp in [[words, raw, redirects, inputs]] + others:
                if w and w[-1].isdigit():
                    w.pop()          # the fd number of `2>`
                    r.pop()
                if target is None:
                    continue
                if '>' in t:
                    dup = '&' in t and (target.isdigit() or target == '-')
                    if not dup and target != '/dev/null' and not target.startswith(('/dev/fd/', '/dev/std')):
                        rd.append(target)
                elif t == '<':
                    inp.append(target)
            continue
        if _is_op(t):
            first = True
            for piece in SEP_PIECE.findall(t):
                if first:
                    flush_all(piece)
                    words, raw, redirects, inputs = [], [], [], []
                    first = False
                if piece == '(':
                    paren += 1
                elif piece == ')':
                    paren = max(0, paren - 1)
                elif paren == 0:
                    sep = piece
                    if piece == '||':
                        orl = True
                    elif piece in (';', '\n', '&'):
                        orl = False
        elif prep is not None and t == MARK + '{':
            # git_forms: a lone unquoted `{` starts a command only where a compound command can begin (`_brace_role`);
            # anywhere else it is a word, and where the two cannot be told apart both readings are judged
            roles = []
            for alt in [[words, raw, redirects, inputs]] + others:
                roles.append(_brace_role(alt[0], cond_open))
                if roles[-1] == 'start':
                    flush(';', alt)
                    for part in alt:
                        part.clear()
                else:
                    alt[0].append('{')
                    alt[1].append('{')
            if any(role != 'word' for role in roles):
                groups, cond_open = groups + 1, False
            settle('both' in roles)
        elif prep is not None and t == '}':
            # a lone `}` after a command is the closer of an open group in zsh (`function g { cmd }`) and a word in
            # bash: with a group open both readings are judged
            alts = [[words, raw, redirects, inputs]] + others
            used = any(alt[0] for alt in alts)
            for alt in alts:
                if alt[0]:
                    alt[0].append('}')
                    alt[1].append('}')
            settle(groups > 0 and used)
            groups = max(0, groups - 1)
        else:
            made = _braces([t]) if prep is not None else [t]      # git_forms: the words the shell makes
            for alt in [[words, raw]] + others:
                alt[0].extend(made)
                alt[1].extend(made)
        i += 1
    flush_all('')
    return out


def _header_rest(rest: List[str]) -> List[str]:
    """`rest` (it starts with `function`, `coproc` or `repeat`) without that header: `function NAME`, `coproc [NAME]`
    (the name only before a compound command) and zsh `repeat COUNT`."""
    if rest[0] == 'coproc':
        named = len(rest) > 2 and (rest[2] in COMPOUND or rest[2] in RESERVED)
        return rest[2:] if named else rest[1:]
    return rest[2:]


def _brace_role(words: List[str], cond_open: bool) -> str:
    """`git_forms`: how a lone unquoted `{` after `words` (one simple command so far) is read. 'start': a command
    starts there, the words so far end (a plain word here would be the command word: nothing before it, after a
    reserved word, a prefix word, a precommand modifier or a header `function NAME`, `coproc`, `repeat N`; and after the
    words of a short form that takes a body, `for`/`foreach`/`select` words and `} always`). 'word': an argument of
    the command word (`git commit -m {`, `echo {`), also the value of a prefix option (`env -u {`). 'both': the two
    cannot be told apart (the condition of a zsh `if`/`elif`/`while`/`until` short form, also one that began in an
    earlier command of its list, `function NAME word… {`, `coproc word word… {`), so both are judged."""
    if not words:
        return 'start'
    lead = words[:BRACE_LEAD]
    rest = _simple(lead, [], [], True).words
    if not rest:
        if len(words) > BRACE_LEAD:
            return 'both'
        if _simple(lead + [PROBE], [], [], True).words == [PROBE] or 'function' in lead:
            return 'start'
        return 'word'
    head = lead[:len(lead) - len(rest)]
    if 'coproc' in head and len(rest) == 1:
        return 'start'           # `coproc NAME {`: the name is read before a compound command
    if cond_open or any(w in COND_WORDS or w in ('function', 'coproc') for w in head):
        return 'both'
    return 'start' if rest[0] in FOR_WORDS or rest == ['always'] else 'word'


def _prefix_value(name: str, opt: str) -> bool:
    """`git_forms`: whether the option `opt` of the prefix word `name` takes a value that `PREFIX_VALUE` does not name
    (`exec -a NAME`, also in a cluster ending in `a`; `time -f FORMAT`, `-o FILE`)."""
    return opt in ZSH_PREFIX_VALUE.get(name, ()) or (name == 'exec' and opt[1:2] not in ('-', '') and opt[-1] == 'a')


def _simple(words, redirects, inputs, zsh: bool = False) -> Simple:
    rest, xargs = list(words), False
    while rest:
        if zsh and rest[0][:1] == '=' and rest[0][1:]:
            rest[0] = rest[0][1:]            # zsh `=git` is the path of git
        name = os.path.basename(rest[0])
        if ASSIGN.match(rest[0]) or rest[0] in RESERVED or (zsh and rest[0] in ZSH_MODIFIERS):
            rest.pop(0)
        elif zsh and rest[0] in HEADERS:
            rest = _header_rest(rest)
        elif name in PREFIX:
            xargs = xargs or name == 'xargs'
            rest.pop(0)
            while rest and rest[0].startswith('-'):
                opt = rest.pop(0)
                if (opt in PREFIX_VALUE.get(name, ()) or (zsh and _prefix_value(name, opt))) and rest:
                    rest.pop(0)
            if name == 'timeout' and rest:
                rest.pop(0)      # the duration
        else:
            break
    return Simple(rest, xargs, list(redirects), list(inputs))


def _positional(args: List[str]) -> List[str]:
    out, after = [], False
    for a in args:
        if after:
            out.append(a)
        elif a == '--':
            after = True
        elif not a.startswith('-') or a == '-':
            out.append(a)
    return out


def _path(tok: str, cwd: Path) -> Optional[Path]:
    if '$' in tok or '`' in tok:
        return None
    p = Path(os.path.expanduser(tok))
    if not p.is_absolute():
        p = Path(cwd) / p
    return p.resolve()


def _git_sub(args: List[str]):
    """(subcommand, its arguments, the global options) of a git argument list (-C x, -c k=v, --no-pager…)."""
    i, opts = 0, []
    while i < len(args) and args[i].startswith('-'):
        opts.append(args[i])
        i += 2 if args[i] in ('-C', '-c') else 1
    return (args[i], args[i + 1:], opts) if i < len(args) else (None, [], opts)


def _git_mutating(args: List[str]) -> bool:
    """True unless the git command is a known read (an allowlist, 4.5 "read and check commands"): `-c` and `--exec-path`
    can run code, `--output` writes a file."""
    sub, rest, opts = _git_sub(args)
    if any(o in ('-c', '--config-env') or o.startswith(('--exec-path', '--config-env=')) for o in opts):
        return True
    if sub is None:
        return False
    if any(r.startswith('--output') for r in rest) or (sub == 'grep' and any(r.startswith(('-O', '--open-files'))
                                                                             for r in rest)):
        return True
    pos = _positional(rest)
    if sub in GIT_READ:
        return False
    if sub == 'stash':
        return not (pos and pos[0] in ('list', 'show'))
    if sub == 'branch':
        return bool(pos) or any(r in GIT_BRANCH_WRITE for r in rest)
    if sub == 'tag':
        return bool(pos) or any(r in ('-d', '--delete', '-a', '-s', '-f') for r in rest)
    if sub == 'config':
        return len(pos) >= 2 or any(r.startswith(('--unset', '--add', '--replace', '--rename', '--remove'))
                                    for r in rest)
    if sub in ('worktree', 'remote', 'submodule'):
        return bool(pos) and pos[0] not in ('list', 'show', 'status', '-v')
    return True


def _sed_files(args: List[str]) -> List[str]:
    inplace = any(a == '--in-place' or a.startswith('--in-place=')
                  or (a.startswith('-') and not a.startswith('--') and 'i' in a[1:]) for a in args)
    if not inplace:
        return []
    pos, script, i = [], False, 0
    while i < len(args):
        a = args[i]
        if a in ('-e', '-f', '--expression', '--file'):
            script, i = True, i + 2
            continue
        if a.startswith(('--expression=', '--file=')):
            script = True
        elif a == '-i' and i + 1 < len(args) and args[i + 1] == '':
            i += 1           # BSD `sed -i ''`: empty backup suffix
        elif not a.startswith('-') and a != '':
            pos.append(a)
        i += 1
    return pos if script else pos[1:]


def _git_mv(args: List[str]) -> Optional[List[str]]:
    """[src, dst] (raw words) when `args` is exactly `mv <src> <dst>`, else None: a global option before `mv` (`-C dir`
    re-bases the paths and nothing here follows it), any word starting with `-`, or other than two words."""
    if len(args) == 3 and args[0] == 'mv' and not any(a.startswith('-') for a in args[1:]):
        return args[1:]
    return None


def _sets_git_env(raw: List[str]) -> bool:
    """Whether one simple command (raw words) sets a `GIT_*` variable (bare assignment, export, declare, typeset) or
    runs `set -a` or sources a file (`source f`, `. f`), which can re-base the paths of a later `git mv`."""
    if not raw:
        return False
    if raw[0] in ('source', '.'):
        return True
    if os.path.basename(raw[0]) == 'set':
        return any(a.startswith('-') and not a.startswith('--') and 'a' in a[1:] for a in raw[1:])
    return any(w.startswith('GIT_') and ASSIGN.match(w) for w in raw) or (
        raw[0] in ('export', 'declare', 'typeset') and any(w.startswith('GIT_') for w in raw[1:]))


def _writes(c: Simple, before: List[Simple] = ()) -> Optional[List[str]]:
    """Raw target words of one simple command, or None when it writes somewhere it cannot name. `before` is the
    simple commands earlier on the command line (they may set `GIT_*`, which re-bases `git mv`)."""
    if not c.words:
        return []
    name, args = os.path.basename(c.words[0]), c.words[1:]
    if name == 'git':
        mv = _git_mv(args)
        if mv is not None:
            if (c.xargs or not c.raw or os.path.basename(c.raw[0]) != 'git'
                    or any(_sets_git_env(b.raw) for b in before)):
                return None
            return mv
        return None if _git_mutating(args) else []
    if name == 'find':
        return None if any(a in FIND_WRITE for a in args) else []
    if name == 'sed':
        targets = _sed_files(args)
    elif name == 'dd':
        targets = [a[3:] for a in args if a.startswith('of=')]
    elif name in LAST_ARG:
        targets = _positional(args)[-1:]
    elif name in ALL_ARGS:
        targets = _positional(args)
    else:
        return []
    if c.xargs and (targets or name != 'tee'):
        return None
    return targets


def _walk(cmd: str, cwd: Path):
    """(simple command, every folder it may run in) in order. A literal `cd`/`pushd` joined to what follows by `&&`
    only (at the top level, not after a `||`) replaces the folder for those commands; after the first other separator
    the folders are the start and every folder reached, because the `cd` may have failed. Any other `cd` (`cd x; cmd`,
    `cd x || cmd`, in `( )`) adds its target to the folders. None when a `cd` goes to a folder it cannot name
    (`$VAR`, `-`) or `cmd` does not tokenize."""
    try:
        cmds = _literal_vars(cmd, _commands(cmd))
    except ValueError:
        return None
    return _follow(cmds, cwd)


def _follow(cmds: List[Simple], cwd: Path):
    cwds, every, joined, out = [Path(cwd)], [Path(cwd)], False, []
    for c in cmds:
        if joined and c.sep != '&&':
            cwds, joined = list(every), False
        out.append((c, list(cwds)))
        if c.words and c.words[0] in CD:
            args = _positional(c.words[1:])
            target = args[0] if args else '~'
            if target == '-':
                return None
            new = [_path(target, d) for d in cwds]
            if None in new:
                return None
            if c.top and c.after == '&&' and not c.orl and c.sep in ('', ';', '\n', '&&'):
                cwds, joined = [n for i, n in enumerate(new) if n not in new[:i]], True
            else:
                cwds += [n for n in new if n not in cwds]
            every += [n for n in new if n not in every]
    return out


def _resolve_all(tok: str, cwds: List[Path]) -> Optional[List[Path]]:
    out = []
    for d in cwds:
        p = _path(tok, d)
        if p is None:
            return None
        if p not in out:
            out.append(p)
    return out


def _hidden_names(cmd: str) -> set:
    """Names used as `$NAME` / `${NAME` where the shell does not expand them: inside single quotes or after a
    backslash (shlex drops the quotes, so the words alone cannot tell)."""
    text = _scan(_strip_heredocs(cmd))
    lit, i, n, quote = [], 0, len(text), None
    while i < n:
        c = text[i]
        if quote == "'":
            if c == "'":
                quote = None
                lit.append(' ')
            else:
                lit.append(c)
        elif c == '\\' and i + 1 < n:
            if text[i + 1] == '$':
                m = re.match(r'\{?[A-Za-z_]\w*', text[i + 2:])
                lit.append(' $' + (m.group(0) if m else ''))
            i += 2
            continue
        elif quote == '"':
            if c == '"':
                quote = None
        elif c in '\'"':
            quote = c
        i += 1
    return set(re.findall(r'\$\{?([A-Za-z_]\w*)', ''.join(lit)))


def _sets_unseen(c: Simple) -> bool:
    """Whether one simple command can set a variable by a name the text does not show."""
    if not c.words:
        return False
    name = os.path.basename(c.words[0])
    if name in SETTERS:
        return True
    if name == 'printf':
        return any(w.startswith('-v') for w in c.words[1:])
    return name in SHELLS and any(re.fullmatch(r'-[A-Za-z]*c[A-Za-z]*', w) for w in c.raw)


def _literal_vars(cmd: str, cmds: List[Simple]) -> List[Simple]:
    """`cmds` with `$NAME` / `${NAME}` replaced by its value, for each NAME that is safe to follow. All must hold:
    exactly one simple command assigns it (not a shell-managed name such as `PWD`), as a bare `NAME=value` that always runs (top level, not after `&&` or
    `||`, not in a pipeline, the background, `( )` or a compound command); no other word names it, sets it or uses
    it in another form (`${NAME:-x}`, `${#NAME}`), and every use comes after the assignment, unquoted by single
    quotes or a backslash; the value is a literal (not empty, no whitespace, `$`, quote-removal leftovers, glob
    characters, leading `~`); and the line has no command that can set a variable unseen (`eval`, `read`,
    `export`, `bash -c`, `printf -v`, `((`, `IFS`…), which turns following off for the whole line. Otherwise the
    variable stays as it is and the path is unknown."""
    if '((' in cmd or any(_sets_unseen(c) for c in cmds):
        return cmds
    words = [c.raw + c.redirects + c.inputs for c in cmds]
    if any(re.search(r'(?<![A-Za-z0-9_])IFS(?![A-Za-z0-9_])', w) for ws in words for w in ws):
        return cmds
    hidden, values = None, {}
    for i, c in enumerate(cmds):
        if c.words or c.redirects or c.inputs or not c.raw or not all(ASSIGN.match(w) for w in c.raw):
            continue
        if not (c.top and not c.orl and c.sep in ('', ';', '\n')):
            continue
        for k, w in enumerate(c.raw):
            name, value = w.split('=', 1)
            if name in values:
                values[name] = None
                continue
            values[name] = (i, k, value)
    out = {}
    for name, found in values.items():
        if found is None or name in SHELL_VARS or name == '_' or name.startswith('BASH'):
            continue
        i, k, value = found
        if (not value or re.search(r'[\s$`\\*?\[\]{}!]', value) or value.startswith('~') or ':~' in value):
            continue
        if hidden is None:
            hidden = _hidden_names(cmd)
        if name in hidden:
            continue
        mention = re.compile(r'(?<![A-Za-z0-9_])' + name + r'(?![A-Za-z0-9_])')
        use = re.compile(r'\$(?:\{' + name + r'\}|' + name + r'(?![A-Za-z0-9_]))')
        ok = True
        for j, ws in enumerate(words):
            for m, w in enumerate(ws):
                if j == i and m == k:
                    continue
                if mention.search(w if j <= i else use.sub('', w)):
                    ok = False
        if ok:
            out[name] = (value, use)
    if not out:
        return cmds

    def expand(w):
        for value, use in out.values():
            w = use.sub(lambda _: value, w)
        return w

    return [c._replace(words=[expand(w) for w in c.words], redirects=[expand(w) for w in c.redirects],
                       inputs=[expand(w) for w in c.inputs]) for c in cmds]


def write_targets(cmd: str, cwd: Path) -> Optional[List[Path]]:
    """Absolute paths `cmd` creates, changes or deletes; [] when it writes nothing it knows of;
    None when it writes but a target cannot be named (git that changes the tree, except a plain
    `git mv <src> <dst>`, `$VAR`, xargs, find -delete,
    a symlink made in the same command as another write, anything `_walk` cannot follow). It does not read inline
    interpreter code (`python3 -c "open('x','w')"`): `interpreter_writes` does, for scope-guard only."""
    walked = _walk(cmd, cwd)
    if walked is None:
        return None
    out, writers, link = [], 0, False
    for i, (c, cwds) in enumerate(walked):
        raw = _writes(c, [w[0] for w in walked[:i]])
        if raw is None:
            return None
        if c.redirects or raw:
            writers += 1
            link = link or os.path.basename(c.words[0]) == 'ln' if c.words else link
        for tok in c.redirects + raw:
            ps = _resolve_all(tok, cwds)
            if ps is None:
                return None
            out += ps
    if link and writers > 1:
        return None
    return out


# Inline interpreter code (architecture 4.12 "Inline interpreter code"). Only scope-guard calls `interpreter_writes`;
# nothing above this line knows of it.
INTERPRETER = re.compile(r'python|node|ruby|perl')
HEREDOC_MARK = '__MAHEREDOC%d__'
HEREDOC_MARKED = re.compile(r'__MAHEREDOC(\d+)__$')
NO_WRITE = {'/dev/null', '/dev/stdout', '/dev/stderr'}
WRITE_FLAGS = {'O_WRONLY', 'O_RDWR', 'O_CREAT', 'O_APPEND', 'O_TRUNC'}
XARGS_VALUE = set('IPLnsdEa')       # short xargs options that take a value (attached or the next word)
XARGS_LONG = {'--max-args', '--max-procs', '--max-lines', '--max-chars', '--delimiter', '--arg-file',
              '--process-slot-var'}
# per interpreter: letters of a short-option cluster that take the code, a value (rest of the cluster or the next
# word), the rest of the cluster only, digits (`-0777`), or name a module (no inline code); long options with a value
OPT_SPECS = {
    'python': dict(code='c', value='WX', rest='', skip='', stop='m', long_value={'--check-hash-based-pycs'}, once=True),
    'ruby': dict(code='e', value='IrCE', rest='FxWKTi', skip='0', stop='',
                 long_value={'--encoding', '--external-encoding', '--internal-encoding', '--enable', '--disable'},
                 once=False),
    'perl': dict(code='eE', value='I', rest='FCMmxidDV', skip='0l', stop='', long_value=set(), once=False),
}
NODE_VALUE = {'-r', '--require', '--import', '--loader', '--experimental-loader', '-C', '--conditions', '--input-type'}
NODE_CODE = {'-e', '--eval', '-p', '--print', '-pe', '-ep'}


def _heredoc_marks(line: str) -> List[tuple]:
    """(start, end, word, quoted, dash) of each `<<` / `<<-` on `line`: the span with its delimiter word, the word and
    whether it is quoted, read the way `_delimiters` reads them."""
    out = []
    for m in HEREDOC.finditer(line):
        j, word, quoted = m.end(), [], False
        while j < len(line) and line[j] not in ' \t\n;&|()<>':
            c = line[j]
            quoted = quoted or c in '\'"\\'
            if c in '\'"':
                k = line.find(c, j + 1)
                k = len(line) if k < 0 else k
                word.append(line[j + 1:k])
                j = k + 1
            elif c == '\\' and j + 1 < len(line):
                word.append(line[j + 1])
                j += 2
            else:
                word.append(c)
                j += 1
        if word:
            out.append((m.start(), j, ''.join(word), quoted, '-' in m.group(0)))
    return out


def _pair_heredocs(cmd: str) -> tuple:
    """(text, bodies): `cmd` as `_strip_heredocs` leaves it, with each `<<WORD` replaced by an input redirect from a
    placeholder word (`< __MAHEREDOC0__`), so the placeholder lands in the `inputs` of the command that reads the
    heredoc; and the body lines of heredoc N in `bodies[N]`. ValueError exactly where `_strip_heredocs` raises it."""
    out, bodies, waiting = [], [], []
    for line in cmd.split('\n'):
        if waiting:
            word, quoted, dash, k = waiting[0]
            if line.strip() == word:
                waiting.pop(0)
            elif not quoted and ('`' in line or '$(' in line):
                raise ValueError('command substitution')
            else:
                bodies[k].append(line.lstrip('\t') if dash else line)
            continue
        marks = _heredoc_marks(line)
        base = len(bodies)
        for n, (_, _, word, quoted, dash) in enumerate(marks):
            bodies.append([])
            waiting.append((word, quoted, dash, base + n))
        for n, (start, end, *_) in reversed(list(enumerate(marks))):
            line = line[:start] + '< ' + HEREDOC_MARK % (base + n) + ' ' + line[end:]
        out.append(line)
    if waiting:
        raise ValueError('heredoc not closed')
    return '\n'.join(out), bodies


def _xargs_words(raw: List[str]) -> Optional[tuple]:
    """(the words after `xargs` and its options, whether it has a replace option) for a simple command run through
    xargs, from its raw words: `_simple` does not know the clusters (`-tI {}`) and can take a value for the command."""
    k = next((i for i, w in enumerate(raw) if os.path.basename(w) == 'xargs'), None)
    if k is None:
        return None
    rest, i, replace = raw[k + 1:], 0, False
    while i < len(rest) and rest[i].startswith('-') and rest[i] != '-':
        opt = rest[i]
        i += 1
        if opt == '--':
            break
        if opt.startswith('--'):
            name = opt.split('=', 1)[0]
            replace = replace or name == '--replace'
            i += '=' not in opt and name in XARGS_LONG
            continue
        for j, ch in enumerate(opt[1:], 1):
            replace = replace or ch in 'Ii'
            if ch in XARGS_VALUE:
                i += j == len(opt) - 1
                break
            if ch in 'ile':          # the value of these is attached or none
                break
    return _simple(rest[i:], [], []).words, replace


def _scan_args(args: List[str], spec: dict) -> tuple:
    """(code strings, status, module words) of the arguments of python, ruby or perl. status: 'code' (an inline
    option was given), 'script' (a script file or module comes first), 'stdin' (neither: the code comes on stdin)."""
    codes, mods, i = [], [], 0
    while i < len(args):
        a = args[i]
        if a == '--':
            i += 1
            break
        if a == '-' or not a.startswith('-'):
            break
        i += 1
        if a.startswith('--'):
            i += '=' not in a and a in spec['long_value']
            continue
        j = 1
        while j < len(a):
            ch = a[j]
            if ch in spec['code']:
                tail = a[j + 1:]
                if tail:
                    codes.append(tail)
                elif i < len(args):
                    codes.append(args[i])
                    i += 1
                break
            if ch in spec['stop']:
                return [], 'script', mods
            if ch in spec['value']:
                i += j == len(a) - 1
                break
            if ch in spec['rest']:
                mods.append(a[j + 1:])
                break
            j += 1
            if ch in spec['skip']:
                while j < len(a) and a[j] in '01234567':
                    j += 1
        if codes and spec['once']:
            return codes, 'code', mods
    if codes:
        return codes, 'code', mods
    return [], ('stdin' if i >= len(args) or args[i] == '-' else 'script'), mods


def _node_args(args: List[str]) -> tuple:
    """`_scan_args` for node: `-e` / `--eval` / `-p` / `--print` (also `-pe`, `--eval=CODE`) give the code."""
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--':
            i += 1
            break
        if a == '-' or not a.startswith('-'):
            break
        i += 1
        name, eq, value = a.partition('=')
        if name in NODE_CODE:
            if eq:
                return [value], 'code', []
            return ([args[i]], 'code', []) if i < len(args) else ([], 'script', [])
        i += not eq and name in NODE_VALUE
    return [], ('stdin' if i >= len(args) or args[i] == '-' else 'script'), []


class _Found:
    """What one piece of inline code writes: literal paths in source order, whether a write has a path that is not a
    literal (or a mode that cannot be told), and whether the code changes its folder."""

    def __init__(self):
        self.paths, self.unknown, self.chdir = [], False, False

    def add(self, path: Optional[str]) -> None:
        """A write to `path`: None is a path that is not a literal."""
        if path is None:
            self.unknown = True
        elif path not in NO_WRITE:
            self.paths.append(path)

    def cannot_tell(self) -> None:
        self.unknown = True


def _plain(text: str) -> bool:
    """Whether the text of a string literal is a plain path: no `$` (shell or interpreter variable), `@` or `#{`."""
    return not re.search(r'[$@]|#\{', text)


# ---- python (ast) ----
PY_PATHS = {
    'os': {'remove': ((0, 'path'),), 'unlink': ((0, 'path'),), 'rmdir': ((0, 'path'),), 'removedirs': ((0, 'name'),),
           'mkdir': ((0, 'path'),), 'makedirs': ((0, 'name'),), 'truncate': ((0, 'path'),), 'mkfifo': ((0, 'path'),),
           'rename': ((0, 'src'), (1, 'dst')), 'renames': ((0, 'old'), (1, 'new')),
           'replace': ((0, 'src'), (1, 'dst')), 'symlink': ((1, 'dst'),), 'link': ((1, 'dst'),)},
    'shutil': {'copy': ((1, 'dst'),), 'copy2': ((1, 'dst'),), 'copyfile': ((1, 'dst'),), 'copytree': ((1, 'dst'),),
               'move': ((0, 'src'), (1, 'dst')), 'rmtree': ((0, 'path'),)},
}
PY_STAR = {'os': [*PY_PATHS['os'], 'chdir', 'open'], 'shutil': [*PY_PATHS['shutil']], 'io': ['open'],
           'codecs': ['open'], 'pathlib': ['Path']}      # what `from <module> import *` brings in
PY_PATH_METHODS = {'write_text', 'write_bytes', 'touch', 'mkdir', 'unlink', 'rmdir', 'symlink_to', 'hardlink_to'}
PY_FORMS = re.compile(r'\b(?:open|' + '|'.join(sorted({n for t in PY_PATHS.values() for n in t} | PY_PATH_METHODS))
                      + r')\b')


def _py_arg(call: ast.Call, index: int, name: str):
    """The argument node of `call` at `index` (or the keyword `name`); None when it is not given; False when a `*args`
    or `**kw` hides it."""
    if any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords):
        return False
    if index < len(call.args):
        return call.args[index]
    return next((k.value for k in call.keywords if k.arg == name), None)


def _py_lit(node) -> Optional[str]:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) and _plain(node.value) else None


def _py_path(found: _Found, node) -> None:
    """The path argument `node` of a write: a literal is judged; an int is a file descriptor (no path); anything
    else (or an argument that is missing or hidden) is a path that cannot be told."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return
    found.add(None if node is None or node is False else _py_lit(node))


def _py_mode(node) -> str:
    """'read', 'write' or 'unknown' for the mode argument of open (None: not given)."""
    if node is None:
        return 'read'
    text = _py_lit(node) if isinstance(node, ast.Constant) else None
    if text is None:
        return 'unknown'
    return 'write' if any(c in text for c in 'wax+') else 'read'


def _py_flag_names(node) -> Optional[set]:
    """The `O_*` names of an os.open flags expression (`os.O_CREAT | os.O_APPEND`); None when it is anything else.
    A number other than 0 may hold any write flag."""
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return {'O_WRONLY'} if node.value else set()
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left, right = _py_flag_names(node.left), _py_flag_names(node.right)
        return None if left is None or right is None else left | right
    return None


def _py_flags(node) -> str:
    """'read', 'write' or 'unknown' for the flags argument of os.open."""
    if node is None:
        return 'read'
    names = None if node is False else _py_flag_names(node)
    if names is None:
        return 'unknown'
    if names & WRITE_FLAGS:
        return 'write'
    return 'read' if all(n.startswith('O_') for n in names) else 'unknown'


def _python_writes(code: str, mods: List[str]) -> _Found:
    found = _Found()
    try:
        tree = ast.parse(code)
    except Exception:       # SyntaxError, ValueError (null byte), RecursionError: judged by the names the text has
        if PY_FORMS.search(code):
            found.cannot_tell()
        return found
    modules, funcs = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    modules[a.asname] = a.name
                else:
                    modules[a.name.split('.')[0]] = a.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                if a.name != '*':
                    funcs[a.asname or a.name] = (node.module, a.name)
                    continue
                for name in PY_STAR.get(node.module, ()):
                    funcs.setdefault(name, (node.module, name))

    def ref(f):
        if isinstance(f, ast.Name):
            return funcs.get(f.id) or (('builtins', 'open') if f.id == 'open' else None)
        if isinstance(f, ast.Attribute):
            if isinstance(f.value, ast.Name) and f.value.id in modules:
                return (modules[f.value.id], f.attr)
            return ('.', f.attr, f.value)
        return None

    def path_call(recv):
        """None when `recv` is not a `Path(...)` call; else its literal path, or False when it is not a literal."""
        if not (isinstance(recv, ast.Call) and ref(recv.func) == ('pathlib', 'Path')):
            return None
        parts = [_py_lit(a) for a in recv.args]
        if not parts or recv.keywords or None in parts:
            return False
        return os.path.join(*parts)

    calls = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Call)), key=lambda n: (n.lineno, n.col_offset))
    for call in calls:
        r = ref(call.func)
        if r is None:
            continue
        if r[0] == '.':
            name, recv = r[1], path_call(r[2])
            if name in PY_PATH_METHODS:
                found.add(None if recv in (None, False) else recv)
            elif recv is not None and name in ('rename', 'replace'):
                found.add(None if recv is False else recv)
                target = _py_arg(call, 0, 'target')
                found.add(_py_lit(target) if target else None)
            elif recv is not None and name == 'open':
                mode = _py_mode(_py_arg(call, 0, 'mode'))
                if mode == 'unknown' or (mode == 'write' and recv is False):
                    found.cannot_tell()
                elif mode == 'write':
                    found.add(recv)
            continue
        mod, name = r
        if name == 'open' and mod in ('builtins', 'io', 'codecs'):
            mode = _py_mode(_py_arg(call, 1, 'mode'))
            if mode == 'unknown':
                found.cannot_tell()
            elif mode == 'write':
                _py_path(found, _py_arg(call, 0, 'file') or _py_arg(call, 0, 'filename'))
        elif (mod, name) == ('os', 'open'):
            flags = _py_flags(_py_arg(call, 1, 'flags'))
            if flags == 'unknown':
                found.cannot_tell()
            elif flags == 'write':
                _py_path(found, _py_arg(call, 0, 'path'))
        elif (mod, name) == ('os', 'chdir'):
            found.chdir = True
        else:
            for index, kw in PY_PATHS.get(mod, {}).get(name, ()):
                _py_path(found, _py_arg(call, index, kw))
    return found


# ---- node, ruby, perl (a small lexer, then the calls by name) ----
LEX_WORD = {'js': re.compile(r'[A-Za-z_$][\w$]*'), 'rb': re.compile(r'[A-Za-z_]\w*[?!]?'),
            'pl': re.compile(r'[A-Za-z_]\w*(?:::\w+)*')}
REGEX_AFTER = {   # a word after which `/` starts a regex literal, not a division
    'js': {'return', 'typeof', 'case', 'in', 'of', 'delete', 'void', 'throw', 'new', 'else', 'do', 'yield', 'await'},
    'rb': {'if', 'unless', 'and', 'or', 'not', 'return', 'puts', 'print', 'when', 'while', 'until', 'then', 'elsif',
           'case', 'p'},
    'pl': {'if', 'unless', 'and', 'or', 'not', 'split', 'grep', 'map', 'return', 'print', 'while', 'until', 'push',
           'join', 'x', 'eq', 'ne', 'lt', 'gt', 'le', 'ge', 'cmp', 'when'}}
QUOTE_LIKE = {'m', 's', 'tr', 'y', 'qr', 'q', 'qq', 'qw'}
QUOTE_DELIMS = set('/|!{([<#"\'~^%+:')
BRACKETS = {'(': ')', '[': ']', '{': '}', '<': '>'}
PL_VAR = re.compile(r'\w+(?:::\w+)*')
RB_VAR = re.compile(r'(?:@@?\w+|\$(?:\w+|[^\s\w]))')
RB_PERCENT = re.compile(r'%[qQwWiIrsx]?([^\w\s])')
STOP_WORDS = {'if', 'unless', 'while', 'until', 'and', 'or', 'xor', 'do', 'then', 'end', 'rescue', 'for', 'foreach'}
ARG_START_OPS = {'[', '{', '\\', '-', '+', '*', '!'}
ARG_START = {'str', 'xstr', 'num', 'var', 'sym', 'quote', 'cmd'}


def _skip_to(code: str, i: int, close: str, nest: Optional[str] = None) -> int:
    """Index just past the `close` that ends a literal whose body starts at `i` (escapes skipped, `nest` is an opener
    that is counted); len(code) when it never closes."""
    depth, n = 0, len(code)
    while i < n:
        c = code[i]
        if c == '\\':
            i += 2
            continue
        if nest and c == nest:
            depth += 1
        elif c == close:
            if depth == 0:
                return i + 1
            depth -= 1
        i += 1
    return n


def _lex(code: str, lang: str) -> List[tuple]:
    """(kind, text) tokens of node ('js'), ruby ('rb') or perl ('pl') code. Kinds: id, str (a string literal with no
    backslash), xstr (any other string), num, var, sym, quote (a regex or other quote-like literal), cmd (backticks),
    nl, op. Comments are dropped; a name inside a string, regex or comment is no id."""
    toks, i, n = [], 0, len(code)

    def operand() -> bool:       # the last token ends a value, so `/` divides and `%` is an operator
        if not toks:
            return False
        kind, text = toks[-1]
        if kind == 'id':
            return text not in REGEX_AFTER[lang]
        return text in (')', ']', '}') if kind == 'op' else kind != 'nl'

    while i < n:
        c, nxt = code[i], code[i + 1:i + 2]
        if c in ' \t\r':
            i += 1
        elif c == '\n':
            toks.append(('nl', c))
            i += 1
        elif (lang == 'js' and code.startswith('//', i)) or (lang != 'js' and c == '#'):
            j = code.find('\n', i)
            i = n if j < 0 else j
        elif lang == 'js' and code.startswith('/*', i):
            j = code.find('*/', i + 2)
            i = n if j < 0 else j + 2
        elif c in '\'"`':
            j = _skip_to(code, i + 1, c)
            body = code[i + 1:j - 1]
            if c == '`' and lang != 'js':
                toks.append(('cmd', body))
            else:
                toks.append(('xstr' if '\\' in body else 'str', body))
            i = j
        elif lang == 'pl' and (c in '$@' or (c == '%' and not operand() and (nxt.isalpha() or nxt in '_{$'))):
            j = i + 1 + (c == '$' and nxt == '#')
            m = PL_VAR.match(code, j)
            if m:
                j = m.end()
            elif c == '$' and code[j:j + 1] not in ('', '{', '$') and not code[j].isspace():
                j += 1
            toks.append(('var', code[i:j]))
            i = j
        elif lang == 'rb' and RB_VAR.match(code, i):
            m = RB_VAR.match(code, i)
            toks.append(('var', m.group(0)))
            i = m.end()
        elif lang == 'rb' and c == ':' and (nxt.isalpha() or nxt == '_') and code[i - 1:i] != ':':
            m = re.compile(r'\w+[?!=]?').match(code, i + 1)
            toks.append(('sym', m.group(0)))
            i = m.end()
        elif c == '/' and not operand():
            j = _skip_to(code, i + 1, '/')
            while j < n and code[j].isalpha():
                j += 1
            toks.append(('quote', ''))
            i = j
        elif lang == 'rb' and c == '%' and not operand() and RB_PERCENT.match(code, i):
            d = RB_PERCENT.match(code, i).group(1)
            toks.append(('quote', ''))
            i = _skip_to(code, RB_PERCENT.match(code, i).end(), BRACKETS.get(d, d), d if d in BRACKETS else None)
        elif c.isdigit():
            m = re.compile(r'\d[\w.]*').match(code, i)
            toks.append(('num', m.group(0)))
            i = m.end()
        elif LEX_WORD[lang].match(code, i):
            word = LEX_WORD[lang].match(code, i).group(0)
            j = i + len(word)
            d = code[j:j + 1]
            if (lang == 'pl' and word in QUOTE_LIKE and d in QUOTE_DELIMS and d != ''
                    and not (toks and toks[-1] == ('op', '->'))):
                end = _skip_to(code, j + 1, BRACKETS.get(d, d), d if d in BRACKETS else None)
                body = code[j + 1:end - 1]
                if word in ('s', 'tr', 'y'):
                    if d in BRACKETS:
                        while end < n and code[end].isspace():
                            end += 1
                        d2 = code[end:end + 1]
                        end = _skip_to(code, end + 1, BRACKETS.get(d2, d2), d2 if d2 in BRACKETS else None)
                    else:
                        end = _skip_to(code, end, d)
                while end < n and code[end].isalpha():
                    end += 1
                if word in ('q', 'qq'):
                    toks.append(('xstr' if '\\' in body else 'str', body))
                else:
                    toks.append(('quote', ''))
                i = end
            else:
                toks.append(('id', word))
                i = j
        else:
            two = code[i:i + 2]
            op = two if two in ('->', '=>', '::', '&&', '||') else c
            toks.append(('op', op))
            i += len(op)
    return toks


def _starts_arg(tok: tuple) -> bool:
    kind, text = tok
    if kind == 'id':
        return text not in STOP_WORDS
    return kind in ARG_START or (kind == 'op' and text in ARG_START_OPS)


def _call_args(toks: List[tuple], k: int, optional: bool) -> Optional[List[List[tuple]]]:
    """The arguments of the call whose name ends before `toks[k]`: a list of token lists, split at the commas. With
    parentheses they end at the matching `)`; without (`optional`, ruby and perl) at the end of the statement, a
    closing bracket, `&&`, `||` or a word like `if`, `do`, `or`. None when no call follows."""
    n = len(toks)
    paren = k < n and toks[k] == ('op', '(')
    if paren:
        k += 1
    elif not optional or k >= n or not _starts_arg(toks[k]):
        return None
    args, cur, depth = [], [], 0
    while k < n:
        kind, text = toks[k]
        if kind == 'nl':
            if paren or depth or toks[k - 1] == ('op', ','):
                k += 1
                continue
            break
        if kind == 'op' and text in '([{':
            depth += 1
        elif kind == 'op' and text in ')]}':
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and ((kind == 'op' and text in (';', '&&', '||')) or (
                not paren and kind == 'id' and text in STOP_WORDS)):
            break
        if kind == 'op' and text == ',' and depth == 0:
            args.append(cur)
            cur = []
        else:
            cur.append(toks[k])
        k += 1
    if cur or args:
        args.append(cur)
    return args


def _lit(args: List[List[tuple]], index: int) -> Optional[str]:
    """The string of argument `index` when it is one plain string literal, else None."""
    if index < len(args) and len(args[index]) == 1 and args[index][0][0] == 'str' and _plain(args[index][0][1]):
        return args[index][0][1]
    return None


def _flag_write(args: List[List[tuple]], index: int, letters: str) -> str:
    """'read', 'write' or 'unknown' for the mode or flags argument `index` of an open call: a string with one of
    `letters` writes; no argument reads; anything else cannot be told."""
    if index >= len(args):
        return 'read'
    text = _lit(args, index)
    if text is None:
        return 'unknown'
    return 'write' if any(c in text for c in letters) else 'read'


def _paths_of(found: _Found, args: List[List[tuple]], indexes) -> None:
    for index in indexes:
        found.add(_lit(args, index))


JS_FS = re.compile(r"""['"`](?:node:)?fs(?:/promises)?['"`]""")
JS_PATH0 = {'writeFile', 'writeFileSync', 'appendFile', 'appendFileSync', 'createWriteStream', 'mkdir', 'mkdirSync',
            'mkdtemp', 'mkdtempSync', 'rm', 'rmSync', 'rmdir', 'rmdirSync', 'unlink', 'unlinkSync', 'truncate',
            'truncateSync'}
JS_BOTH = {'rename', 'renameSync'}
JS_DEST = {'copyFile', 'copyFileSync', 'cp', 'cpSync', 'symlink', 'symlinkSync', 'link', 'linkSync'}
JS_OPEN = {'open', 'openSync'}


def _node_writes(code: str, mods: List[str]) -> _Found:
    found = _Found()
    if not JS_FS.search(code):
        return found
    toks = _lex(code, 'js')
    for k, (kind, name) in enumerate(toks):
        if kind != 'id' or (k and toks[k - 1] in (('id', 'function'), ('id', 'new'))):
            continue
        if name == 'chdir' and k and toks[k - 1] == ('op', '.') and toks[k - 2:k - 1] == [('id', 'process')]:
            found.chdir = True
            continue
        if name not in JS_PATH0 | JS_BOTH | JS_DEST | JS_OPEN:
            continue
        args = _call_args(toks, k + 1, False)
        if args is None:
            continue
        if name in JS_PATH0:
            _paths_of(found, args, (0,))
        elif name in JS_BOTH:
            _paths_of(found, args, (0, 1))
        elif name in JS_DEST:
            _paths_of(found, args, (1,))
        else:
            mode = _flag_write(args, 1, 'wa+')
            if mode == 'unknown':
                found.cannot_tell()
            elif mode == 'write':
                _paths_of(found, args, (0,))
    return found


RB_CALLS = {
    'File': {'write': (0,), 'binwrite': (0,), 'delete': 'all', 'unlink': 'all', 'rename': (0, 1), 'symlink': (1,),
             'link': (1,), 'truncate': (0,), 'open': 'open', 'new': 'open'},
    'IO': {'write': (0,), 'binwrite': (0,)},
    'FileUtils': {**{n: (0,) for n in ('rm', 'rm_f', 'rm_r', 'rm_rf', 'rmtree', 'remove', 'remove_dir', 'remove_file',
                                        'rmdir', 'mkdir', 'mkdir_p', 'makedirs', 'mkpath', 'touch')},
                  **{n: (0, 1) for n in ('mv', 'move')},
                  **{n: (1,) for n in ('cp', 'copy', 'cp_r', 'copy_file', 'install', 'ln', 'ln_s', 'ln_sf',
                                       'symlink')}},
    'Dir': {'mkdir': (0,), 'rmdir': (0,), 'delete': (0,), 'unlink': (0,), 'chdir': 'chdir'},
}


def _ruby_writes(code: str, mods: List[str]) -> _Found:
    found = _Found()
    toks = _lex(code, 'rb')
    for k in range(len(toks) - 2):
        cls, sep, name = (t[1] for t in toks[k:k + 3])
        if toks[k][0] != 'id' or toks[k + 2][0] != 'id' or sep not in ('.', '::') or name not in RB_CALLS.get(cls, ()):
            continue
        what = RB_CALLS[cls][name]
        if what == 'chdir':
            found.chdir = True
            continue
        args = _call_args(toks, k + 3, True)
        if args is None:
            continue
        if what == 'all':
            _paths_of(found, args, range(len(args)))
        elif what == 'open':
            mode_arg = next((a[2:] for a in args[1:] if a[:2] in ([('id', 'mode'), ('op', ':')],
                                                                    [('sym', 'mode'), ('op', '=>')])), None)
            rest = args[:1] + ([mode_arg] if mode_arg is not None else args[1:2])
            mode = _flag_write(rest, 1, 'wa+')
            if mode == 'unknown':
                found.cannot_tell()
            elif mode == 'write':
                _paths_of(found, args, (0,))
        else:
            _paths_of(found, args, what)
    return found


PL_ONE = {'unlink': 'all', 'rename': (0, 1), 'mkdir': (0,), 'rmdir': (0,), 'link': (1,), 'symlink': (1,),
          'truncate': (0,)}
PL_COPY = {'copy': (1,), 'cp': (1,), 'move': (0, 1), 'mv': (0, 1)}
PL_PATH = {'make_path', 'mkpath', 'remove_tree', 'rmtree'}
PL_MODE = re.compile(r'\s*(\+?(?:>>|>|<))\s*(.*?)\s*$', re.S)


def _perl_flags(tokens: List[tuple]) -> str:
    """'read', 'write' or 'unknown' for the flags argument of sysopen: names such as `O_WRONLY|O_CREAT`."""
    names = [t[1].split('::')[-1] for t in tokens if t[0] == 'id']
    others = [t for t in tokens if t[0] not in ('id',) and t != ('op', '|') and t != ('num', '0')]
    if set(names) & WRITE_FLAGS or any(t[0] == 'num' for t in others):
        return 'write'
    return 'read' if tokens and not others and all(n.startswith('O_') for n in names) else 'unknown'


def _perl_writes(code: str, mods: List[str]) -> _Found:
    found = _Found()
    toks = _lex(code, 'pl')
    modules = {'File::Copy': 'File::Copy' in code or any('File::Copy' in m for m in mods),
               'File::Path': 'File::Path' in code or any('File::Path' in m for m in mods)}
    for k, (kind, word) in enumerate(toks):
        if kind != 'id' or (k and toks[k - 1] in (('op', '->'), ('id', 'sub'))):
            continue
        pkg, _, name = word.rpartition('::')
        if name == 'chdir':
            found.chdir = True
            continue
        copy = name in PL_COPY and (pkg == 'File::Copy' or (not pkg and modules['File::Copy']))
        path = name in PL_PATH and (pkg == 'File::Path' or (not pkg and modules['File::Path']))
        if not (copy or path or (not pkg and (name in PL_ONE or name in ('open', 'sysopen')))):
            continue
        args = _call_args(toks, k + 1, True)
        if args is None:
            continue
        if name == 'open' and not pkg:
            if len(args) >= 3:
                mode = _perl_open_mode(args)
                if mode == 'unknown':
                    found.cannot_tell()
                elif mode == 'write':
                    _paths_of(found, args, (2,))
            elif len(args) == 2:
                spec = _lit(args, 1)
                if spec is None:
                    found.cannot_tell()
                else:
                    m = PL_MODE.match(spec)
                    if m and ('>' in m.group(1) or m.group(1) == '+<') and m.group(2) not in ('', '-'):
                        found.add(m.group(2))
        elif name == 'sysopen' and not pkg:
            mode = _perl_flags([t for a in args[2:3] for t in a]) if len(args) > 2 else 'read'
            if mode == 'unknown':
                found.cannot_tell()
            elif mode == 'write':
                _paths_of(found, args, (1,))
        elif path:
            for a in args:
                if a[:1] == [('op', '{')] or (len(a) == 1 and a[0][0] == 'num'):
                    continue
                found.add(_lit([a], 0))
        elif copy:
            _paths_of(found, args, PL_COPY[name])
        else:
            which = PL_ONE[name]
            if which == 'all':
                _paths_of(found, args, range(len(args))) if args else found.cannot_tell()
            else:
                _paths_of(found, args, which)
    return found


def _perl_open_mode(args: List[List[tuple]]) -> str:
    """'read', 'write' or 'unknown' for the mode of a three-argument open: `>`, `>>`, `+<`, `+>`, `+>>`, also with a
    layer (`>:utf8`); a mode that is not a literal cannot be told."""
    text = _lit(args, 1)
    if text is None:
        return 'unknown'
    m = PL_MODE.match(text)
    return 'write' if m and ('>' in m.group(1) or m.group(1) == '+<') else 'read'


ANALYSERS = {'python': _python_writes, 'node': _node_writes, 'ruby': _ruby_writes, 'perl': _perl_writes}


def _inline_writes(c: 'Simple', bodies: List[List[str]]) -> Optional[List[str]]:
    """The literal paths the inline interpreter code of one simple command writes ([] when it runs no interpreter or
    no code is given inline); None when a write cannot be told."""
    words, replace = (_xargs_words(c.raw) or (c.words, False)) if c.xargs else (c.words, False)
    if not words:
        return []
    name = os.path.basename(words[0])
    kind = 'python' if PYTHON.match(name) else name if name in ('node', 'ruby', 'perl') else None
    if kind is None:
        return []
    codes, status, mods = _node_args(words[1:]) if kind == 'node' else _scan_args(words[1:], OPT_SPECS[kind])
    if status == 'script':
        return []
    if status == 'stdin':
        marked = HEREDOC_MARKED.match(c.inputs[-1]) if c.inputs and not c.xargs else None
        if not marked:
            return []
        codes = ['\n'.join(bodies[int(marked.group(1))]) + '\n']
    elif replace:
        return None         # the code text can change under `xargs -I`
    found = ANALYSERS[kind]('\n'.join(codes), mods)
    if found.unknown or (found.chdir and found.paths):
        return None
    return found.paths


def interpreter_writes(cmd: str, cwd: Path) -> Optional[List[Path]]:
    """Absolute paths the inline interpreter code in `cmd` creates, changes or deletes: `python`/`python3 -c`, `node`
    `-e`/`-p`, `ruby -e`, `perl -e`/`-E`, or code fed through a heredoc on the interpreter's own command, also behind
    the prefix words of `_simple` and in `bash -c` and `eval` strings. [] when it shows no write; None when a visible
    write has a path that is not one plain string literal, or one of them cannot be told (a symlink made in the same
    command, `os.chdir`, a replace option of `xargs`, a heredoc or quote `_walk` cannot follow). A script file or
    module (`python3 tool.py`, `-m mod`) is not read: the stated limit. Only scope-guard calls it."""
    try:
        return _interpreter_writes(cmd, cwd)
    except Exception:       # a form this reader does not expect: cannot tell
        return None


def _interpreter_writes(cmd: str, cwd: Path) -> Optional[List[Path]]:
    """`interpreter_writes` without the catch-all: only the ValueError of `_pair_heredocs` (a heredoc left open, a
    substitution in an expanded body: the same commands `write_targets` gives None) is turned into None here."""
    if not INTERPRETER.search(re.sub(r'[\'"\\]', '', cmd)):      # the shell joins `py'thon'3`
        return []
    try:
        text, bodies = _pair_heredocs(cmd)
    except ValueError:
        return None
    walked = _walk(text, cwd)
    if walked is None:
        return None
    out = []
    for c, cwds in walked:
        paths = _inline_writes(c, bodies)
        if paths is None:
            return None
        for tok in paths:
            ps = _resolve_all('./' + tok if tok.startswith('~') else tok, cwds)
            if ps is None:
                return None
            out += ps
    if out and any(c.words and os.path.basename(c.words[0]) == 'ln' for c, _ in walked):
        return None
    return out


def _looks_like_path(tok: str, cwd: Path) -> bool:
    if tok == '' or NOT_PATH.search(tok):
        return False
    if '/' in tok or tok.startswith(('.', '~')):
        return True
    try:
        return (Path(cwd) / tok).exists()
    except OSError:
        return False


def _var_path(tok: str) -> bool:
    return '$' in tok and not VAR_PATH_NOT.search(tok) and ('/' in tok or tok.startswith(('~', '.')))


PATTERN_FIRST = {'sed': ('-e', '-f', '--expression', '--file'), 'awk': ('-f', '--file'), 'gawk': ('-f', '--file'),
                 'grep': ('-e', '-f', '--regexp', '--file'), 'egrep': ('-e', '-f', '--regexp', '--file'),
                 'fgrep': ('-e', '-f', '--regexp', '--file'), 'rg': ('-e', '-f', '--regexp', '--file')}
AWK_VALUE = {'-v', '-F', '--assign', '--field-separator'}


def _text_indexes(words: List[str]) -> set:
    """Indexes in `words` of arguments that are text, not files the command reads: the script or pattern of sed, awk
    or grep (their first positional argument, unless an option such as `-e` or `-f` gives it) and the value of awk's
    `-F` and `-v`."""
    given = PATTERN_FIRST.get(os.path.basename(words[0])) if words else None
    if given is None:
        return set()
    awk = os.path.basename(words[0]) in ('awk', 'gawk')
    out = {i + 1 for i, a in enumerate(words) if awk and a in AWK_VALUE}
    if any(a in given or a.startswith(tuple(g + '=' for g in given if g.startswith('--'))) for a in words[1:]):
        return out
    for i in range(1, len(words)):
        a = words[i]
        if i in out:
            continue
        if a == '--':
            return out | {i + 1}
        if not a.startswith('-') or a == '-':
            return out | {i}
    return out


def _device(tok: str) -> bool:
    return tok == '/dev/null' or tok.startswith(('/dev/fd/', '/dev/std'))


def read_paths(cmd: str, cwd: Path) -> Optional[List[Path]]:
    """Every argument of `cmd` that looks like a path (has `/`, starts with `.` or `~`, or exists under `cwd`),
    resolved against every folder a `cd` may have reached; `--opt=/x` values included, the command word itself and
    patterns (`^/api`, `s/a/b/`, URLs, the script of sed or awk, the pattern of grep) and `/dev/null` not. None when a read cannot be named: a path built from a variable
    (`$HOME/.ssh/x`), or anything `_walk` cannot follow."""
    walked = _walk(cmd, cwd)
    if walked is None:
        return None
    out = []
    for c, cwds in walked:
        skip = _text_indexes(c.words)
        for i, a in list(enumerate(c.words))[1:] + [(None, a) for a in c.inputs]:
            if i in skip:
                continue
            if a.startswith('-'):
                if '=' not in a:
                    continue
                a = a.split('=', 1)[1]
            if _device(a):
                continue
            if _var_path(a):
                return None
            if any(_looks_like_path(a, d) for d in cwds):
                for p in _resolve_all(a, cwds) or []:
                    if p not in out:
                        out.append(p)
    return out


def copy_sources(cmd: str, cwd: Path) -> List[Path]:
    """Source arguments of every cp, mv or rsync in `cmd` (all positional arguments but the last), relative ones
    resolved against the folders a `cd` gives (same rule as `_walk`; a `cd` it cannot name leaves `cwd`)."""
    try:
        cmds = _literal_vars(cmd, _commands(cmd))
    except ValueError:
        return []
    out = []
    for c, cwds in _follow(cmds, cwd) or [(c, [Path(cwd)]) for c in cmds]:
        if c.words and os.path.basename(c.words[0]) in COPY:
            for a in _positional(c.words[1:])[:-1]:
                out += _resolve_all(a, cwds) or []
    return out


CURL_SEND_SHORT = set('dFT')                  # -d DATA, -F FORM, -T FILE (also clustered: -sd)
CURL_SEND_LONG = ('--data', '--form', '--upload-file', '--json', '--url-query')
WGET_SEND_LONG = ('--post-data', '--post-file', '--body-data', '--body-file', '--method')


def http_sends(cmd: str) -> Optional[bool]:
    """Whether a curl or wget in `cmd` sends data (POST/PUT, form, upload); None when `cmd` does not tokenize."""
    try:
        cmds = _commands(cmd)
    except ValueError:
        return None
    for c in cmds:
        if not c.words:
            continue
        name, args = os.path.basename(c.words[0]), c.words[1:]
        if name == 'wget' and any(a.split('=', 1)[0] in WGET_SEND_LONG for a in args):
            return True
        if name != 'curl':
            continue
        for i, a in enumerate(args):
            if a.startswith('--'):
                key = a.split('=', 1)[0]
                if key.startswith(CURL_SEND_LONG):
                    return True
                if key == '--request':
                    method = a.split('=', 1)[1] if '=' in a else (args[i + 1] if i + 1 < len(args) else '')
                    if method.upper() not in ('GET', 'HEAD'):
                        return True
            elif a.startswith('-') and len(a) > 1:
                flags = a[1:]
                for j, ch in enumerate(flags):
                    if ch in CURL_SEND_SHORT:
                        return True
                    if ch == 'X':
                        method = flags[j + 1:] or (args[i + 1] if i + 1 < len(args) else '')
                        if method.upper() not in ('GET', 'HEAD'):
                            return True
                        break
                    if ch in 'oHAeuUwbcEKm':   # options taking a value end the cluster
                        break
    return False


PRINT_ONLY = {'export', 'declare', 'typeset'}
PROC_ENVIRON = re.compile(r'/proc/[^/\s]+/(?:task/[^/\s]+/)?environ')


def _dumps_env(raw: List[str]) -> bool:
    """Whether one simple command (its raw words) prints the environment. Assignments and prefixes come off the way
    `_simple` does them, but `env` is looked through, not dropped: bare `env` (options only) prints, `env -i cmd`
    runs `cmd`, which is then judged on its own."""
    rest, bare_env = list(raw), False
    while rest:
        name = os.path.basename(rest[0])
        if ASSIGN.match(rest[0]) or rest[0] in RESERVED:
            rest.pop(0)
        elif name in PREFIX:
            rest.pop(0)
            while rest and rest[0].startswith('-'):
                opt = rest.pop(0)
                if opt in PREFIX_VALUE.get(name, ()) and rest:
                    rest.pop(0)
            if name == 'timeout' and rest:
                rest.pop(0)
            bare_env = name == 'env'
        else:
            break
    if not rest:
        return bare_env
    name, args = os.path.basename(rest[0]), rest[1:]
    if _python_env(rest):
        return True
    if name == 'printenv':
        return True
    if name == 'set':
        return not args
    if name in PRINT_ONLY:
        return all(a.startswith('-') for a in args)
    return name == 'launchctl' and bool(args) and args[0] == 'getenv'


PY_ENV = re.compile(r'os\.environb?\b|os\.getenvb?\b|from\s+os\s+import\s[^;\n]*\b(?:environb?|getenvb?)\b')
PYTHON = re.compile(r'python(?:3(?:\.\d+)?)?$')
PY_VALUE = {'-W', '-X'}
SUBST = '__MASUBST%d__'


def _python_env(rest: List[str]) -> bool:
    """Whether `rest` (a command, prefixes off) is `python -c <code>` with code that names the environment. Textual
    and best effort: code that reaches it another way (`importlib`, `exec` of a built string, `getattr(os, …)`) is
    not seen."""
    if not rest or not PYTHON.match(os.path.basename(rest[0])):
        return False
    args, i = rest[1:], 0
    while i < len(args) and args[i].startswith('-') and args[i] != '-':
        a = args[i]
        if not a.startswith('--') and a.endswith('c'):
            return i + 1 < len(args) and bool(PY_ENV.search(args[i + 1]))
        i += 2 if a in PY_VALUE else 1
    return False


def _close(text: str, i: int) -> int:
    """Index just past the `)` that closes a `$(` whose body starts at `i`; len(text) when it never closes."""
    n, depth, quote = len(text), 0, None
    while i < n:
        c = text[i]
        if quote == "'":
            quote = None if c == "'" else quote
        elif c == '\\':
            i += 1
        elif c == '$' and text[i + 1:i + 2] == '(':
            i = _close(text, i + 2)
            continue
        elif c == '`':
            i = _backtick(text, i + 1)
            continue
        elif quote == '"':
            quote = None if c == '"' else quote
        elif c in '\'"':
            quote = c
        elif c == '(':
            depth += 1
        elif c == ')':
            if depth == 0:
                return i + 1
            depth -= 1
        i += 1
    return n


def _backtick(text: str, i: int) -> int:
    """Index just past the backtick that closes one whose body starts at `i`; len(text) when it never closes."""
    while i < len(text):
        if text[i] == '\\':
            i += 1
        elif text[i] == '`':
            return i + 1
        i += 1
    return len(text)


MARK = '\x01'       # `git_forms`: put before an unquoted `{` so a brace expansion is told from quoted text
ANSI_SIMPLE = {'a': '\a', 'b': '\b', 'e': '\x1b', 'E': '\x1b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t', 'v': '\v',
               '\\': '\\', "'": "'", '"': '"', '?': '?'}
ANSI_NUMBER = {'x': re.compile(r'[0-9a-fA-F]{1,2}'), 'u': re.compile(r'[0-9a-fA-F]{1,4}'),
               'U': re.compile(r'[0-9a-fA-F]{1,8}'), '0': re.compile(r'[0-7]{1,3}')}
PARAM_OPERAND = re.compile(r'!?(?:[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?|\d+|[@*?$!#-])(?::?[-=+?]|//?[^/]*/)(.*)$', re.S)


def _ansi_c(body: str) -> Optional[str]:
    """The text a `$'<body>'` word stands for, or None when that is not certain: an escape that is unknown, ends the
    string (`\\0`, `\\x00`), needs a locale or a byte (`\\xff`, `\\u00e9`), or has no digits (`\\x`), `\\cX`."""
    out, i, n = [], 0, len(body)
    while i < n:
        c = body[i]
        i += 1
        if c != '\\':
            out.append(c)
            continue
        if i >= n:
            return None
        e = body[i]
        if e in ANSI_SIMPLE:
            out.append(ANSI_SIMPLE[e])
            i += 1
            continue
        if e in '01234567':
            pattern, base, at = ANSI_NUMBER['0'], 8, i
        elif e in 'xuU':
            pattern, base, at = ANSI_NUMBER[e], 16, i + 1
        else:
            return None
        m = pattern.match(body, at)
        if not m or not 0 < int(m.group(), base) < 0x80:
            return None
        out.append(chr(int(m.group(), base)))
        i = m.end()
    return ''.join(out)


def _brace_end(text: str, i: int) -> int:
    """Index just past the `}` that closes the `{` at `i`; len(text) when it never closes."""
    n, depth, quote = len(text), 0, None
    while i < n:
        c = text[i]
        if quote == "'":
            quote = None if c == "'" else quote
        elif c == '\\':
            i += 1
        elif quote == '"':
            quote = None if c == '"' else quote
        elif c in '\'"':
            quote = c
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _default_operand(word: str) -> str:
    """The operand of a `${NAME:-operand}`-style word (default, assign, alternative, error, `${NAME/pat/operand}`), else ''."""
    m = PARAM_OPERAND.match(word[2:-1] if word.endswith('}') else word[2:])
    return m.group(1).lstrip('\'"\\') if m else ''


def _process_at(text: str, i: int) -> bool:
    """Whether a process substitution (`<(`, `>(`, zsh `=(` at a word start) opens at `i`."""
    return text[i + 1:i + 2] == '(' and (text[i] in '<>' or (text[i] == '=' and (i == 0 or text[i - 1] in ' \t\n;&|(')))


def _split_subst(text: str, subs: List[str], drop: bool = False, forms: bool = False):
    """(text with every top-level command substitution replaced by one placeholder word, the same for the body of
    every substitution, nested ones included). Quote-aware like `_scan` but it collects instead of raising, so it
    works on text that does not tokenize: single-quoted text and escapes are skipped, a substitution is found
    inside double quotes, `$((…))` is arithmetic (scanned on), an unclosed one runs to the end of the text.
    `subs` collects the original text of each substitution, placeholders index it. With `drop`, the quoted heredoc
    bodies of each substitution body are removed before its own substitutions are taken out (the usual
    `$(cat <<'EOF' … EOF)` commit message: backticks there are text). With `forms` (`git_forms`) the words are also
    read as the shell reads them: a process substitution is taken out like a command substitution, `$'…'` is the text
    it decodes to (a placeholder when that is not certain), `$"…"` is a double-quoted word, a `${NAME:-<-f>}` word whose
    operand begins with `-`, `+` or `:` is a placeholder, and an unquoted `{` gets a `MARK` before it (a lone `{` too:
    `_commands` reads it as a command start or as a word, `_brace_role`)."""
    out, bodies, i, n, quote = [], [], 0, len(text), None
    while i < n:
        c = text[i]
        proc = forms and quote is None and _process_at(text, i)
        if quote == "'":
            quote = None if c == "'" else quote
        elif c == '\\' and i + 1 < n:
            out.append(text[i:i + 2])
            i += 2
            continue
        elif forms and c == '$' and text[i + 1:i + 2] == '{':
            end = _brace_end(text, i + 1)
            closed = end - 1 > i + 1 and text[end - 1] == '}'
            inside, nested = _split_subst(text[i + 2:end - 1 if closed else end], subs, drop, forms)
            bodies += nested
            if _default_operand(text[i:end])[:1] in ('-', '+', ':'):
                out.append(SUBST % len(subs))
                subs.append(text[i:end])
            else:
                out.append('${' + inside + ('}' if closed else ''))
            i = end
            continue
        elif forms and quote is None and c == '$' and text[i + 1:i + 2] == "'":
            j = i + 2
            while j < n and text[j] != "'":
                j += 2 if text[j] == '\\' else 1
            decoded = _ansi_c(text[i + 2:j]) if j < n else None
            if decoded is None:
                out.append(SUBST % len(subs))
                subs.append(text[i:j + 1])
            else:
                out.append(shlex.quote(decoded))
            i = j + 1
            continue
        elif forms and quote is None and c == '$' and text[i + 1:i + 2] == '"':
            i += 1                   # `$"…"` is the double-quoted word
            continue
        elif forms and quote is None and c == '{' and (text[i + 1:i + 2] not in ('', ' ', '\t', '\n')
                                                      or i == 0 or text[i - 1] in ' \t\n;&|('):
            out.append(MARK + c)
            i += 1
            continue
        elif c == '`' or proc or (c == '$' and text[i + 1:i + 2] == '(' and text[i + 2:i + 3] != '('):
            start = i + (1 if c == '`' else 2)
            end = _backtick(text, start) if c == '`' else _close(text, start)
            closed = end > start and text[end - 1] == ('`' if c == '`' else ')') and end - 1 >= start
            body = text[start:end - 1 if closed else end]
            if c == '`':
                body = re.sub(r'\\([`\\$])', r'\1', body)
            out.append(SUBST % len(subs))
            subs.append(text[i:end])
            inner, nested = _split_subst(_drop_quoted_bodies(body, True) if drop else body, subs, drop, forms)
            bodies += [inner] + nested
            i = end
            continue
        elif quote == '"':
            quote = None if c == '"' else quote
        elif c in '\'"':
            quote = c
        out.append(c)
        i += 1
    return ''.join(out), bodies


def env_reads(cmd: str) -> List[str]:
    """The simple commands of `cmd` (pipelines, `;`, `&&`, `||`, `bash -c` strings, command substitutions included)
    that read the process environment: `env`/`printenv` with no command, `set`/`export`/`declare`/`typeset` with no
    name, `launchctl getenv`, `python -c` code that names `os.environ` (textual, see `_python_env`), any word naming
    `/proc/<pid>/environ`. Each as written. A line with substitutions is judged in pieces, each body and the line with
    every substitution replaced by a placeholder word (put back in the finding); a piece that does not tokenize gives
    no finding (the read-path rule denies it)."""
    subs: List[str] = []
    outer, bodies = _split_subst(_drop_quoted_bodies(cmd), subs)
    out = []
    for piece in [outer] + bodies:
        try:
            cmds = _commands(piece)
        except ValueError:
            continue
        for c in cmds:
            if _dumps_env(c.raw) or any(PROC_ENVIRON.search(w) for w in c.raw + c.inputs):
                text = ' '.join(c.raw + [f'< {i}' for i in c.inputs])
                out.append(re.sub(r'__MASUBST(\d+)__', lambda m: subs[int(m.group(1))], text))
    return out


def _unquote(seg: str) -> str:
    """`seg` as the shell reads its words: backslash-newline gone, escapes and quotes removed (`g"i"t co\\mmit`)."""
    return re.sub(r'[\'"]', '', re.sub(r'\\(.)', r'\1', seg.replace('\\\n', ''), flags=re.S))


def _shape_segs(text: str):
    """(the simple commands of `text` as written, the quote stack left open at its end). Separators inside quotes,
    backticks and `$( … )` do not end a command; an unbalanced quote or `$(` runs to the end of the text."""
    segs, cur, stack, i, n = [], [], [], 0, len(text)
    while i < n:
        c = text[i]
        top = stack[-1] if stack else None
        if top in ("'", '`'):
            if c == '\\' and top == '`' and i + 1 < n:
                cur.append(c)
                i += 1
                c = text[i]
            elif c == top:
                stack.pop()
            cur.append(c)
            i += 1
            continue
        if c == '\\' and i + 1 < n:
            cur.append(text[i:i + 2])
            i += 2
            continue
        if c == '$' and text[i + 1:i + 2] == '(':
            stack.append('(')
            cur.append('$(')
            i += 2
            continue
        if c in '\'"`':
            if c == top:
                stack.pop()
            elif not (top == '"' and c != '"'):
                stack.append(c)
        elif top == '(':
            if c == '(':
                stack.append('(')
            elif c == ')':
                stack.pop()
        elif top is None and c in ';&|\n()':
            segs.append(''.join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    return segs + [''.join(cur)], stack


def _git_commit_shape(text: str, sub: str = 'commit') -> bool:
    """Whether `text` has `git … <sub>` inside one simple command (see `_shape_segs`)."""
    raw, stack = _shape_segs(text)
    segs = [_unquote(seg) for seg in raw]
    if any(re.search(r'\bgit\b.*\b' + re.escape(sub) + r'\b', seg, re.S) for seg in segs):
        return True
    # git as the command word with a quote or `$(` left open: what follows may be `<sub>`
    return bool(stack) and bool(re.match(r'\s*(?:\w+=\S*\s+)*git\b', segs[-1]))


def git_subcommands(cmd: str) -> List[str]:
    """The subcommand of every git in `cmd`, in order; ['?'] when `cmd` does not tokenize and has the shape
    `git … commit` in one simple command."""
    try:
        cmds = _commands(cmd)
    except ValueError:
        try:
            text = _strip_heredocs(cmd)
        except ValueError:
            text = cmd
        return ['?'] if _git_commit_shape(text) else []
    subs = [_git_sub(c.words[1:])[0] for c in cmds if c.words and os.path.basename(c.words[0]) == 'git']
    return [s for s in subs if s is not None]


def command_texts(cmd: str) -> List[str]:
    """The text of every simple command in `cmd` (its words joined by one space; assignments and prefix words such as
    `sudo` and `env` removed, `sh -c` and `eval` bodies read in place), for the text patterns of permission-guard.py.
    A command that does not tokenize (an open quote, a command substitution, an open heredoc) gives its text cut at
    the separators, heredoc bodies stripped where they can be."""
    try:
        return [' '.join(c.words) for c in _commands(cmd) if c.words]
    except ValueError:
        try:
            text = _strip_heredocs(cmd)
        except ValueError:
            text = cmd
        return [piece for piece in (' '.join(p.split()) for p in SEP_PIECE.split(text)) if piece]


class GitForm(NamedTuple):
    verdict: str   # 'deny' or 'ask'
    form: str      # one line naming the form and the word: force push with a + refspec (`+main`)
    text: str      # the simple command as written, substitutions put back, at most 200 characters


GIT_VALUE_OPTS = {'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--super-prefix', '--config-env',
                  '--attr-source'}
HOOKS_PATH = 'core.hookspath'
HOOK_SKIP = '--no-verify'
SUBST_WORD = re.compile(r'__MASUBST(\d+)__')
CONFIG_ENV = re.compile(r'(GIT_CONFIG_KEY_\d+|GIT_CONFIG_PARAMETERS)=(.*)$', re.S)
# per subcommand: dangerous long options (name, shortest abbreviation git accepts here, kind), the long options that
# take a value, the short letters that take a value (the rest of the word, else the next word), the ones that take
# only an attached value, and the judged letters
PUSH_SPEC = {'danger': (('--force', 4, 'force'), ('--force-with-lease', 9, 'lease'), ('--mirror', 4, 'mirror'),
                        ('--delete', 4, 'delete'), ('--prune', 4, 'delete'), (HOOK_SKIP, 6, 'skip')),
             'values': ('--repo', '--receive-pack', '--exec', '--push-option'),
             'value_letters': 'o', 'attached_letters': '', 'judged': {'f': 'force', 'd': 'delete'}}
COMMIT_SPEC = {'danger': ((HOOK_SKIP, 6, 'skip'),),
               'values': ('--message', '--file', '--reuse-message', '--reedit-message', '--fixup', '--squash', '--author',
                          '--date', '--template', '--cleanup', '--pathspec-from-file', '--trailer'),
               'value_letters': 'mFCct', 'attached_letters': 'uS', 'judged': {'n': 'commit-n'}}
FORM_NAMES = {'force': 'force push', 'lease': 'force push with lease', 'mirror': 'mirror push',
              'delete': 'push that deletes remote refs', 'skip': 'hook-skipping option',
              'commit-n': 'commit that skips hooks', 'refspec': 'force push with a + refspec'}


class _Brace(str):
    """A word with a brace expansion that is too big to expand: what it stands for cannot be told."""


BRACE_MAX = 64
SEQ_INT = re.compile(r'(-?\d+)\.\.(-?\d+)(?:\.\.(-?\d+))?$')
SEQ_CHAR = re.compile(r'([^\d,{}])\.\.([^\d,{}])(?:\.\.(-?\d+))?$')
GLOB = re.compile(r'[*?\[]')


def _sequence(body: str):
    """The words of a `{a..b}` body: a list; False when it is no sequence (the braces are text); None when it is too big."""
    m = SEQ_INT.match(body)
    if m:
        first, last, step = int(m.group(1)), int(m.group(2)), abs(int(m.group(3) or 1)) or 1
        padded = any(len(x.lstrip('-')) > 1 and x.lstrip('-')[0] == '0' for x in m.group(1, 2))
        width = max(len(m.group(1)), len(m.group(2))) if padded else 0
    else:
        m = SEQ_CHAR.match(body)
        if not m:
            return False
        first, last, step, width = ord(m.group(1)), ord(m.group(2)), abs(int(m.group(3) or 1)) or 1, 0
    if abs(last - first) // step + 1 > BRACE_MAX:
        return None
    values = range(first, last + 1, step) if first <= last else range(first, last - 1, -step)
    return [str(v).zfill(width) if m.re is SEQ_INT else chr(v) for v in values]


def _brace_words(w: str):
    """The words an unquoted brace expansion in `w` (each `{` to expand has a `MARK` before it) makes, else None when
    there are more than BRACE_MAX. A `{` that is no expansion (`{x}`, `{}`, never closed) is text."""
    s = w.find(MARK + '{')
    if s < 0:
        return [w]
    depth, j, commas = 1, s + 2, []
    while j < len(w) and depth:
        depth += (w[j] == '{') - (w[j] == '}')
        if w[j] == ',' and depth == 1:
            commas.append(j)
        j += 1
    if depth:
        return _brace_words(w[:s] + w[s + 1:])
    if commas:
        cuts = [s + 1] + commas + [j - 1]
        parts = [w[cuts[k] + 1:cuts[k + 1]] for k in range(len(cuts) - 1)]
    else:
        parts = _sequence(w[s + 2:j - 1].replace(MARK, ''))
        if parts is False:
            return _brace_words(w[:s] + w[s + 1:])
        if parts is None:
            return None
    out = []
    for part in parts:
        sub = _brace_words(w[:s] + part + w[j:])
        if sub is None or len(out) + len(sub) > BRACE_MAX:
            return None
        out += sub
    return out


def _braces(words: List[str]) -> List[str]:
    """`words` with every unquoted brace expansion expanded (the shell makes the words, so `git push {+main,x}` is two
    refspecs), the `MARK`s removed, empty results dropped; a word too big to expand stays, as a `_Brace`."""
    out = []
    for w in words:
        if MARK not in w:
            out.append(w)
            continue
        made = _brace_words(w)
        out += [_Brace(w.replace(MARK, ''))] if made is None else [x.replace(MARK, '') for x in made if x.replace(MARK, '')]
    return out


def _prep_inner(text: str, subs: List[str]) -> str:
    """`_tokens` hook for an `sh -c` or `eval` body: the continuation lines joined and the words read like the line
    itself (`_split_subst` with `forms`). A body with a substitution is not followed here: ValueError, so the command
    is judged as one that does not tokenize."""
    out, bodies = _split_subst(_join_lines(text.replace(MARK, '')), subs, False, True)
    if bodies:
        raise ValueError('command substitution')
    return out


def _glob_ask(word: str) -> bool:
    """A word with a glob character that can name an option or a refspec form: it starts with the glob (any file) or
    with `-`, `+` or `:` (a file whose name does). A word with whitespace was quoted: its glob is text."""
    m = GLOB.search(word)
    return bool(m) and (m.start() == 0 or word[0] in '-+:') and not any(c.isspace() for c in word)


def _expands_ask(word: str) -> tuple:
    return ('ask', f'cannot tell what `{word if len(word) <= 80 else word[:79] + "…"}` expands to')


def _judged(kind: str, word: str) -> tuple:
    return ('ask' if kind == 'lease' else 'deny', f'{FORM_NAMES[kind]} (`{word}`)')


def _subst_ask(word: str) -> tuple:
    return ('ask', f'cannot tell what `{SUBST_WORD.search(word).group(0)}` expands to')


def _long_kind(name: str, spec: dict) -> str:
    """The kind of the long option `name` (no `=value`): a dangerous kind, 'value' (takes the next word), or '' (a
    flag). Exact names first; then a prefix of a dangerous name at least as long as its minimum, and a prefix of a
    value option from 4 characters (`--force-if-includes` and `--force-` are no prefix of a dangerous name)."""
    for full, _, kind in spec['danger']:
        if name == full:
            return kind
    if name in spec['values']:
        return 'value'
    for full, least, kind in spec['danger']:
        if len(name) >= least and full.startswith(name):
            return kind
    if len(name) >= 4 and any(v.startswith(name) for v in spec['values']):
        return 'value'
    return ''


def _sub_findings(sub: str, args: List[str]) -> List[tuple]:
    """(verdict, form) of every dangerous form among the arguments of `git push` or `git commit`."""
    spec, out, i, n, after = PUSH_SPEC if sub == 'push' else COMMIT_SPEC, [], 0, len(args), False
    while i < n:
        w = args[i]
        i += 1
        if not after and w == '--':
            after = True
            continue
        name = w.split('=', 1)[0] if w.startswith('--') else w
        found = len(out)
        if after or not w.startswith('-') or w == '-' or any(c.isspace() for c in name):
            if sub == 'push':
                if (w.startswith(':') and len(w) > 1) or (w.startswith('+:') and len(w) > 2):
                    out.append(_judged('delete', w))
                elif w.startswith('+'):
                    out.append(_judged('refspec', w))
            if not after and SUBST_WORD.search(w):
                out.append(_subst_ask(w))
            elif not after and len(out) == found and _glob_ask(w):
                out.append(_expands_ask(w))
        elif w.startswith('--'):
            kind = _long_kind(name, spec)
            if kind == 'value':
                i += '=' not in w
            elif kind:
                out.append(_judged(kind, w))
            elif SUBST_WORD.search(w):
                out.append(_subst_ask(w))
            elif GLOB.search(name):
                out.append(_expands_ask(w))
        else:
            end = len(w)
            for j in range(1, len(w)):
                ch = w[j]
                if ch in spec['value_letters']:
                    i += j == len(w) - 1
                    end = j + 1
                    break
                if ch in spec['attached_letters']:
                    end = j + 1
                    break
                if ch in spec['judged']:
                    out.append(_judged(spec['judged'][ch], w))
            if SUBST_WORD.search(w[:end]):
                out.append(_subst_ask(w[:end]))
            elif len(out) == found and GLOB.search(w[:end]):
                out.append(_expands_ask(w))
    return out


def _hook_skip(name: str) -> bool:
    return len(name) >= 6 and HOOK_SKIP.startswith(name)


def _git_findings(args: List[str]) -> List[tuple]:
    """(verdict, form) of every dangerous form in the arguments of one git command (after the `git` word): a hooks-path
    override in a global config option, then the forms of the subcommand. The global options are parsed here and
    nowhere else (`_git_sub` keeps its own, shorter list)."""
    out, i, n = [], 0, len(args)
    while i < n and args[i].startswith('-'):
        word = args[i]
        i += 1
        name, eq, val = word.partition('=')
        if name not in GIT_VALUE_OPTS:
            continue
        if not eq and i < n:
            val = args[i]
            i += 1
        if name in ('-c', '--config-env'):
            key = val.split('=', 1)[0]
            if SUBST_WORD.search(key):
                out.append(_subst_ask(key))
            elif key.lower() == HOOKS_PATH:
                out.append(('deny', f'hooks-path override (`{key}`)'))
    if i >= n:
        return out
    sub, rest = args[i], args[i + 1:]
    pushing = sub in ('push', 'commit') or any(a in ('push', 'commit') for a in rest)
    if pushing:
        out += [_expands_ask(a) for a in args if isinstance(a, _Brace)]
    if SUBST_WORD.search(sub):
        return out + ([_subst_ask(sub)] if any(a in ('push', 'commit') for a in rest) else [])
    if sub in ('push', 'commit'):
        return out + _sub_findings(sub, rest)
    for a in rest:
        if a == '--':
            break
        name = a.split('=', 1)[0]
        if not any(c.isspace() for c in name) and _hook_skip(name):
            out.append(_judged('skip', a))
    return out


def _assignment_words(raw: List[str]) -> List[str]:
    """The words of one simple command (as written) that the shell takes as variable assignments: those before the
    command word (also after `env` and the other prefix words) and the arguments of `export`, `declare`, `typeset`.
    An argument of git or echo that looks like an assignment is not one."""
    out, rest = [], list(raw)
    while rest:
        name = os.path.basename(rest[0])
        if ASSIGN.match(rest[0]):
            out.append(rest.pop(0))
        elif rest[0] in RESERVED:
            rest.pop(0)
        elif name in PREFIX:
            rest.pop(0)
            while rest and rest[0].startswith('-'):
                opt = rest.pop(0)
                if opt in PREFIX_VALUE.get(name, ()) and rest:
                    rest.pop(0)
            if name == 'timeout' and rest:
                rest.pop(0)
        else:
            break
    if rest and os.path.basename(rest[0]) in PRINT_ONLY:
        out += [w for w in rest[1:] if ASSIGN.match(w)]
    return out


def _hooks_path_env(word: str) -> bool:
    """Whether the assignment `word` sets `core.hooksPath` for git: `GIT_CONFIG_KEY_<n>=core.hooksPath` (any case) or a
    `GIT_CONFIG_PARAMETERS` value that names it."""
    m = CONFIG_ENV.match(word)
    if not m:
        return False
    value = m.group(2).lower()
    return value == HOOKS_PATH if m.group(1).startswith('GIT_CONFIG_KEY') else HOOKS_PATH in value


def _git_runs(words: List[str]) -> List[tuple]:
    """(the words before the `git` word since the last separator, the words after it up to the next separator) for
    every git in `words`. A separator is a word made of `;&|()` (a glued one is split off by the caller)."""
    runs, pre, cur = [], [], None
    for w in words:
        bare = w.rstrip(';&|)')
        if cur is None and os.path.basename(bare) == 'git' and bare:
            cur = []
        elif bare:
            (pre if cur is None else cur).append(bare)
        if bare != w or not bare:
            if cur is not None:
                runs.append((pre, cur))
            pre, cur = [], None
    if cur is not None:
        runs.append((pre, cur))
    return runs


def _unparsed_forms(piece: str) -> List[tuple]:
    """(verdict, form, text) for a piece of the command line that does not tokenize. Without the push or commit shape:
    nothing. With it: the forms visible in the text (each segment unquoted and split on whitespace, every git word
    scanned up to the next separator, the same option rules), else one ask. A heredoc left open caps every finding at
    ask: its text is not a command."""
    capped = False
    try:
        text = _strip_heredocs(piece)
    except ValueError:
        text, capped = piece, True
    if not (_git_commit_shape(text, 'push') or _git_commit_shape(text, 'commit')):
        return []
    found = []
    for seg in _shape_segs(text)[0]:
        words = _braces(re.sub(r'[;&|()]+', lambda m: f' {m.group(0)} ', _unquote(seg)).split())
        for pre, args in _git_runs(words):
            hits = _git_findings(args) + [('deny', f'hooks-path override (`{w}`)')
                                          for w in pre if ASSIGN.match(w) and _hooks_path_env(w)]
            found += [('ask' if capped else v, f, seg.strip().replace(MARK, '')) for v, f in hits]
    return found or [('ask', 'cannot parse the command', piece)]


def _join_lines(piece: str) -> str:
    """`piece` with each backslash-newline continuation removed (an escaped backslash before a newline stays)."""
    return re.sub(r'(?<!\\)((?:\\\\)*)\\\n', r'\1', piece)


def _restore(s: str, subs: List[str], limit: int = 0) -> str:
    """`s` with every substitution placeholder replaced by the text it stood for, on one line (cut to `limit`)."""
    def put(m):
        sub = ' '.join(subs[int(m.group(1))].split()) if int(m.group(1)) < len(subs) else m.group(0)
        return sub[:limit - 1] + '…' if limit and len(sub) > limit else sub
    return SUBST_WORD.sub(put, s)


def _written(raw: List[str]) -> str:
    """The simple command as written, for a reason: its words quoted for one line, without the words of the group it
    stands in (`!`, `then`, `do`, `{` before it, a zsh `}` after it)."""
    words = list(raw)
    while len(words) > 1 and words[0] in RESERVED:
        words.pop(0)
    if len(words) > 1 and words[-1] == '}':
        words.pop()
    return ' '.join(shlex.quote(w) for w in words)


def git_forms(cmd: str) -> List[GitForm]:
    """The dangerous `git push` and `git commit` forms in `cmd` (the check of architecture 4.4 "Git guard"), every one
    found, in order; [] when there is none (also for an empty command and one with no git). Deny: a force option in
    any position or cluster, a `+` refspec, `--mirror`, the forms that delete remote refs, `commit -n`, the long
    hook-skipping option on any subcommand, a hooks-path override (a config option, or `GIT_CONFIG_KEY_<n>` /
    `GIT_CONFIG_PARAMETERS` set on the line that runs git). Ask: `--force-with-lease`, a command substitution in an
    option, refspec or pathspec slot, a command that does not tokenize and shows no form, and a word in such a slot
    that cannot be told (`$'\\xff'`, a brace expansion over BRACE_MAX words, `${X:--f}`, a glob that can name an
    option). The line is judged in pieces like `env_reads` (the line with each substitution, process substitution
    and undecidable word a placeholder, each body), `sh -c`, `eval` and `env -S` bodies followed to depth 3. The words
    are read as the shell reads them: `$'…'` and `$"…"` words, brace expansions (`MARK`ed in `_split_subst`), `=git`.
    A quoted argument is data, a plain `$VAR` word is not judged."""
    subs: List[str] = []
    outer, bodies = _split_subst(_drop_quoted_bodies(cmd, True), subs, True, True)
    found, parsed, ran_git = [], [], False
    for piece in [outer] + bodies:
        piece = _join_lines(piece)       # after the heredoc drop, so message text does not merge into a delimiter line
        try:
            cmds = _commands(piece, 0, lambda text: _prep_inner(text, subs))
        except ValueError:
            found += _unparsed_forms(piece)
            continue
        parsed += cmds
        for c in cmds:
            if c.words and os.path.basename(c.words[0]) == 'git':
                ran_git = True
                text = _written(c.raw or c.words)
                found += [(v, f, text) for v, f in _git_findings(c.words[1:])]
    if ran_git:
        for c in parsed:
            text = _written(c.raw)
            found += [('deny', f'hooks-path override (`{w}`)', text)
                      for w in _assignment_words(c.raw) if _hooks_path_env(w)]
    out = []
    for verdict, form, text in found:
        text = ' '.join(_restore(text, subs).replace(MARK, '').split())
        item = GitForm(verdict, ' '.join(_restore(form, subs, 80).replace(MARK, '').split()),
                       text if len(text) <= 200 else text[:199] + '…')
        if item not in out:
            out.append(item)
    return out
