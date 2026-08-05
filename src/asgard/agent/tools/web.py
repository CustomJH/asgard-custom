"""도구 — 웹 가져오기. 사설 주소를 막고, HTML 을 글로 눌러 상한까지만 돌려준다."""

from __future__ import annotations

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from ._core import _MAX_FETCH_BYTES, _MAX_OUT, ToolError


class _HTMLText(HTMLParser):
    _BLOCKS = frozenset({"article", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "pre", "section", "tr"})
    _SKIP = frozenset({"embed", "iframe", "noscript", "object", "script", "style", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if self.skip or tag in self._SKIP:
            self.skip += 1
        elif tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.skip:
            self.skip -= 1
        elif tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)

    def text(self) -> str:
        lines = (re.sub(r"[ \t]+", " ", line).strip() for line in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line)


def _public_url(raw: str) -> str:
    try:
        parsed = urlsplit(raw.strip())
        port = parsed.port
    except ValueError as exc:
        raise ToolError(f"잘못된 URL: {exc}") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ToolError("web_fetch는 공개 http:// 또는 https:// URL만 지원합니다")
    if parsed.username or parsed.password:
        raise ToolError("URL 사용자정보는 허용하지 않습니다")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ToolError("내부 호스트 URL은 차단됩니다")
    try:
        ipaddress.ip_address(host)
        addresses = {host}
    except ValueError:
        try:
            addresses = {
                item[4][0] for item in socket.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80))
            }
        except OSError as exc:
            raise ToolError(f"URL 호스트를 확인할 수 없습니다: {exc}") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ToolError("사설·루프백·링크로컬·예약 주소는 차단됩니다")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""))


def run_web_fetch(_root: str, tool_input: dict) -> str:
    import httpx

    url = str(tool_input.get("url") or "")
    output_format = str(tool_input.get("format") or "text")
    max_chars = int(tool_input.get("max_chars") or _MAX_OUT)
    if output_format not in {"text", "html"} or not 1 <= max_chars <= _MAX_OUT:
        raise ToolError("format은 text|html, max_chars는 1..30000이어야 합니다")
    headers = {
        "Accept": "text/html, text/plain, application/json, application/xml;q=0.9, */*;q=0.1",
        "User-Agent": "Asgard/1 web_fetch",
    }
    try:
        with httpx.Client(follow_redirects=False, timeout=30, headers=headers) as client:
            for _ in range(6):
                url = _public_url(url)
                with client.stream("GET", url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise ToolError("리다이렉트 대상이 없습니다")
                        url = urljoin(url, location)
                        continue
                    response.raise_for_status()
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > _MAX_FETCH_BYTES:
                            raise ToolError("응답이 5 MiB 안전 상한을 초과합니다")
                        chunks.append(chunk)
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if content_type and not (
                        content_type.startswith("text/")
                        or content_type
                        in {"application/json", "application/ld+json", "application/xml", "application/xhtml+xml"}
                    ):
                        raise ToolError(f"텍스트가 아닌 응답입니다: {content_type}")
                    body = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                    if output_format == "text" and ("html" in content_type or "<html" in body[:500].lower()):
                        parser = _HTMLText()
                        parser.feed(body)
                        body = parser.text()
                    shown = urlunsplit((*urlsplit(url)[:3], "", ""))
                    suffix = "" if len(body) <= max_chars else f"\n[... {len(body) - max_chars} chars 절단]"
                    return f"[{response.status_code} {content_type or 'unknown'} · {shown}]\n{body[:max_chars]}{suffix}"
            raise ToolError("리다이렉트가 5회를 초과했습니다")
    except ToolError:
        raise
    except httpx.HTTPError as exc:
        raise ToolError(f"URL 요청 실패: {exc}") from exc
