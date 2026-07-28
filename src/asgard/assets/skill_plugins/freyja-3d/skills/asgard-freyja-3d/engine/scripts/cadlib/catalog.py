"""기성품 조달 — 규격 부품의 STEP 을 받아 오거나, 못 받으면 그 사실을 말한다.

## 왜 나사산을 그리지 않는가

M3 볼트를 직접 모델링하면 두 가지가 동시에 나빠진다. 나사산 형상이 파일을 무겁게 만들고
(부품 하나가 수만 면), 그러고도 실물 규격과 미세하게 다르다. 기성품은 **받아 쓰는 것**이 맞다.

## 이 모듈이 상류와 다르게 하는 것

이전 판은 특정 회사의 호스팅 카탈로그 주소를 코드에 박아 두고 그것을 전제로 문서를 썼다. 남의
서비스가 사라지면 능력도 같이 사라지는 배선이고, 무엇보다 **아스가르드가 소유하지 않은 의존**이다.

여기서는 뒤집는다. 카탈로그는 **설정으로 주는 것**이고 기본값은 없다:

    ASGARD_CAD_CATALOG=https://example.invalid/api   환경변수, 또는
    python cad.py parts "M3x12 socket head" --catalog <url>

카탈로그가 없으면 부품을 지어내지 않는다. 대신 **치수를 명시한 자리표시자를 만들라**고 말하고,
그 자리표시자가 실물이 아니라는 사실을 보고에 남기게 한다. 조달 실패를 조용한 근사로 덮는 것이
이 레인에서 가장 비싼 사고다 — 볼트가 1mm 짧은 조립체는 도면상 완벽하다.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .report import Report

ENV_ENDPOINT = "ASGARD_CAD_CATALOG"
TIMEOUT = 20

NO_CATALOG = (
    "부품 카탈로그가 설정돼 있지 않다. 규격 부품을 지어내지 않는다.\n"
    f"  카탈로그를 붙이려면: {ENV_ENDPOINT}=<base-url> 또는 --catalog <base-url>\n"
    "  카탈로그 없이 진행하려면: 치수를 명시한 자리표시자를 직접 모델링하고, 보고에 "
    "'실물 STEP 아님 — 자리표시자'라고 적어라. 그 문장 없이 납품하지 않는다."
)


def endpoint(explicit: str | None) -> str:
    return (explicit or os.environ.get(ENV_ENDPOINT) or "").rstrip("/")


def search(query: str, *, catalog: str | None, limit: int = 8) -> Report:
    """부품을 찾는다. 카탈로그가 없으면 없다고 말한다 — 근사 형상을 제안하지 않는다."""
    report = Report(tool="parts search", target=query)
    base = endpoint(catalog)
    if not base:
        report.fail("no-catalog", NO_CATALOG)
        return report

    url = f"{base}/search?" + urllib.parse.urlencode({"q": query, "limit": limit})
    payload, error = _fetch_json(url)
    if error:
        report.unverified(
            "catalog-unreachable",
            f"카탈로그에 닿지 못했다({error}). 네트워크 실패는 '부품 없음'이 아니다 — "
            "다시 시도하거나, 자리표시자로 진행한다고 명시하라.",
        )
        return report

    items = payload.get("results") if isinstance(payload, dict) else payload
    if not isinstance(items, list) or not items:
        report.unverified("no-match", f"카탈로그가 {query!r} 에 대해 후보를 내지 않았다.")
        return report

    for order, item in enumerate(items[:limit], start=1):
        if not isinstance(item, dict):
            continue
        report.facts[f"{order}. {item.get('id', '?')}"] = (
            f"{item.get('name', '')} — {item.get('standard', '')} {item.get('size', '')}".strip()
        )
    report.ok("search", f"후보 {min(len(items), limit)}건. `--download <id>` 로 STEP 을 받는다.")
    return report


def download(part_id: str, out: str | Path, *, catalog: str | None) -> Report:
    """STEP 을 받아 체크섬까지 확인한다. 받은 파일이 STEP 이 맞는지도 본다."""
    from . import stepfile  # noqa: PLC0415 — 순환 없음, 지역 임포트로 의존을 얕게 둔다

    report = Report(tool="parts download", target=part_id)
    base = endpoint(catalog)
    if not base:
        report.fail("no-catalog", NO_CATALOG)
        return report

    meta, error = _fetch_json(f"{base}/parts/{urllib.parse.quote(part_id)}")
    if error or not isinstance(meta, dict):
        report.unverified("catalog-unreachable", f"부품 메타데이터를 받지 못했다: {error or '형식 오류'}")
        return report

    href = str(meta.get("step_url") or meta.get("url") or "")
    if not href:
        report.fail("no-step", f"{part_id} 에 STEP 내려받기 주소가 없다.")
        return report

    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(href, timeout=TIMEOUT) as response:  # noqa: S310 — 설정된 카탈로그만 부른다
            target.write_bytes(response.read())
    except (urllib.error.URLError, OSError) as failure:
        report.unverified("download", f"STEP 을 받지 못했다: {failure}")
        return report

    report.facts["산출물"] = str(target)
    report.facts["크기"] = f"{target.stat().st_size / 1024:.1f} KiB"

    expected = str(meta.get("sha256") or "")
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    report.facts["sha256"] = actual
    if expected and expected != actual:
        report.fail("checksum", f"체크섬이 다르다 — 받은 파일을 쓰지 않는다(기대 {expected[:12]}…, 실제 {actual[:12]}…).")
        return report
    if expected:
        report.ok("checksum", "카탈로그가 준 체크섬과 일치한다.")
    else:
        report.unverified("checksum", "카탈로그가 체크섬을 주지 않았다 — 무결성을 확인하지 못했다.")

    if not stepfile.looks_like_step(target):
        report.fail("not-step", "받은 파일이 ISO-10303-21 머리표를 갖고 있지 않다 — STEP 이 아니다.")
        return report

    facts = stepfile.read(target)
    report.facts["솔리드 / 면"] = f"{facts.solids} / {facts.faces}"
    report.ok("download", f"{part_id} 를 받았다. `import_step` 으로 조립체에 넣어라.")
    return report


def _fetch_json(url: str) -> tuple[object, str]:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:  # noqa: S310 — 설정된 카탈로그만 부른다
            return json.loads(response.read().decode("utf-8")), ""
    except urllib.error.HTTPError as error:
        return {}, f"HTTP {error.code}"
    except (urllib.error.URLError, OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        return {}, str(error)
