import { Vibration } from "react-native";
import { Audio } from "expo-av";

let cachedSound: Audio.Sound | null = null;
let loadingPromise: Promise<Audio.Sound> | null = null;

async function getSound(): Promise<Audio.Sound> {
  if (cachedSound) return cachedSound;
  if (!loadingPromise) {
    loadingPromise = Audio.Sound.createAsync(require("../../assets/alert_beep.wav")).then(
      ({ sound }) => {
        cachedSound = sound;
        return sound;
      }
    );
  }
  return loadingPromise;
}

/**
 * 위험 단계 진입/IMU 충돌·전복 감지 시 진동+경고음을 울린다.
 * 주행 중엔 도로를 봐야 해서 화면 색만으로는 못 알아차릴 수 있음 — 그래서 필요함.
 */
export async function playRideAlert(pattern: number[] = [0, 250, 120, 250]): Promise<void> {
  Vibration.vibrate(pattern);
  try {
    const sound = await getSound();
    await sound.replayAsync();
  } catch {
    // 소리 재생이 실패해도 진동은 이미 울렸으니 무시하고 넘어감
  }
}

export function unloadRideAlertSound(): void {
  cachedSound?.unloadAsync();
  cachedSound = null;
  loadingPromise = null;
}
