# 뷰어 — 로컬 리뷰 서버

사람이 눈으로 돌려보는 창. STEP·GLB·STL·3MF·DXF·G-code·URDF·SRDF·SDF·`.implicit.js` 를 로컬 브라우저에서 연다.

**뷰어는 편의이지 검증이 아니다.** 검증의 본체는 `inspect` 의 측정값과 `snapshot` 의 렌더 증거다. 뷰어가 안 떠도 배달은 진행된다 — 못 띄웠다고 적으면 된다.

## 기동 — 실측된 절차

```bash
V=engine/vendor/text-to-cad/skills/cad-viewer/scripts/viewer
node $V/backend/server.mjs --host 127.0.0.1 --port 4178
```

그리고 **산출물 위치는 URL 질의로 준다**:

```text
http://127.0.0.1:4178/?dir=<산출물 절대 디렉터리>&file=<dir 기준 상대 경로>
```

`file=` 을 붙이지 않으면 그 디렉터리의 카탈로그가 열린다.

## 상류 문서와 다른 점 — 그대로 따르면 실패한다

벤더링된 `cad-viewer/SKILL.md` 는 `npm --prefix scripts/viewer run agent:start -- --dir <root>` 를 지시하지만, **패키징된 번들에는 그 런처가 없다.** `agent:start` 스크립트도 `scripts/start-agent-viewer.mjs` 도 상류 개발 트리에만 있고, 포트 선택과 `--dir` 를 소유한 것이 바로 그 런처였다.

실측 결과:

| 하려던 것 | 실제 |
|---|---|
| `npm run agent:start` | 스크립트 없음 — 실패 |
| `backend/server.mjs --dir <경로>` | **조용히 무시된다.** 서버는 스킬 디렉터리를 루트로 잡는다 |
| `backend/server.mjs --root-dir <경로>` | `--root-dir has been removed; pass ?dir= in the Viewer URL.` 로 종료 |
| `backend/server.mjs` + `?dir=` | **동작한다** |

이것은 상류의 공백이고 벤더링 이전부터 있었다(`vendor/text-to-cad/UPSTREAM.md`). 아스가르드 쪽 회귀로 보고하지 않는다.

## 링크를 돌려주기 전에

- **`<dir>/<file>` 을 실제로 resolve 해서 파일이 있는지 확인한다.** 없는 링크를 돌려주지 않는다.
- 생성물을 가리킨다(`.step`), 생성기를 가리키지 않는다(`.py`).
- 파일마다 URL 하나. 디렉터리당 서버는 한 번만 띄우고 `file=` 만 바꾼다.
- **사용자가 요청하지 않으면 돌고 있는 서버를 끄지 않는다.** 다른 세션이 쓰고 있을 수 있다.

## 준비 상태 확인

서버가 떴는지 기계로 확인하려면:

```bash
curl -s http://127.0.0.1:4178/__cad/server
```

`{"schemaVersion":1,"serverApiVersion":2,"app":"cad-viewer",...}` 가 오면 준비된 것이다. 미리보기 도구에 URL 을 넘기기 전에 이걸로 200 을 확인한다.

## 안 될 때

샌드박스에서 로컬 바인딩이 `EPERM`·`EACCES` 로 막히는 것은 정상적으로 있는 일이다. 포트가 점유돼 있으면 다른 포트를 준다.

**띄우지 못했으면 그렇게 보고하고, CLI 사실·측정·스냅샷으로 검증을 마친다.** 뷰어 링크가 없다고 검증이 없는 것이 아니다. 반대로, 뷰어 링크를 돌려줬다는 사실이 검증도 아니다.

## MoveIt2 (선택)

SRDF 의 IK·경로 계획을 대화적으로 보려면 `vendor/text-to-cad/skills/cad-viewer/references/moveit2-server.md`. conda 환경과 ROS 설치가 필요하다 — 사용자가 그 상호작용을 실제로 필요로 할 때만 켜고, 설치 비용을 먼저 말한다.
