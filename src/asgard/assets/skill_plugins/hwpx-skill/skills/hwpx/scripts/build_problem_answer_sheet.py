#!/usr/bin/env python3
"""Build a two-page HWPX problem sheet + answer sheet.

Input JSON shape:
{
  "title": "뜀틀운동",
  "unit": "영상 수업",
  "subtitle": "핵심 내용과 실천 목표",
  "subject": "국어",
  "main_actor": "학생",
  "scenes": [{"title": "...", "summary": "..."}],
  "change": "예시 답안 문장",
  "theme": "예시 답안 문장",
  "activity2_problem": ["문제 문장", "..."],
  "activity2_answer": ["답안 문장", "..."],
  "activity3_problem": "서술형 문제",
  "activity3_answer": "예시 답안"
}
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from lxml import etree

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REFERENCE_HWPX = SKILL_DIR / "assets" / "problem-answer-reference.hwpx"

sys.path.insert(0, str(SCRIPT_DIR))
from hwpx_helpers import (  # noqa: E402
    NS_DECL,
    extract_secpr_and_colpr,
    make_first_para,
    make_page_break,
    make_text_para,
    next_id,
    reset_id,
    xml_escape,
)


def pack_hwpx(work: Path, output: Path) -> None:
    with ZipFile(output, "w", ZIP_DEFLATED) as zf:
        zf.write(work / "mimetype", "mimetype", compress_type=ZIP_STORED)
        for path in sorted(p for p in work.rglob("*") if p.is_file()):
            rel = path.relative_to(work).as_posix()
            if rel == "mimetype":
                continue
            zf.write(path, rel, compress_type=ZIP_DEFLATED)


def cell_xml(text: str, col: int, row: int, width: int, height: int, charpr="14", parapr="21", bf="2") -> str:
    lines = text.split("\n") if text else [""]
    paragraphs = []
    for line in lines:
        pid = next_id()
        paragraphs.append(
            f'<hp:p paraPrIDRef="{parapr}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0" id="{pid}">'
            f'<hp:run charPrIDRef="{charpr}"><hp:t>{xml_escape(line)}</hp:t></hp:run></hp:p>'
        )
    return (
        f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="1" borderFillIDRef="{bf}">'
        '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
        'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        + "".join(paragraphs)
        + "</hp:subList>"
        f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
        f'<hp:cellSz width="{width}" height="{height}"/>'
        '<hp:cellMargin left="510" right="510" top="141" bottom="141"/></hp:tc>'
    )


def make_header_table(label: str, subject: str, unit: str, title: str, subtitle: str) -> str:
    widths = [5312, 34461, 13519]
    height = 5810
    table_width = sum(widths)
    tbl_id = next_id()
    p_id = next_id()
    middle = f"{unit}\n{title}"
    if subtitle:
        middle += f"\n{subtitle}"
    cells = [subject, middle, f"{label}\n학년   반 (    )번\n이름 : (          )"]
    xml = [
        f'<hp:p id="{p_id}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">',
        '<hp:run charPrIDRef="0">',
        f'<hp:tbl id="{tbl_id}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
        f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="0" '
        f'rowCnt="1" colCnt="3" cellSpacing="0" borderFillIDRef="2" noAdjust="0">',
        f'<hp:sz width="{table_width}" widthRelTo="ABSOLUTE" height="{height}" heightRelTo="ABSOLUTE" protect="0"/>',
        '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
        'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" '
        'vertOffset="0" horzOffset="0"/>',
        '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:inMargin left="0" right="0" top="0" bottom="0"/>',
        "<hp:tr>",
    ]
    for idx, text in enumerate(cells):
        charpr = "8" if idx != 1 else "11"
        parapr = "20" if idx != 2 else "1"
        xml.append(cell_xml(text, idx, 0, widths[idx], height, charpr=charpr, parapr=parapr))
    xml.append("</hp:tr></hp:tbl></hp:run></hp:p>")
    return "".join(xml)


def make_one_col_table(rows: list[str], row_h: int, charpr="14", parapr="21") -> str:
    width = 53294
    tbl_id = next_id()
    p_id = next_id()
    total_h = row_h * len(rows)
    xml = [
        f'<hp:p id="{p_id}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">',
        '<hp:run charPrIDRef="0">',
        f'<hp:tbl id="{tbl_id}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
        f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="0" '
        f'rowCnt="{len(rows)}" colCnt="1" cellSpacing="0" borderFillIDRef="2" noAdjust="0">',
        f'<hp:sz width="{width}" widthRelTo="ABSOLUTE" height="{total_h}" heightRelTo="ABSOLUTE" protect="0"/>',
        '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
        'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" '
        'vertOffset="0" horzOffset="0"/>',
        '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:inMargin left="0" right="0" top="0" bottom="0"/>',
    ]
    for idx, text in enumerate(rows):
        xml.append("<hp:tr>")
        xml.append(cell_xml(text, 0, idx, width, row_h, charpr=charpr, parapr=parapr))
        xml.append("</hp:tr>")
    xml.append("</hp:tbl></hp:run></hp:p>")
    return "".join(xml)


def prompt(text: str) -> str:
    return make_text_para(f"▶ {text}", charpr="9", parapr="0")


def clean_text(value: object) -> str:
    return str(value or "").replace("\\n", "\n")


def clean_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [clean_text(value) for value in values]


def blank_text(text: str, keywords: list[str]) -> str:
    for src in keywords:
        if src and src in text:
            text = text.replace(src, "________", 1)
    return text


def build_problem_answer_sheet(data: dict, output: Path) -> None:
    if not REFERENCE_HWPX.exists():
        raise SystemExit(f"Missing reference template: {REFERENCE_HWPX}")
    reset_id()
    title = clean_text(data.get("title")) or "수업 활동지"
    unit = clean_text(data.get("unit")) or "영상 수업"
    subtitle = clean_text(data.get("subtitle")) or "핵심 내용과 실천 목표"
    subject = clean_text(data.get("subject")) or "국어"
    main_actor = clean_text(data.get("main_actor")) or "학생"
    scenes = data.get("scenes") or []
    if len(scenes) < 3:
        raise SystemExit("Input JSON must include at least 3 scenes.")
    scene_answers = [f"{clean_text(scene['title'])} - {clean_text(scene['summary'])}" for scene in scenes[:9]]
    while len(scene_answers) < 7:
        scene_answers.append("영상의 중요한 내용을 정리한다.")
    keywords = clean_list(data.get("blank_keywords")) or [title, main_actor, "안전", "도움닫기", "발구름", "착지", "순서", "연습", "도전"]
    scene_problems = [blank_text(text, keywords) for text in scene_answers]
    scene_problems.append(clean_text(data.get("summary_question")) or "가장 중요하다고 생각한 핵심 내용을 쓰세요. ______________________________")
    scene_problems.append(clean_text(data.get("theme_question")) or "이 자료에서 배운 점을 한 문장으로 쓰세요. ______________________________")
    scene_answers.append(clean_text(data.get("change")) or "예시 답안을 작성합니다.")
    scene_answers.append(clean_text(data.get("theme")) or "핵심 주제를 한 문장으로 정리합니다.")

    activity2_problem = clean_list(data.get("activity2_problem")) or [
        f"처음의 {main_actor}: 어떤 점을 어려워하거나 조심해야 할까요? ______________________________",
        f"연습 뒤 {main_actor}에게 생긴 변화는 무엇일까요? ______________________________",
        "내가 고른 장면에서 중요한 내용은 무엇인가요? ______________________________",
    ]
    activity2_answer = clean_list(data.get("activity2_answer")) or [
        f"처음의 {main_actor}: 순서와 주의할 점을 확인하며 시작한다.",
        clean_text(data.get("change")) or "연습을 통해 더 자신 있게 참여한다.",
        f"예: {clean_text(scenes[min(2, len(scenes) - 1)]['summary'])}",
    ]
    activity3_problem = clean_text(data.get("activity3_problem")) or "오늘 배운 내용을 바탕으로 나의 실천 목표를 3문장 이상 쓰세요.\n처음: ____________________\n가운데: ____________________\n끝: ____________________"
    activity3_answer = clean_text(data.get("activity3_answer")) or f"나의 목표: {title}에서 배운 내용을 차근차근 실천하겠습니다."

    secpr, colpr = extract_secpr_and_colpr(REFERENCE_HWPX)
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>', f"<hs:sec {NS_DECL}>"]
    parts.append(make_first_para(secpr, colpr))
    parts.append(make_header_table("문제지", subject, unit, title, subtitle))
    parts.append(prompt(clean_text(data.get("activity1_prompt")) or "첫 번째 활동: 자료를 보고 내용을 확인해 봅시다. 빈칸에 알맞은 말을 쓰세요."))
    parts.append(make_one_col_table(scene_problems, 3100, charpr="14", parapr="21"))
    parts.append(prompt(clean_text(data.get("activity2_prompt")) or "두 번째 활동: 중요한 내용과 근거를 정리해 봅시다."))
    parts.append(make_one_col_table(activity2_problem, 4100, charpr="14", parapr="23"))
    parts.append(prompt(clean_text(data.get("activity3_prompt")) or "세 번째 활동: 나의 생각이나 실천 목표를 써 봅시다."))
    parts.append(make_one_col_table([activity3_problem], 4300, charpr="14", parapr="23"))
    parts.append(make_page_break())
    parts.append(make_header_table("답안지", subject, unit, title, subtitle))
    parts.append(prompt("첫 번째 활동 정답"))
    parts.append(make_one_col_table(scene_answers, 3100, charpr="14", parapr="21"))
    parts.append(prompt("두 번째 활동 예시 답안"))
    parts.append(make_one_col_table(activity2_answer, 4100, charpr="14", parapr="23"))
    parts.append(prompt("세 번째 활동 예시 답안"))
    parts.append(make_one_col_table([activity3_answer], 4300, charpr="14", parapr="23"))
    parts.append("</hs:sec>")

    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / "hwpx"
        shutil.copytree(SKILL_DIR / "templates" / "base", work)
        with ZipFile(REFERENCE_HWPX) as rz:
            (work / "Contents" / "header.xml").write_bytes(rz.read("Contents/header.xml"))
        (work / "Contents" / "section0.xml").write_text("\n".join(parts), encoding="utf-8")
        for file in list(work.rglob("*.xml")) + list(work.rglob("*.hpf")):
            etree.parse(str(file))
        pack_hwpx(work, output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    data = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    build_problem_answer_sheet(data, output)
    print(output)


if __name__ == "__main__":
    main()
