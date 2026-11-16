# New task: Flags · Intake

L1 reads this file when a new task starts, before Intake item 1 (SKILL.md "Procedure files"); `continue`, `status` and a phase rerun read it only for a flag problem.

## Flags

Check the leading words of the argument before Intake item 1. Leading words starting with `--` are flags (`--auto` and the profile flags); a `--dev` or `--auto` later in the request is part of the request text. A leading em dash (`—dev`, macOS autocorrect of `--`) reads as `--`.

- Valid: one of `--general`, `--research`, `--dev` (lowercase), `--auto` alone, or `--auto` with one profile flag in either order, then a request.
- Invalid: an unknown name (`--foo`), a different case (`--Dev`, `--Auto`), two profile flags, `--auto` twice, or a flag before `continue`, `status` or a phase name. Show the valid flags; popup: `Let the Router pick (Recommended)` / `Abort`. `Let the Router pick` drops every flag, `--auto` included, and treats the rest as a call without flags (`continue` runs `continue`; an empty rest shows the no-argument popup).
- Valid flags with no request: popup, question "Type the request in the Other field": `Type the request in Other (Recommended)` / `Abort`. Read the request from Other, then start the task with those flags.
- In these three popups, `Abort` stops the call and creates nothing.
- `Request:` keeps the leading flags as written; the label rule (Intake item 3) looks for a profile flag among the leading flags.
- Record these popups only when a new task starts, as `--ask`/`--answer` values of the create call (Intake item 10) with the item 1–5 popups. Always give `rec=`; do not start the `q=` value with `--` (e.g. `q="dev flag outside a git repository"`). After `Let the Router pick` leads to `continue` or `status`, write none.

## Intake (step 1, Router)

In order. In one message run the facts call (SKILL.md "Data folder") and Read `${CLAUDE_PLUGIN_ROOT}/l1-orchestration/recorder.md`. Items 1–5 and the Git check read its lines and run no command; the create call of item 6 does items 5–10 after all popups. If an item fails, show the reason and popup: `Retry (Recommended)` / `Abort`. Exit 1 or 2 of the create call wrote nothing. Exit 3 names what it wrote: show it in the popup; for both choices first finish "Abort" in `changes.md` when `.active` was written (`Retry` reruns the call).

1. **Task already running:** The task location candidates are the git root of the folder you ran in or, outside a git repository, the location `<data folder>/active-index.json` gives for the run folder and the folders the item 2 popup offers. If `<task_dir>/.active` exists in one, popup: `Continue it (Recommended)` / `Abort that task and start new` / `Cancel`. If the task location is a git repository, add the choice `New task in a worktree` ("Task worktree" in `changes.md`). If its `uncommitted:` is above 0, ask about the changes as a second question in the popup. Continue it runs `continue`; abort first finishes "Abort" in `changes.md`. A valid profile flag applies only after `Abort that task and start new`; after `Continue it` or `Cancel` the flag is ignored. A request naming an existing file or skill outside the data folder: rerun the facts call with `--candidate "<that folder>"` before the item 2 popup.
2. **Task location:**
   - Inside a git repository (`run_git:`), it is the repository root; do not ask.
   - Otherwise, popup every time: `<data folder> (Recommended)` / `Current folder` / `Other path`. For `Other path`, a second popup asks for the path in Other.
   - If the request names an existing file or skill outside the data folder, offer its folder (git root if any) first, `(Recommended)`.
   - If the chosen location is not one item 1 checked (an `Other path`) and has `<task_dir>/.active`, show the item 1 popup for it first (facts rerun with `--candidate "<path>"`).
   - The task folder is `<task location>/<task_dir>/<task-id>/`.
   - Then do the **Git check** (every profile; below item 11).
3. **Profile:** With a valid profile flag (Flags), use that profile; the Router does not pick. For `--dev` outside a git repository, popup with the reason: `Proceed as general (Recommended)` / `Abort` (`Abort` stops the call and creates nothing). After `Proceed as general`, `Request:` keeps `--dev` as its first word while `Profile:` is general; the label is `(set by you)`. Without a flag, the Router picks one from the request by the rules below and asks: popup with its pick first as `<profile> (Recommended)`, then the others (no `dev` outside a git repository); the question gives the reason for the pick in one line. If the person picks another profile, item 10 writes a `profile` line. Label in the report and first gate popup: `(set by you)` if a profile flag is among the leading flags of `Request:` or the run-log has a `profile` line (also after `continue`), else `(Router)`. Change it later: "Profile change at the first gate" in `changes.md`. The Router's pick:
   - `dev`: requests that change code in a git repository (feature, bug fix, refactoring); the deliverable is a commit. Outside a git repository, pick `general` and give the reason in the report.
   - `research`: requests to research a topic into a note or report with sources (mainly web).
   - `general`: any other multi-step task.
   - **Models preset:** see "Models preset" below item 11.
4. **Task ID:** The create call makes `<date>-<slug>` from your `--slug` and adds `-b`, `-c` if the folder exists; the facts `date:` and `ids:` lines show the day's IDs. The slug: 2–4 English words for the request without the profile flag, lowercase, digits, hyphens, at most 30 characters. No question; the first gate popup shows it.
5. **`.gitignore`:** Only when the `gitignore:` line is `ask`, popup: `Don't commit (Recommended)` / `Commit`. The question says `Commit` puts task records into the project's commits. Don't commit is `--gitignore ignore` (the line `*`); Commit is `--gitignore commit` (the line `# my-agent: commit`).
6. **`.active` and index:** The one create call: `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/intake.py" create --loc "<task location>" --profile <profile> --slug <slug> --request='<the request line as is>' [--preset <name>] [--follows <task ID>] [--gitignore ignore|commit] [--auto] [--router-pick <Router's pick>] [--ask '<fields>' --answer '<fields>' ...] --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"`. A `'` in the request is written `'\''`; no other character changes. The `q=`, `rec=`, `choice=` values hold no quote characters (leave them out). The single-quoted `--request=`, `--ask` and `--answer` values are data: a backtick, `$(`, `;` or `|` inside them does not breach "Tool choice". Exit 1 (`.active` or the task folder exists) and 2 (invalid argument, named in its message) write nothing. It writes `.active` (`phase: 1`, `started:` its own time, `session:` from the environment) and, when the task location differs from the folder you ran in (or its git root), one line `{"<run folder>": "<task location>"}` in `<data folder>/active-index.json`.
7. **`intake.md`:** The create call writes it:

   ```text
   Status: active
   my-agent: <the facts plugin: value>
   Location: <task location>
   Profile: <general | research | dev>
   Task: <task-id>
   Request: <the request as written, one line; keep the leading valid flags as written, drop invalid flags the person let the Router replace>
   ```

   For a follow-up, add `Follows: <previous task ID>` (`--follows`). When the preset file has presets for the profile, add `Models: <preset>` (`--preset`, Intake item 3).
8. **Project list:** The create call adds one line to `<data folder>/projects.txt` when `listed:` is `no`, never deleting lines.
9. **Monitor:** The create call starts it; put its `monitor:` line in the report as `Monitor: <line>`. If it does not start, the task goes on; `"autostart": false` in `<data folder>/monitor-config.json` gives the reason `autostart off`. Not a run-log line.
10. **Record:** The create call writes the run-log lines in this order: `step n=1 name=Intake` (with a statusline file, also the `baseline` cost line); the flag popups and the item 1–5 popups in order asked, from `--ask 'gate=Q q="<question>" rec="<choice>"'` / `--answer 'gate=Q choice="<choice>"'`; with `--auto`, `delegate state=on how=flag` (Delegation covers popups after it; the item 1–5 and flag popups go to the person); only when `Models:` was written, `models preset=<name> source=file`; only when the person picked another profile than the Router's (item 3), `profile from=<Router's pick> to=<choice> back=- archive=-`. Handle `MISMATCH:` lines as `recorder.md` "Failure handling" says.
11. **Report:** In 7 lines or fewer, show the task ID (`task:` line), task location, profile (`(set by you)` or `(Router)`) and monitor line; the git line (`Git: <branch>, clean` or `Git: <branch>, <n> uncommitted`) only when the Git check ran; `Task folder: <task_dir>` only when it is not `.my-agent`; `Delegated approval: on (--auto)` only when it is on. Then step 2 in `define.md`.

**Git check (item 2)** — In every profile, once the location is set, read its `git:` line. Only when it is `true` (a local git repository), use `uncommitted:` and `branch:`. Otherwise skip the whole check: no question, no `Git:` line. The script leaves out `*.pyc` and `__pycache__/`; also leave out build outputs in `path:` lines. Popup only for a problem: uncommitted changes (not when item 1 already asked about them), a detached HEAD (`branch: (detached)`), or the branch `main` or `master`. The question lists the problems and the advice: commit or stash, or switch to a work branch. Choices: `Fix it first (Recommended)` / `Proceed as is` / `Abort` (`Abort` stops the call and creates nothing). After `Fix it first` and "done", rerun the facts call with `--candidate "<task location>"` and repeat the check. Item 11 shows the result.

**Models preset (item 3)** — after the profile is set, read the facts `presets <profile>:` lines. Only with 2 or more presets, popup (an item 1–5 popup: to the person, recorded in item 10): the question opens with one line saying what a preset is; 2–4 choices, one per line, the first `(Recommended)`. One preset or `none`: no popup (one preset: `standard` is used). An `error:` line: show the cause in one line and popup `Use definition values (Recommended)` / `Abort`; after `Use definition values` there is no `Models:` or `models` line, as with a missing file.
