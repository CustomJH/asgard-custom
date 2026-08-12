#!/usr/bin/env python3
"""분류와 라우팅 — 결정론 휴리스틱·LLM 폴백·outcome prior."""

import json
import os
import unittest
from unittest import mock

from asgard.agent.heimdall import Heimdall
from heimdall.harness import (
    CLS_WRITE,
    DONE,
    PLAN_WITH_UNITS,
    Base,
    FakeHeimdall,
    thinker,
    verifier,
    worker,
)


class TestRoutePriorsE2E(Base):
    """Bayesian-lite — 종결 outcome 기록 + prior가 승격 문턱을 실제로 낮추는 e2e."""

    def read_priors(self):
        return json.load(open(os.path.join(self.root, ".asgard", "state", "route-priors.json")))

    def outcomes(self):
        path = os.path.join(self.root, ".asgard", "state", "classify.jsonl")
        events = [json.loads(ln) for ln in open(path) if ln.strip()]
        return [e for e in events if e.get("event") == "outcome"]

    def test_happy_path_records_pass_outcome_and_prior(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        self.assertEqual(self.read_priors()["classes"]["deep"], {"n": 1, "red": 0})  # task_class 미상 = deep
        (out,) = self.outcomes()
        self.assertEqual((out["task_class"], out["result"], out["baseline_red"]), ("deep", "pass", False))
        first = json.loads(self.quest_log_text().splitlines()[0])
        self.assertEqual(first["risk"].get("task_class"), "deep")  # open이 클래스를 기록

    def test_escalate_records_outcome(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("ESCALATE")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        (out,) = self.outcomes()
        self.assertEqual(out["result"], "escalate")
        self.assertEqual(self.read_priors()["classes"]["deep"]["n"], 1)

    def test_red_majority_prior_promotes_on_first_red(self):
        # standard 클래스 과반-red 이력 → 첫 Verifier red에 THINKER_REPLAN
        os.makedirs(os.path.join(self.root, ".asgard", "state"), exist_ok=True)
        with open(os.path.join(self.root, ".asgard", "state", "route-priors.json"), "w") as f:
            json.dump({"schema": 1, "classes": {"standard": {"n": 3, "red": 2}}}, f)
        seq = [
            worker({"w1.txt": "a\n"}, self.root),
            verifier("FAIL", sig="broken"),
            thinker("재설계 1"),
            worker({"w1.txt": "b\n"}, self.root),
            verifier("ESCALATE"),
        ]
        h = FakeHeimdall(self.root, seq, cls={**CLS_WRITE, "task_class": "standard"})
        out = h.handle("w1.txt 만들어")
        self.assertIn("Odin", out)
        labels = [s.label for s in h.consumed]
        self.assertEqual(labels[:3], ["worker", "verifier", "thinker"])  # red 1회 만에 재계획
        self.assertIn("prior", "".join(h.texts))  # 전이 사유에 prior 하향 표기
        self.assertEqual(self.read_priors()["classes"]["standard"], {"n": 4, "red": 2})
        (out_ev,) = self.outcomes()
        self.assertEqual((out_ev["result"], out_ev["baseline_red"]), ("escalate", False))


class TestClassify(Base):
    def test_parse_failure_with_write_verb_defaults_to_gated_write(self):
        h = FakeHeimdall(self.root, [], cls=None)
        mock.patch.object(h, "_complete_text", lambda *a, **k: "이건 JSON 이 아님").start()
        self.addCleanup(mock.patch.stopall)
        d = Heimdall._classify(h, "버그 설명해주고 고쳐줘")  # read+write 혼재 → 휴리스틱 불확정 → 파싱 실패
        self.assertTrue(d["write_expected"])  # write 신호 존재 → 게이트 경로
        # 파싱 실패는 분류기 장애지 요청의 모호함이 아니다 — ambiguous로 게이트-우선을 박탈하거나
        # deep(12턴)으로 최대 예산을 태우지 않는다 (26-07-23 감사). 물리 가드가 승격을 판정한다.
        self.assertFalse(d["ambiguous"])
        self.assertEqual(d["task_class"], "standard")

    def test_parse_failure_without_write_verb_fails_open_to_direct(self):
        # 분류기가 JSON 대신 대화체로 응답(인사 등) → 파싱 실패. write 동사가 없으면 DIRECT
        # fail-open — DIRECT는 read-only + Canon 10 소급 검증이 실제 write를 잡는다.
        # 구 기본값(무조건 write+deep)은 인사 하나가 deep 예산을 태우는 경로였다 (26-07-21 실측).
        h = FakeHeimdall(self.root, [], cls=None)
        mock.patch.object(h, "_complete_text", lambda *a, **k: "안녕하세요! 무엇을 도와드릴까요?").start()
        self.addCleanup(mock.patch.stopall)
        d = Heimdall._classify(h, "뭔가 대충 처리해줘")  # write 동사 없음 + 휴리스틱 불확정
        self.assertFalse(d["write_expected"])
        self.assertEqual(d["task_class"], "standard")

    def test_llm_read_only_verdict_cannot_override_a_deterministic_write_verb(self):
        """분류기가 write 요청을 read-only로 읽으면 Write 도구 없는 DIRECT가 붙어 과업이 불가능해진다.

        실측(26-07-26 helios): "모듈 경계를 정리해서 공통 로직을 한 곳으로 모아줘"가 read-only로
        분류돼, 리팩터링이 파일 변경 없는 제안문으로 끝났다. 거부권은 한 방향 — read를 write로
        승격만 하고, 그 반대는 없다 (오판 비용의 비대칭)."""
        h = FakeHeimdall(self.root, [], cls=None)
        payload = '{"write_expected":false,"ambiguous":false,"destructive":false,'
        payload += '"external_research":false,"shared":false,"criteria":[],"task_class":"standard"}'
        mock.patch.object(h, "_complete_text", lambda *a, **k: payload).start()
        self.addCleanup(mock.patch.stopall)
        d = Heimdall._classify(h, "이 스크립트들 읽어보고 중복을 정리해서 공통 로직으로 모아줘")
        self.assertTrue(d["write_expected"])
        # 게이트-우선 자격을 박탈하지 않는다 — ambiguous 승격은 소형 수정을 최중량 검증으로 민다.
        self.assertFalse(d["ambiguous"])

    def test_llm_read_only_verdict_stands_without_a_write_verb(self):
        h = FakeHeimdall(self.root, [], cls=None)
        payload = '{"write_expected":false,"ambiguous":false,"destructive":false,'
        payload += '"external_research":false,"shared":false,"criteria":[],"task_class":"trivial"}'
        mock.patch.object(h, "_complete_text", lambda *a, **k: payload).start()
        self.addCleanup(mock.patch.stopall)
        d = Heimdall._classify(h, "이 구조 어떤 의도인지 짚어줘")
        self.assertFalse(d["write_expected"])

    def test_destructive_refused_without_sessions(self):
        cls = dict(CLS_WRITE, destructive=True)
        h = FakeHeimdall(self.root, [], cls=cls)
        out = h.handle("전부 지워")
        self.assertIn("되돌릴 수 없는 작업이라", out)
        self.assertEqual(h.consumed, [])


class TestClassifyHeuristic(Base):
    """결정론 pre-LLM 분류 — 명백 케이스 LLM 호출 0."""

    def test_obvious_cases_no_llm(self):
        from asgard.agent.heimdall import classify_heuristic as ch

        read_only = [
            "이 함수 설명해줘",
            "왜 여기서 에러가 나지?",
            "what does this function do",
            "README 요약해줘",
            "파일이 몇 개 있어?",
            "README.md 첫 제목만 읽고 답해. 파일은 수정하지 마.",
            "pwd와 README 첫 줄을 보여줘. 파일 수정 금지.",
            "describe config.py without changing any files",
        ]
        writes = [
            "app.py 만들어줘",
            "버그 고쳐",
            "테스트 추가해줘",
            "implement the parser in parser.py",
            "이 모듈 리팩터해줘",
            "로고 시스템을 실제 산출물로 제작해줘",
            # 벤치 실측 — "완성해줘"가 동사 리스트 밖이라 LLM 폴백으로 새던 케이스
            "우리 API 서비스에 요청 rate limit 기능을 완성해줘. limiter.py에 골격만 있고 아직 동작하지 않아.",
        ]
        destructive = ["rm -rf ./build 실행해", "git push --force 해", "임시 파일 다 지워"]
        for q in read_only:
            d = ch(q)
            assert d is not None, q  # ty 내로잉 — assertIsNotNone은 타입을 못 좁힌다
            self.assertFalse(d["write_expected"], q)
        for q in writes:
            d = ch(q)
            assert d is not None, q
            self.assertTrue(d["write_expected"], q)
            self.assertFalse(d["destructive"], q)
        for q in destructive:
            d = ch(q)
            assert d is not None, q
            self.assertTrue(d["destructive"], q)

    def test_ambiguous_falls_back_to_llm(self):
        from asgard.agent.heimdall import classify_heuristic as ch

        self.assertIsNone(ch("로그인 화면이 이상함"))  # 동사 신호 없음
        self.assertIsNone(ch("버그 설명해주고 고쳐줘"))  # read+write 혼재

    def test_smalltalk_routes_direct_no_llm(self):
        # 인사·감사·수긍은 결정론으로 DIRECT — LLM 분류기가 인사에 인사로 답해(JSON 파싱 실패)
        # Trinity를 태우던 경로 차단 (26-07-21 "안녕" 실측: deep 예산 소진)
        from asgard.agent.heimdall import classify_heuristic as ch

        smalltalk = [
            "안녕",
            "안녕하세요!",
            "hi",
            "hello~",
            "고마워",
            "감사합니다",
            "ㅋㅋㅋ",
            "넵",
            "수고하셨습니다",
            "thanks!",
            "잘가",
            "응 좋아",
        ]
        for q in smalltalk:
            d = ch(q)
            assert d is not None, q
            self.assertFalse(d["write_expected"], q)
        # 인사가 실제 과업에 섞이면 스몰톡이 아니다 — write 동사가 정상 우선
        mixed = ch("안녕, login.py 버그 고쳐줘")
        assert mixed is not None
        self.assertTrue(mixed["write_expected"])

    def test_memory_instruction_routes_direct_no_llm(self):
        # 기억 지시가 어느 동사 표에도 없어 LLM 폴백 trivial로 흐르고, 모델이 저장 없이
        # "기억했다" 허위 확답하던 경로 (26-07-21 실측) — 결정론 DIRECT + memory_save 계약으로 봉인.
        from asgard.agent.heimdall import classify_heuristic as ch
        from asgard.agent.heimdall import memory_write_intent

        d = ch("내 이름은 썬더오브갓이야. 기억해줘.")
        assert d is not None
        self.assertFalse(d["write_expected"])
        for q in (
            "내 이름은 썬더오브갓이야. 기억해줘.",
            "이 규칙 잊지 마",
            "내 생일은 3월 3일이야. 기억해",
            "메모리에 저장해: 배포는 금요일 금지",
            "please remember my timezone is KST",
        ):
            self.assertTrue(memory_write_intent(q), q)
        # 회상 질문·과거형은 저장 지시가 아니다 — 오탐이면 폴백 ingest가 잡담을 영구 저장한다
        for q in (
            "내 이름 기억해?",
            "우리 지난주에 뭐 했는지 기억하고 있어?",
            "do you remember my name?",
        ):
            self.assertFalse(memory_write_intent(q), q)
        # 혼합(기억 + repo write)은 여전히 write 분기 — Trinity 게이트 우선
        mixed = ch("이 규칙 기억해두고 config.py 수정해줘")
        assert mixed is not None
        self.assertTrue(mixed["write_expected"])

    def test_durable_user_fact_without_explicit_memory_command(self):
        """실측 회귀 (26-07-26): "이제부터 썬더오브갓이라 불러라"가 명시적 기억 명령 표에
        없어 memory_save 도구가 안 열렸고, 모델이 셸아웃으로 우회하려다 read-only 레인에
        막혀 "세션에서만 기억"으로 끝났다. 호칭·정체성·지속 지시는 명령 없이도 사실이다."""
        from asgard.agent.heimdall import classify_heuristic as ch
        from asgard.agent.heimdall import memory_write_intent

        for q in (
            "이제부터 썬더오브갓이라 불러라",
            "앞으로 썬더오브갓이라고 불러줘",
            "썬더오브갓이라고 불러줘",
            "나를 썬더오브갓이라고 불러",
            "내 이름은 썬더오브갓이야",
            "사용자의 canonical 호칭은 썬더오브갓이다",
            "항상 짧게 답해줘",
            "이제부터 이모지 쓰지 마",
            "앞으로 한국어로 답해",
            "from now on call me Thunder",
            "my name is Thunder",
            "always use pytest for tests",
        ):
            self.assertTrue(memory_write_intent(q), q)
        # 회상 질문·일회성 지시·잡담은 사실 선언이 아니다 — 오탐이면 잡담이 영구 저장된다
        for q in (
            "내 이름이 뭐야?",
            "앞으로 어떻게 진행할까?",
            "이제부터 뭘 해야 하지?",
            "이제부터 시작하자",
            "call me when the build finishes",
            "이 함수 뭐 하는 거야?",
            "테스트 좀 돌려줘",
        ):
            self.assertFalse(memory_write_intent(q), q)
        # 지속 지시라도 repo write가 섞이면 write 분기 — 게이트 우선은 그대로
        mixed = ch("앞으로 이 규칙 지켜서 config.py 수정해줘")
        assert mixed is not None
        self.assertTrue(mixed["write_expected"])

    def test_explicit_parallel_write_routes_through_deep_planning(self):
        from asgard.agent.heimdall import classify_heuristic as ch

        requests = [
            "alpha.py와 beta.py를 독립 Worker 단위로 분해해 병렬 구현해줘",
            "implement the parser with parallel subagents and a TODO list",
        ]
        for request in requests:
            classified = ch(request)
            assert classified is not None
            self.assertTrue(classified["write_expected"])
            self.assertTrue(classified["parallel_requested"])
            self.assertEqual(classified["task_class"], "deep")

    def test_explicit_parallel_write_actually_runs_thinker_and_wave(self):
        h = FakeHeimdall(
            self.root,
            [
                thinker(PLAN_WITH_UNITS),
                worker({"u1.txt": "1\n"}, self.root),
                worker({"u2.txt": "2\n"}, self.root),
                worker({"sum.txt": "12\n"}, self.root),
                verifier("PASS"),
            ],
            cls=None,
        )

        out = h.handle("u1과 u2를 독립 Worker 단위로 분해해 병렬 구현해줘")

        self.assertIn(DONE, out)
        self.assertEqual(
            [session.label for session in h.consumed], ["thinker", "worker", "worker", "worker", "verifier"]
        )

    def test_explicit_parallel_write_replans_instead_of_collapsing_invalid_graph_to_one_worker(self):
        invalid = '```json\n{"units":[{"id":1,"subtask":"monolith","files":["u1.txt"],"access":[]}]}\n```'
        h = FakeHeimdall(
            self.root,
            [
                thinker(invalid),
                thinker(PLAN_WITH_UNITS),
                worker({"u1.txt": "1\n"}, self.root),
                worker({"u2.txt": "2\n"}, self.root),
                worker({"sum.txt": "12\n"}, self.root),
                verifier("PASS"),
            ],
            cls=None,
        )

        out = h.handle("u1과 u2를 독립 Worker 단위로 분해해 병렬 구현해줘")

        self.assertIn(DONE, out)
        self.assertEqual(
            [session.label for session in h.consumed],
            ["thinker", "thinker", "worker", "worker", "worker", "verifier"],
        )
        self.assertIn("invalid-parallel-plan", self.quest_log_text())

    def test_classify_uses_heuristic_without_client_call(self):
        h = FakeHeimdall(self.root, [], cls=None)

        def boom(*a, **k):
            raise AssertionError("LLM 호출 금지 — 휴리스틱이 처리해야 함")

        mock.patch.object(h, "_complete_text", boom).start()
        self.addCleanup(mock.patch.stopall)
        d = Heimdall._classify(h, "이 함수 설명해줘")
        self.assertFalse(d["write_expected"])

    def test_telemetry_logged(self):
        h = FakeHeimdall(self.root, [worker({"w1.txt": "x\n"}, self.root), verifier("PASS")], cls=CLS_WRITE)
        h.handle("w1.txt 만들어")
        log = open(os.path.join(self.root, ".asgard", "state", "classify.jsonl")).read()
        self.assertIn('"route": "trinity"', log.replace('":"', '": "'))


if __name__ == "__main__":
    unittest.main(verbosity=1)
