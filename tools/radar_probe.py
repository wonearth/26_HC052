#!/usr/bin/env python3
"""
레이더 브링업 확인 도구 (파이에서 직접 실행하는 개발용 도구 — app.py/서비스와 무관).

  python3 tools/radar_probe.py --cfg radar.cfg --seconds 30 --log radar_log.jsonl

하는 일: 설정을 보내고(--no-cfg로 생략 가능), 프레임을 받아 한 줄씩 요약해서 보여주고,
프레임 전체를 .jsonl로 저장한다. 이 로그가 이후 알고리즘 튜닝(재생 시험)의 실제 데이터가 된다.
처음 실행하면 첫 프레임의 헤더 값(version, TLV 길이 해석 방식)을 출력하니, 파서 가정과 맞는지 확인할 것.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import radar_parser
import radar_reader


def main():
    ap = argparse.ArgumentParser(description="레이더 브링업 확인 도구")
    ap.add_argument("--cli", default=radar_reader.CLI_PORT)
    ap.add_argument("--data", default=radar_reader.DATA_PORT)
    ap.add_argument("--cfg", default=None, help=".cfg 경로 (생략하면 설정 전송 안 함)")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--log", default=None, help="프레임을 저장할 .jsonl 경로")
    args = ap.parse_args()

    import serial
    cli = serial.Serial(args.cli, radar_reader.CLI_BAUD, timeout=0.1)
    data = serial.Serial(args.data, radar_reader.DATA_BAUD, timeout=0.1)
    log_file = open(args.log, "w", encoding="utf-8") if args.log else None
    state = {"first": True, "n": 0}

    def show(parsed):
        if state["first"]:
            state["first"] = False
            print(f"\n[첫 프레임 헤더] version=0x{parsed['version']:08x} platform=0x{parsed['platform']:08x} "
                  f"numTLVs={parsed['num_tlvs']} numObj(헤더)={parsed['num_detected_header']} "
                  f"TLV길이가헤더포함={parsed['tlv_length_includes_header']}\n")
        radar_reader.handle_frame(parsed)
        pts = parsed["points"]
        state["n"] += 1
        if pts:
            nearest = min(pts, key=lambda p: p["range_m"])
            print(f"#{parsed['frame_number']:>6} 점 {len(pts):>3}개 | 가장 가까운 점: "
                  f"거리 {nearest['range_m']:5.2f}m  x={nearest['x']:+5.2f} y={nearest['y']:+5.2f}  v={nearest['v']:+5.2f}m/s")
        else:
            print(f"#{parsed['frame_number']:>6} 점 0개")
        if log_file:
            log_file.write(json.dumps({"t": time.time(), **parsed}, ensure_ascii=False) + "\n")
            log_file.flush()

    try:
        if args.cfg:
            print(f"설정 전송: {args.cfg}")
            radar_reader.send_cfg(cli, radar_reader.load_cfg_lines(args.cfg))
        deadline = time.monotonic() + args.seconds
        radar_reader.read_frames(
            data, radar_parser.FrameExtractor(), show,
            should_stop=lambda: time.monotonic() > deadline,
        )
    finally:
        stats = radar_reader.get_stats()
        print(f"\n요약: 정상 프레임 {stats['frames_ok']}개, 깨진 프레임 {stats['frames_bad']}개")
        for port in (cli, data):
            port.close()
        if log_file:
            log_file.close()


if __name__ == "__main__":
    main()
