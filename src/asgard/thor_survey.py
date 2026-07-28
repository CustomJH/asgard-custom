"""토르 정찰 사이드카 — `survey` 가 알아낸 것을 세션 너머로 들고 간다.

왜 필요한가: 절차의 첫 동사가 "여기서 무엇이 지배하는가"인데, 그 답이 세션이 끝나면 증발했다.
같은 저장소를 매번 다시 훑는 것은 낭비가 아니라 **위험**이다 — 매번 다시 훑으면 매번 조금씩 다르게
읽고, 그 차이가 파일마다 다른 관례로 굳는다. 프레이야가 PRODUCT.md/DESIGN.md 를 들고 다니는 것과
같은 이유다.

경계는 이 저장소의 원칙 그대로다: **기계가 잴 수 있는 것만 기계가 적는다.** 매니페스트에서 읽히는
런타임·프레임워크·검증 명령은 여기서 결정론으로 채우고, 계층 구조·오류 모델·트랜잭션 경계처럼
코드를 읽어야 아는 것은 빈칸으로 남긴다. 빈칸을 추측으로 채우면 사이드카가 거짓말을 시작하고,
거짓말하는 사이드카는 없느니만 못하다.

신선도는 두 지문으로 잰다. **매니페스트**가 바뀌었으면 의존성이 움직인 것이고, 의존성이 바뀌는
것과 관례가 바뀌는 것은 자주 같이 온다. **구조**(판정 가능한 소스 파일의 경로 집합)가 바뀌었으면
계층이 움직였을 수 있다 — 판단 칸 넷이 전부 코드를 읽어야 아는 것이라 매니페스트만으로는 그 넷의
낡음을 못 잰다.

구조 지문에 내용을 안 넣는 이유: 내용은 커밋마다 바뀌므로 모든 판단이 영구히 낡음으로 뜬다.
언제나 켜진 경고는 꺼진 경고와 같다. 파일이 생기고 사라지고 옮겨 다니는 것이 계층이 실제로
움직이는 사건이고, 그 입자성에서 재야 신호가 신호로 남는다.

그리고 지문은 **판단마다** 붙는다. 기록 전체에 하나만 두면 "언제 적혔는지 모르는 네 줄"이 되고,
그중 셋이 어제 것이어도 하나 때문에 넷 다 의심받는다. 여섯 달 전에 적은 것과 방금 적은 것을
구분하지 못하는 기록은, 다음 세션이 그대로 믿는다는 점에서 없느니만 못하다.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

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
# 구조 지문을 만든 자(尺)의 판. 자가 바뀌면 옛 지문과 새 지문은 **비교 자체가 안 된다** —
# 그때 "구조가 움직였다"고 말하면 움직인 것은 저장소가 아니라 이 파일인데 사람은 저장소를 본다.
# 실측에서 자를 한 번 바꾸자 적어 둔 판단 넷이 전부 영구 낡음으로 떴다. 판 번호는 그 거짓말의 값이다.
SHAPE_RULER = "dirs1"


@dataclass(frozen=True)
class Note:
    """판단 한 줄 + 그것이 적힌 시점의 세계. 빈 출처는 **모른다**는 뜻이지 최신이라는 뜻이 아니다.

    구 형식(`"layering": "flat"`)으로 적힌 기록을 읽으면 출처 칸이 비게 되는데, 그 자리를
    "지금"으로 채우면 사이드카가 거짓말을 시작한다 — 이 모듈이 빈칸을 추측으로 안 채우는 것과
    같은 규율이다. 모르는 것은 모른다고 실어야 사람이 다시 확인할 수 있다.
    """

    text: str
    at: str = ""  # ISO-8601 UTC. 빈 문자열 = 출처 미상
    manifest: str = ""  # 적을 때의 매니페스트 지문
    shape: str = ""  # 적을 때의 구조 지문

    @property
    def sourced(self) -> bool:
        return bool(self.at)


@dataclass
class Survey:
    ecosystems: list[str] = field(default_factory=list)
    manifests: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    verifiers: list[str] = field(default_factory=list)
    judgement: dict[str, Note] = field(default_factory=dict)
    fingerprint: str = ""

    @property
    def blanks(self) -> list[str]:
        return [key for key in JUDGEMENT_KEYS if not (self.judgement.get(key) or Note("")).text]

    @property
    def unsourced(self) -> list[str]:
        """적혀 있으나 언제 적혔는지 모르는 것 — 신선도를 판정할 수 없는 판단."""
        return [key for key, note in sorted(self.judgement.items()) if note.text and not note.sourced]

    def text_of(self, key: str) -> str:
        note = self.judgement.get(key)
        return note.text if note else ""


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


def shape(root: str) -> str:
    """소스가 **어느 디렉터리에 사는가**의 지문 — 계층이 움직였는지의 대리 지표.

    입자성을 두 번 골랐고, 두 번 다 근거는 같다: 언제나 켜진 경고는 꺼진 경고와 같다.

    ① 내용은 안 센다. 내용까지 재면 커밋마다 지문이 바뀌어 모든 판단이 영구히 낡음으로 뜬다.
    ② 파일 이름도 안 센다. 실측에서 테스트 파일 하나를 더한 것만으로 판단 넷이 전부 흔들렸는데,
       이 저장소에서 그것은 거의 매일 일어나는 일이다. 파일이 늘고 주는 것은 계층이 움직이는
       사건이 아니라 계층 **안에서** 일이 벌어지는 사건이다.

    남는 것이 디렉터리 집합이다. 패키지가 생기고, 모듈이 다른 층으로 옮겨 가고, 층이 통째로
    사라지는 것 — 판단 넷(계층·오류·트랜잭션·정리)이 실제로 다시 읽혀야 하는 사건이 이것이다.
    """
    from . import thor_gate

    digest = hashlib.sha256()
    homes: set[str] = set()
    for dirpath, files in _walk(root):
        if any(thor_gate._language(name) for name in files):
            homes.add(os.path.relpath(dirpath, root).replace(os.sep, "/"))
    for rel in sorted(homes):
        digest.update(rel.encode("utf-8") + b"\n")
    return f"{SHAPE_RULER}:{digest.hexdigest()[:16]}"


def drifted(root: str, survey: Survey) -> dict[str, tuple[str, ...]]:
    """판단마다, 적힌 뒤 무엇이 움직였는가. 빈 사전 = 넷 다 적힌 그대로의 세계다.

    출처를 모르는 판단(`unsourced`)은 여기 안 담는다 — 움직였는지 **모르는** 것이지 안 움직인
    것이 아니고, 둘을 같은 칸에 넣으면 화면이 거짓말한다. 그쪽은 `Survey.unsourced` 가 따로 낸다.
    """
    now_manifest = fingerprint(root, survey.manifests)
    now_shape = shape(root)
    out: dict[str, tuple[str, ...]] = {}
    for key, note in sorted(survey.judgement.items()):
        if not note.text or not note.sourced:
            continue
        moved = []
        if note.manifest and note.manifest != now_manifest:
            moved.append("의존성")
        if _same_ruler(note.shape, now_shape) and note.shape != now_shape:
            moved.append("구조")
        if moved:
            out[key] = tuple(moved)
    return out


def _same_ruler(before: str, now: str) -> bool:
    """두 지문이 같은 자로 만들어졌는가. 아니면 비교하지 않는다 — 못 재는 것을 움직였다고 하지 않는다."""
    return bool(before) and before.split(":", 1)[0] == now.split(":", 1)[0]


def unmeasured(survey: Survey) -> list[str]:
    """적혀 있으나 **지금 자로는 구조 낡음을 못 재는** 판단 — 자가 바뀐 뒤의 옛 기록.

    `drifted` 가 침묵하는 것과 "안 움직였다"는 다르다. 침묵이 곧 통과가 되면 게이트가 아니라
    알리바이가 된다는 이 저장소의 계약을 사이드카에도 그대로 건다.
    """
    return [
        key
        for key, note in sorted(survey.judgement.items())
        if note.text and note.sourced and not _same_ruler(note.shape, SHAPE_RULER + ":")
    ]


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
        judgement=_notes(raw.get("judgement")),
        fingerprint=str(raw.get("fingerprint") or ""),
    )


def _notes(raw: object) -> dict[str, Note]:
    """구 형식(`"layering": "flat"`)과 새 형식을 같이 읽는다 — 기록을 버리지 않고 출처만 비워 둔다."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Note] = {}
    for key, value in raw.items():
        if key not in JUDGEMENT_KEYS:
            continue
        if isinstance(value, dict):
            text = str(value.get("text") or "")
            if text:
                out[str(key)] = Note(
                    text,
                    str(value.get("at") or ""),
                    str(value.get("manifest") or ""),
                    str(value.get("shape") or ""),
                )
        elif str(value):
            out[str(key)] = Note(str(value))  # 출처 미상 — 지금 시각으로 채우면 그것이 거짓말이다
    return out


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
                "judgement": {
                    key: {"text": note.text, "at": note.at, "manifest": note.manifest, "shape": note.shape}
                    for key, note in sorted(survey.judgement.items())
                },
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
    """탐지는 다시 하고, 사람이 적어 둔 판단은 보존한다 — 기계가 사람의 답을 지우면 안 된다.

    **이번에 적은 것만** 지금의 지문을 받는다. 옛 판단에 새 지문을 찍으면 그 순간 낡음이 지워지고,
    사이드카는 다시 "언제 적혔는지 모르는 네 줄"로 돌아간다.
    """
    survey = detect(root)
    previous = load(root)
    if previous:
        survey.judgement.update(previous.judgement)
    written = _stamp(root, survey.fingerprint)
    survey.judgement.update({k: Note(v, *written) for k, v in notes.items() if k in JUDGEMENT_KEYS and v})
    return survey


def _stamp(root: str, manifest: str) -> tuple[str, str, str]:
    """(적은 시각, 매니페스트 지문, 구조 지문). 세 칸 전부 기계가 재는 것이라 추측이 안 섞인다."""
    return (datetime.now(timezone.utc).isoformat(timespec="seconds"), manifest, shape(root))
