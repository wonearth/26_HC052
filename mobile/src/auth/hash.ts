import * as Crypto from "expo-crypto";

function randomSalt(): string {
  const bytes = Crypto.getRandomBytes(16);
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** 로컬 전용 앱이라 서버로 유출될 일이 없어서 SHA-256 salted hash 정도로 충분 (bcrypt급 보안 불필요). */
export async function hashPassword(password: string, salt?: string): Promise<{ hash: string; salt: string }> {
  const usedSalt = salt ?? randomSalt();
  const hash = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    usedSalt + password
  );
  return { hash, salt: usedSalt };
}

export async function verifyPassword(password: string, salt: string, expectedHash: string): Promise<boolean> {
  const { hash } = await hashPassword(password, salt);
  return hash === expectedHash;
}
