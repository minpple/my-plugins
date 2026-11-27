#!/usr/bin/env python3
"""Run the task's check commands once and record the result with a working-tree fingerprint (accept.md step 3B; architecture Q47).

usage: check-commands.py --task "<absolute task folder>"

Reads `Location:` and `Profile:` from intake.md. Applies in the dev profile, and in the general profile when plan.md has a
`my-agent:coder` unit; never in the research profile. The commands, in this order with duplicates removed: each plan unit's
`- Check commands:` (the backticked spans of the line and the first span of each nested bullet), then the commands under
`## Check commands` of explore.md. `- Environment:` lines of scope.md (plan.md for a small task) mark a command `not run here`
(not run, no log), `replaced by` another command, or `fails before the task` (source label only).
Each command runs one at a time with `shell=True` from the task location, in a new process group, with its output streamed into
`<task folder>/checks/<nn>.log` (line 1 `$ <command>`, line 2 `cwd: <folder>`, line 3 `time limit: <n> s`, then the output,
then `exit <code> after <n> s` or `timeout after <n> s`). The time limit is twice the duration on the matching explore.md line,
or twice the longest duration there for another command, at least 60 s, 600 s when no duration is given; a command that
passes it is killed and counts as failed.
Writes `<task folder>/checks.md` last, through a temporary file and a rename (format: `ma_checks.py`). The fingerprint is taken
before the first command and again after the last; when they differ (a command changed files git does not ignore) the record
says `Fingerprint: none (tree changed by the run: <n> paths)` and the script prints `tree changed by the run: <n> paths (<paths>)`;
when the second one cannot be taken the record says `Fingerprint: none (git status failed after the run)`.
Prints `check-commands: <n> run, <f> failed, <k> not run (Environment); record: <task folder>/checks.md`, then one
`failed: <command> (<source>) <exit N | timeout after N s>: <summary>; log: <path>` line per failed command.
When nothing applies or the list is empty it prints `check-commands: no check commands; no record` and removes any old record.
exit: 0 every command that ran passed (or nothing to run), 1 the record is written and a command failed or timed out,
2 bad arguments, 3 the script could not do its job, also on an unexpected error (prints `check-commands: not run: <cause>; no
record`, no record left).
"""
import argparse
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import ma_checks  # noqa: E402
import ma_schema  # noqa: E402

TMP_RECORD = '.checks.md.tmp'


def say(text: str, code: int) -> int:
    print(f'check-commands: {text}')
    return code


def field(text: str, name: str):
    m = re.search(rf'(?m)^{name}:\s*(.*\S)\s*$', text or '')
    return m.group(1) if m else None


def summary_of(output: str) -> str:
    """`Ran <n> tests in <t>s, OK|FAILED …` for unittest output, else the last non-blank line (200 characters), else `(no output)`."""
    lines = [l.rstrip() for l in output.splitlines()]
    for i, line in enumerate(lines):
        if ma_checks.RAN_LINE.match(line):
            ran = ma_checks.RAN_LINE.match(line).group(0)
            tail = [l for l in lines[i + 1:] if l.startswith('OK') or l.startswith('FAILED')]
            if tail:
                return f'{ran}, {tail[-1]}'
    spoken = [l for l in lines if l.strip()]
    return spoken[-1].strip()[:200] if spoken else '(no output)'


def run_command(command: str, cwd: Path, limit: int, log: Path):
    """Run one command into `log`; returns (timed_out, exit code, seconds, summary)."""
    start = time.monotonic()
    with open(log, 'wb') as out:
        header = f'$ {command}\ncwd: {cwd}\ntime limit: {limit} s\n'.encode('utf-8', 'surrogateescape')
        out.write(header)
        out.flush()
        proc = subprocess.Popen(command, shell=True, cwd=str(cwd), stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        timed_out = False
        try:
            code = proc.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.wait()
            code = proc.returncode
    secs = limit if timed_out else max(1, math.ceil(time.monotonic() - start))
    raw = log.read_bytes()
    output = raw[len(header):].decode('utf-8', 'replace')
    footer = f'timeout after {limit} s' if timed_out else f'exit {code} after {secs} s'
    with open(log, 'ab') as out:
        out.write((b'' if not raw or raw.endswith(b'\n') else b'\n') + footer.encode() + b'\n')
    return timed_out, code, secs, summary_of(output)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('--task', required=True)
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    task = Path(args.task).resolve()
    try:
        return check(task)
    except Exception as exc:   # anything else still ends in the one `not run` line, exit 3 and no record
        return fail(task, f'unexpected error: {type(exc).__name__}: {exc}')


def clean(task: Path):
    (task / ma_schema.CHECKS).unlink(missing_ok=True)
    shutil.rmtree(task / ma_schema.CHECKS_LOGS, ignore_errors=True)


def fail(task: Path, cause: str) -> int:
    try:
        clean(task)
        (task / TMP_RECORD).unlink(missing_ok=True)
    except OSError:
        pass
    return say(f'not run: {cause}; no record', 3)


def check(task: Path) -> int:
    record, logs = task / ma_schema.CHECKS, task / ma_schema.CHECKS_LOGS
    try:
        clean(task)
        itext = (task / 'intake.md').read_text(encoding='utf-8')
        ptext = (task / 'plan.md').read_text(encoding='utf-8')
        profile = field(itext, 'Profile')
        location = Path(field(itext, 'Location') or task.parent.parent)
        entries = ma_checks.commands_for(task, profile, ptext, strict=True)
    except (OSError, UnicodeDecodeError) as exc:
        return fail(task, f'cannot read {getattr(exc, "filename", None) or task}: {getattr(exc, "strerror", None) or exc}')
    if not entries:
        return say('no check commands; no record', 0)

    try:
        logs.mkdir(parents=True)
    except OSError as exc:
        return fail(task, f'cannot write {logs}: {exc.strerror or exc}')
    before = ma_checks.fingerprint(location, task)
    results, ran, failed, skipped = [], 0, 0, 0
    try:
        for i, entry in enumerate(entries, 1):
            nn = f'{i:02d}'
            if entry['not_run'] is not None:
                skipped += 1
                results.append(f'- {nn} `{entry["command"]}` ({entry["source"]}) → not run (scope: Environment: {entry["not_run"]})')
                continue
            ran += 1
            timed_out, code, secs, summary = run_command(entry['run'], location, entry['limit'], logs / f'{nn}.log')
            bad = timed_out or code != 0
            failed += bad
            result = f'timeout after {entry["limit"]} s' if timed_out else f'exit {code}'
            entry['result'], entry['summary'], entry['log'], entry['bad'] = result, summary, logs / f'{nn}.log', bad
            results.append(f'- {nn} `{entry["run"]}` ({entry["source"]}) → {result} | {summary} | {secs} s | '
                           f'{ma_schema.CHECKS_LOGS}/{nn}.log')
    except OSError as exc:
        return fail(task, f'cannot run or log a command: {exc.strerror or exc}')

    after = ma_checks.fingerprint(location, task)
    changed = []
    if before is None:
        fp_line, paths = 'Fingerprint: none (not a git location)', None
    elif after is None:
        fp_line, paths = 'Fingerprint: none (git status failed after the run)', None
    elif (before['head'], before['files']) != (after['head'], after['files']):
        changed = ma_checks.differing_paths(before['paths'], after['paths'])
        fp_line, paths = f'Fingerprint: none (tree changed by the run: {len(changed)} paths)', None
    else:
        fp_line = f'Fingerprint: head={after["head"]} files={after["files"]} paths={len(after["paths"])}'
        paths = after['paths']
    lines = [f'# Check record: {task.name}', fp_line, f'Taken: {datetime.now():%Y-%m-%d %H:%M:%S}',
             f'Result: {ran} run, {failed} failed, {skipped} not run', ''] + results
    if paths is not None:
        lines += ['', '## Fingerprint paths'] + [f'- {p} {paths[p]}' for p in sorted(paths)]
    tmp = task / TMP_RECORD
    try:
        tmp.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        os.replace(tmp, record)
    except OSError as exc:
        return fail(task, f'cannot write {record}: {exc.strerror or exc}')

    print(f'check-commands: {ran} run, {failed} failed, {skipped} not run (Environment); record: {record}')
    for entry in entries:
        if entry.get('bad'):
            print(f'failed: {entry["run"]} ({entry["source"]}) {entry["result"]}: {entry["summary"]}; log: {entry["log"]}')
    if changed:
        print(f'tree changed by the run: {len(changed)} paths ({", ".join(changed[:5])})')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
