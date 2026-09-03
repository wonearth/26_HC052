import { Vibration } from "react-native";
import { createAudioPlayer, type AudioPlayer } from "expo-audio";

let cachedPlayer: AudioPlayer | null = null;

function getPlayer(): AudioPlayer {
  if (!cachedPlayer) {
    cachedPlayer = createAudioPlayer(require("../../assets/alert_beep.wav"));
  }
  return cachedPlayer;
}

export async function playRideAlert(pattern: number[] = [0, 250, 120, 250]): Promise<void> {
  Vibration.vibrate(pattern);
  try {
    const player = getPlayer();
    player.seekTo(0);
    player.play();
  } catch {
  }
}

export function unloadRideAlertSound(): void {
  cachedPlayer?.remove();
  cachedPlayer = null;
}
