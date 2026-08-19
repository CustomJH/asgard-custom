"""훅이 도는 프로젝트의 뿌리를 기계 단위로 남기는 흔적 파일.

`asgard sync` 는 `~/.asgard/projects.json` 에 이름이 오른 프로젝트만 고친다. 그 파일에 이름이
오르는 길은 둘뿐이었다 — 이 기계에서 `asgard init` 을 돌렸거나, 그 폴더 안에 서서 `sync` 를
쳤거나. 그래서 동료가 셋업한 저장소를 clone 한 사람, `~/.asgard` 를 잃은 사람, 기계를 갈아탄
사람은 업그레이드가 아무리 돌아도 자기 프로젝트가 옛 코어인 채로 남고, 복구할 길이 프로젝트마다
찾아가 `init` 을 다시 돌리는 것뿐이었다. 게다가 `sync` 는 등록된 것만 세어 "all projects on the
latest core" 로 끝나 그 상태가 화면에서 초록으로 보인다.

훅은 셋업된 프로젝트에서만 돈다. 그러니 훅이 돈다는 사실 자체가 "여기 Asgard 가 깔려 있다"는
증거다. 이 모듈은 그 사실만 남기고, **등록 여부는 정하지 않는다** — 무엇이 등록할 만한
프로젝트인지는 `asgard sync` 가 `registry` 한 곳에서 판단한다. 판단이 두 벌로 갈라지면 한쪽만
고쳐진 채 남는다.

값: 이미 남긴 프로젝트에서는 `expanduser`·`realpath`·`exists` 로 경로 성분마다 stat 이 몇 번
도는 것이 전부다 — 실측 10.29µs/호출(20,000회 평균). 훅 하나를 띄우는 값이 실측 CPU 15.8ms
(`hook_dispatch.py` 머리말)인 것에 비하면 0.07% 다. 처음 보는 프로젝트에서만 작은 파일 하나를
쓴다(316.6µs). 이 값은 세션당 한 번이 아니라 `firing.run` 을 지나는 훅 호출마다 든다.

기록은 전부 fail-open 이다 — 흔적을 못 남겨도 훅의 판단은 그대로 나간다.
"""

from __future__ import annotations

import hashlib
import os


def _dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".asgard", "seen")


def _name(root: str) -> str:
    # 경로를 파일 이름에 그대로 쓸 수 없어(구분자·길이·대소문자) 해시로 줄인다. 내용에 원본
    # 경로가 들어 있으므로 해시는 이름의 유일성만 맡고, 되읽는 쪽은 해시를 풀지 않는다.
    return hashlib.sha1(root.encode("utf-8")).hexdigest()[:16] + ".path"


def note(root: str) -> None:
    """이 뿌리를 한 번 남긴다. 이미 있으면 경로를 풀고 존재를 확인하는 stat 몇 번으로 끝난다."""
    if not root:
        return
    try:
        target = os.path.join(_dir(), _name(os.path.realpath(root)))
        if os.path.exists(target):
            return
        os.makedirs(_dir(), exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(os.path.realpath(root))
        os.replace(tmp, target)
    except Exception:
        pass


def roots() -> list:
    """남아 있는 흔적의 뿌리 경로들. 읽을 수 없는 파일은 건너뛴다."""
    out = []
    try:
        names = sorted(os.listdir(_dir()))
    except Exception:
        return out
    for name in names:
        if not name.endswith(".path"):
            continue
        try:
            with open(os.path.join(_dir(), name), encoding="utf-8") as handle:
                text = handle.read().strip()
        except Exception:
            continue
        if text:
            out.append(text)
    return out


def clear(root: str) -> None:
    """흡수했거나 프로젝트가 아니라고 판정된 뿌리의 흔적을 지운다."""
    try:
        os.remove(os.path.join(_dir(), _name(os.path.realpath(root))))
    except Exception:
        pass
