"""로봇 기술 파일 — URDF · SRDF · SDF 생성과 생성 시점 검증.

## 이 레인의 오류가 문법이 아닌 이유

무효한 XML 은 파서가 잡는다. 실제로 사람을 다치게 하는 것은 **그럴듯한데 틀린 파일**이다:
축이 뒤집힌 조인트, 도(degree)를 라디안 자리에 넣은 그룹 상태, 근거 없이 넓은 비활성 충돌 행렬,
질량이 0 인 링크. 전부 문법적으로 완전하다.

그래서 검증은 문법이 아니라 **의미**를 본다. 그리고 셋 중 둘 사이의 관계까지 본다 — SRDF 는
URDF 위에 얹히는 계층이라, URDF 를 같이 주면 존재하지 않는 링크를 가리키는 계획 그룹과 한계를
벗어난 그룹 상태를 잡는다. 이것이 이 모듈이 이전 판보다 늘린 몫이다.

## 규약

`gen_urdf()` / `gen_srdf()` / `gen_sdf()` 를 정의한 파이썬이 정본이고 XML 은 생성물이다. 반환값은
문자열, `xml.etree.ElementTree.Element`, 또는 `ElementTree` 중 하나면 된다.

검증은 **생성할 때 자동으로** 돈다. 별도 `validate` 동사를 두지 않는다 — 따로 두면 안 돌린다.
"""

from __future__ import annotations

import math
import runpy
import xml.etree.ElementTree as ET
from pathlib import Path

from .report import Report

KINDS = ("urdf", "srdf", "sdf")
JOINT_TYPES = ("revolute", "continuous", "prismatic", "fixed", "floating", "planar")
BOUNDED_JOINTS = ("revolute", "prismatic")

# 라디안 자리에 도(degree)가 들어온 것을 의심하는 문턱. 2π 를 넘는 관절각은 거의 항상 실수다.
RADIAN_SUSPICION = 2 * math.pi


def generate(kind: str, script: str | Path, out: str | Path | None, *, urdf: str | Path | None = None) -> Report:
    """소스를 실행해 XML 을 쓰고, 쓴 것을 곧바로 검증한다."""
    script = Path(script).resolve()
    report = Report(tool=kind, target=str(script))
    namespace = runpy.run_path(str(script), run_name=f"__{kind}_model__")
    generator = namespace.get(f"gen_{kind}")
    if not callable(generator):
        report.fail("contract", f"소스에 `gen_{kind}()` 가 없다 — 이 레인의 정본 진입점이다.")
        return report

    produced = generator()
    text = _to_xml_text(produced)
    if text is None:
        report.fail("contract", f"`gen_{kind}()` 가 XML 을 돌려주지 않았다: {type(produced).__name__}")
        return report

    target = Path(out) if out else script.parent / f"{script.stem}.{kind}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    report.facts["산출물"] = str(target)

    checked = validate(kind, target, urdf=urdf)
    report.facts.update(checked.facts)
    report.checks.extend(checked.checks)
    return report


def _to_xml_text(value: object) -> str | None:
    if isinstance(value, str):
        return value if value.lstrip().startswith("<") else None
    if isinstance(value, ET.ElementTree):
        value = value.getroot()
    if isinstance(value, ET.Element):
        return ET.tostring(value, encoding="unicode")
    return None


def validate(kind: str, path: str | Path, *, urdf: str | Path | None = None) -> Report:
    """생성된 문서를 의미 수준으로 본다. URDF 를 같이 주면 SRDF 교차 검증까지 간다."""
    path = Path(path)
    report = Report(tool=f"{kind} validate", target=str(path))
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError) as error:
        report.fail("xml", f"XML 을 읽지 못했다: {error}")
        return report

    if kind == "urdf":
        _check_urdf(report, root)
    elif kind == "srdf":
        _check_srdf(report, root, urdf)
    else:
        _check_sdf(report, root)
    return report


# ─────────────────────────────────────────────────────────────────────────────
# URDF
# ─────────────────────────────────────────────────────────────────────────────


def parse_urdf(root: ET.Element) -> tuple[dict[str, ET.Element], dict[str, ET.Element]]:
    links = {element.get("name", ""): element for element in root.findall("link") if element.get("name")}
    joints = {element.get("name", ""): element for element in root.findall("joint") if element.get("name")}
    return links, joints


def _check_urdf(report: Report, root: ET.Element) -> None:
    if root.tag != "robot":
        report.fail("urdf-root", f"루트가 <robot> 이 아니다: <{root.tag}>")
        return
    name = root.get("name") or ""
    report.facts["로봇"] = name or "(이름 없음)"
    if not name:
        report.fail("urdf-name", "<robot> 에 name 이 없다 — 하류 도구가 네임스페이스를 못 만든다.")

    links, joints = parse_urdf(root)
    report.facts["링크 / 조인트"] = f"{len(links)} / {len(joints)}"
    if not links:
        report.fail("urdf-empty", "링크가 하나도 없다.")
        return

    _check_duplicates(report, "link", [element.get("name", "") for element in root.findall("link")])
    _check_duplicates(report, "joint", [element.get("name", "") for element in root.findall("joint")])

    # ── 위상: 트리인가 ────────────────────────────────────────────────────────
    children: set[str] = set()
    dangling: list[str] = []
    for joint_name, joint in joints.items():
        # ElementTree 의 Element 는 자식이 없으면 falsy 다. `find(...) or 기본값` 은 실재하는
        # <parent link="..."/> 를 조용히 삼킨다 — 반드시 `is None` 으로 가른다.
        parent = _attr(joint.find("parent"), "link")
        child = _attr(joint.find("child"), "link")
        for role, value in (("parent", parent), ("child", child)):
            if not value:
                report.fail("urdf-joint-link", f"조인트 {joint_name} 에 {role} link 이 없다.")
            elif value not in links:
                dangling.append(f"{joint_name}.{role}={value}")
        if child:
            if child in children:
                report.fail("urdf-tree", f"링크 {child} 가 두 조인트의 자식이다 — URDF 는 트리여야 한다.")
            children.add(child)
    if dangling:
        report.fail("urdf-dangling", "존재하지 않는 링크를 가리키는 조인트가 있다: " + ", ".join(dangling[:8]))

    roots = sorted(set(links) - children)
    report.facts["루트 링크"] = ", ".join(roots) or "(없음)"
    if len(roots) == 0:
        report.fail("urdf-root-link", "부모 없는 링크가 없다 — 조인트에 순환이 있다.")
    elif len(roots) > 1 and joints:
        report.fail("urdf-forest", f"루트 링크가 {len(roots)}개다 — 연결되지 않은 조각이 있다: {', '.join(roots[:6])}")
    else:
        report.ok("urdf-tree", f"단일 루트({roots[0] if roots else '—'})를 갖는 트리다.")

    # ── 조인트 의미 ───────────────────────────────────────────────────────────
    for joint_name, joint in joints.items():
        kind = joint.get("type") or ""
        if kind not in JOINT_TYPES:
            report.fail("urdf-joint-type", f"조인트 {joint_name} 의 type 이 규격 밖이다: {kind!r}")
            continue
        if kind in BOUNDED_JOINTS:
            limit = joint.find("limit")
            if limit is None:
                report.fail("urdf-limit", f"{kind} 조인트 {joint_name} 에 <limit> 이 없다 — 계획기가 무한 범위로 읽는다.")
            else:
                _check_limit(report, joint_name, limit, kind)
        axis = joint.find("axis")
        if axis is not None:
            _check_axis(report, joint_name, axis)
        origin = joint.find("origin")
        if origin is not None:
            _check_rpy(report, f"조인트 {joint_name}", origin.get("rpy"))

    # ── 관성 ──────────────────────────────────────────────────────────────────
    massless: list[str] = []
    for link_name, link in links.items():
        inertial = link.find("inertial")
        if inertial is None:
            if link.find("visual") is not None or link.find("collision") is not None:
                massless.append(link_name)
            continue
        _check_inertial(report, link_name, inertial)
    if massless:
        report.unverified(
            "urdf-inertial",
            f"형상은 있는데 <inertial> 이 없는 링크가 {len(massless)}개다({', '.join(massless[:6])}). "
            "좌표계 전용 링크면 의도된 것이고, 물리 링크면 시뮬레이터가 기본값을 지어낸다.",
        )

    # ── 메시 참조 ─────────────────────────────────────────────────────────────
    _check_meshes(report, root)


def _check_duplicates(report: Report, kind: str, names: list[str]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    if duplicates:
        report.fail("urdf-duplicate", f"{kind} 이름이 중복이다: {', '.join(sorted(duplicates)[:8])}")


def _check_limit(report: Report, joint_name: str, limit: ET.Element, kind: str) -> None:
    for attribute in ("effort", "velocity"):
        if limit.get(attribute) is None:
            report.fail("urdf-limit", f"조인트 {joint_name} 의 <limit> 에 {attribute} 가 없다(규격 필수).")
    lower, upper = _float(limit.get("lower")), _float(limit.get("upper"))
    if kind == "revolute" and (lower is None or upper is None):
        report.fail("urdf-limit", f"revolute 조인트 {joint_name} 에 lower/upper 가 없다.")
    elif lower is not None and upper is not None:
        if lower > upper:
            report.fail("urdf-limit", f"조인트 {joint_name} 의 lower({lower}) 가 upper({upper}) 보다 크다.")
        elif kind == "revolute" and max(abs(lower), abs(upper)) > RADIAN_SUSPICION:
            report.unverified(
                "urdf-radians",
                f"조인트 {joint_name} 의 한계가 ±{max(abs(lower), abs(upper)):g} 로 2π 를 넘는다 — "
                "도(degree)를 라디안 자리에 넣었을 수 있다. URDF 는 라디안이다.",
            )


def _check_axis(report: Report, joint_name: str, axis: ET.Element) -> None:
    values = _triple(axis.get("xyz"))
    if values is None:
        report.fail("urdf-axis", f"조인트 {joint_name} 의 axis xyz 를 읽지 못했다.")
        return
    length = math.dist((0.0, 0.0, 0.0), values)
    if length == 0:
        report.fail("urdf-axis", f"조인트 {joint_name} 의 회전축이 영벡터다.")
    elif abs(length - 1.0) > 1e-3:
        report.unverified(
            "urdf-axis",
            f"조인트 {joint_name} 의 축 길이가 {length:.4f} 다 — 규격은 단위벡터를 요구한다(파서마다 다르게 정규화한다).",
        )


def _check_rpy(report: Report, label: str, rpy: str | None) -> None:
    values = _triple(rpy)
    if values and max(abs(value) for value in values) > RADIAN_SUSPICION:
        report.unverified(
            "urdf-radians",
            f"{label} 의 rpy 최대값이 {max(abs(value) for value in values):g} 로 2π 를 넘는다 — 도를 넣었을 수 있다.",
        )


def _check_inertial(report: Report, link_name: str, inertial: ET.Element) -> None:
    mass = inertial.find("mass")
    value = _float(mass.get("value")) if mass is not None else None
    if value is None:
        report.fail("urdf-mass", f"링크 {link_name} 의 <mass> 를 읽지 못했다.")
    elif value <= 0:
        report.fail("urdf-mass", f"링크 {link_name} 의 질량이 {value} 다 — 시뮬레이터가 발산한다.")

    inertia = inertial.find("inertia")
    if inertia is None:
        report.fail("urdf-inertia", f"링크 {link_name} 에 <inertia> 가 없다.")
        return
    diagonal = [_float(inertia.get(key)) for key in ("ixx", "iyy", "izz")]
    if any(item is None for item in diagonal):
        report.fail("urdf-inertia", f"링크 {link_name} 의 관성 대각 성분을 읽지 못했다.")
        return
    ixx, iyy, izz = (float(item) for item in diagonal)  # type: ignore[arg-type]
    if min(ixx, iyy, izz) <= 0:
        report.fail("urdf-inertia", f"링크 {link_name} 의 관성 대각에 0 이하가 있다({ixx}, {iyy}, {izz}).")
    elif not (ixx + iyy >= izz and iyy + izz >= ixx and ixx + izz >= iyy):
        report.fail(
            "urdf-inertia",
            f"링크 {link_name} 의 관성 텐서가 삼각 부등식을 어긴다({ixx}, {iyy}, {izz}) — 물리적으로 불가능한 강체다.",
        )


def _check_meshes(report: Report, root: ET.Element) -> None:
    package_refs = 0
    missing: list[str] = []
    total = 0
    for mesh in root.iter("mesh"):
        filename = mesh.get("filename") or ""
        if not filename:
            continue
        total += 1
        if filename.startswith("package://") or filename.startswith("model://"):
            package_refs += 1
        elif not Path(filename).expanduser().exists():
            missing.append(filename)
    if total:
        report.facts["메시 참조"] = f"{total}개 (package:// {package_refs})"
    if missing:
        report.fail("urdf-mesh", f"디스크에 없는 메시를 가리킨다: {', '.join(missing[:6])}")
    if package_refs:
        report.unverified(
            "urdf-mesh-package",
            f"package:// 참조가 {package_refs}개 있다 — ROS 워크스페이스 밖에서는 해석하지 못해 판정 불능이다.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# SRDF
# ─────────────────────────────────────────────────────────────────────────────


def _check_srdf(report: Report, root: ET.Element, urdf_path: str | Path | None) -> None:
    if root.tag != "robot":
        report.fail("srdf-root", f"루트가 <robot> 이 아니다: <{root.tag}>")
        return
    name = root.get("name") or ""
    report.facts["로봇"] = name or "(이름 없음)"

    groups = {element.get("name", ""): element for element in root.findall("group") if element.get("name")}
    states = root.findall("group_state")
    effectors = root.findall("end_effector")
    disabled = root.findall("disable_collisions")
    report.facts["그룹 / 상태 / EE / 비활성쌍"] = f"{len(groups)} / {len(states)} / {len(effectors)} / {len(disabled)}"

    if not groups:
        report.fail("srdf-empty", "계획 그룹이 하나도 없다 — MoveIt 이 계획할 대상이 없다.")

    # ── SRDF 가 넘보면 안 되는 것 ─────────────────────────────────────────────
    trespass = [tag for tag in ("link", "joint", "transmission", "gazebo") if root.find(tag) is not None]
    # <joint> 는 virtual_joint·passive_joint 와 다르다 — 최상위 <joint> 만 침범이다.
    if trespass:
        report.fail(
            "srdf-scope",
            f"SRDF 에 구조 요소가 들어 있다: <{'>, <'.join(trespass)}>. 형상·관성·조인트 원점은 URDF 몫이다.",
        )

    urdf_links: dict[str, ET.Element] = {}
    urdf_joints: dict[str, ET.Element] = {}
    if urdf_path:
        try:
            urdf_root = ET.fromstring(Path(urdf_path).read_text(encoding="utf-8"))
            urdf_links, urdf_joints = parse_urdf(urdf_root)
            report.facts["대조한 URDF"] = str(urdf_path)
            urdf_name = urdf_root.get("name") or ""
            if name and urdf_name and name != urdf_name:
                report.fail("srdf-name", f"SRDF 의 robot name({name}) 이 URDF({urdf_name}) 와 다르다 — MoveIt 이 못 붙인다.")
        except (OSError, ET.ParseError) as error:
            report.unverified("srdf-cross", f"URDF 를 읽지 못해 교차 검증을 건너뛴다: {error}")
    else:
        report.unverified(
            "srdf-cross",
            "URDF 를 주지 않아 교차 검증을 못 했다 — 존재하지 않는 링크를 가리키는 그룹이 있어도 여기서는 안 잡힌다. "
            "`--urdf <경로>` 로 같이 주라.",
        )

    if not urdf_links:
        return

    # ── 그룹이 실재하는 것을 가리키는가 ───────────────────────────────────────
    for group_name, group in groups.items():
        for child in group:
            if child.tag == "link":
                _require(report, "srdf-group-link", child.get("name"), urdf_links, f"그룹 {group_name} 의 링크")
            elif child.tag == "joint":
                _require(report, "srdf-group-joint", child.get("name"), urdf_joints, f"그룹 {group_name} 의 조인트")
            elif child.tag == "chain":
                for role in ("base_link", "tip_link"):
                    _require(report, "srdf-chain", child.get(role), urdf_links, f"그룹 {group_name} 의 {role}")
            elif child.tag == "group":
                if child.get("name") not in groups:
                    report.fail("srdf-subgroup", f"그룹 {group_name} 이 없는 하위 그룹을 가리킨다: {child.get('name')}")

    # ── 그룹 상태가 한계 안인가 ───────────────────────────────────────────────
    for state in states:
        state_name = state.get("name") or "(이름 없음)"
        group_name = state.get("group") or ""
        if group_name and group_name not in groups:
            report.fail("srdf-state-group", f"그룹 상태 {state_name} 이 없는 그룹을 가리킨다: {group_name}")
        for entry in state.findall("joint"):
            joint_name = entry.get("name") or ""
            value = _float(entry.get("value"))
            joint = urdf_joints.get(joint_name)
            if joint is None:
                report.fail("srdf-state-joint", f"그룹 상태 {state_name} 이 없는 조인트를 가리킨다: {joint_name}")
                continue
            if value is None:
                continue
            kind = joint.get("type") or ""
            if kind == "revolute" and abs(value) > RADIAN_SUSPICION:
                report.fail(
                    "srdf-degrees",
                    f"그룹 상태 {state_name} 의 {joint_name} 값이 {value:g} 다 — 라디안이라면 {value / math.pi:.1f}π 회전이다. "
                    "도(degree)를 넣었을 가능성이 높다.",
                )
                continue
            limit = joint.find("limit")
            lower, upper = (_float(limit.get("lower")), _float(limit.get("upper"))) if limit is not None else (None, None)
            if kind in BOUNDED_JOINTS and lower is not None and upper is not None and not (lower <= value <= upper):
                report.fail(
                    "srdf-state-limit",
                    f"그룹 상태 {state_name} 의 {joint_name}={value:g} 가 URDF 한계 [{lower:g}, {upper:g}] 밖이다.",
                )

    # ── 엔드이펙터 ────────────────────────────────────────────────────────────
    for effector in effectors:
        effector_name = effector.get("name") or "(이름 없음)"
        if effector.get("group") and effector.get("group") not in groups:
            report.fail("srdf-ee-group", f"엔드이펙터 {effector_name} 이 없는 그룹을 가리킨다: {effector.get('group')}")
        _require(report, "srdf-ee-link", effector.get("parent_link"), urdf_links, f"엔드이펙터 {effector_name} 의 parent_link")

    # ── 비활성 충돌쌍 ─────────────────────────────────────────────────────────
    unknown_pairs = 0
    for pair in disabled:
        for role in ("link1", "link2"):
            if pair.get(role) and pair.get(role) not in urdf_links:
                unknown_pairs += 1
    if unknown_pairs:
        report.fail("srdf-collision-link", f"비활성 충돌쌍이 없는 링크를 {unknown_pairs}번 가리킨다.")

    possible = len(urdf_links) * (len(urdf_links) - 1) // 2
    if possible and len(disabled) / possible > 0.9:
        report.fail(
            "srdf-collision-broad",
            f"비활성 충돌쌍이 가능한 조합의 {len(disabled) / possible:.0%} 다 — 충돌 검사를 사실상 끈 것이다. "
            "이것은 안전 문제이고, 증거(인접성·샘플링 결과) 없이 넓히지 않는다.",
        )
    elif disabled:
        report.ok("srdf-collision", f"비활성 충돌쌍 {len(disabled)}개 — 가능한 조합의 {len(disabled) / max(possible, 1):.0%}.")

    if not [check for check in report.checks if check.level == "fail"]:
        report.ok("srdf-cross", f"URDF 와 교차 검증했다 — 그룹 {len(groups)}개가 실재하는 링크·조인트를 가리킨다.")


def _require(report: Report, rule: str, value: str | None, universe: dict[str, ET.Element], label: str) -> None:
    if value and value not in universe:
        report.fail(rule, f"{label} 이 URDF 에 없다: {value}")


# ─────────────────────────────────────────────────────────────────────────────
# SDF
# ─────────────────────────────────────────────────────────────────────────────


def _check_sdf(report: Report, root: ET.Element) -> None:
    if root.tag != "sdf":
        report.fail("sdf-root", f"루트가 <sdf> 가 아니다: <{root.tag}>")
        return
    version = root.get("version") or ""
    report.facts["SDFormat"] = version or "(없음)"
    if not version:
        report.fail("sdf-version", "<sdf> 에 version 이 없다 — 파서가 스키마를 못 고른다.")

    worlds = root.findall("world")
    models = root.findall("model")
    report.facts["월드 / 모델"] = f"{len(worlds)} / {len(models)}"
    if not worlds and not models:
        report.fail("sdf-empty", "<world> 도 <model> 도 없다.")
        return
    report.facts["문서 종류"] = "월드 수준" if worlds else "모델 수준"

    for model in list(models) + [item for world in worlds for item in world.findall("model")]:
        _check_sdf_model(report, model)

    for uri in root.iter("uri"):
        value = (uri.text or "").strip()
        if value and not value.startswith(("model://", "package://", "file://", "http")):
            if not Path(value).expanduser().exists():
                report.fail("sdf-uri", f"디스크에 없는 리소스를 가리킨다: {value}")


def _check_sdf_model(report: Report, model: ET.Element) -> None:
    name = model.get("name") or "(이름 없음)"
    links = {element.get("name", "") for element in model.findall("link") if element.get("name")}
    joints = model.findall("joint")
    if not links:
        report.fail("sdf-model", f"모델 {name} 에 링크가 없다.")
        return
    for joint in joints:
        joint_name = joint.get("name") or "(이름 없음)"
        for role in ("parent", "child"):
            element = joint.find(role)
            value = (element.text or "").strip() if element is not None else ""
            if not value:
                report.fail("sdf-joint", f"모델 {name} 의 조인트 {joint_name} 에 <{role}> 이 없다.")
            elif value not in links and value != "world":
                report.fail("sdf-joint", f"모델 {name} 의 조인트 {joint_name} 이 없는 링크를 가리킨다: {value}")
    static = model.find("static")
    is_static = (static.text or "").strip().lower() in ("1", "true") if static is not None else False
    massless = [
        element.get("name", "")
        for element in model.findall("link")
        if element.find("inertial") is None
    ]
    if massless and not is_static:
        report.unverified(
            "sdf-inertial",
            f"모델 {name} 에서 <inertial> 없는 링크가 {len(massless)}개다 — 시뮬레이터가 기본 관성을 지어낸다.",
        )
    report.ok("sdf-model", f"모델 {name} — 링크 {len(links)}개, 조인트 {len(joints)}개.")


# ─────────────────────────────────────────────────────────────────────────────


def _attr(element: ET.Element | None, name: str) -> str:
    """`find()` 결과에서 속성을 꺼낸다. 자식 없는 Element 가 falsy 인 함정을 여기 한 곳에 가둔다."""
    return (element.get(name) or "") if element is not None else ""


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def _triple(value: str | None) -> tuple[float, float, float] | None:
    if not value:
        return None
    parts = value.replace(",", " ").split()
    if len(parts) != 3:
        return None
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError:
        return None
