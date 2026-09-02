import { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, Alert, ActivityIndicator } from "react-native";
import * as Location from "expo-location";
import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import type { RootStackParamList } from "../navigation/types";
import { bleService, RideDataStalledError, type LiveStatus } from "../ble/BleService";
import { RISK_LEVEL_BY_CODE } from "../ble/protocol";
import { saveRide } from "../db/database";
import { colors, riskColor } from "../theme/colors";

type Props = NativeStackScreenProps<RootStackParamList, "Ride">;
type Phase = "connected" | "riding" | "reconnecting" | "receiving";

export default function RideScreen({ route, navigation }: Props) {
  const { mac } = route.params;
  const [phase, setPhase] = useState<Phase>("connected");
  const [elapsedSec, setElapsedSec] = useState(0);
  const [liveStatus, setLiveStatus] = useState<LiveStatus | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const locationSubscriptionRef = useRef<Location.LocationSubscription | null>(null);
  const liveStatusSubscriptionRef = useRef<{ remove: () => void } | null>(null);

  const stopPhoneGps = useCallback(() => {
    locationSubscriptionRef.current?.remove();
    locationSubscriptionRef.current = null;
  }, []);

  const startPhoneGps = useCallback(async () => {
    const permission = await Location.requestForegroundPermissionsAsync();
    if (permission.status !== "granted") {
      throw new Error("휴대폰 위치 권한이 필요합니다.");
    }

    const servicesEnabled = await Location.hasServicesEnabledAsync();
    if (!servicesEnabled) {
      throw new Error("휴대폰의 위치(GPS) 기능을 켜주세요.");
    }

    stopPhoneGps();

    locationSubscriptionRef.current = await Location.watchPositionAsync(
      {
        accuracy: Location.Accuracy.High,
        timeInterval: 1000,
        distanceInterval: 1,
      },
      (location) => {
        const { latitude, longitude, speed } = location.coords;
        const speedKmh = speed != null && speed >= 0 ? speed * 3.6 : 0;

        bleService
          .sendPhoneGps(latitude, longitude, speedKmh)
          .catch((error) => console.log("⚠️ PHONE GPS BLE 전송 실패:", error));
      }
    );
  }, [stopPhoneGps]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      stopPhoneGps();
      liveStatusSubscriptionRef.current?.remove();
    };
  }, [stopPhoneGps]);

  const handleStart = useCallback(async () => {
    try {
      // 먼저 위치 권한/GPS 상태를 확인한다. 실패하면 Pi 주행도 시작하지 않는다.
      await startPhoneGps();

      try {
        await bleService.sendStart();
      } catch (error) {
        stopPhoneGps();
        throw error;
      }

      setPhase("riding");
      setElapsedSec(0);

      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = setInterval(() => setElapsedSec((s) => s + 1), 1000);

      liveStatusSubscriptionRef.current?.remove();
      liveStatusSubscriptionRef.current = bleService.subscribeLiveStatus(setLiveStatus);
    } catch (e) {
      Alert.alert("시작 실패", e instanceof Error ? e.message : String(e));
    }
  }, [startPhoneGps, stopPhoneGps]);

  const ensureConnected = useCallback(async () => {
    if (bleService.isConnected()) return;
    setPhase("reconnecting");
    await bleService.connectByMac(mac);
  }, [mac]);

  const handleStop = useCallback(async () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    // STOP 직전까지의 위치는 이미 Pi로 전달되어 있으므로 추적을 종료한다.
    stopPhoneGps();

    try {
      await ensureConnected();
      setPhase("receiving");
      const payload = await bleService.stopRideAndReceiveData();
      liveStatusSubscriptionRef.current?.remove();
      liveStatusSubscriptionRef.current = null;
      const rideId = await saveRide(payload);
      navigation.replace("RideDetail", { rideId });
    } catch (e) {
      if (e instanceof RideDataStalledError) {
        Alert.alert("전송 중단", "주행기록 수신이 끊겼습니다. 종료를 다시 눌러 재시도해주세요.");
        setPhase("riding");

        // 주행 종료가 확정되지 않았으므로 GPS 추적을 다시 시작한다.
        startPhoneGps().catch((error) =>
          Alert.alert("GPS 재시작 실패", error instanceof Error ? error.message : String(error))
        );
        return;
      }

      Alert.alert("종료 실패", e instanceof Error ? e.message : String(e));
      setPhase("riding");
      startPhoneGps().catch((error) =>
        Alert.alert("GPS 재시작 실패", error instanceof Error ? error.message : String(error))
      );
    }
  }, [ensureConnected, navigation, startPhoneGps, stopPhoneGps]);

  const riskIndex = liveStatus?.riskLevel ?? 0;
  const riskLabel = RISK_LEVEL_BY_CODE[riskIndex] ?? "안전";

  return (
    <View style={styles.container}>
      {phase === "riding" && (
        <View style={[styles.banner, { backgroundColor: riskColor[riskLabel] }]}>
          <Text style={styles.bannerText}>{riskLabel}</Text>
        </View>
      )}

      <Text style={styles.timer}>{formatElapsed(elapsedSec)}</Text>
      <Text style={styles.mac}>파이 {mac}</Text>

      {phase === "connected" && (
        <Pressable style={styles.startButton} onPress={handleStart}>
          <Text style={styles.startButtonText}>주행 시작</Text>
        </Pressable>
      )}

      {phase === "riding" && (
        <Pressable style={styles.stopButton} onPress={handleStop}>
          <Text style={styles.stopButtonText}>주행 종료</Text>
        </Pressable>
      )}

      {(phase === "reconnecting" || phase === "receiving") && (
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} size="large" />
          <Text style={styles.text}>
            {phase === "reconnecting" ? "파이에 재연결하는 중..." : "주행기록을 받는 중..."}
          </Text>
        </View>
      )}
    </View>
  );
}

function formatElapsed(totalSec: number): string {
  const m = String(Math.floor(totalSec / 60)).padStart(2, "0");
  const s = String(totalSec % 60).padStart(2, "0");
  return `${m}:${s}`;
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    gap: 20,
  },
  banner: { position: "absolute", top: 0, left: 0, right: 0, paddingTop: 56, paddingBottom: 16, alignItems: "center" },
  bannerText: { color: "#04222b", fontWeight: "800", fontSize: 18 },
  timer: { color: colors.text, fontSize: 48, fontWeight: "700" },
  mac: { color: colors.textMuted, fontSize: 13 },
  startButton: { backgroundColor: colors.accent, paddingVertical: 18, paddingHorizontal: 48, borderRadius: 100 },
  startButtonText: { color: "#04222b", fontWeight: "800", fontSize: 18 },
  stopButton: { backgroundColor: colors.danger, paddingVertical: 18, paddingHorizontal: 48, borderRadius: 100 },
  stopButtonText: { color: "white", fontWeight: "800", fontSize: 18 },
  center: { alignItems: "center", gap: 12 },
  text: { color: colors.textMuted },
});
