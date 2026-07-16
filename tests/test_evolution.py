"""자가발전 (CUS-251) — skill_bank 레지스트리 + evolution 증류기/인박스 테스트.

검증 축: SKILL.md 파싱 / 디스크 스캔 라우팅 + mtime hot-reload(재시작 불요) / agent 필터·주입 상한 /
usage 기록 / quest 채굴(hard-won 만, 금지 시그니처 제외, latch) / 승인 dry-run(placeholder·충돌 거부) /
거부 latch / 보관 전이 / Heimdall _learned_note 주입 계약.
전부 temp root + temp HOME 격리 — 실사용 ~/.asgard 무접촉.
"""

import json
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from typing import cast
from unittest import mock

from asgard import evolution, skill_bank


def _write_skill(base: str, name: str, triggers: str, agent: str = "worker", body: str = "본문 절차") -> str:
    d = os.path.join(base, name)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "SKILL.md")
    text = (
        f"---\nname: {name}\ndescription: d\ntriggers: {triggers}\nagent: {agent}\n"
        f"origin: retrospective\ncreated: 2026-07-16\n---\n\n{body}\n"
    )
    open(p, "w", encoding="utf-8").write(text)
    open(os.path.join(d, skill_bank.APPROVAL_FILE), "w", encoding="utf-8").write(
        json.dumps(skill_bank.approval_receipt(os.path.dirname(os.path.dirname(base)), name, text, create_key=True))
    )
    return p


def _quest_line(qid: str, **kv) -> str:
    base = {
        "schema": 1,
        "quest_id": qid,
        "session_id": qid,
        "turn": 1,
        "ts": "2026-07-16T00:00:00Z",
        "role": "verifier",
        "event": "verify",
        "risk": {"has_write": True, "task_class": "deep"},
        "criteria": [],
        "changed_files": [],
        "diff_hash": None,
        "commands": [],
        "verdict": "NA",
        "failure_sig": None,
        "failure_count": 0,
    }
    base.update(kv)
    return json.dumps(base, ensure_ascii=False)


def _write_quest(root: str, qid: str, lines: list[str]) -> None:
    d = os.path.join(root, ".asgard", "quest")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, f"{qid}.jsonl"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


def _hard_won(root: str, qid: str = "q-hard", sig: str = "pytest assertion test_gate 판정 누락") -> None:
    _write_quest(
        root,
        qid,
        [
            _quest_line(qid, role="thinker", event="plan"),
            _quest_line(qid, verdict="FAIL", failure_sig=sig, failure_count=1),
            _quest_line(
                qid,
                verdict="PASS",
                criteria=["verifier gate 가 판정 레코드를 요구"],
                commands=[{"cmd": "pytest tests/test_gate.py", "exit_code": 0}],
                changed_files=["src/asgard/hooks/verifier_gate.py"],
            ),
        ],
    )


class EvoBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self._tmp.name, "proj")
        self.home = os.path.join(self._tmp.name, "home")
        os.makedirs(self.root)
        os.makedirs(self.home)
        self._env = mock.patch.dict(os.environ, {"HOME": self.home, "USERPROFILE": self.home})
        self._env.start()
        skill_bank._cache.clear()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def proj_skills(self) -> str:
        return os.path.join(self.root, ".asgard", "skills")


class TestSkillBankParse(EvoBase):
    def test_parse_ok(self):
        parsed = skill_bank.parse_skill_md("---\nname: a\ntriggers: X, y \n---\nbody")
        assert parsed is not None  # ty 내로잉 — 실패 시 여기서 즉사
        meta, body = parsed
        self.assertEqual(meta["name"], "a")
        self.assertEqual(meta["triggers"], ("x", "y"))
        self.assertEqual(meta["agent"], "worker")  # 기본값
        self.assertEqual(body, "body")

    def test_parse_rejects_missing_triggers_or_name(self):
        self.assertIsNone(skill_bank.parse_skill_md("---\nname: a\n---\nbody"))
        self.assertIsNone(skill_bank.parse_skill_md("---\ntriggers: x\n---\nbody"))
        self.assertIsNone(skill_bank.parse_skill_md("no frontmatter"))


class TestSkillBankResolve(EvoBase):
    def test_resolve_matches_trigger_and_agent(self):
        _write_skill(self.proj_skills(), "learned-cache", "캐시, redis", agent="worker")
        hits = skill_bank.resolve_learned(self.root, "Redis 캐시 무효화 수정", "worker")
        self.assertEqual([n for n, _ in hits], ["learned-cache"])
        self.assertEqual(skill_bank.resolve_learned(self.root, "Redis 캐시", "freyja"), [])  # agent 불일치
        self.assertEqual(skill_bank.resolve_learned(self.root, "무관한 작업", "worker"), [])  # trigger 불일치

    def test_agent_any_matches_everywhere(self):
        _write_skill(self.proj_skills(), "learned-any", "배포", agent="any")
        for agent in ("worker", "freyja", "thor"):
            self.assertTrue(skill_bank.resolve_learned(self.root, "배포 스크립트", agent))

    def test_cap_two_by_hit_count(self):
        _write_skill(self.proj_skills(), "learned-a", "알파", body="A")
        _write_skill(self.proj_skills(), "learned-b", "알파, 베타", body="B")
        _write_skill(self.proj_skills(), "learned-c", "알파, 베타, 감마", body="C")
        hits = skill_bank.resolve_learned(self.root, "알파 베타 감마 전부", "worker")
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0][0], "learned-c")  # 매칭 수 내림차순

    def test_hot_reload_without_restart(self):
        """수락 기준 (CUS-252) — 프로세스 재시작 없이 새 SKILL.md 가 다음 resolve 에 라우팅."""
        self.assertEqual(skill_bank.resolve_learned(self.root, "마이그레이션", "worker"), [])
        _write_skill(self.proj_skills(), "learned-mig", "마이그레이션")
        hits = skill_bank.resolve_learned(self.root, "마이그레이션 정리", "worker")
        self.assertEqual([n for n, _ in hits], ["learned-mig"])

    def test_edit_after_approval_invalidates_skill(self):
        p = _write_skill(self.proj_skills(), "learned-x", "엑스", body="OLD")
        self.assertIn("OLD", skill_bank.resolve_learned(self.root, "엑스", "worker")[0][1])
        time.sleep(0.01)
        open(p, "w", encoding="utf-8").write("---\nname: learned-x\ntriggers: 엑스\n---\nNEW")
        os.utime(p)  # mtime 전진 보장 (파일시스템 해상도 방어)
        self.assertEqual(skill_bank.resolve_learned(self.root, "엑스", "worker"), [])

    def test_project_overrides_global(self):
        gdir = os.path.join(self.home, ".asgard", "skills")
        _write_skill(gdir, "learned-dup", "중복", body="GLOBAL")
        _write_skill(self.proj_skills(), "learned-dup", "중복", body="PROJECT")
        hits = skill_bank.resolve_learned(self.root, "중복 확인", "worker")
        self.assertIn("PROJECT", hits[0][1])

    def test_archive_dir_skipped(self):
        _write_skill(os.path.join(self.proj_skills(), ".archive"), "learned-old", "옛날")
        self.assertEqual(skill_bank.resolve_learned(self.root, "옛날 방식", "worker"), [])

    def test_record_use_accumulates(self):
        skill_bank.record_use(self.root, ["learned-a"])
        skill_bank.record_use(self.root, ["learned-a", "learned-b"])
        u = skill_bank.usage(self.root)
        self.assertEqual(u["learned-a"]["uses"], 2)
        self.assertEqual(u["learned-b"]["uses"], 1)
        self.assertIn("last_used", u["learned-a"])


class TestMine(EvoBase):
    def test_hard_won_creates_pending_and_latch(self):
        _hard_won(self.root)
        created = evolution.mine(self.root)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["fail_count"], 1)
        self.assertTrue(created[0]["name"].startswith("learned-"))
        text = evolution.show(self.root, created[0]["id"])
        assert text is not None  # ty 내로잉 — 방금 만든 초안이므로 실존
        self.assertIn("origin: retrospective", text)
        self.assertIn("pytest tests/test_gate.py", text)  # 증거 카드 — 실측 통과 명령
        self.assertEqual(evolution.mine(self.root), [])  # latch — 같은 신호 재제안 없음
        self.assertEqual(evolution.unmined_signals(self.root), 0)

    def test_smooth_pass_not_mined(self):
        _write_quest(self.root, "q-smooth", [_quest_line("q-smooth", verdict="PASS", criteria=["ok"])])
        self.assertEqual(evolution.mine(self.root), [])

    def test_fail_only_not_mined(self):
        _write_quest(self.root, "q-fail", [_quest_line("q-fail", verdict="FAIL", failure_sig="broken thing")])
        self.assertEqual(evolution.mine(self.root), [])

    def test_forbidden_env_sig_not_mined(self):
        _hard_won(self.root, qid="q-env", sig="zsh: command not found: hyperframes")
        self.assertEqual(evolution.mine(self.root), [])

    def test_forbidden_credential_and_negativity_not_mined(self):
        """Hermes 비교검증(26-07-16) 보강 — 크레덴셜·도구 부정 주장도 그날의 사정이지 교훈이 아니다."""
        _hard_won(self.root, qid="q-cred", sig="hindsight api key unauthorized (401)")
        _hard_won(self.root, qid="q-neg", sig="browser tool is broken on this host")
        self.assertEqual(evolution.mine(self.root), [])

    def test_fail_whys_leak_filtered(self):
        """마지막 sig 만 걸러도 앞선 환경 노이즈가 함정 섹션에 박제되던 누수 (비교검증 즉시 권고 1)."""
        qid = "q-mixed"
        _write_quest(
            self.root,
            qid,
            [
                _quest_line(qid, verdict="FAIL", failure_sig="command not found: uv"),
                _quest_line(qid, verdict="FAIL", failure_sig="verifier gate 판정 누락 진짜 결함"),
                _quest_line(qid, verdict="PASS", criteria=["ok"], commands=[{"cmd": "pytest", "exit_code": 0}]),
            ],
        )
        created = evolution.mine(self.root)
        self.assertEqual(len(created), 1)  # 마지막 sig 는 실결함 — 채굴은 유효
        text = evolution.show(self.root, created[0]["id"])
        assert text is not None
        self.assertIn("진짜 결함", text)
        self.assertNotIn("command not found", text)  # 환경 노이즈는 본문에도 박제 금지

    def test_scan_cap(self):
        for i in range(5):
            _hard_won(self.root, qid=f"q-{i}", sig=f"고유 실패 시그니처 {i} deterministic")
        self.assertEqual(len(evolution.mine(self.root, cap=3)), 3)
        self.assertEqual(evolution.unmined_signals(self.root), 2)  # 나머지는 다음 스캔

    def test_unmined_single_quest_filter(self):
        _hard_won(self.root, qid="q-one")
        self.assertEqual(evolution.unmined_signals(self.root, "q-one"), 1)
        self.assertEqual(evolution.unmined_signals(self.root, "q-other"), 0)


class TestInbox(EvoBase):
    def _mined(self) -> dict:
        _hard_won(self.root)
        return evolution.mine(self.root)[0]

    def test_approve_rejects_placeholder_triggers(self):
        _write_quest(
            self.root,
            "q-min",
            [
                _quest_line("q-min", verdict="FAIL", failure_sig="ㅁ"),  # 토큰 추출 불가 → placeholder
                _quest_line("q-min", verdict="PASS"),
            ],
        )
        m = evolution.mine(self.root)[0]
        ok, msg = evolution.approve(self.root, m["id"])
        self.assertFalse(ok)
        self.assertIn("placeholder", msg)

    def test_approve_installs_and_routes(self):
        m = self._mined()
        ok, msg = evolution.approve(self.root, m["id"])
        self.assertTrue(ok, msg)
        self.assertIn(m["name"], skill_bank.learned_skills(self.root))
        hits = skill_bank.resolve_learned(self.root, "pytest 판정 누락 재발", "worker")
        self.assertEqual([n for n, _ in hits], [m["name"]])
        self.assertEqual(evolution.pending_list(self.root), [])  # 인박스에서 제거
        self.assertEqual(evolution.mine(self.root), [])  # approved latch 유지

    def test_approve_name_collision(self):
        m = self._mined()
        _write_skill(self.proj_skills(), m["name"], "아무거나")
        skill_bank._cache.clear()
        ok, msg = evolution.approve(self.root, m["id"])
        self.assertFalse(ok)
        self.assertIn("이름 충돌", msg)

    def test_approve_missing_candidate(self):
        ok, msg = evolution.approve(self.root, "evo-없음")
        self.assertFalse(ok)
        self.assertIn("후보 없음", msg)

    def test_reject_latch_and_audit_trail(self):
        m = self._mined()
        ok, _ = evolution.reject(self.root, m["id"], reason="노이즈")
        self.assertTrue(ok)
        self.assertEqual(evolution.pending_list(self.root), [])
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".asgard", "evolution", "rejected", m["id"])))
        self.assertEqual(evolution.mine(self.root), [])  # rejected latch — 재제안 금지
        seen = json.load(open(os.path.join(self.root, ".asgard", "evolution", "seen.json"), encoding="utf-8"))
        entry = next(v for v in seen.values() if v["id"] == m["id"])
        self.assertEqual(entry["status"], "rejected")
        self.assertEqual(entry["reason"], "노이즈")

    def test_archive_disables_routing(self):
        m = self._mined()
        evolution.approve(self.root, m["id"])
        ok, _ = evolution.archive_skill(self.root, m["name"])
        self.assertTrue(ok)
        self.assertEqual(skill_bank.resolve_learned(self.root, "pytest 판정 누락 재발", "worker"), [])
        archive = os.path.join(self.proj_skills(), ".archive")
        self.assertTrue(any(d.startswith(m["name"]) for d in os.listdir(archive)))  # 삭제 아님 — 복원 가능

    def test_restore_roundtrip_and_collision(self):
        m = self._mined()
        evolution.approve(self.root, m["id"])
        evolution.archive_skill(self.root, m["name"])
        ok, msg = evolution.restore_skill(self.root, m["name"])
        self.assertTrue(ok, msg)
        self.assertTrue(skill_bank.resolve_learned(self.root, "pytest 판정 누락 재발", "worker"))  # 재라우팅
        # 활성 동명 스킬이 있으면 복원 거부 (Hermes restore 충돌 검증 상당)
        evolution.archive_skill(self.root, m["name"])
        _write_skill(self.proj_skills(), m["name"], "다른트리거")
        ok, msg = evolution.restore_skill(self.root, m["name"])
        self.assertFalse(ok)
        self.assertIn("이미 있다", msg)
        self.assertFalse(evolution.restore_skill(self.root, "learned-없는놈")[0])

    def test_bundled_name_collision_blocked(self):
        m = self._mined()
        with mock.patch.object(evolution, "_bundled_names", return_value=frozenset({m["name"]})):
            ok, msg = evolution.approve(self.root, m["id"])
        self.assertFalse(ok)
        self.assertIn("번들", msg)


class TestHeimdallNote(EvoBase):
    """_learned_note 주입 계약 — Heimdall 전체 기동 없이 unbound 호출 (root/on_text 만 사용)."""

    def _note(self, task: str, agent: str, quiet: bool = False):
        from asgard.agent.heimdall import Heimdall

        texts: list[str] = []
        fake = SimpleNamespace(root=self.root, on_text=texts.append)
        # unbound 호출 — self 는 root/on_text 만 쓰므로 SimpleNamespace 로 충분 (ty 는 모른다)
        return Heimdall._learned_note(fake, task, agent, quiet), texts  # ty: ignore[invalid-argument-type]

    def test_injects_matched_skill_and_records_use(self):
        _write_skill(self.proj_skills(), "learned-cache", "캐시", body="캐시 무효화 절차")
        note, texts = self._note("캐시 만료 버그", "worker")
        self.assertIn("캐시 무효화 절차", note)
        self.assertIn("advisory", note)  # 게이트 증거 아님 명시 — 헌법 문구
        self.assertTrue(any("learned-cache" in t for t in texts))
        self.assertEqual(skill_bank.usage(self.root)["learned-cache"]["uses"], 1)

    def test_quiet_suppresses_output(self):
        _write_skill(self.proj_skills(), "learned-cache", "캐시")
        note, texts = self._note("캐시 만료", "worker", quiet=True)
        self.assertTrue(note)
        self.assertEqual(texts, [])

    def test_no_match_empty(self):
        note, texts = self._note("무관한 작업", "worker")
        self.assertEqual(note, "")
        self.assertEqual(texts, [])


class TestDeliveryDeclarative(EvoBase):
    """딜리버리 선언화 (CUS-251 후속) — frontmatter delivery: 키가 디스패치 enum·티어의 단일 소스."""

    def test_delivery_agents_from_frontmatter(self):
        from asgard.templates.roles import delivery_agents

        da = delivery_agents()
        self.assertEqual(
            da,
            {
                "eitri": "standard",
                "freyja": "standard",
                "freyja-lead": "standard",
                "loki": "fast",
                "mimir": "standard",
                "thor": "standard",
            },
        )
        self.assertNotIn("ullr", da)  # delivery 키 없는 role 은 디스패치 비대상 (현행 의미 보존)
        self.assertNotIn("worker", da)  # Trinity 역할은 딜리버리가 아니다

    def test_readonly_derived_from_tools(self):
        from asgard.templates.roles import role_writable

        self.assertFalse(role_writable("asgard-loki.md"))  # Write 부재 = read-only 반례 탐색
        self.assertTrue(role_writable("asgard-thor.md"))

    def test_heimdall_dispatch_surfaces_match(self):
        from asgard.agent.heimdall import _DELIVERY, _DELIVERY_READONLY, _DELIVERY_TIERS

        self.assertEqual(set(_DELIVERY), set(_DELIVERY_TIERS))
        self.assertEqual(_DELIVERY_READONLY, frozenset({"loki", "mimir"}))


class TestEnvDisable(EvoBase):
    """A/B 개입 스위치 — ASGARD_LEARNED_DISABLE 이 라우팅을 끈다 (벤치 하니스 계약)."""

    def test_disable_by_name_and_star(self):
        _write_skill(self.proj_skills(), "learned-cache", "캐시")
        with mock.patch.dict(os.environ, {"ASGARD_LEARNED_DISABLE": "learned-cache"}):
            self.assertEqual(skill_bank.resolve_learned(self.root, "캐시 만료", "worker"), [])
        with mock.patch.dict(os.environ, {"ASGARD_LEARNED_DISABLE": "*"}):
            self.assertEqual(skill_bank.resolve_learned(self.root, "캐시 만료", "worker"), [])
        self.assertTrue(skill_bank.resolve_learned(self.root, "캐시 만료", "worker"))  # 미설정 = 정상 라우팅


class TestBench(EvoBase):
    """C4 A/B 하니스 — MAD confidence 계약 (run<3 / MAD=0 = 판정 불가)."""

    def test_mad_and_confidence(self):
        from asgard.evolution_bench import confidence, mad

        self.assertEqual(mad([10.0, 10.0, 10.0]), 0.0)
        self.assertEqual(mad([1.0, 2.0, 9.0]), 1.0)
        self.assertIsNone(confidence([1.0, 2.0], [1.0, 2.0, 3.0]))  # run < 3
        self.assertIsNone(confidence([5.0, 5.0, 5.0], [1.0, 1.0, 1.0]))  # MAD = 0
        c = confidence([10.0, 11.0, 12.0], [5.0, 5.5, 6.0])
        assert c is not None
        self.assertAlmostEqual(c, 5.5)  # |11 - 5.5| / 1.0

    def test_run_ab_keep_verdict_and_ledger(self):
        from asgard.evolution_bench import run_ab

        seq = {"learned-x": iter([10.0, 11.0, 12.0, 10.5, 11.5]), "": iter([5.0, 5.5, 6.0, 5.2, 5.8])}
        r = run_ab(self.root, "learned-x", "true", "wall", runs=5, direction="min", runner=lambda d: next(seq[d]))
        self.assertEqual(r["verdict"], "keep")  # ON(variant) 이 유의미하게 낮다 (min)
        ledger = os.path.join(self.root, ".asgard", "evolution", "bench.jsonl")
        rec = json.loads(open(ledger, encoding="utf-8").read().strip())
        self.assertEqual(rec["skill"], "learned-x")
        self.assertEqual(rec["verdict"], "keep")

    def test_run_ab_discard_and_inconclusive(self):
        from asgard.evolution_bench import run_ab

        worse = {"learned-x": iter([5.0, 5.1, 5.2]), "": iter([9.0, 9.1, 9.2])}
        r = run_ab(self.root, "learned-x", "true", "wall", runs=3, direction="min", runner=lambda d: next(worse[d]))
        self.assertEqual(r["verdict"], "discard")
        noisy = {"learned-x": iter([5.0, 9.0, 7.0]), "": iter([6.0, 8.0, 7.5])}
        r = run_ab(self.root, "learned-x", "true", "wall", runs=3, direction="min", runner=lambda d: next(noisy[d]))
        self.assertEqual(r["verdict"], "inconclusive")

    def test_metric_parse_contract(self):
        from asgard.evolution_bench import _parse_metric

        self.assertEqual(_parse_metric("noise\nMETRIC wall=3.5\nMETRIC wall=2.5\n", "wall"), 2.5)  # 마지막 매치
        self.assertIsNone(_parse_metric("no metric here", "wall"))


class TestPolish(EvoBase):
    """LLM 증류 (opt-in) — 닫힌 재작성 + satisficing backstop (보존 필드 변조 거부)."""

    def _mined(self) -> dict:
        _hard_won(self.root)
        return evolution.mine(self.root)[0]

    def _fake_provider(self, rewritten: str):
        block = SimpleNamespace(type="text", text=rewritten)
        client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(content=[block])))
        rp = SimpleNamespace(missing=[], model="m", profile=SimpleNamespace(api_mode="anthropic"))
        return (
            mock.patch("asgard.providers.resolve", return_value=rp),
            mock.patch("asgard.agent.session.make_client", return_value=client),
        )

    def test_polish_rewrites_in_place(self):
        m = self._mined()
        text = evolution.show(self.root, m["id"])
        assert text is not None
        rewritten = text.replace("## 함정 (먼저 실패한 지점)", "## 함정 (원칙 수준 서술)")
        p1, p2 = self._fake_provider(rewritten)
        with p1, p2:
            ok, msg = evolution.polish(self.root, m["id"])
        self.assertTrue(ok, msg)
        after = evolution.show(self.root, m["id"])
        assert after is not None
        self.assertIn("원칙 수준 서술", after)
        self.assertEqual(evolution.pending_list(self.root)[0]["id"], m["id"])  # 여전히 pending — 승인 별도

    def test_polish_backstop_rejects_name_change(self):
        m = self._mined()
        text = evolution.show(self.root, m["id"])
        assert text is not None
        p1, p2 = self._fake_provider(text.replace(f"name: {m['name']}", "name: learned-탈취", 1))
        with p1, p2:
            ok, msg = evolution.polish(self.root, m["id"])
        self.assertFalse(ok)
        self.assertIn("보존 필드", msg)
        after = evolution.show(self.root, m["id"])
        assert after is not None
        self.assertIn(f"name: {m['name']}", after)  # 초안 무손상

    def test_polish_rejects_non_skill_output(self):
        m = self._mined()
        p1, p2 = self._fake_provider("죄송하지만 그 요청은 처리할 수 없습니다.")
        with p1, p2:
            ok, msg = evolution.polish(self.root, m["id"])
        self.assertFalse(ok)
        self.assertIn("형식이 아님", msg)

    def test_polish_backs_up_deterministic_draft(self):
        """latch 때문에 초안 재생성이 불가하므로 polish 전 원본 1장 보존 (비교검증 백로그 반영)."""
        m = self._mined()
        original = evolution.show(self.root, m["id"])
        assert original is not None
        p1, p2 = self._fake_provider(original.replace("## 전략", "## 전략(다듬음)"))
        with p1, p2:
            ok, _ = evolution.polish(self.root, m["id"])
        self.assertTrue(ok)
        orig_path = os.path.join(self.root, ".asgard", "evolution", "pending", m["id"], "SKILL.md.orig")
        self.assertEqual(open(orig_path, encoding="utf-8").read(), original)


class TestNoInjectionInvariants(EvoBase):
    """헌법 불변식 고정 (비교검증 즉시 권고 3) — 학습물은 판정 표면(Verifier)·반례 탐색(loki)에 못 들어간다."""

    def _fake_heimdall(self, learned_mock):
        child = SimpleNamespace(run=lambda t: SimpleNamespace(text="done", writes=[]), _nested_dispatch=False)
        return SimpleNamespace(
            root=self.root,
            on_text=lambda s: None,
            delivery_identity="",
            _learned_note=learned_mock,
            _session=lambda *a, **kw: child,
            _delivery_model=lambda agent: None,
            _track_cache=lambda r: None,
        )

    def test_loki_dispatch_skips_learned_note(self):
        from asgard.agent import heimdall

        learned = mock.Mock(return_value="\n\n# 학습 스킬")
        fake = self._fake_heimdall(learned)
        with mock.patch.object(heimdall, "ql"):
            handler = heimdall.Heimdall._dispatch_handler(cast(heimdall.Heimdall, fake), "sid", [])
            handler({"agent": "loki", "task": "반례 탐색", "why": ""})
            learned.assert_not_called()  # read-only 딜리버리 = 무주입
            handler({"agent": "thor", "task": "백엔드 작업", "why": ""})
            learned.assert_called_once()  # 쓰기 딜리버리 = 주입 경로 살아있음 (대조군)

    def test_verifier_assembly_has_no_learned_note(self):
        """mk_verifier 클로저 본문에 learned 주입이 없어야 한다 — 주석이 아니라 테스트가 지킨다."""
        import inspect
        import re as _re

        from asgard.agent import heimdall

        src = inspect.getsource(heimdall)
        m = _re.search(r"def mk_verifier\b.*?(?=\n {16}\w|\n {12}\w)", src, _re.DOTALL)
        assert m is not None, "mk_verifier 조립 지점을 찾지 못함 — 리네임 시 이 테스트도 갱신"
        self.assertNotIn("_learned_note", m.group(0))
        self.assertNotIn("학습 스킬", m.group(0))


if __name__ == "__main__":
    unittest.main()
