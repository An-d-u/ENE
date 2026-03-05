# Obsidian CLI Commands Reference (for ENE `/note`)

아래 목록은 `/note` 오케스트레이터가 사용할 수 있도록 정리한 Obsidian CLI 명령군입니다.  
의도 추론 시 먼저 이 문서를 참고하고, 최소 명령 수로 작업을 끝내는 것을 권장합니다.

## 1) 기본/세션

- `help`
- `version`
- `reload`
- `restart`

예시:

- `obsidian version`
- `obsidian help`

## 2) 파일/폴더

- `files`
- `file path=<path>`
- `folders`
- `folder path=<path>`
- `open path=<path>`
- `create path=<path> [content=<text>]`
- `read path=<path>`
- `append path=<path> content=<text>`
- `prepend path=<path> content=<text>`
- `move path=<src> to=<dst>`
- `rename path=<src> name=<new_name>`
- `delete path=<path>`

예시:

- `obsidian files`
- `obsidian read path="Projects/Plan.md"`
- `obsidian append path="Daily/2026-03-05.md" content="회의 메모 정리"`
- `obsidian move path="Inbox/tmp.md" to="Archive/tmp.md"`

## 3) 데일리 노트

- `daily`
- `daily:path`
- `daily:read`
- `daily:append content=<text>`
- `daily:prepend content=<text>`

예시:

- `obsidian daily:read`
- `obsidian daily:append content="오늘 완료한 작업: API 정리"`

## 4) 검색

- `search query=<query>`
- `search:context query=<query>`
- `search:open query=<query>`

예시:

- `obsidian search query="mcp integration"`
- `obsidian search:context query="release plan"`

## 5) 링크 그래프/진단

- `backlinks path=<path>`
- `links path=<path>`
- `unresolved`
- `orphans`
- `deadends`

예시:

- `obsidian backlinks path="Projects/Plan.md"`
- `obsidian unresolved`

## 6) 태그/속성/메타

- `tags`
- `tag name=<name>`
- `aliases path=<path>`
- `properties path=<path>`
- `property:read path=<path> name=<key>`
- `property:set path=<path> name=<key> value=<value>`
- `property:remove path=<path> name=<key>`

예시:

- `obsidian tags`
- `obsidian property:set path="Projects/Plan.md" name="status" value="drafting"`
- `obsidian property:read path="Projects/Plan.md" name="status"`

## 7) 작업(Task)

- `tasks`
- `task path=<path>`

예시:

- `obsidian tasks`
- `obsidian task path="Daily/2026-03-05.md"`

## 8) 템플릿

- `templates`
- `template:read name=<name>`
- `template:insert name=<template_name>`

예시:

- `obsidian templates`
- `obsidian template:insert name="meeting-template"`

## 9) 플러그인/테마/스니펫

- `plugins`
- `plugins:enabled`
- `plugin:enable <id>`
- `plugin:disable <id>`
- `themes`
- `theme:set <name>`
- `snippets`
- `snippet:enable <name>`
- `snippet:disable <name>`

예시:

- `obsidian plugins:enabled`
- `obsidian plugin:enable dataview`

## 10) Vault/워크스페이스/탭

- `vault`
- `vaults`
- `workspace`
- `workspace:save name=<name>`
- `workspace:load name=<name>`
- `tabs`
- `tab:open file=<path>`
- `recents`

예시:

- `obsidian vault`
- `obsidian tab:open file="Projects/Plan.md"`

## 11) Sync/히스토리/Diff

- `sync:status`
- `sync:start`
- `sync:stop`
- `history path=<path>`
- `diff path=<path>`

예시:

- `obsidian sync:status`
- `obsidian history path="Projects/Plan.md"`

---

## 실행 규칙 (ENE)

- 경로는 Vault 상대경로만 사용한다.
- 셸 체이닝/리다이렉션 금지:
  - `&&`, `||`, `;`, `|`, `>`, `<`, `` ` ``, `$()`
- 같은 목적이면 명령 수를 최소화한다.
- 수정 계열 명령(`append`, `prepend`, `update`, `write`, `move`, `rename`, `delete`)은 필요할 때만 사용한다.
- 먼저 `read/search`로 확인하고 수정하는 순서를 권장한다.
