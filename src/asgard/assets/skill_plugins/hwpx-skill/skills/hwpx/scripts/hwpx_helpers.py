#!/usr/bin/env python3
"""
HWPX 문서 생성 헬퍼 함수 라이브러리.

government 템플릿 기반의 표지 배너, 섹션 바, 본문, 이미지 등
검증된 빌드 패턴을 재사용 가능한 함수로 제공한다.

사용법:
    from hwpx_helpers import *
    # 또는
    exec(open("${CLAUDE_SKILL_DIR}/scripts/hwpx_helpers.py").read())
"""

import os
import re
import zipfile

# --- 네임스페이스 선언 (section0.xml 루트에 사용) ---
NS_DECL = (
    'xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
    'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" '
    'xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
    'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:opf="http://www.idpf.org/2007/opf/" '
    'xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" '
    'xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" '
    'xmlns:epub="http://www.idpf.org/2007/ops" '
    'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"'
)

# --- ID 카운터 ---
_id_counter = 0


def next_id():
    """문서 내 고유 ID 생성."""
    global _id_counter
    _id_counter += 1
    return str(_id_counter)


def reset_id(start=0):
    """ID 카운터 리셋."""
    global _id_counter
    _id_counter = start


def xml_escape(text):
    """XML 특수문자 이스케이프."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


# --- header.xml 검증 ---
def validate_header_for_government(header_path):
    """government 템플릿 header.xml인지 검증.
    charPr 81/82/83/144, borderFill 8~15를 사용하려면
    반드시 government header (335KB, 160+ charPr)가 필요하다.
    기본 header (60KB, 11 charPr)를 쓰면 서식이 깨진다.
    """
    import os
    size = os.path.getsize(header_path)
    if size < 100000:  # government header는 335KB
        raise ValueError(
            f"⚠️ header.xml이 너무 작습니다 ({size:,} bytes).\n"
            f"government 템플릿의 컬러 배너/섹션 바를 사용하려면\n"
            f"government header.xml (335KB)을 사용해야 합니다.\n"
            f"올바른 경로: $SKILL_DIR/templates/government/header.xml\n"
            f"현재 경로: {header_path}"
        )
    # charPr 개수 확인
    with open(header_path, "r", encoding="utf-8") as f:
        content = f.read(500)
    m = re.search(r'charProperties\s+itemCnt="(\d+)"', content)
    if m and int(m.group(1)) < 145:
        raise ValueError(
            f"⚠️ header.xml의 charPr가 {m.group(1)}개뿐입니다.\n"
            f"government 템플릿은 160+ charPr가 필요합니다 (charPr 144 사용).\n"
            f"올바른 header: $SKILL_DIR/templates/government/header.xml"
        )


# --- secPr 추출 ---
def extract_secpr_and_colpr(hwpx_path):
    """레퍼런스 HWPX에서 secPr + colPr 블록 추출."""
    with zipfile.ZipFile(hwpx_path, "r") as z:
        data = z.read("Contents/section0.xml").decode("utf-8")
    m = re.search(r"<hp:secPr.*?</hp:secPr>", data, re.DOTALL)
    secpr = m.group() if m else ""
    end = m.end() if m else 0
    ctrl_m = re.search(r"<hp:ctrl>.*?</hp:ctrl>", data[end:end + 500], re.DOTALL)
    colpr = ctrl_m.group() if ctrl_m else ""
    return secpr, colpr


# --- 기본 문단 생성 ---
def make_first_para(secpr, colpr, charpr="25", parapr="40"):
    """첫 문단 (secPr + colPr 포함, 필수)."""
    p_id = next_id()
    return (
        f'<hp:p id="{p_id}" paraPrIDRef="{parapr}" styleIDRef="0" '
        f'pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{charpr}">'
        f'{secpr}{colpr}'
        f'</hp:run></hp:p>'
    )


def make_empty_line(charpr="41", parapr="18"):
    """빈 줄."""
    p_id = next_id()
    return (
        f'<hp:p id="{p_id}" paraPrIDRef="{parapr}" styleIDRef="0" '
        f'pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{charpr}"><hp:t/></hp:run></hp:p>'
    )


def make_page_break(charpr="41", parapr="18"):
    """강제 페이지 넘김."""
    p_id = next_id()
    return (
        f'<hp:p id="{p_id}" paraPrIDRef="{parapr}" styleIDRef="0" '
        f'pageBreak="1" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{charpr}"><hp:t/></hp:run></hp:p>'
    )


def make_text_para(text, charpr, parapr):
    """텍스트 문단."""
    p_id = next_id()
    return (
        f'<hp:p id="{p_id}" paraPrIDRef="{parapr}" styleIDRef="0" '
        f'pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{charpr}"><hp:t>{xml_escape(text)}</hp:t></hp:run></hp:p>'
    )


def make_body_para(marker, text, marker_charpr="18", text_charpr="38", parapr="4"):
    """본문 문단: 볼드 마커 + 일반 내용. (예: "가. 내용텍스트")"""
    p_id = next_id()
    return (
        f'<hp:p id="{p_id}" paraPrIDRef="{parapr}" styleIDRef="0" '
        f'pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{marker_charpr}"><hp:t>{xml_escape(f"  {marker} ")}</hp:t></hp:run>'
        f'<hp:run charPrIDRef="{text_charpr}"><hp:t>{xml_escape(text)}</hp:t></hp:run></hp:p>'
    )


# --- 표지 배너 (3×2 컬러 테이블) ---
def make_cover_banner(title_text, title_charpr="144", title_parapr="20",
                      bf_top=("10", "8"), bf_bottom=("9", "11"), bf_title="15"):
    """
    표지 배너: 3행 2열 테이블.
    1행: 컬러 바 (좌: bf_top[0], 우: bf_top[1])
    2행: 제목 (colspan=2, bf=bf_title)
    3행: 컬러 바 (좌: bf_bottom[0], 우: bf_bottom[1])
    """
    table_width = 47624
    half_width = 23812
    thin_h = 382
    title_h = 7410
    total_h = thin_h + title_h + thin_h

    tbl_id = next_id()
    p_id = next_id()

    def thin_cell(col, row, bf, w):
        cid = next_id()
        return (
            f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="1" borderFillIDRef="{bf}">'
            f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
            f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
            f'<hp:p paraPrIDRef="2" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0" id="{cid}">'
            f'<hp:run charPrIDRef="42"><hp:t/></hp:run></hp:p>'
            f'</hp:subList>'
            f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
            f'<hp:cellSpan colSpan="1" rowSpan="1"/>'
            f'<hp:cellSz width="{w}" height="{thin_h}"/>'
            f'<hp:cellMargin left="0" right="0" top="0" bottom="0"/></hp:tc>'
        )

    title_cid = next_id()
    title_cell = (
        f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="1" borderFillIDRef="{bf_title}">'
        f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
        f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        f'<hp:p paraPrIDRef="{title_parapr}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0" id="{title_cid}">'
        f'<hp:run charPrIDRef="{title_charpr}"><hp:t>{xml_escape(title_text)}</hp:t></hp:run></hp:p>'
        f'</hp:subList>'
        f'<hp:cellAddr colAddr="0" rowAddr="1"/>'
        f'<hp:cellSpan colSpan="2" rowSpan="1"/>'
        f'<hp:cellSz width="{table_width}" height="{title_h}"/>'
        f'<hp:cellMargin left="283" right="283" top="141" bottom="141"/></hp:tc>'
    )

    return (
        f'<hp:p id="{p_id}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="0">'
        f'<hp:tbl id="{tbl_id}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
        f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="0" '
        f'rowCnt="3" colCnt="2" cellSpacing="0" borderFillIDRef="4" noAdjust="0">'
        f'<hp:sz width="{table_width}" widthRelTo="ABSOLUTE" height="{total_h}" heightRelTo="ABSOLUTE" protect="0"/>'
        f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
        f'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" '
        f'vertOffset="0" horzOffset="0"/>'
        f'<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        f'<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
        f'<hp:tr>{thin_cell(0, 0, bf_top[0], half_width)}{thin_cell(1, 0, bf_top[1], half_width)}</hp:tr>'
        f'<hp:tr>{title_cell}</hp:tr>'
        f'<hp:tr>{thin_cell(0, 2, bf_bottom[0], half_width)}{thin_cell(1, 2, bf_bottom[1], half_width)}</hp:tr>'
        f'</hp:tbl></hp:run></hp:p>'
    )


# --- 섹션 바 (1×3 컬러 테이블) ---
def make_section_bar(number, title, num_charpr="81", gap_charpr="82", title_charpr="83",
                     bf_num="14", bf_gap="13", bf_title="12"):
    """
    섹션 바: 1행 3열.
    Cell 0: 번호 (파랑), Cell 1: 간격 (회색), Cell 2: 제목 (하늘색)
    """
    # 제목 길이에 따라 Cell 2 너비 계산
    korean = sum(1 for ch in title if ord(ch) > 0x7F)
    ascii_c = len(title) - korean
    cell2_width = korean * 2200 + ascii_c * 1100 + 4000

    cell0_width = 3422
    cell1_width = 565
    table_width = cell0_width + cell1_width + cell2_width

    p_id = next_id()
    tbl_id = next_id()
    p0_id = next_id()
    p1_id = next_id()
    p2_id = next_id()

    return (
        f'<hp:p id="{p_id}" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="0">'
        f'<hp:tbl id="{tbl_id}" zOrder="0" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" '
        f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="CELL" repeatHeader="0" '
        f'rowCnt="1" colCnt="3" cellSpacing="0" borderFillIDRef="4" noAdjust="0">'
        f'<hp:sz width="{table_width}" widthRelTo="ABSOLUTE" height="3027" heightRelTo="ABSOLUTE" protect="0"/>'
        f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
        f'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" '
        f'horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
        f'<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        f'<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
        f'<hp:tr>'
        # Cell 0: 번호
        f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="1" borderFillIDRef="{bf_num}">'
        f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
        f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        f'<hp:p paraPrIDRef="21" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0" id="{p0_id}">'
        f'<hp:run charPrIDRef="{num_charpr}"><hp:t>{xml_escape(number)}</hp:t></hp:run></hp:p>'
        f'</hp:subList>'
        f'<hp:cellAddr colAddr="0" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
        f'<hp:cellSz width="{cell0_width}" height="3027"/>'
        f'<hp:cellMargin left="141" right="141" top="141" bottom="141"/></hp:tc>'
        # Cell 1: 간격
        f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="1" borderFillIDRef="{bf_gap}">'
        f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
        f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        f'<hp:p paraPrIDRef="2" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0" id="{p1_id}">'
        f'<hp:run charPrIDRef="{gap_charpr}"><hp:t/></hp:run></hp:p>'
        f'</hp:subList>'
        f'<hp:cellAddr colAddr="1" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
        f'<hp:cellSz width="{cell1_width}" height="3027"/>'
        f'<hp:cellMargin left="141" right="141" top="141" bottom="141"/></hp:tc>'
        # Cell 2: 제목
        f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="1" borderFillIDRef="{bf_title}">'
        f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" '
        f'linkListIDRef="0" linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
        f'<hp:p paraPrIDRef="2" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0" id="{p2_id}">'
        f'<hp:run charPrIDRef="{title_charpr}"><hp:t> {xml_escape(title)}</hp:t></hp:run></hp:p>'
        f'</hp:subList>'
        f'<hp:cellAddr colAddr="2" rowAddr="0"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
        f'<hp:cellSz width="{cell2_width}" height="3027"/>'
        f'<hp:cellMargin left="141" right="141" top="141" bottom="141"/></hp:tc>'
        f'</hp:tr></hp:tbl></hp:run></hp:p>'
    )


# --- 이미지 문단 ---
def make_image_para(binary_item_id, width=40000, height=22500, parapr="19"):
    """
    이미지 문단. 전체 hp:pic 필수 구조 포함.
    width, height: HWPUNIT 단위 (기본 16:9 = 40000×22500).
    """
    p_id = next_id()
    pic_id = next_id()
    inst_id = next_id()
    cx, cy = width // 2, height // 2
    return (
        f'<hp:p id="{p_id}" paraPrIDRef="{parapr}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="0">'
        f'<hp:pic id="{pic_id}" zOrder="0" numberingType="PICTURE" '
        f'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" '
        f'href="" groupLevel="0" instid="{inst_id}" reverse="0">'
        f'<hp:offset x="0" y="0"/>'
        f'<hp:orgSz width="{width}" height="{height}"/>'
        f'<hp:curSz width="{width}" height="{height}"/>'
        f'<hp:flip horizontal="0" vertical="0"/>'
        f'<hp:rotationInfo angle="0" centerX="{cx}" centerY="{cy}" rotateimage="0"/>'
        f'<hp:renderingInfo>'
        f'<hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        f'<hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        f'<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        f'</hp:renderingInfo>'
        f'<hc:img binaryItemIDRef="{binary_item_id}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
        f'<hp:imgRect>'
        f'<hc:pt0 x="0" y="0"/><hc:pt1 x="{width}" y="0"/>'
        f'<hc:pt2 x="{width}" y="{height}"/><hc:pt3 x="0" y="{height}"/>'
        f'</hp:imgRect>'
        f'<hp:imgClip left="0" right="{width}" top="0" bottom="{height}"/>'
        f'<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
        f'<hp:imgDim dimwidth="{width}" dimheight="{height}"/>'
        f'<hp:effects/>'
        f'<hp:sz width="{width}" widthRelTo="ABSOLUTE" height="{height}" heightRelTo="ABSOLUTE" protect="0"/>'
        f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
        f'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="CENTER" '
        f'vertOffset="0" horzOffset="0"/>'
        f'<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        f'</hp:pic><hp:t/></hp:run></hp:p>'
    )


# --- 표지 페이지 어셈블리 ---
def make_cover_page(title, subtitle="", date="", subtitle_charpr="62", subtitle_parapr="52",
                    date_charpr="60", date_parapr="1"):
    """표지 페이지 전체 생성: 빈줄 + 배너 + 부제 + 날짜 + pageBreak."""
    parts = []
    for _ in range(6):
        parts.append(make_empty_line())
    parts.append(make_cover_banner(title))
    if subtitle:
        parts.append(make_empty_line())
        parts.append(make_text_para(subtitle, charpr=subtitle_charpr, parapr=subtitle_parapr))
    for _ in range(8):
        parts.append(make_empty_line())
    if date:
        parts.append(make_text_para(date, charpr=date_charpr, parapr=date_parapr))
    for _ in range(4):
        parts.append(make_empty_line())
    parts.append(make_page_break())
    return parts


# --- 이미지 ZIP 추가 ---
def add_images_to_hwpx(hwpx_path, images):
    """images: [{"file": "photo.jpg", "id": "img1", "src_path": "/abs/path"}]"""
    tmp = str(hwpx_path) + ".img_tmp"
    with zipfile.ZipFile(hwpx_path, "r") as zin:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "mimetype":
                    zout.writestr(item, data, compress_type=zipfile.ZIP_STORED)
                else:
                    zout.writestr(item, data)
            for img in images:
                zout.write(img["src_path"], f"BinData/{img['file']}")
    os.replace(tmp, str(hwpx_path))


def update_content_hpf(hwpx_path, images):
    """content.hpf에 이미지 항목 등록."""
    tmp = str(hwpx_path) + ".hpf_tmp"
    with zipfile.ZipFile(hwpx_path, "r") as zin:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "Contents/content.hpf":
                    text = data.decode("utf-8")
                    items = ""
                    for img in images:
                        ext = img["file"].rsplit(".", 1)[-1].lower()
                        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                                "png": "image/png", "bmp": "image/bmp"}[ext]
                        items += (f'<opf:item id="{img["id"]}" '
                                  f'href="BinData/{img["file"]}" '
                                  f'media-type="{mime}" isEmbeded="1"/>')
                    text = text.replace("</opf:manifest>", items + "</opf:manifest>")
                    data = text.encode("utf-8")
                if item.filename == "mimetype":
                    zout.writestr(item, data, compress_type=zipfile.ZIP_STORED)
                else:
                    zout.writestr(item, data)
    os.replace(tmp, str(hwpx_path))
