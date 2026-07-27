"""토르 정찰 사이드카 — `survey` 가 알아낸 것을 세션 너머로 들고 간다.

왜 필요한가: 절차의 첫 동사가 "여기서 무엇이 지배하는가"인데, 그 답이 세션이 끝나면 증발했다.
같은 저장소를 매번 다시 훑는 것은 낭비가 아니라 **위험**이다 — 매번 다시 훑으면 매번 조금씩 다르게
읽고, 그 차이가 파일마다 다른 관례로 굳는다. 프레이야가 PRODUCT.md/DESIGN.md 를 들고 다니는 것과
같은 이유다.

경계는 이 저장소의 원칙 그대로다: **기계가 잴 수 있는 것만 기계가 적는다.** 매니페스트에서 읽히는
런타임·프레임워크·검증 명령은 여기서 결정론으로 채우고, 계층 구조·오류 모델·트랜잭션 경계처럼
코드를 읽어야 아는 것은 빈칸으로 남긴다. 빈칸을 추측으로 채우면 사이드카가 거짓말을 시작하고,
거짓말하는 사이드카는 없느니만 못하다.

신선도는 매니페스트 지문으로 잰다. 매니페스트가 바뀌었으면 판단 칸도 의심해야 한다 — 의존성이
바뀌는 것과 관례가 바뀌는 것은 자주 같이 온다.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

REL = os.path.join(".asgard", "thor", "stack.json")

# 매니페스트 → (생태계, 흔한 검증 명령). 파일이 곧 증거인 것만 넣는다 — 디렉터리 이름으로 추측하지
# 않는다(`src/` 가 있다고 무엇도 알 수 없다).
MANIFESTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("pom.xml", "JVM (Maven)", ("mvn -q test",)),
    ("build.gradle.kts", "JVM (Gradle)", ("./gradlew test",)),
    ("build.gradle", "JVM (Gradle)", ("./gradlew test",)),
    ("package.json", "Node", ("npm test",)),
    ("pyproject.toml", "Python", ("pytest",)),
    ("go.mod", "Go", ("go test ./...", "go vet ./...")),
    ("Cargo.toml", "Rust", ("cargo test", "cargo clippy -D warnings")),
    ("requirements.txt", "Python", ("pytest",)),
)
# 사람이 읽어야만 아는 것 — 정찰의 산출물이지 탐지의 산출물이 아니다.
JUDGEMENT_KEYS = ("layering", "errors", "transactions", "cleanup")


@dataclass
class Survey:
    ecosystems: list[str] = field(default_factory=list)
    manifests: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    verifiers: list[str] = field(default_factory=list)
    judgement: dict[str, str] = field(default_factory=dict)
    fingerprint: str = ""

    @property
    def blanks(self) -> list[str]:
        return [key for key in JUDGEMENT_KEYS if not self.judgement.get(key)]


def _walk(root: str):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [
            d
            for d in dirs
            if not d.startswith(".") and d not in ("node_modules", "build", "target", "dist", "__pycache__", "venv")
        ]
        yield dirpath, files


def detect(root: str) -> Survey:
    """매니페스트와 확장자만으로 채운다 — 여기서 나온 것은 전부 파일이 증거다."""
    from . import thor_gate

    found: list[tuple[str, str, tuple[str, ...]]] = []
    languages: set[str] = set()
    seen: set[str] = set()
    for dirpath, files in _walk(root):
        for name, eco, cmds in MANIFESTS:
            if name in files and eco not in seen:
                seen.add(eco)
                found.append((os.path.relpath(os.path.join(dirpath, name), root), eco, cmds))
        for name in files:
            lang = thor_gate._language(name)
            if lang:
                languages.add(lang)
    return Survey(
        ecosystems=[eco for _, eco, _ in found],
        manifests=sorted(rel for rel, _, _ in found),
        languages=sorted(languages),
        verifiers=sorted({cmd for _, _, cmds in found for cmd in cmds}),
        fingerprint=fingerprint(root, [rel for rel, _, _ in found]),
    )


def fingerprint(root: str, manifests: list[str]) -> str:
    """매니페스트 내용의 지문. 내용을 쓰는 이유는 mtime 이 체크아웃마다 바뀌기 때문이다."""
    digest = hashlib.sha256()
    for rel in sorted(manifests):
        digest.update(rel.encode("utf-8"))
        try:
            with open(os.path.join(root, rel), "rb") as handle:
                digest.update(handle.read())
        except OSError:
            digest.update(b"<unreadable>")  # 못 읽은 것도 상태다 — 다음 실행과 구분되어야 한다
    return digest.hexdigest()[:16]


def load(root: str) -> Survey | None:
    try:
        with open(os.path.join(root, REL), encoding="utf-8") as handle:
            raw = json.load(handle)
    except OSError, ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    return Survey(
        ecosystems=[str(x) for x in raw.get("ecosystems") or []],
        manifests=[str(x) for x in raw.get("manifests") or []],
        languages=[str(x) for x in raw.get("languages") or []],
        verifiers=[str(x) for x in raw.get("verifiers") or []],
        judgement={str(k): str(v) for k, v in (raw.get("judgement") or {}).items() if k in JUDGEMENT_KEYS},
        fingerprint=str(raw.get("fingerprint") or ""),
    )


def save(root: str, survey: Survey) -> str:
    path = os.path.join(root, REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"  # temp+rename — 중간에 죽어도 반쪽 사이드카를 남기지 않는다
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "ecosystems": survey.ecosystems,
                "manifests": survey.manifests,
                "languages": survey.languages,
                "verifiers": survey.verifiers,
                "judgement": survey.judgement,
                "fingerprint": survey.fingerprint,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
    os.replace(tmp, path)
    return path


def stale(root: str, survey: Survey) -> bool:
    """매니페스트가 바뀌었나. 판단 칸까지 의심해야 하는 신호다."""
    return survey.fingerprint != fingerprint(root, survey.manifests)


def refresh(root: str, notes: dict[str, str]) -> Survey:
    """탐지는 다시 하고, 사람이 적어 둔 판단은 보존한다 — 기계가 사람의 답을 지우면 안 된다."""
    survey = detect(root)
    previous = load(root)
    if previous:
        survey.judgement.update(previous.judgement)
    survey.judgement.update({k: v for k, v in notes.items() if k in JUDGEMENT_KEYS and v})
    return survey
