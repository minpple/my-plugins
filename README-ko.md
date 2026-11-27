# my-plugins

[English](README.md) | **한국어**

minpple의 Claude Code 플러그인 마켓플레이스입니다.

| 플러그인 | 버전 | 설명 |
|---|---|---|
| `my-agent` | 0.37.1 | 사람의 승인(HITL)을 끼운 멀티 에이전트 작업 스킬: 계획 → 실행 → 검증 → 리뷰 |
| `my-agent-tray` | 0.1.8 | my-agent 모니터용 macOS 메뉴바 앱 (선택; my-agent 0.5.0 이상 필요) |

## 요구 사항

- 플러그인을 지원하는 Claude Code. Claude Code 2.1.311로 테스트했고, 최소 버전은 확인하지 않았습니다.
- Python 3.9 이상, `PATH`에서 `python3`로 실행 가능(표준 라이브러리만 씀). Python 3.13.7로 테스트했습니다. hook, 스크립트, 모니터 서버가 이것으로 돕니다.
- git: `dev` 프로파일(기준 커밋, 병렬 coder의 작업 단위 복사본, 커밋)에 필요. git 2.50.1로 테스트했습니다.
- macOS: 모니터의 창 열기에 필요. macOS 27.0.1에서 테스트했습니다. 다른 플랫폼에서는 모니터가 표준 브라우저 열기 도구로 탭을 열지만 시험하지 않았습니다. Linux와 Windows는 시험하지 않았습니다: hook이 `python3`를 부릅니다.
- 선택, 메뉴바 앱(`my-agent-tray` 플러그인)에만: macOS 12 이상의 Command Line Tools(`swiftc`). Xcode는 필요 없습니다. Swift 6.3.3으로 테스트했고, 더 낮은 Swift 버전은 시험하지 않았습니다.
- 선택, Codex에서 my-agent를 쓰려면: 플러그인을 지원하는 Codex CLI. codex-cli 0.166.0으로 테스트했고, 다른 버전은 시험하지 않았습니다.
- 선택, Antigravity에서 my-agent를 쓰려면: 플러그인을 지원하는 Antigravity CLI(`agy`).

그 밖에 설치하는 것은 없습니다.

## 설치

```bash
claude plugin marketplace add minpple/my-plugins
claude plugin install my-agent@my-plugins
claude plugin install my-agent-tray@my-plugins   # 선택: macOS 메뉴바 앱
```

my-agent의 훅과 권한 규칙은 스킬이 작업을 수행하는 동안에만, 그 작업을 수행하는 세션에만 적용됩니다. 플러그인을 켜 두었더라도 작업을 하고 있지 않은 세션은 이 규칙으로 묻거나 막지 않습니다. 작업 중에는 플러그인의 `permission-guard.py` 훅이 `plugins/my-agent/l4-tools-guards/permissions/permissions.json`의 `ask`·`deny` 목록을 Claude Code에서 적용합니다. `ask` 목록은 위험한 행동 확인(G2: `git commit`, `git push`, `rm -rf`, 패키지 설치, 밖으로 보내는 MCP 도구)을 띄우고, `deny` 목록은 비밀값·자격 증명 파일 읽기(`*.pem`, `*.key`, `*.p12`, `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.kube`, …, 그리고 `.env` 파일은 `.env`, `.env.local`, `.env.production`, `.env.development`, `.env.staging`, `.env.test`, `.env.<name>.local`만)를 막습니다. 그 밖의 `.env.<name>` 파일(예: `.env.prod`, `.env.dev`, `.env.ci`)과 템플릿 파일(`.env.example`)은 막지 않으므로, 비밀값을 다른 이름으로 두었다면 그 이름의 `Read` 규칙을 자기 설정에 직접 추가합니다. `~/.claude/settings.json`에는 아무것도 병합하지 않습니다. 0.26.0 이전 버전에서 이 목록을 병합해 두었다면 그곳의 `permissions`에서 해당 규칙을 지우세요. 지우지 않으면 모든 세션에서 계속 작동합니다. `bypassPermissions` 모드에서는 `ask`가 거부로 바뀌고, auto 모드에서는 Claude Code가 훅의 ask에 대화상자를 띄우는 것에 `ask`가 달려 있습니다. 작업 중에는 `git-guard.py` 훅도 모든 호스트에서 파싱한 `git push`·`git commit` 명령을 판단합니다. 강제 푸시(`-f`, `--force`, `+` refspec, `--mirror`), 원격 ref를 지우는 푸시, `git commit -n`, 훅 건너뛰기 옵션, 훅 경로 덮어쓰기는 막고, `--force-with-lease`는 먼저 묻습니다. 읽기 deny 규칙은 Claude Code의 파일 도구와 명령에 적힌 경로(`cat .env`, `head x.pem`)만 막고, 변수로 만든 경로나 파일을 직접 여는 하위 프로세스는 막지 못합니다: `sh -c 'cat "$HOME"/x.key'`는 파일을 읽습니다. OS 수준의 방법은 Claude Code의 샌드박스입니다.

플러그인을 켤 때 Claude Code가 설정 두 가지를 묻습니다. 첫째는 데이터 폴더입니다(기본값 `~/.my-agent-data`, 나중에 `/config`에서 바꿀 수 있습니다). my-agent가 작업 폴더 밖에 두는 모든 것이 여기에 들어갑니다: 프로젝트 목록(`projects.txt`), 실행 색인(`active-index.json`), 모니터 상태·로그·설정, 가격 재정의, 개선 목록(`feedback.md`), 회고 보고서 사본(`gate-report/`). 앞의 `~`는 홈 폴더로 펼쳐집니다. 플러그인 자기 폴더에는 아무것도 쓰지 않습니다. 폴더를 바꾸면 이전 폴더는 그대로 두고 그때부터 새 폴더를 씁니다. 설정이 없으면(예: `--plugin-dir`로 불러온 경우) `~/.my-agent-data`를 씁니다. 환경변수 `MA_DATA_DIR`(데이터 폴더), `MA_PROJECTS_FILE`, `MA_FEEDBACK_FILE`, `MA_GATE_REPORT_DIR`이 설정보다 먼저 적용됩니다. 0.34.0 이전에는 데이터 폴더 변수 이름이 `MA_TASKS_DIR`였습니다. 이 이름은 더 이상 읽지 않으니 `MA_DATA_DIR`로 바꾸세요. 이전 버전의 폴더(`~/my-agent`)는 옮겨 주지 않습니다. 새 위치로 직접 옮기거나, 데이터 폴더를 옛 경로로 지정하세요. 둘째 설정 `task_dir`은 작업 위치 안의 작업 폴더입니다(기본값 `.my-agent`, 나중에 `/config`에서 바꿀 수 있습니다). 이전 버전은 작업 기록을 `docs/agent`에 두었습니다. 이 기록은 옮기거나 읽어 주지 않으므로, `task_dir`을 `docs/agent`로 지정하거나 폴더를 직접 옮기세요(`mv docs/agent .my-agent`). `..`가 없는 상대 경로여야 하며, 아니면 기본값을 씁니다. 환경변수 `MA_TASK_DIR`이 설정보다 먼저 적용됩니다.

데이터 폴더에는 선택적으로 `agent-models.json`을 둘 수 있습니다. 프로필별로 이름 붙인 모델 프리셋(에이전트마다 모델과 effort)을 정의하는 파일이며, `plugins/my-agent/docs/agent-models.example.json`을 복사해서 시작하세요. 프로필에 프리셋이 둘 이상이면 작업을 시작할 때 어느 것을 쓸지 묻습니다. 프리셋은 역할을 `"model": "inline"`으로 표시할 수도 있습니다(함께 제공되는 `inline` 프리셋은 열 역할 모두를 그렇게 표시합니다). 그러면 에이전트를 시작하지 않고 메인 세션이 그 역할을 직접 실행하며, 두 호스트 모두에서 같습니다. 파일이 없으면 아무것도 바뀌지 않습니다. 모든 에이전트가 정의 파일의 모델과 effort로 실행됩니다.

## Codex에서 쓰기

my-agent는 Codex에서도 돕니다. 마켓플레이스 원본으로는 이 저장소의 로컬 클론만 시험했습니다:

```bash
git clone https://github.com/minpple/my-plugins ~/dev/my-plugins
codex plugin marketplace add ~/dev/my-plugins
codex plugin add my-agent@my-plugins
```

- Codex는 플러그인의 hook을 신뢰하기 전에는 실행하지 않습니다. Codex를 한 번 열고 `Hooks need review` 화면에서 my-agent hook을 신뢰하세요(`t`는 모두 신뢰). 그 전에는 Intake가 실행되지 않은 hook의 이름을 알려 줍니다.
- Codex는 메인 스킬을 `my-agent:my-agent`로 `my-agent:monitor`와 함께 `skills/my-agent/SKILL.md`에서 목록에 올립니다. 세션을 시작할 때 my-agent hook이 Codex에 플러그인, 데이터, 작업 폴더를 알려 주는 한 줄을 줍니다.
- Codex는 에이전트 정의를 플러그인이 아니라 `~/.codex/agents/`에서 불러옵니다. Intake가 my-agent 역할 열 개를 `my-agent-<role>`로 그곳에 설치하므로 Codex가 서브에이전트를 my-agent 역할로 실행합니다. 설치되기 전에는 Codex가 그 이름을 거부하고, 서브에이전트 시작·종료 기록과 역할 기반 점검이 적용되지 않습니다.
- 작업을 시작할 때 Intake가 `~/.codex/agents/`의 my-agent 에이전트 열 개를 점검하고, 없거나 오래되었으면 설치하기 전에 물어봅니다(`build-codex.py --install-agents`). my-agent 버전 주석이 없는 파일은 덮어쓰지 않습니다. 새 에이전트는 새 Codex 세션에서 보입니다.
- `/my-agent:monitor`는 Codex에서 스킬 `my-agent:monitor`이며, Codex가 목록에 올립니다.
- Codex에서 다른 점: coder 작업 단위 복사본 없음, 백그라운드 시작 없음, 플러그인 설정이 전달되지 않음. Codex에는 자체 G2 권한 대화상자가 없습니다. 위험한 작업은 호출을 멈추고, my-agent가 자기 팝업으로 묻고, `Allow once` 뒤에 그 호출 하나만 통과시킵니다. 모델 프리셋은 `agent-models.json`의 `codex` 섹션으로 Codex에서도 적용되고, 에이전트의 `tools`와 `maxTurns`는 쓸 수 없습니다. `plugins/my-agent/l1-orchestration/hosts.md`가 이름을 하나씩 대응시키고, `plugins/my-agent/docs/build-guide/my-agent-architecture.md`의 4.14절에 제한이 정리되어 있습니다.

## Antigravity에서 쓰기

my-agent는 Antigravity(`agy`)에서도 돕니다. 이 저장소의 로컬 클론에서 플러그인을 설치하고, 열 개의 Antigravity 서브에이전트 정의를 `~/.gemini/config/agents/`에 설치합니다:

```bash
git clone https://github.com/minpple/my-plugins ~/dev/my-plugins
agy plugin install ~/dev/my-plugins/plugins/my-agent
python3 ~/dev/my-plugins/plugins/my-agent/l4-tools-guards/scripts/build-antigravity.py --install-agents
```

- `plugins/my-agent/.antigravity-plugin/plugin.json`, `plugins/my-agent/hooks.json`, 그리고 `plugins/my-agent/antigravity/agents/`의 에이전트 열 개는 `build-antigravity.py --write`로 생성합니다.
- 세션이 시작될 때 `session-notice.py`가 플러그인 폴더(`$PLUGIN_ROOT`), 데이터 폴더, 작업 폴더, 세션 ID(`$ANTIGRAVITY_CONVERSATION_ID`)를 시스템 메시지로 주입하고 `plugins/my-agent/l1-orchestration/hosts-antigravity.md`를 안내합니다.
- 가드 훅(`scope-guard.py`, `plan-approved-check.py`, `verdict-fresh-check.py`, `git-guard.py`)은 Antigravity의 camelCase `PreToolUse` 입력을 변환해 네이티브 결정(`allow`, `deny`, `force_ask`)을 반환합니다.
- 모델 프리셋은 `agent-models.json`의 `antigravity` 섹션(`inherit`, `pro`, `flash`, `flash_lite`, 또는 `inline`)으로 적용됩니다. Antigravity에는 `SubagentStart`, `SubagentStop`, `PermissionRequest` 훅 이벤트가 없으므로, 서브에이전트 호출은 `PreToolUse`에서 `subagent-log.py call`이 기록하고 G2 확인은 네이티브 `force_ask`로 처리합니다.

## my-agent

메인 세션(L1)이 요청을 받아 계획 → 실행 → 검증 → 리뷰를 돌리고(검증과 리뷰는 함께 시작), 정해진 지점마다 팝업으로 사람에게 묻습니다.

| 레벨 | 구성 |
|---|---|
| L1 | 메인 세션 (`/my-agent` 스킬): 단계 진행, 위임, 질문, 기록 |
| L2 | `scope-reviewer` · `architect` · `plan-reviewer` · `verifier` · `reviewer` · `gate-analyst`: 범위·계획 판정, 계획, 결과 판정, 결정 해석 |
| L3 | `explorer` · `researcher` · `writer` · `coder`: 맡은 작업 하나 |
| L4 | 도구·MCP · hook · 권한 규칙 · 스크립트: 실행, 기록과 차단 |

레벨별 구성 요소, 각 구성의 역할과 권한, 단계와 게이트, 작업 파일마다의 형식까지 전체 구조는 한 페이지 `docs/architecture.html`에 있고, [architecture](https://minpple.github.io/my-plugins/architecture.html) 에서 볼 수 있습니다. 사이트 첫 화면 [introduction](https://minpple.github.io/my-plugins/) 은 기능 소개 페이지입니다. `python3 tools/build-docs.py`가 플러그인 파일에서 아키텍처 페이지를 만들며, 플러그인 파일을 고친 뒤 다시 실행합니다.

| 명령 | 하는 일 |
|---|---|
| `/my-agent <요청>` | 새 작업을 시작합니다. |
| `/my-agent --auto <요청>` | 새 작업을 시작하고 일상적인 팝업은 메인 세션이 대신 답합니다. 최종 인수(G3)에서는 열린 리뷰 항목을 모두 고치게 하고(최대 3회), 남은 것이 없으면 수락합니다. 위험한 작업(G2)과 에스컬레이션(E)은 계속 사람에게 옵니다. 프로필 플래그와 함께 쓸 수 있습니다. |
| `/my-agent --dev <요청>` | 지정한 프로필로 새 작업을 시작합니다: `--general`, `--research`, `--dev`. 플래그가 없으면 요청을 보고 프로필을 고릅니다. |
| `/my-agent continue` | 진행 중인 작업을 이어 갑니다. |
| `/my-agent status` | 진행 중인 작업과 최근 작업을 보여 줍니다. |
| `/my-agent:monitor` | 작업 기록을 보는 로컬 웹 페이지(읽기 전용)를 띄웁니다. 선택한 작업의 범위·계획·결과를 한 페이지로 요약하는 Report 탭이 있습니다. `status`, `stop`. 작업을 시작해도 모니터는 저절로 뜨지 않습니다. 뜨게 하려면 데이터 폴더의 `monitor-config.json`에 `"autostart": true`를 넣습니다. |

승인(범위, 계획, 최종 인수)마다 `pre-gate.py`를 한 번 호출하면 지적 표(BLOCKER, SHOULD-FIX, NITPICK별 라운드마다 발견·수정·열린 개수)가 출력되고, G1-B와 G3의 관문 리포트는 writer가 씁니다. 모든 팝업은 `[1B] Explore → Scope · Q` 같은 라벨 줄로 시작합니다. 팝업은 개수 줄 `BLOCKER · <n> / SHOULD-FIX · <n> / NITPICK · <n>`과 열린 항목을 한 줄에 하나씩 보여 줍니다.

작업 기록은 작업 위치의 `<task location>/<task_dir>/<작업 ID>/`에 남습니다(기본값은 `.my-agent/<작업 ID>/`).
끝난 작업은 그곳과 모니터 목록에 계속 쌓입니다. 끝난 지 30일 이상 된 작업을 `<task_dir>/.archived/`로 옮겨 목록에서 빼려면 다음을 실행합니다(되돌리려면 폴더를 다시 옮깁니다):

```bash
python3 ~/dev/my-plugins/plugins/my-agent/l4-tools-guards/scripts/archive-tasks.py --dry-run [--data-dir <폴더>] [--task-dir <폴더>]   # 목록만
python3 ~/dev/my-plugins/plugins/my-agent/l4-tools-guards/scripts/archive-tasks.py [--days N] [--data-dir <폴더>] [--task-dir <폴더>]
```

셸에서 직접 실행하면 스크립트는 설정을 알지 못합니다. 데이터 폴더가 기본값 `~/.my-agent-data`가 아니면 `--data-dir <폴더>`로 알려 주어야 프로젝트 목록을 찾습니다. `task_dir`을 바꿨다면 `--task-dir <폴더>`도 같이 알려 주세요.

프로젝트의 현재 상태는 프로젝트 blueprint인 `<task location>/docs/blueprint/`에 남습니다: `features.md`(지금 있는 기능과 완료 기준, 그 기준을 확인하는 방법), `decisions.md`(이후 작업이 지켜야 하는 제약, 비목표, 결정), `backlog.md`(아직 남은 일). 세 프로필 모두에서 작업이 시작할 때 이 폴더를 읽고 최종 인수 뒤에 갱신합니다. 작업 기록과 달리 커밋하는 파일입니다: dev 프로필에서는 작업의 커밋에 함께 들어가고, 다른 프로필에서는 바뀐 파일을 직접 커밋하도록 남겨 둡니다. 프로젝트 밖에서 실행한 작업은 blueprint를 두지 않습니다.

작업이 진행되는 동안 앞선 coder 유닛이 알게 된 것은 coder 노트로 뒤의 유닛에 전해집니다: coder의 최종 보고는 10줄 이하의 노트 부분(찾아낸 관례, 함정, 통하는 명령, 뒤 유닛이 지켜야 할 선택)으로 끝날 수 있고, L1이 이를 작업 폴더의 `coder-notes.md`에 저장하며, 파일 경로는 뒤의 coder 유닛만 받습니다. 작업이 끝난 뒤에 쓰이는 blueprint와 회고와 달리, 노트는 작업 중에 쓰입니다.

## 업데이트와 제거

```bash
claude plugin marketplace update my-plugins
claude plugin update my-agent@my-plugins
claude plugin uninstall my-agent@my-plugins
claude plugin update my-agent-tray@my-plugins      # 설치했다면
claude plugin uninstall my-agent-tray@my-plugins   # 설치했다면
```

## 저장소 구조

- `CLAUDE.md`: 개발용 안내(폴더 역할, 테스트 명령, 버전 규칙)
- `.claude-plugin/marketplace.json`: 플러그인 목록
- `.agents/plugins/marketplace.json`: Codex용 플러그인 목록
- `plugins/<이름>/`: 플러그인. 설치하면 이 폴더만 복사됩니다.
- `tools/build-docs.py`, `tools/docs-template.html`: my-agent 아키텍처 페이지를 만듭니다
- `docs/architecture.html`: 아키텍처 페이지(생성물, GitHub Pages 소스 `main` · `/docs`)
- `docs/index.html`: my-agent 기능 소개 영어판(사이트 첫 화면, 직접 관리)
- `docs/index-ko.html`: my-agent 기능 소개 한국어판(직접 관리)
- `tests/`: `tools/` 테스트
- `docs/handoff/`: 다른 환경에서 이어 할 작업의 handoff 문서
- `.my-agent/`: 이 저장소에서 돌린 my-agent 작업 기록. git에서 제외됩니다.
- `plugins/my-agent/docs/reference.md`: 참고 문서의 출처 목록. 로컬 사본(`plugins/my-agent/docs/ref/`)은 git에서 제외됩니다.

## 라이선스

[MIT](LICENSE)
