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
Docs-only round (architecture Q48; the script decides, it takes no argument): when `ma_checks.docs_round` says the current record
passed and only documents differ from it, the run narrows. Each unittest discover command runs only the test files that read a
changed document (`-p <file>`, one invocation per file, joined with ` && `), or is carried from the base when no test file reads
one; every other command, and a command the base has no passing line for, runs in full. Run order: keep the base under
`<task folder>/checks/kept/<id>/` (`checks.md` and its logs; `checks.md` is deleted first, so a killed run leaves no record), run
the commands one at a time, write the record last, then delete the kept folders no reference reaches. A full run removes
`checks.md` and all of `checks/`, `kept/` included. The record forms and the first-run, failed-base and HEAD-moved rules are in
`ma_checks.py`. A narrowed run prints `check-commands: docs-only round: <n> run (<m> narrowed), <c> carried, <f> failed, <k> not
run (Environment); record: <task folder>/checks.md`, then `docs-only: <d> paths (<up to 5 paths>); test files: <names | none>`,
then the `failed:` lines (the narrowed command, its source) and the `tree changed by the run:` line. Exit codes are unchanged.
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


summary_of = ma_checks.summary_of   # `Ran <n> tests in <t>s, OK|FAILED …` per `Ran` line, joined with `; `; else the last line


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


def keep_base(task: Path, base: dict, text: str) -> str:
    """Docs-only run order, steps 2 and 3: delete `checks.md` first (a run killed from here on leaves no record), then move the
    base's top-level logs into `checks/kept/<id>/` and write the base text there as its `checks.md`. An existing folder of the
    base's id is reused when its `checks.md` is the same text; otherwise the id gets `-2`, `-3`, …. Returns the folder name."""
    logs = task / ma_schema.CHECKS_LOGS
    kept_root, base_id = logs / ma_schema.CHECKS_KEPT, ma_checks.record_id(base)
    kid, n = base_id, 1
    while True:
        try:
            same = (kept_root / kid / ma_schema.CHECKS).read_text(encoding='utf-8') == text
        except OSError:
            same = not (kept_root / kid).exists()
        if same:
            break
        n += 1
        kid = f'{base_id}-{n}'
    (task / ma_schema.CHECKS).unlink()
    folder = kept_root / kid
    folder.mkdir(parents=True, exist_ok=True)
    for log in sorted(logs.glob('*.log')):
        shutil.move(str(log), str(folder / log.name))
    (folder / ma_schema.CHECKS).write_text(text, encoding='utf-8')
    return kid


def base_ref(line: dict, base_id) -> str:
    """The reference a new line makes to the base line: a carried base line passes its own reference on."""
    return line['ref'] if line['kind'] == 'carried' else f'{base_id}/{line["n"]}'


def carried_result(line: dict, base_id) -> str:
    """The result part of the base line, its log path pointing into `checks/kept/<id>/` when the log was moved there."""
    log = line['log'] if line['kind'] == 'carried' else re.sub(r'^checks/', f'checks/{ma_schema.CHECKS_KEPT}/{base_id}/', line['log'])
    return f'exit {line["code"]} | {line["summary"]} | {line["secs"]} s | {log}'


def drop_unreached(task: Path, record: Path):
    """Docs-only run order, step 6: delete every kept folder the new record's references no longer reach."""
    rec = ma_checks.parse_record(record.read_text(encoding='utf-8'))
    reached = set(ma_checks.kept_closure(task, rec)) if rec else set()
    kept_root = task / ma_schema.CHECKS_LOGS / ma_schema.CHECKS_KEPT
    for entry in sorted(kept_root.iterdir()) if kept_root.is_dir() else []:
        if entry.name not in reached:
            shutil.rmtree(entry, ignore_errors=True) if entry.is_dir() else entry.unlink(missing_ok=True)


def check(task: Path) -> int:
    record, logs = task / ma_schema.CHECKS, task / ma_schema.CHECKS_LOGS
    base_text = None
    try:
        itext = (task / 'intake.md').read_text(encoding='utf-8')
        ptext = (task / 'plan.md').read_text(encoding='utf-8')
        profile = field(itext, 'Profile')
        location = Path(field(itext, 'Location') or task.parent.parent)
        entries = ma_checks.commands_for(task, profile, ptext, strict=True)
        decision = ma_checks.docs_round(task, location, profile, ptext, entries) if entries else {'kind': 'full'}
        if decision['kind'] == 'run due':
            base_text = record.read_text(encoding='utf-8')
            if ma_checks.record_id(decision['base']) is None:
                decision = {'kind': 'full'}
    except (OSError, UnicodeDecodeError) as exc:
        return fail(task, f'cannot read {getattr(exc, "filename", None) or task}: {getattr(exc, "strerror", None) or exc}')
    narrowed = decision['kind'] == 'run due'
    base_id = None
    try:
        if narrowed:
            base_id = keep_base(task, decision['base'], base_text)   # step 2 and 3 of the run order
        else:
            clean(task)
    except OSError as exc:
        return fail(task, f'cannot keep the earlier record in {logs}: {exc.strerror or exc}')
    if not entries:
        return say('no check commands; no record', 0)

    try:
        logs.mkdir(parents=True, exist_ok=narrowed)
    except OSError as exc:
        return fail(task, f'cannot write {logs}: {exc.strerror or exc}')
    plan = decision['plan'] if narrowed else [
        {'entry': e, 'action': 'not run' if e['not_run'] is not None else 'full', 'base': None, 'files': [], 'run': e['run']}
        for e in entries]
    before = ma_checks.fingerprint(location, task)
    results, ran, failed, skipped, carried = [], 0, 0, 0, 0
    try:
        for i, item in enumerate(plan, 1):
            entry, nn, action = item['entry'], f'{i:02d}', item['action']
            if action == 'not run':
                skipped += 1
                results.append(f'- {nn} `{entry["command"]}` ({entry["source"]}) → not run (scope: Environment: {entry["not_run"]})')
                continue
            if action == 'carried':
                carried += 1
                results.append(f'- {nn} `{entry["run"]}` ({entry["source"]}) → carried from {base_ref(item["base"], base_id)}: '
                               f'{carried_result(item["base"], base_id)}')
                continue
            ran += 1
            timed_out, code, secs, summary = run_command(item['run'], location, entry['limit'], logs / f'{nn}.log')
            bad = timed_out or code != 0
            failed += bad
            result = f'timeout after {entry["limit"]} s' if timed_out else f'exit {code}'
            entry['result'], entry['summary'], entry['log'], entry['bad'] = result, summary, logs / f'{nn}.log', bad
            entry['shown'] = item['run']
            prefix = f'narrowed to {", ".join(item["files"])}: ' if action == 'narrowed' else ''
            rest = f'; rest carried from {base_ref(item["base"], base_id)}' if action == 'narrowed' else ''
            results.append(f'- {nn} `{entry["run"]}` ({entry["source"]}) → {prefix}{result} | {summary} | {secs} s | '
                           f'{ma_schema.CHECKS_LOGS}/{nn}.log{rest}')
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
    result_line = f'Result: {ran} run, {failed} failed, {skipped} not run' + (f', {carried} carried' if narrowed else '')
    lines = [f'# Check record: {task.name}', fp_line, f'Taken: {datetime.now():%Y-%m-%d %H:%M:%S}', result_line, ''] + results
    if paths is not None:
        lines += ['', '## Fingerprint paths'] + [f'- {p} {paths[p]}' for p in sorted(paths)]
    tmp = task / TMP_RECORD
    try:
        tmp.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        os.replace(tmp, record)
        if narrowed:
            drop_unreached(task, record)
    except OSError as exc:
        return fail(task, f'cannot write {record}: {exc.strerror or exc}')

    if narrowed:
        docs, files = decision['docs'], decision['files']
        count = sum(1 for item in plan if item['action'] == 'narrowed')
        print(f'check-commands: docs-only round: {ran} run ({count} narrowed), {carried} carried, {failed} failed, '
              f'{skipped} not run (Environment); record: {record}')
        print(f'docs-only: {len(docs)} paths ({", ".join(docs[:5])}); test files: {", ".join(files) or "none"}')
    else:
        print(f'check-commands: {ran} run, {failed} failed, {skipped} not run (Environment); record: {record}')
    for entry in entries:
        if entry.get('bad'):
            print(f'failed: {entry["shown"]} ({entry["source"]}) {entry["result"]}: {entry["summary"]}; log: {entry["log"]}')
    if changed:
        print(f'tree changed by the run: {len(changed)} paths ({", ".join(changed[:5])})')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
