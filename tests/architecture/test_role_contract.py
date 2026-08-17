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


if __name__ == "__main__":
    unittest.main()
