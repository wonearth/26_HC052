"""
TI mmWave(AWR6843) 데모 펌웨어가 UART 데이터 포트로 보내는 프레임 파서. 시리얼/하드웨어와 무관한 순수 함수.

!! 아래 형식은 TI mmWave SDK 3.x Out-of-Box 데모 기준으로 문서/기억에 의존한 가정이다.
!! 실물 레이더 로그로 반드시 확인할 것 (tools/radar_probe.py가 헤더 값을 그대로 출력해 준다).

프레임 = [magic 8바이트][헤더 32바이트][TLV ...][패딩]
  헤더(리틀엔디언 uint32 8개): version, totalPacketLen, platform, frameNumber,
                               timeCpuCycles, numDetectedObj, numTLVs, subFrameNumber
  TLV  = [type uint32][length uint32][payload]
  TLV type 1 (감지된 점): 점마다 float32 4개 (x, y, z, velocity)
        x = 좌우(+오른쪽), y = 전방, z = 위, velocity = m/s  ← 접근 방향의 부호는 실물에서 확인
  TLV type 7 (점별 부가정보): 점마다 int16 2개 (snr, noise), 0.1dB 단위
모르는 TLV 타입은 건너뛴다. TLV length가 헤더를 포함하는 펌웨어도 있어서 두 방식을 모두 시도한다.
"""
import math
import struct

MAGIC = b"\x02\x01\x04\x03\x06\x05\x08\x07"
HEADER_BYTES = 40
MAX_FRAME_BYTES = 32768   # 이보다 크다고 적힌 길이는 깨진 것으로 보고 버림
MAX_TLVS = 16
FRAME_ALIGN = 32          # 프레임 끝은 32바이트 배수로 패딩됨

TLV_DETECTED_POINTS = 1
TLV_SIDE_INFO = 7
POINT_BYTES = 16
SIDE_INFO_BYTES = 4


class FrameExtractor:
    """바이트 스트림에서 완전한 프레임을 잘라낸다. 쓰레기 바이트, 쪼개져 들어온 프레임, 가짜 magic에 견딘다."""

    def __init__(self):
        self._buf = bytearray()
        self.dropped_bytes = 0
        self.bad_length_frames = 0

    def add(self, data):
        self._buf += data

    def iter_frames(self):
        """버퍼에서 완전한 프레임을 하나씩 꺼낸다. 제너레이터라서, 꺼낸 프레임이 깨졌을 때
        resync()로 되돌린 데이터가 다음 반복에서 순서대로 다시 처리된다."""
        while True:
            idx = self._buf.find(MAGIC)
            if idx < 0:
                keep = len(MAGIC) - 1  # 끝에 magic이 반쯤 걸쳐 있을 수 있어 남겨둠
                if len(self._buf) > keep:
                    self.dropped_bytes += len(self._buf) - keep
                    del self._buf[:-keep]
                return
            if idx > 0:
                self.dropped_bytes += idx
                del self._buf[:idx]
            if len(self._buf) < HEADER_BYTES:
                return
            total = struct.unpack_from("<I", self._buf, 12)[0]
            if total < HEADER_BYTES or total > MAX_FRAME_BYTES:
                self.bad_length_frames += 1
                del self._buf[:len(MAGIC)]  # 데이터 안에 우연히 들어있던 가짜 magic — 다음 후보를 찾음
                continue
            if len(self._buf) < total:
                return  # 나머지가 더 들어올 때까지 대기
            frame = bytes(self._buf[:total])
            del self._buf[:total]
            yield frame

    def feed(self, data):
        """편의 함수: 데이터를 넣고 지금 꺼낼 수 있는 프레임을 전부 리스트로 돌려준다."""
        self.add(data)
        return list(self.iter_frames())

    def resync(self, raw):
        """해석에 실패한 프레임이면, 맨 앞 magic만 버리고 나머지를 되돌려 그 안에 든 정상 프레임을 다시 찾는다.
        (길이 값이 그럴듯하게 깨졌을 때 뒤따르는 정상 프레임까지 같이 버려지는 것을 막음)"""
        self.bad_length_frames += 1
        self._buf[:0] = raw[len(MAGIC):]


def _decode_points(payload):
    points = []
    for i in range(len(payload) // POINT_BYTES):
        x, y, z, v = struct.unpack_from("<4f", payload, i * POINT_BYTES)
        if not all(math.isfinite(val) for val in (x, y, z, v)):
            continue
        points.append({
            "x": x, "y": y, "z": z, "v": v,
            "range_m": math.sqrt(x * x + y * y + z * z),
            "azimuth_deg": math.degrees(math.atan2(x, y)),
            "snr_db": None,
        })
    return points


def _parse_tlvs(frame, num_tlvs, length_includes_header):
    total = len(frame)
    cursor = HEADER_BYTES
    points, side = [], None
    for _ in range(num_tlvs):
        if cursor + 8 > total:
            return None
        tlv_type, tlv_len = struct.unpack_from("<II", frame, cursor)
        payload_len = tlv_len - 8 if length_includes_header else tlv_len
        if payload_len < 0 or cursor + 8 + payload_len > total:
            return None
        payload = frame[cursor + 8: cursor + 8 + payload_len]
        cursor += 8 + payload_len
        if tlv_type == TLV_DETECTED_POINTS:
            if payload_len % POINT_BYTES:
                return None
            points = _decode_points(payload)
        elif tlv_type == TLV_SIDE_INFO:
            if payload_len % SIDE_INFO_BYTES:
                return None
            side = [struct.unpack_from("<hh", payload, i * SIDE_INFO_BYTES)[0] / 10.0
                    for i in range(payload_len // SIDE_INFO_BYTES)]
    if not 0 <= total - cursor < FRAME_ALIGN:
        return None  # TLV를 다 읽었는데 남는 길이가 패딩 범위를 벗어남 → 길이 해석이 틀렸다는 신호
    if side is not None and len(side) == len(points):
        for point, snr in zip(points, side):
            point["snr_db"] = snr
    return points


def parse_frame(frame):
    """완전한 프레임 하나를 해석. 깨졌으면 None."""
    if len(frame) < HEADER_BYTES or frame[:len(MAGIC)] != MAGIC:
        return None
    version, total, platform, frame_number, cycles, num_obj, num_tlvs, subframe = struct.unpack_from("<8I", frame, 8)
    if total != len(frame) or num_tlvs > MAX_TLVS:
        return None
    for length_includes_header in (False, True):
        points = _parse_tlvs(frame, num_tlvs, length_includes_header)
        if points is not None:
            return {
                "frame_number": frame_number,
                "version": version,
                "platform": platform,
                "num_detected_header": num_obj,
                "num_tlvs": num_tlvs,
                "tlv_length_includes_header": length_includes_header,
                "points": points,
            }
    return None
