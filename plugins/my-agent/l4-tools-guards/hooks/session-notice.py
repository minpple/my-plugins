#!/usr/bin/env python3
"""Plugin hook (SessionStart): remind a new, resumed, cleared, compacted or forked session of an
unfinished my-agent task (architecture 4.8.2 "new-session notice"). Prints nothing when no `.active` is found.
The notice depends on the session ids only, whatever the start source: the owner session (same id) gets the
"run /my-agent continue first" notice; any other session gets no notice, because the hooks apply only to the session
that is running the task. A side without an id counts as the owner (so a fork start with no `session_id`
gets the owner notice). Always exits 0.
Codex: always prints exactly one line of plain text, also without an active task: `my-agent on Codex: plugin folder
<root> (read ${CLAUDE_PLUGIN_ROOT} in the skill text as this folder), data folder <data> (${user_config.data_dir}),
task folder <task> (${user_config.task_dir}). Before the first my-agent question, read l1-orchestration/hosts.md in
that plugin folder; ask the person only with request_user_input.`, then, in the owner session of an active task, the
notice text after one space. The folder line is not a rule: it is how the skill finds its folders on a host that does
not expand the variables, so it is printed with or without a task. Codex adds
a SessionStart hook's stdout to the developer context, and Codex does not expand those variables in skill text, so the
line names the folders. It is plain text, not the JSON of the Claude branch: a plain line cannot be malformed JSON.
On any failure nothing is printed.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import ma_active  # noqa: E402
import ma_data  # noqa: E402
import ma_host  # noqa: E402

NOTICE = ('Unfinished my-agent task `{task}`, phase `{phase}`. Run `/my-agent continue` before doing anything else. '
          'If `plan.md` has no approval line, do not delegate or write.')


FOLDERS = ('my-agent on Codex: plugin folder {root} (read ${{CLAUDE_PLUGIN_ROOT}} in the skill text as this folder), '
           'data folder {data} (${{user_config.data_dir}}), task folder {task} (${{user_config.task_dir}}). '
           'Before the first my-agent question, read l1-orchestration/hosts.md in that plugin folder; '
           'ask the person only with request_user_input.')

AGY_FOLDERS = ('my-agent on Antigravity: plugin folder {root} (read ${{CLAUDE_PLUGIN_ROOT}} in the skill text as '
               'this folder), data folder {data} (${{user_config.data_dir}}), task folder {task} '
               '(${{user_config.task_dir}}), session {session} ($CLAUDE_CODE_SESSION_ID). Before the first my-agent '
               'question, read l1-orchestration/hosts-antigravity.md in that plugin folder; '
               'ask the person only with ask_question.')


def folder_line() -> str:
    root = ma_host.plugin_root(Path(__file__).resolve().parents[2])
    return FOLDERS.format(root=root, data=ma_data.data_dir(None), task=ma_data.task_dir(None))


def agy_folder_line(session: str) -> str:
    root = ma_host.plugin_root(Path(__file__).resolve().parents[2])
    return AGY_FOLDERS.format(root=root, data=ma_data.data_dir(None), task=ma_data.task_dir(None),
                              session=session or 'none')


def main() -> int:
    try:
        inp = json.loads(sys.stdin.read() or '{}')
        if not isinstance(inp, dict):
            return 0
        host = ma_host.hook_host(inp)
        inp = ma_host.record_input(inp)
        active = ma_active.find_active(inp.get('cwd') or os.getcwd())
        if host == 'antigravity':
            line = agy_folder_line(inp.get('session_id') or '')
            if active is not None and ma_active.owns(active, inp):
                line = line + ' ' + NOTICE.format(task=active.task, phase=active.phase or '-')
            print(json.dumps({'injectSteps': [{'systemMessage': {'systemMessage': line}}]}, ensure_ascii=False))
            return 0
        line = folder_line() if host == 'codex' else None
        if active is None or not ma_active.owns(active, inp):
            if line:
                print(line)
            return 0
        msg = NOTICE.format(task=active.task, phase=active.phase or '-')
        if line:
            print(line + ' ' + msg)
            return 0
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': msg}},
                         ensure_ascii=False))
    except BaseException:   # the session starts as usual whatever happens
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
