"""
파이의 블루투스 MAC 주소를 QR코드 이미지로 만든다.
BLE_PROTOCOL.md 의 QR 포맷(PMADAS:<MAC>)을 그대로 따름.

사용법:
    python3 generate_pi_qr.py AA:BB:CC:DD:EE:FF
    python3 generate_pi_qr.py AA:BB:CC:DD:EE:FF --out pi_qr.png

파이에서 실제 MAC 주소 확인하는 법:
    bluetoothctl show   # Address: AA:BB:CC:DD:EE:FF 부분
"""
import argparse
import re
import sys

import qrcode

QR_PREFIX = "PMADAS:"
MAC_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def main():
    parser = argparse.ArgumentParser(description="파이 페어링용 QR코드 생성")
    parser.add_argument("mac", help="파이의 블루투스 MAC 주소 (예: AA:BB:CC:DD:EE:FF)")
    parser.add_argument("--out", default="pi_qr.png", help="저장할 파일명 (기본: pi_qr.png)")
    args = parser.parse_args()

    mac = args.mac.strip().upper()
    if not MAC_PATTERN.match(mac):
        print(f"❌ MAC 주소 형식이 아닙니다: {mac} (예: AA:BB:CC:DD:EE:FF)")
        sys.exit(1)

    payload = f"{QR_PREFIX}{mac}"
    img = qrcode.make(payload)
    img.save(args.out)
    print(f"✅ QR 저장됨: {args.out}")
    print(f"   내용: {payload}")


if __name__ == "__main__":
    main()
