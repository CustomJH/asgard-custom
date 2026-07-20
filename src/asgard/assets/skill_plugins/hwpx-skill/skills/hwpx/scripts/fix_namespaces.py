#!/usr/bin/env python3
"""
HWPX 네임스페이스 후처리 유틸리티

python-hwpx가 생성한 HWPX 파일의 XML 네임스페이스 프리픽스를
한컴오피스 표준 프리픽스로 교체한다.

이 스크립트를 실행하지 않으면 한글 Viewer(특히 macOS)에서
문서가 빈 페이지로 표시될 수 있다.

사용법:
  CLI:    python fix_namespaces.py <file.hwpx>
  Import: exec(open("fix_namespaces.py").read())
          fix_hwpx_namespaces("output.hwpx")
"""

import zipfile
import os
import re
import sys


def _fix_item_counts(header_xml):
    """header.xml의 itemCnt 속성을 실제 자식 요소 수와 일치시킨다.

    charPr, borderFill 등을 추가/삭제한 뒤 itemCnt가 불일치하면
    한컴 뷰어가 추가된 스타일을 무시하므로 반드시 보정해야 한다.
    """
    count_map = {
        "charProperties": r"<hh:charPr ",
        "borderFills": r"<hh:borderFill ",
        "paraProperties": r"<hh:paraPr ",
        "styles": r"<hh:style ",
    }
    for container, child_re in count_map.items():
        actual = len(re.findall(child_re, header_xml))
        if actual > 0:
            header_xml = re.sub(
                rf"(<hh:{container}\s+itemCnt=\")\d+(\")",
                rf"\g<1>{actual}\2",
                header_xml,
            )
    return header_xml


def fix_hwpx_namespaces(hwpx_path):
    """
    HWPX 파일의 ns0:/ns1: 등 자동 생성 프리픽스를
    한컴오피스 표준 프리픽스(hh/hc/hp/hs)로 교체한다.

    Args:
        hwpx_path: 수정할 .hwpx 파일 경로
    """
    NS_MAP = {
        "http://www.hancom.co.kr/hwpml/2011/head": "hh",
        "http://www.hancom.co.kr/hwpml/2011/core": "hc",
        "http://www.hancom.co.kr/hwpml/2011/paragraph": "hp",
        "http://www.hancom.co.kr/hwpml/2011/section": "hs",
    }

    tmp_path = hwpx_path + ".tmp"

    with zipfile.ZipFile(hwpx_path, "r") as zin:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)

                if item.filename.startswith("Contents/") and item.filename.endswith(".xml"):
                    text = data.decode("utf-8")

                    ns_aliases = {}
                    for match in re.finditer(r'xmlns:(ns\d+)="([^"]+)"', text):
                        alias, uri = match.group(1), match.group(2)
                        if uri in NS_MAP:
                            ns_aliases[alias] = NS_MAP[uri]

                    for old_prefix, new_prefix in ns_aliases.items():
                        text = text.replace(f"xmlns:{old_prefix}=", f"xmlns:{new_prefix}=")
                        text = text.replace(f"<{old_prefix}:", f"<{new_prefix}:")
                        text = text.replace(f"</{old_prefix}:", f"</{new_prefix}:")

                    # header.xml의 itemCnt 보정 (charPr/borderFill 추가 시 필수)
                    if item.filename == "Contents/header.xml":
                        text = _fix_item_counts(text)

                    data = text.encode("utf-8")

                # mimetype은 반드시 ZIP_STORED로 유지
                if item.filename == "mimetype":
                    zout.writestr(item, data, compress_type=zipfile.ZIP_STORED)
                else:
                    zout.writestr(item, data)

    os.replace(tmp_path, hwpx_path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python fix_namespaces.py <file.hwpx>")
        print("  Fixes namespace prefixes for Hangul Viewer compatibility.")
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"Error: File not found: {path}")
        sys.exit(1)

    fix_hwpx_namespaces(path)
    print(f"Fixed namespaces: {path}")
