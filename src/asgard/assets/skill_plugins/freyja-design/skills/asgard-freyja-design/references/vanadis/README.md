# Vanadis

Freyja 디자인 엔진이 읽기 전용으로 참조하는 스냅샷. 프로젝트 소유 `DESIGN.md` 워크플로와
실회사 레퍼런스 카탈로그를 담는다. 별도 API 키·데몬·MCP 서버 없이 호스트 에이전트 세션
안에서만 동작한다.

`DESIGN.md`는 토큰(색·타이포·간격)에 Voice, Narrative, Principles, Personas, States,
Motion 을 더한 이식 가능한 브랜드 명세다. 15섹션 포맷의 정본은 `spec/vanadis-v0.1.md`.

## Repository layout

- `web/references/<id>/DESIGN.md` — 실회사 레퍼런스 카탈로그의 **정본**. `design-md/`,
  `packages/mcp/data/references/`, 루트 `references` 심링크는 전부 여기서 파생된다.
  수정은 `web/references/`에만 한다.
- `skills/vanadis-*` — 디자인 스킬 (Claude Code · Codex · OpenCode 채널).
- `agents/`, `.claude/agents/`, `.codex/agents/` — 디자인 하니스 전문 역할.
- `src/` — `vanadis` CLI 소스 (`bin/vanadis.ts` 진입점).
- `spec/` — DESIGN.md 포맷 스펙.

## Asgard에서의 접근

이 스냅샷은 asgard-freyja-design 팩의 참조 자료다. 직접 실행하지 않고
`freyja_design.py` 러너를 통해 접근한다:

- `reference list <query>` / `reference show <id>` — 레퍼런스 카탈로그 조회
- `extract <상대경로> <출력경로>` — 바이너리 자산 추출

## Build / test

- Build: `npm run build` (tsup → `dist/`)
- Type-check: `npm run lint`
- Unit tests: `npm test` (vitest)
