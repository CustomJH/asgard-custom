"""역할 문서의 계약 문구 — 다시 쓰기가 떨어뜨리면 빨개진다."""

import unittest


class TestRoleContract(unittest.TestCase):
    """역할 문서는 산문이라 통째로 다시 쓰이는데, 그때 사라지는 것은 문장이 아니라 계약이다."""

    def test_role_documents_keep_their_contract_phrases(self):
        """다시 쓰기가 계약 문구를 떨어뜨리면 그 역할과 사유를 대며 죽는다.

        26-08-04 실측: 판정자 문서가 41줄에서 105줄로 다시 쓰이면서 `not a verification waiver`
        와 `read-only guard` 가 같이 사라졌다. 그때도 빨개지긴 했지만, 두 시험 다 **우연히** 그
        문구를 쓰고 있었을 뿐이라(하나는 doctor 드리프트 카나리아의 치환 대상, 하나는 lagom
        계약 검사) 무엇이 왜 깨졌는지는 어디에도 안 적혀 있었다. 게다가 둘 다 스캐폴딩을 도는
        느린 시험이라, 자기가 만진 파일만 돌린 사람은 초록을 보고 끝낸다.

        이 시험은 표(`ROLE_CONTRACT_INVARIANTS`) 하나만 읽는다 — 파일 I/O도 스캐폴딩도 없다."""
        from asgard.templates.roles import ROLE_AGENTS, ROLE_CONTRACT_INVARIANTS, missing_role_invariants

        bodies = dict(ROLE_AGENTS)
        for fname in ROLE_CONTRACT_INVARIANTS:
            self.assertIn(fname, bodies, f"{fname} — 표가 없는 역할 문서를 가리킨다")
        missing = missing_role_invariants()
        self.assertFalse(missing, "역할 문서가 자기 계약 문구를 잃었다:\n" + "\n".join(missing))

    def test_dispatch_sentence_names_a_seat_someone_can_choose(self):
        """호출자를 지목한 카드가 전이 함수 전용 좌석만 대면 그 문은 아무도 못 연다.

        26-08-19 실측: asgard-ullr 카드가 `Dispatch only when Thinker delegates broad exploration`
        이었다. 위임표는 그 정찰을 열 좌석에 열어 뒀는데 카드는 Thinker 하나만 댔고, Thinker 는
        전이 함수가 배정하는 자리라 아무도 골라서 앉힐 수 없다 (`UNDISPATCHABLE`). 카드 설명은
        호스트가 에이전트를 고를 때 읽는 전부여서, 결과는 세션 624건에 배차 6건이었다 — 그 6건도
        한 세션에 몰려 있고, 같은 기간 조건 없는 내장 Explore 카드가 54건을 가져갔다.

        약한 쪽으로만 판정한다. 카드가 호출자를 아예 안 대면 통과이고, 고를 수 있는 좌석을 하나라도
        대면 통과다. 지목한 좌석이 **전부** 배차 불가일 때만 빨개진다 — 산문의 좋은 모양을 세지
        않고 죽은 문 하나만 잡는다."""
        import re

        from asgard.hooks.subagent_gate import UNDISPATCHABLE
        from asgard.templates.roles import ROLE_AGENTS

        # 카드 산문이 쓰는 호칭 → 에이전트 이름. 표가 아니라 산문을 읽으므로 별칭도 같이 건다.
        SEATS = {
            "thinker": "asgard-thinker",
            "verifier": "asgard-verifier",
            "worker": "asgard-worker",
            "thor-lead": "asgard-thor-lead",
            "thor": "asgard-thor",
            "freyja": "asgard-freyja",
            "eitri": "asgard-eitri",
            "planner": "asgard-planner",
            "mimir": "asgard-mimir",
            "loki": "asgard-loki",
            "ullr": "asgard-ullr",
        }
        dead: list[str] = []
        for fname, body in ROLE_AGENTS:
            desc = re.search(r"^description:\s*(.+)$", body, re.M)
            if not desc:
                continue
            hit = re.search(r"Dispatch\b.*?(?:\.(?:\s|$)|$)", desc.group(1), re.S)
            if not hit:
                continue  # 호출자를 안 대는 카드 — 판정 대상이 아니다
            sentence = hit.group(0).strip()
            named = {agent for word, agent in SEATS.items() if re.search(rf"\b{re.escape(word)}\b", sentence, re.I)}
            if named and named <= UNDISPATCHABLE:
                dead.append(f"{fname}: 지목한 호출자가 배차 불가 좌석뿐이다 ({', '.join(sorted(named))}) — {sentence}")
        self.assertFalse(
            dead,
            "카드가 아무도 못 여는 문을 가리킨다 — 언제 부르는지를 적어라:\n" + "\n".join(dead),
        )


if __name__ == "__main__":
    unittest.main()
