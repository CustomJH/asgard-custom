"""프로토콜 하네스 앵커 — 스킬이 들려주는 오라클이 실제로 도는가.

실행: uv run pytest tests/test_thor_protocol.py

이 스킬의 주장은 "하드웨어 없이 검증할 수 있다"이다. 주장은 여기서 실행으로 증명한다 — 스킬이
싣는 스크립트를 그대로 돌리고, 진짜 TCP 소켓으로 왕복시키고, 쪼개진 수신까지 재현한다.
문서에 적힌 자체 테스트가 실제로 안 돌면 그건 문서가 아니라 거짓말이다.

기준점은 우리 구현이 아니라 **공표된 확인값**이다: CRC-16/MODBUS("123456789") = 0x4B37.
자기 인코더로 자기 디코더를 재면 같은 오해가 양쪽에 앉아 있어도 통과한다.
"""

from __future__ import annotations

import importlib.util
import os
import socket
import struct
import subprocess
import sys
import threading
import unittest

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src/asgard/assets/skill_plugins/asgard-thor-bilskirnir/skills/asgard-thor-vimur/scripts/modbus_ref.py",
)


def _load():
    spec = importlib.util.spec_from_file_location("modbus_ref", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mb = _load()


class SelfTestRunsTest(unittest.TestCase):
    def test_the_bundled_selftest_actually_passes(self):
        """스킬이 안내하는 명령을 그대로 돌린다 — 안내문과 실행 결과가 어긋나면 안 된다."""
        proc = subprocess.run([sys.executable, _SCRIPT, "selftest"], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("passed", proc.stdout)
        self.assertNotIn("FAIL", proc.stdout)

    def test_the_published_check_value_grounds_the_implementation(self):
        self.assertEqual(mb.crc16(b"123456789"), 0x4B37)

    def test_selftest_fails_loudly_when_the_checksum_is_wrong(self):
        """게이트가 고장나면 조용히 통과하는 게 아니라 시끄럽게 실패해야 한다."""
        original = mb.crc16
        try:
            mb.crc16 = lambda payload: 0x0000
            self.assertEqual(mb.selftest(), 1)
        finally:
            mb.crc16 = original


class FramingTest(unittest.TestCase):
    def test_rtu_checksum_goes_out_low_byte_first(self):
        """다른 모든 필드와 반대다 — 여기서 뒤집으면 장비는 그냥 침묵한다."""
        frame = mb.rtu_encode(1, b"\x03\x00\x00\x00\x01")
        self.assertEqual(frame[-2:], struct.pack("<H", mb.crc16(frame[:-2])))

    def test_a_single_flipped_bit_is_rejected(self):
        frame = bytearray(mb.rtu_encode(17, b"\x03\x00\x6b\x00\x03"))
        frame[3] ^= 0x01
        with self.assertRaises(mb.FrameError):
            mb.rtu_decode(bytes(frame))

    def test_tcp_carries_no_checksum_but_a_length(self):
        frame = mb.tcp_encode(0x1234, 5, b"\x03\x00\x00\x00\x02")
        self.assertEqual(mb.tcp_decode(frame), (0x1234, 5, b"\x03\x00\x00\x00\x02"))
        with self.assertRaises(mb.FrameError):
            mb.tcp_decode(frame[:-1])  # 길이 필드와 실제가 어긋난다

    def test_protocol_limits_are_refused_not_truncated(self):
        with self.assertRaises(mb.FrameError):
            mb.read_request(0x03, 0, mb.MAX_READ_REGISTERS + 1)
        self.assertEqual(len(mb.read_request(0x01, 0, mb.MAX_READ_COILS)), 5)

    def test_word_order_is_a_setting_not_a_constant(self):
        """규격은 워드 순서를 정하지 않는다 — 상수로 박으면 다른 벤더에서 조용히 틀린다."""
        self.assertNotEqual(mb.decode_u32([1, 0], "big"), mb.decode_u32([1, 0], "little"))

    def test_silent_interval_is_fixed_above_19200(self):
        self.assertEqual(mb.rtu_silent_interval(115200), 0.00175)
        self.assertGreater(mb.rtu_silent_interval(9600), mb.rtu_silent_interval(115200))


class LoopbackTest(unittest.TestCase):
    """실제 소켓으로 왕복시킨다 — 전송을 흉내내는 시험은 전송 결함을 못 잡는다."""

    def setUp(self):
        self.server = mb.serve(0, mb.Device({0: 0x1234, 1: 0x5678}))
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _ask(self, pdu: bytes, transaction: int = 1, chunked: bool = False) -> bytes:
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            frame = mb.tcp_encode(transaction, 1, pdu)
            if chunked:  # 프레임이 두 번에 나뉘어 도착하는 경우 — 실전에서 정상이다
                sock.sendall(frame[:4])
                sock.sendall(frame[4:])
            else:
                sock.sendall(frame)
            head = sock.recv(6)
            length = struct.unpack(">H", head[4:6])[0]
            body = b""
            while len(body) < length:
                body += sock.recv(length - len(body))
            return mb.tcp_decode(head + body)[2]

    def test_a_read_round_trips_over_a_real_socket(self):
        reply = self._ask(mb.read_request(0x03, 0, 2))
        self.assertEqual(mb.bytes_to_registers(reply[2:]), [0x1234, 0x5678])

    def test_a_frame_split_across_two_sends_is_reassembled(self):
        reply = self._ask(mb.read_request(0x03, 0, 2), chunked=True)
        self.assertEqual(mb.bytes_to_registers(reply[2:]), [0x1234, 0x5678])

    def test_an_illegal_address_returns_an_exception_not_a_default(self):
        reply = self._ask(mb.read_request(0x03, 900, 1))
        self.assertTrue(mb.is_exception(reply), reply.hex())
        self.assertEqual(reply[1], mb.ILLEGAL_DATA_ADDRESS)

    def test_a_write_echoes_the_request_and_takes_effect(self):
        echo = self._ask(struct.pack(">BHH", 0x06, 0, 0x00FF))
        self.assertEqual(echo, struct.pack(">BHH", 0x06, 0, 0x00FF))
        self.assertEqual(mb.bytes_to_registers(self._ask(mb.read_request(0x03, 0, 1))[2:]), [0x00FF])


class SkillWiringTest(unittest.TestCase):
    def test_the_skill_is_registered_and_points_at_a_script_that_exists(self):
        import json

        path = os.path.join(os.path.dirname(_SCRIPT), "..", "..", "..", "plugin.json")
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertIn("asgard-thor-vimur", manifest["skills"])
        self.assertTrue(os.path.isfile(_SCRIPT))


if __name__ == "__main__":
    unittest.main()
