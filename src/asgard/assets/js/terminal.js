/* 창 안의 터미널 화면 — 판을 짓고, 셸 하나를 붙들고, 그 출력을 그린다.
 *
 * **터미널은 컴포넌트 트리 밖에 있다.** `Terminal` 인스턴스와 세션 열쇠를 이 모듈 스코프에
 * 두는 이유는 하나다: 화면을 나갔다 들어올 때마다 다시 만들면 스크롤백과 셸이 같이 날아간다.
 * `initTerminalView()` 는 처음 한 번만 짓고, 그다음부터는 이미 있는 판을 제자리에 도로
 * 붙이고 크기만 다시 잰다.
 *
 * **색은 CSS 로 못 준다.** xterm 은 CSS 변수를 읽지 않고 자기 팔레트를 JS 객체로 받는다.
 * 그래서 `palette()` 가 tokens.css 의 의미 토큰을 계산된 값으로 읽어 넣고, `data-theme` 이
 * 바뀌면 다시 넣는다. 이 배선이 없으면 화면만 라이트로 바뀌고 터미널만 다크로 남는다.
 */

(() => {
  "use strict";

  const HOST_ID = "terminal-view";
  // 크기 재기를 붙잡는 창. 이 판은 전환이 아니라 정착을 기다리는 자리라 짧게 잡는다 —
  // 끌어서 넓히는 동안 매 프레임 `/resize` 를 보내면 셸이 그만큼 다시 그린다.
  const RESIZE_SETTLE = 100;
  // 스트림이 끊겼을 때 다시 붙기까지. 시도할수록 늘리고, 이 횟수를 넘기면 손으로 넘긴다.
  const RETRY_STEP = 500;
  const RETRY_CEIL = 4000;
  const RETRY_LIMIT = 5;
  const SCROLLBACK = 5000;

  let root = null; // 판 전체 — 화면을 나가도 살아 있다
  let screen = null; // xterm 이 붙는 자리
  let probe = null; // 토큰 값을 읽으려고만 두는 요소
  let where = null;
  let state = null;
  let notice = null;
  let term = null;
  let fit = null;

  let session = null; // {id, token} — 토큰은 여기 말고 어디에도 없다
  let stream = null;
  let lastSeq = 0;
  let sent = { cols: 0, rows: 0 };
  let ended = false;
  let attempts = 0;
  let retryTimer = 0;
  let settleTimer = 0;

  // ── 창구 ───────────────────────────────────────────────────────────────────

  function post(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Asgard-Studio": "1" },
      body: JSON.stringify(body),
    }).then(
      (res) =>
        res
          .json()
          .catch(() => ({}))
          .then((data) => ({ status: res.status, data })),
      (err) => ({ status: 0, data: { error: { message: String(err && err.message ? err.message : err) } } }),
    );
  }

  // ── 색 ─────────────────────────────────────────────────────────────────────

  /** 의미 토큰 하나를 계산된 색 문자열로. 브라우저가 `rgb(r, g, b)` 꼴로 정규화해 준다. */
  function readColor(name) {
    probe.style.color = "";
    probe.style.color = "var(" + name + ")";
    return getComputedStyle(probe).color;
  }

  /** `rgb(r, g, b)` · `rgba(r, g, b, a)` → 숫자 넷. 알파가 없으면 1 이다. */
  function channels(css) {
    const found = String(css).match(/(-?[\d.]+)/g);
    if (!found || found.length < 3) return [0, 0, 0, 1];
    const alpha = found.length > 3 ? Number(found[3]) : 1;
    return [Number(found[0]), Number(found[1]), Number(found[2]), alpha];
  }

  /** 반투명 토큰을 판 바탕에 얹어 불투명한 값 하나로 만든다. 알파를 그냥 버리면 다크에서
   * `--faint`(양피지 55%)가 바탕에 겹친 회색이 아니라 **양피지 원색**으로 튄다 — 가장 흐린
   * 회색이 가장 밝은 색이 되어 대비 순서가 뒤집힌다. */
  function flatten(rgba, bg) {
    const alpha = rgba[3];
    return [0, 1, 2].map((i) => rgba[i] * alpha + bg[i] * (1 - alpha));
  }

  /** 앞의 세 칸만 쓴다 — 알파가 딸려 오면 xterm 이 못 읽는 여덟 자리 값이 된다. */
  function hex(rgb) {
    const pair = (v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0");
    return "#" + pair(rgb[0]) + pair(rgb[1]) + pair(rgb[2]);
  }

  function mix(a, b, ratio) {
    return hex([0, 1, 2].map((i) => a[i] + (b[i] - a[i]) * ratio));
  }

  /**
   * ANSI 16색을 우리 토큰에서 짓는다. 두 가지를 정해 두고 나머지는 그 규칙을 따른다.
   *
   * 1. **밝은 짝은 잉크 쪽으로 22% 섞은 것이다.** 라이트에서는 더 짙어지고 다크에서는 더
   *    밝아진다 — 두 테마 모두에서 바탕과의 대비가 올라간다는 뜻이고, 밝은 짝이 실제로 하는
   *    일(눈에 먼저 띄기)이 그것이다. 테마별 표를 따로 두지 않는 이유이기도 하다.
   * 2. **없는 색조는 있는 색조 사이에서 얻는다.** 우리 토큰에 자홍과 청록은 없다. 색상환에서
   *    자홍은 빨강과 파랑 사이, 청록은 파랑과 초록 사이라 그 중간을 쓴다. 새 색을 지어내지
   *    않으므로 팔레트 밖으로 나가지 않는다.
   */
  function palette() {
    const bg = channels(readColor("--surface-1"));
    const read = (name) => flatten(channels(readColor(name)), bg);
    const ink = read("--ink");
    const red = read("--danger");
    const green = read("--ok");
    const yellow = read("--warn");
    const blue = read("--info");
    const magenta = [0, 1, 2].map((i) => (red[i] + blue[i]) / 2);
    const cyan = [0, 1, 2].map((i) => (blue[i] + green[i]) / 2);
    const faint = read("--faint");
    const muted = read("--muted");
    const gold = read("--gold");
    const lit = 0.22;
    return {
      background: hex(bg),
      foreground: hex(ink),
      cursor: hex(gold),
      cursorAccent: hex(bg),
      // 선택 면은 알파를 그대로 쓴다 — 밑의 글자가 비쳐야 무엇을 골랐는지 보인다.
      selectionBackground: "rgba(" + gold.map(Math.round).join(", ") + ", 0.3)",
      selectionInactiveBackground: "rgba(" + gold.map(Math.round).join(", ") + ", 0.16)",
      // 회색 넷은 대비 순으로 세운다: faint < muted < ink. ANSI 검정은 어느 터미널에서나
      // 바탕에 가장 가까운 색이고(표준 다크 배색에서는 아예 안 보인다), 그 자리에 우리는
      // 가장 흐린 회색을 둔다 — 라이트에서 3.07, 다크에서 4.99 로 최소한 읽히기는 한다.
      black: hex(faint),
      brightBlack: hex(muted),
      white: hex(muted),
      brightWhite: hex(ink),
      red: hex(red),
      brightRed: mix(red, ink, lit),
      green: hex(green),
      brightGreen: mix(green, ink, lit),
      yellow: hex(yellow),
      brightYellow: mix(yellow, ink, lit),
      blue: hex(blue),
      brightBlue: mix(blue, ink, lit),
      magenta: hex(magenta),
      brightMagenta: mix(magenta, ink, lit),
      cyan: hex(cyan),
      brightCyan: mix(cyan, ink, lit),
    };
  }

  function token(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function repaint() {
    if (!term) return;
    term.options.theme = palette();
    term.options.fontFamily = token("--mono");
  }

  /** 테마는 두 갈래로 바뀐다 — 창이 `data-theme` 을 갈아 끼우거나, 운영체제 설정이 바뀌거나. */
  function watchTheme() {
    new MutationObserver(repaint).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    const dark = window.matchMedia("(prefers-color-scheme: dark)");
    dark.addEventListener("change", repaint);
  }

  // ── 판 ─────────────────────────────────────────────────────────────────────

  function button(label, kind, act) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "ak-btn ak-btn--" + kind;
    el.textContent = label;
    el.addEventListener("click", act);
    return el;
  }

  function build() {
    root = document.createElement("div");
    root.className = "trm";

    const bar = document.createElement("header");
    bar.className = "trm__bar";

    state = document.createElement("span");
    state.className = "ak-badge";

    where = document.createElement("span");
    where.className = "trm__where";

    const acts = document.createElement("div");
    acts.className = "trm__acts";
    acts.append(
      button("지우기", "secondary", () => term && term.clear()),
      button("닫기", "secondary", shut),
      button("새 터미널", "primary", () => open(true)),
    );

    bar.append(state, where, acts);

    screen = document.createElement("div");
    screen.className = "trm__screen";

    probe = document.createElement("span");
    probe.className = "trm__probe";
    probe.setAttribute("aria-hidden", "true");

    notice = document.createElement("div");
    notice.className = "trm__notice";
    notice.hidden = true;
    // 셸이 끝났다는 말은 보조기술에도 가야 한다 — 조용히 멈추면 안 되는 자리다.
    notice.setAttribute("role", "status");
    notice.setAttribute("aria-live", "polite");

    root.append(bar, probe, screen, notice);
    setState("아직 안 열림", "");
  }

  function setState(text, kind) {
    state.className = "ak-badge" + (kind ? " ak-badge--" + kind : "");
    state.textContent = text;
  }

  function setWhere(text, hint) {
    where.replaceChildren();
    if (!text) return;
    const inner = document.createElement("span");
    inner.textContent = text;
    where.append(inner);
    where.title = hint || text;
  }

  function clearNotice() {
    notice.hidden = true;
    notice.replaceChildren();
    notice.className = "trm__notice";
    screen.hidden = false;
  }

  /** 알림 하나 — 제목·설명·처방·단추. 오류든 종료든 같은 모양으로 나간다. */
  function say(opts) {
    notice.replaceChildren();
    notice.className = "trm__notice " + (opts.tone === "error" ? "ak-error" : "ak-empty");
    const title = document.createElement("strong");
    title.className = opts.tone === "error" ? "ak-error__title" : "";
    title.textContent = opts.title;
    notice.append(title);
    for (const line of opts.lines || []) {
      if (!line) continue;
      const p = document.createElement("p");
      p.textContent = line;
      notice.append(p);
    }
    if (opts.action) {
      notice.append(button(opts.action.label, "primary", opts.action.run));
    }
    notice.hidden = false;
    if (opts.hideScreen) screen.hidden = true;
  }

  /** 서버 오류 하나를 그대로 보여 준다 — 문구와 처방은 백엔드가 코드마다 들고 있다. */
  function refused(status, data, hideScreen) {
    const err = (data && data.error) || {};
    say({
      tone: "error",
      title: err.code === "terminal_unsupported" ? "이 운영체제에서는 못 열어요" : "터미널을 못 열었어요",
      lines: [err.message || "서버가 " + status + " 를 냈어요", err.remedy],
      hideScreen: hideScreen,
      action:
        err.code === "terminal_unsupported"
          ? null
          : { label: "다시 열기", run: () => open(true) },
    });
    setState("안 열림", "danger");
  }

  // ── 셸 ─────────────────────────────────────────────────────────────────────

  function measure() {
    if (fit) fit.fit();
    return { cols: term.cols, rows: term.rows };
  }

  async function open(reset) {
    if (reset) {
      dropStream();
      session = null;
      term.reset();
    }
    clearNotice();
    setState("여는 중", "info");
    const size = measure();
    const { status, data } = await post("/api/terminal/open", { cols: size.cols, rows: size.rows });
    if (status !== 200) {
      refused(status, data, true);
      return;
    }
    session = { id: data.id, token: data.token };
    lastSeq = 0;
    ended = false;
    attempts = 0;
    sent = { cols: data.cols, rows: data.rows };
    setWhere(data.cwd, data.shell + " · pid " + data.pid + " · " + data.cwd);
    setState("도는 중", "ok");
    connect();
    term.focus();
  }

  function dropStream() {
    if (retryTimer) {
      clearTimeout(retryTimer);
      retryTimer = 0;
    }
    if (stream) {
      stream.close();
      stream = null;
    }
  }

  /** 스트림에 붙는다. `after` 는 마지막으로 그린 프레임 번호다 — 재연결이 처음부터 다시
   * 그리지 않게 하는 자리. `EventSource` 자신의 재연결은 처음 주소를 그대로 다시 쓰므로
   * 쓰지 않는다: 끊기면 우리가 닫고, 그때의 `after` 로 새로 연다. */
  function connect() {
    if (!session) return;
    dropStream();
    const query =
      "id=" +
      encodeURIComponent(session.id) +
      "&token=" +
      encodeURIComponent(session.token) +
      "&after=" +
      String(lastSeq);
    stream = new EventSource("/api/terminal/stream?" + query);
    stream.onmessage = (event) => {
      attempts = 0;
      let frame;
      try {
        frame = JSON.parse(event.data);
      } catch {
        return;
      }
      lastSeq = frame.seq;
      term.write(frame.data);
    };
    stream.addEventListener("exit", (event) => {
      let status = null;
      try {
        status = JSON.parse(event.data).status;
      } catch {
        status = null;
      }
      finish(status);
    });
    stream.onerror = () => {
      if (ended) return;
      dropStream();
      attempts += 1;
      if (attempts > RETRY_LIMIT) {
        setState("끊김", "warn");
        say({
          tone: "error",
          title: "터미널 출력이 끊겼어요",
          lines: ["다시 붙기를 " + RETRY_LIMIT + "번 시도했어요. 셸은 아직 살아 있을 수 있어요."],
          action: {
            label: "다시 붙기",
            run: () => {
              attempts = 0;
              clearNotice();
              connect();
            },
          },
        });
        return;
      }
      setState("다시 붙는 중", "warn");
      retryTimer = setTimeout(connect, Math.min(RETRY_STEP * attempts, RETRY_CEIL));
    };
  }

  function finish(status) {
    ended = true;
    dropStream();
    setState("끝남", "");
    say({
      title: "셸이 끝났어요",
      lines: [status === null || status === undefined ? "종료 상태를 못 읽었어요" : "종료 상태 " + status],
      action: { label: "다시 열기", run: () => open(true) },
    });
  }

  async function shut() {
    if (!session) return;
    const key = session;
    session = null;
    ended = true;
    dropStream();
    setState("닫는 중", "");
    await post("/api/terminal/close", { id: key.id, token: key.token });
    setState("닫힘", "");
    setWhere("", "");
    say({ title: "터미널을 닫았어요", lines: [], action: { label: "새 터미널", run: () => open(true) } });
  }

  // ── 크기 ───────────────────────────────────────────────────────────────────

  /** 판에 맞춘 뒤, **값이 달라졌을 때만** 서버에 보낸다. 응답은 기다리지 않는다. */
  function pushSize() {
    if (!term) return;
    const size = measure();
    if (!session || ended) return;
    if (size.cols === sent.cols && size.rows === sent.rows) return;
    sent = size;
    post("/api/terminal/resize", { id: session.id, token: session.token, cols: size.cols, rows: size.rows });
  }

  function watchSize() {
    new ResizeObserver(() => {
      clearTimeout(settleTimer);
      settleTimer = setTimeout(pushSize, RESIZE_SETTLE);
    }).observe(screen);
  }

  // ── 문 ─────────────────────────────────────────────────────────────────────

  /** 판을 짓고 곧바로 문서에 붙인 뒤 터미널을 만든다. **순서가 중요하다** — 떼어 놓은
   * 요소는 계산된 스타일을 내주지 않으므로, 먼저 붙이지 않으면 첫 팔레트가 통째로 비어
   * 온다(그러면 xterm 이 자기 기본 색으로 그린다). */
  function mount(host) {
    build();
    host.append(root);
    const quiet = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    term = new window.Terminal({
      // 깜빡이는 커서도 모션이다 — 줄여 달라고 한 사용자에게는 세워 둔다.
      cursorBlink: !quiet,
      scrollback: SCROLLBACK,
      fontSize: 13,
      fontFamily: token("--mono"),
      theme: palette(),
    });
    fit = new window.FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(screen);
    // 키 입력은 왕복을 기다리지 않는다. 기다리면 그 지연이 그대로 타이핑 지연이 된다.
    term.onData((data) => {
      if (!session || ended) return;
      post("/api/terminal/input", { id: session.id, token: session.token, data: data });
    });
    watchSize();
    watchTheme();
  }

  /**
   * 터미널 화면에 들어올 때 창이 부르는 문. 여러 번 불려도 안전하다 —
   * 처음 한 번만 짓고, 그다음은 제자리에 도로 붙이고 크기를 다시 잰다.
   */
  function initTerminalView() {
    const host = document.getElementById(HOST_ID);
    if (!host) return;
    if (!term) {
      if (!window.Terminal || !window.FitAddon) return; // 벤더링 파일이 아직 안 왔다
      mount(host);
    } else if (!host.contains(root)) {
      host.append(root);
    }
    repaint();
    if (!session && !ended) {
      open(false);
      return;
    }
    pushSize();
    if (session && !ended) term.focus();
  }

  window.initTerminalView = initTerminalView;
})();
