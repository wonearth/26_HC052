// react-native-ble-plx는 characteristic 값을 base64 문자열로 주고받는다.
// RN 환경에 Buffer/atob/btoa가 항상 있다고 보장할 수 없어서 직접 구현한다.

const BASE64_CHARS =
  "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

export function base64Encode(bytes: Uint8Array): string {
  let result = "";
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i];
    const b1 = i + 1 < bytes.length ? bytes[i + 1] : undefined;
    const b2 = i + 2 < bytes.length ? bytes[i + 2] : undefined;
    const triplet = (b0 << 16) | ((b1 ?? 0) << 8) | (b2 ?? 0);
    result += BASE64_CHARS[(triplet >> 18) & 0x3f];
    result += BASE64_CHARS[(triplet >> 12) & 0x3f];
    result += b1 === undefined ? "=" : BASE64_CHARS[(triplet >> 6) & 0x3f];
    result += b2 === undefined ? "=" : BASE64_CHARS[triplet & 0x3f];
  }
  return result;
}

export function base64Decode(input: string): Uint8Array {
  const clean = input.replace(/=+$/, "");
  const bytes: number[] = [];
  let buffer = 0;
  let bits = 0;
  for (const char of clean) {
    const value = BASE64_CHARS.indexOf(char);
    if (value === -1) continue;
    buffer = (buffer << 6) | value;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      bytes.push((buffer >> bits) & 0xff);
    }
  }
  return new Uint8Array(bytes);
}
