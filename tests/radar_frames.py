"""시험 전용: 합성 레이더 프레임 생성기. 실행되는 코드(app.py 등)는 이 파일을 import하지 않는다."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar_parser import MAGIC


def build_frame(points, frame_number=1, side_info=True, length_includes_header=False,
                extra_tlvs=(), version=0x03060000, platform=0xA6843, declared_total=None):
    """points: (x, y, z, v) 목록. TI SDK 3.x Out-of-Box 형식을 흉내낸 바이트열을 만든다."""
    tlvs = [(1, b"".join(struct.pack("<4f", *p) for p in points))]
    if side_info:
        tlvs.append((7, b"".join(struct.pack("<hh", 150 + 10 * i, 40) for i in range(len(points)))))
    tlvs.extend(extra_tlvs)

    body = b""
    for tlv_type, payload in tlvs:
        length = len(payload) + (8 if length_includes_header else 0)
        body += struct.pack("<II", tlv_type, length) + payload

    total = 40 + len(body)
    pad = (-total) % 32
    total += pad
    header = MAGIC + struct.pack(
        "<8I", version, declared_total if declared_total is not None else total,
        platform, frame_number, 123456, len(points), len(tlvs), 0,
    )
    return header + body + b"\x00" * pad
