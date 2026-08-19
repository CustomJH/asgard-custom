# xterm — 벤더링 사본

창은 CDN 을 부르지 않는다(`loopback.CSP` 가 `'self'` 하나만 연다). 그래서 터미널 화면이 쓰는
라이브러리는 이 디렉터리에 사본으로 들어와 `/asset/vendor/xterm/...` 로 나간다.

| 파일 | 출처 | 판 |
| --- | --- | --- |
| `xterm.js` | npm `@xterm/xterm`, `lib/xterm.js` | 5.5.0 |
| `xterm.css` | npm `@xterm/xterm`, `css/xterm.css` | 5.5.0 |
| `addon-fit.js` | npm `@xterm/addon-fit`, `lib/addon-fit.js` | 0.10.0 |

둘 다 MIT 이고 두 사본의 원문이 `LICENSE` 에 이어 붙어 있다.

`.js.map` 은 가져오지 않았다 — 합쳐 1.1MB 이고 배송에 필요 없다. `.map` 이 없으므로 브라우저
개발자 도구는 최소화된 원문을 그대로 보여 준다.

판을 올릴 때는 위 세 경로를 같은 판에서 다시 받고 `LICENSE` 도 함께 갱신한다. 디렉터리 이름이
`vendor` 인 것은 우연이 아니다: `asgard.health` 의 `IGNORED_DIRS`/`GATE_SKIP_DIRS` 가 이 이름을
크기·중복 검사에서 빼 준다. 다른 이름으로 옮기면 283KB 최소화 파일이 게이트에 걸린다.
