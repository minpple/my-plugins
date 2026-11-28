# my-plugins

Claude Code plugin marketplace: `my-agent` and `my-agent-tray`.

## Layout

- `plugins/my-agent/`: `skills/` (`my-agent/SKILL.md` core rules, `monitor`, `mock-up`), `l1-orchestration/` (procedures, phases, profiles, host notes), `l2-design-judge/agents/` (planner and judges), `l3-workers/agents/` (explorer, researcher, writer, coder), `l4-tools-guards/` (hooks, scripts, shared `lib/`), `codex/` and `antigravity/` (generated host copies), `monitor/` (read-only web monitor), `tests/`, `docs/build-guide/` (the architecture document).
- `plugins/my-agent-tray/`: the menu bar app (macOS Swift, Windows).
- `docs/`: GitHub Pages (`architecture.html` generated, `index.html` and `index-ko.html` by hand) and `blueprint/` (the project record).
- `tools/`: `build-docs.py` and `docs-template.html` (the architecture page), `codex-probe/`, `claude-skill-check.py` (which skills a fresh session registers), `claude_mcp_server.py`. `tests/`: tests for `tools/`, the pages and the READMEs.

## Commands

```sh
cd plugins/my-agent && python3 -m unittest discover -s tests                   # L1~L4 rules and hooks
cd plugins/my-agent/monitor && python3 -m unittest discover tests            # monitor
python3 -m unittest discover -s tests                                        # tools/ (architecture page, feature pages, READMEs)
cd plugins/my-agent-tray && python3 -m unittest discover -s tests            # menu bar app (skips without swiftc)
```

- One test file: `cd plugins/my-agent && python3 -m unittest discover -s tests -p test_skill_md.py` (`python3 -m unittest tests.test_x` fails: `helpers` is not on the path). The full plugin suite takes over 180 s; in a tool call with that limit, run it as two halves, `-p 'test_[a-h]*.py'` and `-p 'test_[i-z]*.py'`.
- The root suite prints many tool-output lines from tests of failure cases, on stdout and stderr (for example `Outcome: problem`, `refusing to run inside the repository …`, `plugin-list.txt shows version …`); they are expected. The exit code, or the `OK` or `FAILED` line after `Ran <n> tests`, decides.
- Generators: `python3 tools/build-docs.py` (`docs/architecture.html`), `python3 plugins/my-agent/l4-tools-guards/scripts/build-codex.py --write` and `python3 plugins/my-agent/l4-tools-guards/scripts/build-antigravity.py --write` (the Codex and Antigravity copies). Each takes `--check` to report a stale output.
- There is no build step (Python and static HTML). Exception: the Swift app in `plugins/my-agent-tray/macos/menubar/` is built with `sh plugins/my-agent-tray/macos/menubar/build.sh` (optional).
- Environment: the tool versions are under "Requirements" in `README.md`; do not copy them here.

## After a change

### Which tests a change needs

| Changed | Run |
|---|---|
| `plugins/my-agent/docs/build-guide/my-agent-architecture.md` | `python3 tools/build-docs.py`, then the plugin suite (`test_agents`, `test_arch_doc`, `test_blueprint` read it) and the root suite |
| other files under `plugins/my-agent/docs/` (`reference.md`, `agent-models.example.json`) | the plugin suite (`test_arch_doc`, `test_agent_models`) |
| `plugins/my-agent-tray/macos/menubar/README.md` | the tray suite (`test_menubar`) and the root suite |
| `plugins/my-agent-tray/README.md`, `plugins/my-agent/monitor/README.md` | the root suite |
| `plugins/my-agent/monitor/web/index.html` | the monitor, tray and root suites |
| `plugins/my-agent/l2-design-judge/agents/verifier.md` or `reviewer.md` | also `plugins/my-agent/tests/judge-fixtures/run-judge-check.sh` (it calls a real model), besides the suites and generators |
| `docs/index.html`, `docs/index-ko.html`, `README.md`, `README-ko.md` | the root suite; a README version row also `test_version_sync` in the plugin suite |
| `CLAUDE.md` | `test_skill_md` (it pins the size line) |
| `docs/blueprint/*.md` | `python3 plugins/my-agent/l4-tools-guards/scripts/blueprint.py check --loc . --data-dir ~/.my-agent-data` only |
| `docs/handoff/` (not in git) | nothing |
| code, rules, agent definitions, hooks, tests | the suites that cover them, and the generators in the next table |

### Generated files and pairs

| Edit | Then |
|---|---|
| An agent definition | `build-codex.py --write` and `build-antigravity.py --write`; their `--check` fails while the copies differ |
| `plugins/my-agent/l4-tools-guards/hooks/hooks.json` | Codex reads it directly (the manifest's `hooks` path). The Antigravity plugin-root `hooks.json` comes from the `ANTIGRAVITY_HOOKS` table in `build-antigravity.py`, which `--check` does not compare with this file: for a change that applies to Antigravity, edit the table, then run `build-antigravity.py --write` |
| A manifest, agent frontmatter or a `hooks.json` | `claude plugin validate --strict` in the plugin folder and in the repository root (the marketplace) |
| A file under `plugins/my-agent/` or `tools/docs-template.html` (the page reads the manifest, agent definitions, SKILL.md, phase, profile and procedure files, hooks, permissions, docstrings and the architecture document); `python3 tools/build-docs.py --check` tells whether the page is stale | `python3 tools/build-docs.py`; `tests/test_build_docs.py` fails while the page is out of date. A renamed heading the generator cuts by stops the build: update `ARTIFACTS`, `STEP_RULES` or `L1_SOURCES` in the generator |
| `README.md` or `README-ko.md` | the other one, with the same content (including the tool versions under requirements) |
| `docs/index.html` or `docs/index-ko.html` | the other one, with the same content; both are maintained by hand and no generator touches them |

- The pre-commit hook `.githooks/pre-commit` runs `tools/build-docs.py` on every commit and stages the page. Turn it on once per clone: `git config core.hooksPath .githooks`.
- Generated, never edited by hand: `docs/architecture.html` (`build-docs.py`); `plugins/my-agent/.codex-plugin/plugin.json` and `codex/` (`build-codex.py`); `plugins/my-agent/.antigravity-plugin/plugin.json`, `antigravity/`, `rules/AGENTS.md` and the plugin-root `hooks.json` (`build-antigravity.py`).
- `plugins/my-agent/monitor/web/index.html` is edited by hand; it has no generator.

## Conventions

- Write all documents, comments, prompts and messages in this repository in English. Exceptions: `README-ko.md` (the Korean README), `docs/index-ko.html` (the Korean feature page), the Korean UI strings of the monitor (`plugins/my-agent/monitor/web/index.html`), and Korean strings quoted as data in any file (UI text, output a rule, record or test cites, the `한국어` language links).
- File and folder names: English, lowercase, hyphen-separated (`aa-bb-cc.md`); underscores only where a tool or format requires them (Python modules, `test_*.py`). This is the "CLAUDE.md naming rule" the architecture document cites.
- Plugin code is Python standard library only. `tools/claude_mcp_server.py` is the exception: a local tool that needs `.venv` with `anthropic` and `mcp`.
- Write home paths in tracked files as `~/`, never as an absolute `/Users/<name>/` path (examples use `/Users/x/`).
- Write every run-log command in a rule file in full, `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" <kind> …`: `test_run_log_templates_run` runs only commands written that way.
- Keep `plugins/my-agent/skills/my-agent/SKILL.md` under 15,000 characters: it holds the core rules and the arguments only, and the procedures are in `plugins/my-agent/l1-orchestration/` (`new-task.md`, `resume.md`, `recorder.md`, `gates.md`, `retro.md`, `changes.md`). So does every file L1 reads in one go (those procedure files, the phase and profile files, `hosts.md`, `unit-copies.md`; `test_skill_md` checks both); `hosts-antigravity.md` has 11,500 (`test_antigravity`). Place rules by purpose, not by the room left; the reason for the limit is the size-limit line under `## Constraints` in `docs/blueprint/decisions.md`. Measure a size with Python `len()` on the UTF-8-decoded text; `wc -m` in a C locale counts bytes and reads high.
- my-agent must behave only as designed in `plugins/my-agent/docs/build-guide/my-agent-architecture.md`: change the design there first, then the rules. Do not put temporary exceptions or workaround wording into the runtime rules.
- Do not pin the wording of record documents (`docs/blueprint/*.md`, `docs/handoff/`) in tests; tests may pin the specification (`plugins/my-agent/docs/build-guide/my-agent-architecture.md`), rule files and generated pages.
- A new plugin goes in `plugins/<name>/` with an entry in `.claude-plugin/marketplace.json`; add it to `.agents/plugins/marketplace.json` only when it ships a Codex manifest, and update `test_codex_marketplace`, which pins both lists.

## Versioning

Each plugin has its own version. When you raise one, change all these places of that plugin together, in the same commit. All these values must always match.

- my-agent: `"version"` in `plugins/my-agent/.claude-plugin/plugin.json`, in `plugins/my-agent/.codex-plugin/plugin.json` and in `plugins/my-agent/.antigravity-plugin/plugin.json` (`build-codex.py --write` and `build-antigravity.py --write` generate the Codex and Antigravity ones from the Claude one, so run both after raising the version, and after a merge that raised it), and the `my-agent` rows of the plugin tables in `README.md` and `README-ko.md`
- my-agent-tray: `"version"` in `plugins/my-agent-tray/.claude-plugin/plugin.json`, and the `my-agent-tray` rows of the plugin tables in `README.md` and `README-ko.md`
- Not shown by the `grep` below, also in the same commit: the version literals in `plugins/my-agent/tests/test_version_sync.py` (`test_every_version_place_shows_…`), and `test_status_line_starts_with_the_newest_entry` in `plugins/my-agent/tests/test_arch_doc.py` with the architecture document's status line (then `python3 tools/build-docs.py`).

Check that the values show the same version for each plugin:

```sh
grep -n '"version"' plugins/my-agent/.claude-plugin/plugin.json plugins/my-agent/.codex-plugin/plugin.json plugins/my-agent/.antigravity-plugin/plugin.json plugins/my-agent-tray/.claude-plugin/plugin.json
grep -n '^| `my-agent' README.md README-ko.md
```

Tag that commit `<plugin>-v<version>` (for example `git tag my-agent-v0.5.1`) and push the tag with the commit (`git push origin main my-agent-v0.5.1`). Tag every version on the commit that raised it; the versions tagged neither locally nor on the remote are listed in `docs/blueprint/backlog.md`. The older `v0.x` tags stay as they are.

## Records

- `docs/blueprint/` (`features.md`, `decisions.md`, `backlog.md`) is the record of what the plugins are now, in the format of `plugins/my-agent/l3-workers/blueprint-format.md`: a my-agent task updates it after G3, and a direct edit in a normal session updates the entries it changes, with the ID `direct-<yymmdd>-<slug>`. A dependence on external behavior, a point to watch or an accepted limit goes into `decisions.md`; an open risk or a probe still to run goes into `backlog.md` as `[next]`.
- There is no separate change log: what changed and when is in git and in the architecture document's status line.

## Don't

- Commit `plugins/my-agent/docs/ref/`: it holds local copies of other people's documents and the repository is public. List each source in `plugins/my-agent/docs/reference.md` instead.
- Commit `.my-agent/` (my-agent task records), `.superpowers/` or `CLAUDE.local.md` (personal instructions); all are excluded from git.
