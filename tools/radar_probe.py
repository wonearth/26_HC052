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
#!/usr/bin/env python3
"""
레이더 브링업 확인 도구
(Pi에서 직접 실행하는 개발용 도구 — app.py/서비스와 무관)

사용 예:
    python3 tools/radar_probe.py --seconds 30

설정을 다시 보낼 경우:
    python3 tools/radar_probe.py \
        --cfg radar.cfg \
        --seconds 30 \
        --log radar_log.jsonl

현재 Raspberry Pi 연결:
- /dev/ttyUSB0 -> IMU
- /dev/ttyUSB1 -> Radar CLI
- /dev/ttyUSB2 -> Radar DATA
"""

import argparse
import json
import os
import sys
import time


# 프로젝트 루트를 Python path에 추가
sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    ),
)

import radar_parser
import radar_reader


def main():

    ap = argparse.ArgumentParser(
        description="레이더 브링업 확인 도구"
    )

    # ========================================================
    # 현재 실제 연결 포트
    # ========================================================

    auto_cli = "/dev/ttyUSB1"
    auto_data = "/dev/ttyUSB2"

    ap.add_argument(
        "--cli",
        default=auto_cli,
        help=f"명령 포트 (기본: {auto_cli})",
    )

    ap.add_argument(
        "--data",
        default=auto_data,
        help=f"데이터 포트 (기본: {auto_data})",
    )

    ap.add_argument(
        "--cfg",
        default=None,
        help=".cfg 경로 (생략하면 설정 전송 안 함)",
    )

    ap.add_argument(
        "--seconds",
        type=float,
        default=30.0,
        help="측정 시간(초)",
    )

    ap.add_argument(
        "--log",
        default=None,
        help="프레임을 저장할 .jsonl 경로",
    )

    args = ap.parse_args()

    import serial

    print("======================================")
    print("TI mmWave Radar Probe")
    print("======================================")
    print(f"CLI  : {args.cli}")
    print(f"DATA : {args.data}")
    print(
        f"BAUD : CLI={radar_reader.CLI_BAUD}, "
        f"DATA={radar_reader.DATA_BAUD}"
    )
    print("======================================")

    print("레이더 포트 연결 중...")

    cli = serial.Serial(
        args.cli,
        radar_reader.CLI_BAUD,
        timeout=0.1,
    )

    data = serial.Serial(
        args.data,
        radar_reader.DATA_BAUD,
        timeout=0.1,
    )

    print("레이더 포트 연결 완료")

    log_file = (
        open(
            args.log,
            "w",
            encoding="utf-8",
        )
        if args.log
        else None
    )

    state = {
        "first": True,
        "n": 0,
    }

    def show(parsed):

        if state["first"]:

            state["first"] = False

            print()
            print("========== 첫 프레임 헤더 ==========")

            print(
                f"version = "
                f"0x{parsed['version']:08x}"
            )

            print(
                f"platform = "
                f"0x{parsed['platform']:08x}"
            )

            print(
                f"numTLVs = "
                f"{parsed['num_tlvs']}"
            )

            print(
                f"numObj(헤더) = "
                f"{parsed['num_detected_header']}"
            )

            print(
                "TLV 길이가 헤더 포함 = "
                f"{parsed['tlv_length_includes_header']}"
            )

            print("====================================")
            print()

        # 기존 dashboard용 통계에도 반영
        radar_reader.handle_frame(parsed)

        pts = parsed["points"]

        state["n"] += 1

        if pts:

            nearest = min(
                pts,
                key=lambda p: p["range_m"],
            )

            print(
                f"#{parsed['frame_number']:>6} "
                f"점 {len(pts):>3}개 | "
                f"가장 가까운 점: "
                f"거리 {nearest['range_m']:5.2f}m  "
                f"x={nearest['x']:+5.2f} "
                f"y={nearest['y']:+5.2f}  "
                f"v={nearest['v']:+5.2f}m/s"
            )

        else:

            print(
                f"#{parsed['frame_number']:>6} "
                "점 0개"
            )

        if log_file:

            log_file.write(
                json.dumps(
                    {
                        "t": time.time(),
                        **parsed,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

            log_file.flush()

    try:

        # cfg를 명시했을 때만 설정 전송
        if args.cfg:

            print(
                f"설정 전송 시작: {args.cfg}"
            )

            radar_reader.send_cfg(
                cli,
                radar_reader.load_cfg_lines(
                    args.cfg
                ),
            )

            print("설정 전송 완료")

        else:

            print(
                "CFG 전송 생략 "
                "(현재 레이더 설정 그대로 사용)"
            )

        print()
        print(
            f"레이더 프레임 수신 시작 "
            f"({args.seconds:.0f}초)"
        )
        print()

        deadline = (
            time.monotonic()
            + args.seconds
        )

        radar_reader.read_frames(
            data,
            radar_parser.FrameExtractor(),
            show,
            should_stop=lambda:
                time.monotonic() > deadline,
        )

    except KeyboardInterrupt:

        print()
        print("사용자가 측정을 중지했습니다.")

    except Exception as e:

        print()
        print(
            f"레이더 probe 오류: "
            f"{type(e).__name__}: {e}"
        )

        raise

    finally:

        stats = radar_reader.get_stats()

        print()
        print("========== 측정 요약 ==========")

        print(
            f"정상 프레임 : "
            f"{stats['frames_ok']}개"
        )

        print(
            f"깨진 프레임 : "
            f"{stats['frames_bad']}개"
        )

        print(
            f"Probe 처리 프레임 : "
            f"{state['n']}개"
        )

        print("===============================")

        for port in (cli, data):

            try:
                port.close()

            except Exception:
                pass

        if log_file:

            log_file.close()


if __name__ == "__main__":
    main()
