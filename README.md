# my-plugins

**English** | [한국어](README-ko.md)

A Claude Code plugin marketplace by minpple.

| Plugin | Version | Description |
|---|---|---|
| `my-agent` | 0.37.1 | Multi-agent task skill with human approval (HITL): plan → execute → verify → review |
| `my-agent-tray` | 0.1.8 | macOS menu bar app for the my-agent monitor (optional; needs my-agent 0.5.0 or later) |

## Requirements

- Claude Code with plugin support. Tested with Claude Code 2.1.311; the minimum version was not checked.
- Python 3.9 or later, available as `python3` in `PATH` (standard library only). Tested with Python 3.13.7. Hooks, scripts and the monitor server run on it.
- git, for the `dev` profile (base commit, unit copies of parallel coders, commit). Tested with git 2.50.1.
- macOS, for the monitor's window opening. Tested on macOS 27.0.1. On other platforms the monitor opens a tab through the standard browser opener; this was not tried. Linux and Windows were not tried: the hooks call `python3`.
- Optional, for the menu bar app (the `my-agent-tray` plugin) only: Command Line Tools (`swiftc`) on macOS 12 or later; Xcode is not required. Tested with Swift 6.3.3; older Swift versions were not tried.
- Optional, to use my-agent in Codex: Codex CLI with plugin support. Tested with codex-cli 0.166.0; other versions were not tried.
- Optional, to use my-agent in Antigravity: Antigravity CLI (`agy`) with plugin support.

Nothing else is installed.

## Install

```bash
claude plugin marketplace add minpple/my-plugins
claude plugin install my-agent@my-plugins
claude plugin install my-agent-tray@my-plugins   # optional: macOS menu bar app
```

The hooks and the permission rules of my-agent apply only while the skill is running a task, in the session that runs it; a session that has the plugin on but runs no task is not asked or blocked by them. During a task the plugin's `permission-guard.py` hook applies the `ask` and `deny` lists of `plugins/my-agent/l4-tools-guards/permissions/permissions.json` on Claude Code. The `ask` list raises the risky-action prompts (G2: `git commit`, `git push`, `rm -rf`, package installs, MCP tools that send outward). The `deny` list blocks reads of secret and credential files (`*.pem`, `*.key`, `*.p12`, `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.kube`, …, and these `.env` files only: `.env`, `.env.local`, `.env.production`, `.env.development`, `.env.staging`, `.env.test` and `.env.<name>.local`). Other `.env.<name>` files (for example `.env.prod`, `.env.dev`, `.env.ci`) and the template files (`.env.example`) are not denied; if you keep secrets under another name, add a `Read` rule for it to your own settings. Nothing is merged into `~/.claude/settings.json`: if you merged the list for a version before 0.26.0, remove those rules from `permissions` there, or they keep acting in every session. In `bypassPermissions` mode an `ask` becomes a deny, and in auto mode an `ask` rests on Claude Code showing the dialog for a hook's ask. During a task the `git-guard.py` hook also judges the parsed `git push` and `git commit` command on every host. It denies force pushes (`-f`, `--force`, a `+` refspec, `--mirror`), pushes that delete remote refs, `git commit -n`, the hook-skipping option and a hooks-path override, and it asks before `--force-with-lease`. Read deny rules stop Claude Code's file tools and the paths named in a command (`cat .env`, `head x.pem`), not a path built from a variable or a subprocess that opens the file itself: `sh -c 'cat "$HOME"/x.key'` still reads the file. Claude Code's sandbox is the OS-level option.

When you enable the plugin, Claude Code asks for two settings. The first is the data folder (default `~/.my-agent-data`; change it later in `/config`). It holds everything my-agent keeps outside task folders: the project list (`projects.txt`), the run index (`active-index.json`), the monitor state, log and settings, the price override, the improvement list (`feedback.md`) and the retrospective report copies (`gate-report/`). A leading `~` is expanded. Nothing is written into the plugin's own folder. If the folder is changed, the old one is left as is and the new one is used from then on. If the setting is missing (for example with `--plugin-dir`), `~/.my-agent-data` is used. The environment variables `MA_DATA_DIR` (data folder), `MA_PROJECTS_FILE`, `MA_FEEDBACK_FILE` and `MA_GATE_REPORT_DIR` win over the setting. Before 0.34.0 the data folder variable was called `MA_TASKS_DIR`; that name is no longer read, so rename it. A folder from an earlier version (`~/my-agent`) is not moved: move it to the new place, or set the Data folder to the old path. The second setting, `task_dir`, is the task folder inside the task location (default `.my-agent`; change it later in `/config`). Task records were kept in `docs/agent` in earlier versions: they are not moved or read unless you set `task_dir` to `docs/agent` (or move the folder: `mv docs/agent .my-agent`). It must be a relative path without `..`; otherwise the default is used. The environment variable `MA_TASK_DIR` wins over the setting.

Optionally, the data folder can hold `agent-models.json`, which defines named model presets per profile (a model and an effort per agent; copy `plugins/my-agent/docs/agent-models.example.json` to start). With two or more presets for the profile, my-agent asks which one to use at the start of a task. A preset may also mark a role `"model": "inline"` (the shipped `inline` preset does so for all ten roles); the main session then runs that role itself instead of starting an agent, on both hosts. Without the file nothing changes: every agent runs on the model and effort of its definition file.

## Use in Codex

my-agent also runs in Codex. Only a local clone of this repository was tried as the marketplace source:

```bash
git clone https://github.com/minpple/my-plugins ~/dev/my-plugins
codex plugin marketplace add ~/dev/my-plugins
codex plugin add my-agent@my-plugins
```

- Codex does not run a plugin's hooks until you trust them. Start Codex once; on the `Hooks need review` screen, trust the my-agent hooks (`t` trusts all). Before that, Intake names the hooks that did not run.
- Codex lists the main skill as `my-agent:my-agent`, beside `my-agent:monitor`, from `skills/my-agent/SKILL.md`. At session start the my-agent hook gives Codex one line with the plugin, data and task folders.
- Codex loads agent definitions from `~/.codex/agents/`, not from the plugin. Intake installs the ten my-agent roles there as `my-agent-<role>`, so Codex runs subagents as my-agent roles. Until they are installed, Codex refuses the names, and the subagent start and stop records and the role-based checks do not apply.
- At the start of a task Intake checks the ten my-agent agents in `~/.codex/agents/` and, when they are missing or stale, asks before installing them (`build-codex.py --install-agents`). A file without the my-agent version comment is never overwritten. New agents show in a new Codex session.
- `/my-agent:monitor` is the skill `my-agent:monitor` in Codex, and Codex lists it.
- Codex differs in some places: no coder unit copies, no background start, and the plugin settings are not passed. Codex has no G2 permission dialog of its own: a risky action stops the call, my-agent asks in its own popup, and after `Allow once` it lets that one call through. Model presets apply on Codex through the `codex` section of `agent-models.json`; agent `tools` and `maxTurns` are not available. `plugins/my-agent/l1-orchestration/hosts.md` maps each name, and section 4.14 of `plugins/my-agent/docs/build-guide/my-agent-architecture.md` lists the limits.

## Use in Antigravity

my-agent also runs in Antigravity (`agy`). Install from a local clone of this repository and install the ten Antigravity subagent definitions into `~/.gemini/config/agents/`:

```bash
git clone https://github.com/minpple/my-plugins ~/dev/my-plugins
agy plugin install ~/dev/my-plugins/plugins/my-agent
python3 ~/dev/my-plugins/plugins/my-agent/l4-tools-guards/scripts/build-antigravity.py --install-agents
```

- `plugins/my-agent/.antigravity-plugin/plugin.json` and `plugins/my-agent/hooks.json` are generated by `build-antigravity.py --write` alongside the ten agent definitions under `plugins/my-agent/antigravity/agents/`.
- At session start `session-notice.py` injects a system message with the plugin folder (`$PLUGIN_ROOT`), data folder, task folder and conversation ID (`$ANTIGRAVITY_CONVERSATION_ID`), and points L1 to `plugins/my-agent/l1-orchestration/hosts-antigravity.md`.
- The gate hooks (`scope-guard.py`, `plan-approved-check.py`, `verdict-fresh-check.py`, `git-guard.py`) translate Antigravity's camelCase `PreToolUse` payloads and emit native Antigravity decisions (`allow`, `deny`, `force_ask`).
- Model presets apply on Antigravity through the `antigravity` section of `agent-models.json` (`inherit`, `pro`, `flash`, `flash_lite`, or `inline`). Antigravity has no `SubagentStart`, `SubagentStop` or `PermissionRequest` hook events, so `subagent-log.py call` logs subagent invocations on `PreToolUse` while G2 confirmations use `force_ask`.

## my-agent

The main session (L1) takes a request, runs plan → execute → verify → review (Verify and Review start together), and asks the person in a popup at fixed points.

| Level | Members |
|---|---|
| L1 | Main session (`/my-agent` skill): runs the steps, delegates, asks, records |
| L2 | `scope-reviewer` · `architect` · `plan-reviewer` · `verifier` · `reviewer` · `gate-analyst`: scope and plan judgments, plans, result judgments, decision analysis |
| L3 | `explorer` · `researcher` · `writer` · `coder`: one assigned piece of work each |
| L4 | Tools·MCP · hooks · permission rules · scripts: running, recording and blocking |

The whole architecture — each level's components, their roles and permissions, the steps and gates, and the format of every task file — is on one page, `docs/architecture.html`, published as [architecture](https://minpple.github.io/my-plugins/architecture.html). The site root, [introduction](https://minpple.github.io/my-plugins/), shows the feature overview. `python3 tools/build-docs.py` builds the architecture page from the plugin files; run it again after changing them.

| Command | What it does |
|---|---|
| `/my-agent <request>` | Starts a new task. |
| `/my-agent --auto <request>` | Starts a new task and lets the main session answer the routine popups. At the final acceptance (G3) it has every open review item fixed (up to 3 rounds), then accepts when none is left; risky actions (G2) and escalations (E) still go to you. Combine with a profile flag if you like. |
| `/my-agent --dev <request>` | Starts a new task with the profile you name: `--general`, `--research` or `--dev`. Without a flag, the profile is picked from the request. |
| `/my-agent continue` | Continues the task in progress. |
| `/my-agent status` | Shows the task in progress and recent tasks. |
| `/my-agent:monitor` | Opens a local, read-only web page of task records, with a Report tab that sums up the scope, plan and results of the selected task on one page. Also `status`, `stop`. The monitor does not start on its own when a task starts; set `"autostart": true` in `monitor-config.json` (data folder) to have it start. |

At each approval (scope, plan, final acceptance) one `pre-gate.py` call prints the findings table (BLOCKER, SHOULD-FIX and NITPICK, each with the counts found, fixed and open per round), and the writer writes the G1-B and G3 gate report. Every popup starts with a label line such as `[1B] Explore → Scope · Q`. The popup shows the counts line `BLOCKER · <n> / SHOULD-FIX · <n> / NITPICK · <n>` and each open item on its own line.

Task records are kept in `<task location>/<task_dir>/<task ID>/` (by default `.my-agent/<task ID>/`).
Finished tasks pile up there and in the monitor's list. To move tasks finished 30 days ago or more to `<task_dir>/.archived/` (out of the list; move a folder back to bring it back):

```bash
python3 ~/dev/my-plugins/plugins/my-agent/l4-tools-guards/scripts/archive-tasks.py --dry-run [--data-dir <folder>] [--task-dir <folder>]   # list only
python3 ~/dev/my-plugins/plugins/my-agent/l4-tools-guards/scripts/archive-tasks.py [--days N] [--data-dir <folder>] [--task-dir <folder>]
```

Run by hand in a shell, the script does not know the setting. Unless your data folder is the default `~/.my-agent-data`, pass it with `--data-dir <folder>` so the script finds the project list; likewise pass `--task-dir <folder>` if you changed `task_dir`.

What a project is now is kept in the project blueprint, `<task location>/docs/blueprint/`: `features.md` (what exists, with each completion criterion and what checks it), `decisions.md` (constraints, non-goals and decisions later tasks must keep) and `backlog.md` (what is still open). Every task reads it at the start and updates it after the final acceptance, in all three profiles. Unlike the task records it is meant to be committed: in the dev profile it is part of the task's commit, in the other profiles the changed files are left for you to commit. A task run outside any project keeps no blueprint.

While a task runs, what one coder unit learned reaches the later ones through the coder notes: a coder's final report may end with a notes part of at most 10 lines (conventions found, traps, commands that work, choices later units must keep), L1 saves it in `coder-notes.md` in the task folder, and only later coder units get the file path. Unlike the blueprint and the retrospective, which work after the task, the notes work during it.

## Update and remove

```bash
claude plugin marketplace update my-plugins
claude plugin update my-agent@my-plugins
claude plugin uninstall my-agent@my-plugins
claude plugin update my-agent-tray@my-plugins      # if installed
claude plugin uninstall my-agent-tray@my-plugins   # if installed
```

## Repository layout

- `CLAUDE.md`: notes for development (folder roles, test commands, version rule)
- `.claude-plugin/marketplace.json`: plugin list
- `.agents/plugins/marketplace.json`: plugin list for Codex
- `plugins/<name>/`: a plugin. Only this folder is copied on install.
- `tools/build-docs.py`, `tools/docs-template.html`: build the my-agent architecture page
- `docs/architecture.html`: the architecture page (generated; GitHub Pages source `main` · `/docs`)
- `docs/index.html`: the my-agent feature overview in English (the site root; maintained by hand)
- `docs/index-ko.html`: the my-agent feature overview in Korean (maintained by hand)
- `tests/`: tests for `tools/`
- `docs/handoff/`: handoff notes for work continued in another environment
- `.my-agent/`: my-agent task records from this repository. Excluded from git.
- `plugins/my-agent/docs/reference.md`: sources of the reference documents. The local copies in `plugins/my-agent/docs/ref/` are excluded from git.

## License

[MIT](LICENSE)
