"""라우팅 — 요청 하나를 어느 레인으로 보낼지. 스킬 분류와 작업 종류 판정."""

from __future__ import annotations

import json

from ..classify import (
    _DESTRUCTIVE_PAT,
    _PARALLEL_WORK_PAT,
    _pred_fields,
    classify_heuristic,
    has_write_verbs,
)
from ..journal import _log_classify


class _RoutingMixin:
    """라우팅 — 요청 하나를 어느 레인으로 보낼지. 스킬 분류와 작업 종류 판정.

    `Heimdall` 가 상속한다 — 혼자서는 아무것도 아니다."""

    def _invoked_lane(self, invoked: str) -> str:
        """`/skill args` 원문이 가리키는 스킬의 선언 레인 — 실패·미선언은 빈 문자열 (fail-open)."""
        try:
            from ....skill_registry import skill_lane

            return skill_lane(self.root, invoked.split()[0].removeprefix("/"))
        except Exception:
            return ""

    def _skill_classification(self, invoked: str) -> dict:
        """스킬 호출의 결정론 분류 — 선언된 레인이 있으면 그 레인, 없으면 딜리버리.

        스킬 호출에 분류기를 부르면 무엇을 물어봐도 결과는 하나다: 스킬 본문에는 write 동사가
        늘 있고, `_classify` 의 write 거부권이 분류 결과와 무관하게 그것을 write 로 확정한다.
        이미 정해진 결과를 받으려고 스킬 본문 전체를 실은 호출을 한 번 더 내보내는 셈이라
        그 호출만 없앤다 — 레인 선언이 없는 스킬의 라우팅 결과는 종전과 같다."""
        lane = self._invoked_lane(invoked)
        d = {
            "write_expected": True,
            "ambiguous": False,
            "destructive": False,
            "external_research": False,
            "shared": False,
            "parallel_requested": bool(_PARALLEL_WORK_PAT.search(invoked.lower())),
            "criteria": [],
            "task_class": lane if lane in ("vcs",) else "standard",
        }
        _log_classify(self.root, {"event": "classify", "source": "skill", **_pred_fields(d)})
        return d

    def _route(self, subject: str, invoked: str | None) -> dict:
        """이 턴의 분류 — 스킬 호출은 결정론, 나머지는 휴리스틱·분류기."""
        from ....i18n import t

        if invoked:
            return self._skill_classification(invoked)
        self.on_status(t("classifying"))  # 분류도 모델 호출 — 침묵 구간 커버 (하임달이 길을 살피는 문구)
        try:
            return self._classify(subject)
        finally:
            self.on_status(None)

    def _classify(self, request: str) -> dict:
        # 1차 결정론 휴리스틱 (LLM 토큰 0) — 명백 케이스만. 모호하면 LLM 폴백.
        d = classify_heuristic(request)
        if d is not None:
            _log_classify(self.root, {"event": "classify", "source": "heuristic", **_pred_fields(d)})
            return d
        # structured-output 강제 대신 "JSON만 출력" + 관대한 파싱 — 두 트랜스포트(및 nemotron 류
        # JSON-mode 불확실 모델) 공통. 파싱 실패는 안전 기본값(write로 간주 → 게이트가 잡는다).
        sysmsg = (
            "Task classifier. Read the request and output only the JSON below (no explanation, no surrounding text). "
            "write_expected = true if the task requires creating or modifying files. "
            "**false when only an answer is needed: questions, calculations, explanations, lookups, greetings, chat** "
            "(e.g. '1+1?', 'explain this function', '안녕' — never answer a greeting with a greeting; output JSON only). "
            "criteria only for write tasks, phrased so they can be checked by commands. "
            "task_class = trivial(small, single file)|standard|deep(multi-file, refactor, risky). "
            '{"write_expected":bool,"ambiguous":bool,"destructive":bool,'
            '"external_research":bool,"shared":bool,"criteria":[str],"task_class":str}'
        )
        try:
            raw = self._complete_text(sysmsg, request, max_tokens=2000)
            s = raw[raw.index("{") : raw.rindex("}") + 1]
            d = json.loads(s)
            for k in ("write_expected", "ambiguous", "destructive", "external_research", "shared"):
                d[k] = bool(d.get(k))
            d["criteria"] = [str(c) for c in (d.get("criteria") or [])]
            if not d["write_expected"] and has_write_verbs(request):
                # 결정론 write 신호의 거부권 — 한 방향으로만 작동한다. 분류기가 write 요청을
                # read-only로 읽으면 Write 도구 없는 DIRECT 세션이 붙어 과업 자체가 불가능해지고,
                # 반대 오판은 불필요한 Trinity 세금에 그친다 (비대칭). 이 경로에 오는 요청은
                # 휴리스틱이 read/write 신호를 둘 다 본 것들이라, 사용자가 write 동사를 쓴 것은
                # 사실이다 (26-07-26 helios 실측: "모듈 경계를 정리해서 …모아줘"가 read-only로
                # 분류돼 리팩터링이 제안문으로 끝났다 — 부정구는 has_write_verbs가 이미 제거한다).
                # ambiguous는 건드리지 않는다 — True로 올리면 게이트-우선(BASELINE_VERIFY)
                # 자격이 사라져 소형 수정이 최중량 검증으로 승격된다 (26-07-23 감사).
                d["write_expected"] = True
            d["parallel_requested"] = bool(d["write_expected"] and _PARALLEL_WORK_PAT.search(request.lower()))
            if d.get("task_class") not in ("trivial", "standard", "deep"):
                d["task_class"] = "standard"
            _log_classify(self.root, {"event": "classify", "source": "llm", **_pred_fields(d)})
            return d
        except Exception:
            # 파싱 실패의 라우팅은 '요청의 write 동사 유무'로 결정론 판정한다. write 신호가 없으면
            # DIRECT fail-open — DIRECT 세션은 read-only 이고 bash 우회 write는 Canon 10 소급
            # 검증(워킹트리 fingerprint)이 Trinity로 편입하므로 게이트는 우회되지 않는다.
            # 구 기본값(무조건 write+deep)은 분류기가 인사에 JSON 대신 인사로 응답하는 순간
            # "안녕" 하나가 deep 턴 예산을 전부 태우는 최악 비용 경로였다 (26-07-21 실측).
            wr = has_write_verbs(request)
            d = {
                "write_expected": wr,
                # ambiguous 금지 — 분류기 파싱 실패는 요청이 모호하다는 신호가 아니라 분류기
                # 장애다. ambiguous=True는 게이트-우선(BASELINE_VERIFY) 자격을 박탈해 모든
                # 검증을 LLM Verifier로 밀었다 (26-07-23 감사: flaky classify 1회가 소형 수정을
                # 최중량 파이프라인으로 승격). 물리 가드(민감 경로·big diff·sig_risk·테스트
                # 삭제)는 ambiguous와 무관하게 그대로 작동한다.
                "ambiguous": False,
                "destructive": bool(_DESTRUCTIVE_PAT.search(request.lower())),
                "external_research": False,
                "shared": False,
                "parallel_requested": wr and bool(_PARALLEL_WORK_PAT.search(request.lower())),
                "criteria": [],
                # deep(12턴) 폴백 폐기 — 실측(state/classify.jsonl)에서 fallback 승격 2건 모두
                # 소형 요청이었고 그중 1건은 40초 뒤 trivial 재분류. standard(6턴)면 충분하고,
                # 진짜 deep은 FAIL/재계획 경로가 자연 승격한다.
                "task_class": "standard",
            }
            _log_classify(self.root, {"event": "classify", "source": "fallback", **_pred_fields(d)})
            return d
