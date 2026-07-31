#!/usr/bin/env python3
"""Modbus reference oracle — stdlib only, no hardware, no dependencies.

Two jobs. As a **checker** it tells you whether a byte string is a well-formed frame and what it
means, so an implementation in any language can be validated against something that is not itself.
As a **device** it answers requests over a real TCP socket, so a client under development has
something to talk to before the field device exists.

Why an oracle at all: Modbus failures are silent. A wrong CRC byte order, a register address off by
one, a word order swapped on a 32-bit value — none of these raise. The line just goes quiet, or the
number is wrong in a way that looks like a sensor problem. Testing against your own encoder proves
nothing, because the same misunderstanding sits on both sides.

Usage
    python3 modbus_ref.py selftest            # known-answer vectors; exit 1 on any failure
    python3 modbus_ref.py serve --port 15020  # in-process device simulator (Ctrl-C to stop)
    python3 modbus_ref.py decode 0104020001b8 --transport rtu
"""

from __future__ import annotations

import argparse
import socket
import socketserver
import struct
import sys

MAX_READ_REGISTERS = 125  # 응답 바이트 수 필드가 1바이트라 250바이트가 상한이다
MAX_READ_COILS = 2000
MAX_WRITE_REGISTERS = 123

ILLEGAL_FUNCTION = 0x01
ILLEGAL_DATA_ADDRESS = 0x02
ILLEGAL_DATA_VALUE = 0x03
SERVER_FAILURE = 0x04


class FrameError(Exception):
    """프레임이 규격을 벗어났다. 조용히 넘기지 않는다 — 조용한 실패가 이 프로토콜의 기본 실패다."""


# ── CRC / LRC ──────────────────────────────────────────────────────


def crc16(payload: bytes) -> int:
    """CRC-16/MODBUS. 다항식 0xA001(반사), 초기값 0xFFFF, 최종 XOR 없음.

    검증값: b"123456789" → 0x4B37 (CRC 카탈로그의 표준 확인값). 이 한 줄이 구현 전체를 건다.
    """
    crc = 0xFFFF
    for byte in payload:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def lrc(payload: bytes) -> int:
    """ASCII 전송용 종방향 중복 검사 — 2의 보수."""
    return (-sum(payload)) & 0xFF


# ── RTU 프레이밍 ───────────────────────────────────────────────────


def rtu_encode(unit: int, pdu: bytes) -> bytes:
    """주소 + PDU + CRC. CRC는 **하위 바이트 먼저** 나간다 — 나머지 필드와 반대다."""
    body = bytes([unit]) + pdu
    return body + struct.pack("<H", crc16(body))


def rtu_decode(frame: bytes) -> tuple[int, bytes]:
    if len(frame) < 4:
        raise FrameError(f"RTU 프레임이 너무 짧다 ({len(frame)}바이트) — 주소+기능+CRC 만으로 4바이트다")
    body, tail = frame[:-2], frame[-2:]
    want = struct.pack("<H", crc16(body))
    if tail != want:
        raise FrameError(f"CRC 불일치 — 받은 {tail.hex()} 기대 {want.hex()} (하위 바이트 먼저인지 확인하라)")
    return (body[0], body[1:])


def rtu_silent_interval(baud: int) -> float:
    """프레임 경계는 침묵이다 — 3.5 문자 시간. 19200 초과는 규격이 1.75ms로 고정한다."""
    if baud > 19200:
        return 0.00175
    return 3.5 * 11.0 / baud  # 문자 하나 = 시작1 + 데이터8 + 패리티1 + 정지1 = 11비트


# ── TCP 프레이밍 (MBAP) ────────────────────────────────────────────


def tcp_encode(transaction: int, unit: int, pdu: bytes) -> bytes:
    """MBAP 헤더 + PDU. TCP 에는 CRC가 없다 — 무결성은 아래 계층이 이미 보장한다."""
    return struct.pack(">HHHB", transaction, 0, len(pdu) + 1, unit) + pdu


def tcp_decode(frame: bytes) -> tuple[int, int, bytes]:
    if len(frame) < 8:
        raise FrameError(f"MBAP 헤더가 모자란다 ({len(frame)}바이트) — 헤더만 7바이트다")
    transaction, protocol, length, unit = struct.unpack(">HHHB", frame[:7])
    if protocol != 0:
        raise FrameError(f"프로토콜 식별자가 0이 아니다 ({protocol}) — Modbus가 아니다")
    if length != len(frame) - 6:
        raise FrameError(f"길이 필드 {length}가 실제 {len(frame) - 6}와 다르다 — 스트림을 잘못 잘랐다")
    return (transaction, unit, frame[7:])


# ── PDU ────────────────────────────────────────────────────────────


def read_request(function: int, address: int, count: int) -> bytes:
    """주소는 **0 기반**이다. 문서의 홀딩 레지스터 40001은 여기서 0 이다 — 이 한 칸이 가장 흔한 결함."""
    limit = MAX_READ_COILS if function in (0x01, 0x02) else MAX_READ_REGISTERS
    if not 1 <= count <= limit:
        raise FrameError(f"개수 {count}가 기능 {function:#04x}의 범위(1..{limit})를 벗어난다")
    if not 0 <= address <= 0xFFFF:
        raise FrameError(f"주소 {address}가 16비트를 벗어난다")
    return struct.pack(">BHH", function, address, count)


def exception_pdu(function: int, code: int) -> bytes:
    """예외 응답은 기능 코드의 최상위 비트를 세워서 온다 — 정상 응답과 길이로 구분하면 안 된다."""
    return bytes([function | 0x80, code])


def is_exception(pdu: bytes) -> bool:
    return bool(pdu) and bool(pdu[0] & 0x80)


def registers_to_bytes(values: list[int]) -> bytes:
    return b"".join(struct.pack(">H", v & 0xFFFF) for v in values)


def bytes_to_registers(raw: bytes) -> list[int]:
    if len(raw) % 2:
        raise FrameError(f"레지스터 페이로드가 홀수 바이트다 ({len(raw)}) — 레지스터는 항상 2바이트다")
    return [struct.unpack(">H", raw[i : i + 2])[0] for i in range(0, len(raw), 2)]


def decode_u32(regs: list[int], word_order: str = "big") -> int:
    """32비트 값의 워드 순서는 **규격이 정하지 않는다** — 장비마다 다르므로 설정으로 받아야 한다.

    바이트 순서(빅 엔디언)는 규격이 정하지만 두 레지스터 중 무엇이 상위인가는 정하지 않는다.
    이것을 상수로 박은 코드는 다른 벤더의 장비를 만나는 날 조용히 틀린 값을 낸다.
    """
    if len(regs) != 2:
        raise FrameError(f"32비트 값에는 레지스터 2개가 필요하다 (받은 {len(regs)})")
    high, low = (regs[0], regs[1]) if word_order == "big" else (regs[1], regs[0])
    return (high << 16) | low


# ── 인프로세스 장치 시뮬레이터 ─────────────────────────────────────


class Device:
    """레지스터 표 하나를 가진 최소 서버. 실장비 없이 클라이언트를 끝까지 돌려보기 위한 것."""

    def __init__(self, registers: dict[int, int] | None = None, unit: int = 1) -> None:
        self.registers = dict(registers or {i: i for i in range(64)})
        self.unit = unit

    def apply(self, pdu: bytes) -> bytes:
        if not pdu:
            return exception_pdu(0, SERVER_FAILURE)
        function = pdu[0]
        if function not in (0x03, 0x04, 0x06):
            return exception_pdu(function, ILLEGAL_FUNCTION)
        try:
            return self._dispatch(function, pdu)
        except FrameError:
            return exception_pdu(function, ILLEGAL_DATA_VALUE)

    def _dispatch(self, function: int, pdu: bytes) -> bytes:
        if function == 0x06:
            _, address, value = struct.unpack(">BHH", pdu)
            if address not in self.registers:
                return exception_pdu(function, ILLEGAL_DATA_ADDRESS)
            self.registers[address] = value
            return pdu  # 쓰기 응답은 요청을 그대로 되돌려준다
        _, address, count = struct.unpack(">BHH", pdu)
        if count > MAX_READ_REGISTERS:
            return exception_pdu(function, ILLEGAL_DATA_VALUE)
        wanted = range(address, address + count)
        if any(a not in self.registers for a in wanted):
            return exception_pdu(function, ILLEGAL_DATA_ADDRESS)
        payload = registers_to_bytes([self.registers[a] for a in wanted])
        return bytes([function, len(payload)]) + payload


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        device: Device = self.server.device  # ty: ignore[unresolved-attribute] — serve()가 심는다
        while True:
            head = _recv_exact(self.request, 6)
            if head is None:
                return
            length = struct.unpack(">H", head[4:6])[0]
            rest = _recv_exact(self.request, length)
            if rest is None:
                return
            transaction, unit, pdu = tcp_decode(head + rest)
            if unit not in (device.unit, 0, 0xFF):
                continue  # 다른 장치에게 온 것 — 응답하지 않는 것이 옳다
            self.request.sendall(tcp_encode(transaction, unit, device.apply(pdu)))


def _recv_exact(sock: socket.socket, size: int) -> bytes | None:
    """부분 수신은 정상이다 — TCP는 메시지 경계를 지켜주지 않는다. 한 번 읽고 끝내면 간헐 실패한다."""
    buffer = b""
    while len(buffer) < size:
        chunk = sock.recv(size - len(buffer))
        if not chunk:
            return None
        buffer += chunk
    return buffer


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(port: int, device: Device | None = None, host: str = "127.0.0.1") -> _Server:
    """서버 객체를 돌려준다 — 호출자가 수명을 쥔다(테스트에서 확실히 닫기 위해)."""
    server = _Server((host, port), _Handler)
    server.device = device or Device()  # ty: ignore[unresolved-attribute]
    return server


# ── 자체 테스트 ────────────────────────────────────────────────────


def _checks() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []

    def check(name: str, got: object, want: object) -> None:
        out.append((name, got == want, f"got {got!r} want {want!r}"))

    check("CRC-16/MODBUS 표준 확인값", hex(crc16(b"123456789")), "0x4b37")
    check("CRC는 하위 바이트 먼저 나간다", rtu_encode(1, b"\x03\x00\x00\x00\x01")[-2:].hex(), "840a")
    check("LRC 2의 보수", lrc(b"\x01\x03\x00\x00\x00\x01"), 0xFB)

    frame = rtu_encode(17, b"\x03\x00\x6b\x00\x03")
    check("RTU 왕복", rtu_decode(frame), (17, b"\x03\x00\x6b\x00\x03"))
    corrupted = bytearray(frame)
    corrupted[3] ^= 0x01
    out.append(("CRC가 한 비트 변조를 잡는다", _raises(lambda: rtu_decode(bytes(corrupted))), "예외가 안 났다"))

    tcp = tcp_encode(0x1234, 5, b"\x03\x00\x00\x00\x02")
    check("MBAP 왕복", tcp_decode(tcp), (0x1234, 5, b"\x03\x00\x00\x00\x02"))
    check("MBAP 길이 필드", struct.unpack(">H", tcp[4:6])[0], 6)
    out.append(("길이 필드가 어긋나면 잡는다", _raises(lambda: tcp_decode(tcp[:-1])), "예외가 안 났다"))

    out.append(("레지스터 상한 초과를 거부한다", _raises(lambda: read_request(0x03, 0, 126)), "예외가 안 났다"))
    check("코일 상한은 다르다", len(read_request(0x01, 0, 2000)), 5)

    device = Device({0: 0x1234, 1: 0x5678})
    reply = device.apply(read_request(0x03, 0, 2))
    check("읽기 응답 형태", (reply[0], reply[1]), (0x03, 4))
    check("레지스터 값", bytes_to_registers(reply[2:]), [0x1234, 0x5678])
    check("없는 주소는 예외 응답", device.apply(read_request(0x03, 900, 1)), exception_pdu(0x03, ILLEGAL_DATA_ADDRESS))
    check("모르는 기능은 예외 응답", device.apply(b"\x2b\x00"), exception_pdu(0x2B, ILLEGAL_FUNCTION))
    check("예외는 최상위 비트로 구분한다", is_exception(exception_pdu(0x03, 2)), True)
    check("정상 응답은 예외가 아니다", is_exception(reply), False)

    check("워드 순서 big", decode_u32([0x0001, 0x0000], "big"), 0x00010000)
    check("워드 순서 little", decode_u32([0x0001, 0x0000], "little"), 0x00000001)
    check("t3.5는 19200 초과에서 고정", rtu_silent_interval(115200), 0.00175)
    out.append(("t3.5는 저속에서 보드율을 탄다", rtu_silent_interval(9600) > 0.0035, "9600에서 3.5ms 이하"))
    return out


def _raises(call) -> bool:
    try:
        call()
    except FrameError:
        return True
    return False


def selftest() -> int:
    rows = _checks()
    for name, ok, detail in rows:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  — {detail}"))
    failed = sum(1 for _, ok, _ in rows if not ok)
    print(f"\n{len(rows) - failed}/{len(rows)} passed")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("selftest")
    serve_cmd = sub.add_parser("serve")
    serve_cmd.add_argument("--port", type=int, default=15020)
    decode_cmd = sub.add_parser("decode")
    decode_cmd.add_argument("hex")
    decode_cmd.add_argument("--transport", choices=("rtu", "tcp"), default="rtu")
    args = parser.parse_args(argv)

    if args.command == "selftest":
        return selftest()
    if args.command == "serve":
        server = serve(args.port)
        print(f"modbus device on 127.0.0.1:{args.port} — Ctrl-C to stop")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    raw = bytes.fromhex(args.hex)
    try:
        print(rtu_decode(raw) if args.transport == "rtu" else tcp_decode(raw))
    except FrameError as err:
        print(f"frame error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
