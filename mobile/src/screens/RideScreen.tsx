import { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, Alert, ActivityIndicator } from "react-native";
import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import type { RootStackParamList } from "../navigation/types";
import { bleService, RideDataStalledError, type LiveStatus } from "../ble/BleService";
import { RISK_LEVEL_BY_CODE } from "../ble/protocol";
import { saveRide } from "../db/database";
import { colors, riskColor } from "../theme/colors";
import { RideGpsTracker } from "../gps/rideGpsTracker";
import { attachLocationToEvents } from "../gps/mergeEvents";
import type { RiskLevel } from "../types/ride";

type Props = NativeStackScreenProps<RootStackParamList, "Ride">;
type Phase = "connected" | "riding" | "reconnecting" | "receiving";

export default function RideScreen({ route, navigation }: Props) {
  const { mac } = route.params;
  const [phase, setPhase] = useState<Phase>("connected");
  const [elapsedSec, setElapsedSec] = useState(0);
  const [liveStatus, setLiveStatus] = useState<LiveStatus | null>(null);
  const [currentSpeedKmh, setCurrentSpeedKmh] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const liveStatusSubscriptionRef = useRef<{ remove: () => void } | null>(null);
  const trackerRef = useRef(new RideGpsTracker());
  const currentRiskRef = useRef<RiskLevel>("안전");

  useEffect(() => {
    const riskIndex = liveStatus?.riskLevel ?? 0;
    currentRiskRef.current = RISK_LEVEL_BY_CODE[riskIndex] ?? "안전";
  }, [liveStatus]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      trackerRef.current.stop();
      liveStatusSubscriptionRef.current?.remove();
    };
  }, []);

  const handleStart = useCallback(async () => {
    try {
      // GPS는 블루투스 상태와 무관하게 폰이 스스로 계속 기록한다 (연결 끊겨도 안전).
      await trackerRef.current.start({
        getCurrentRisk: () => currentRiskRef.current,
        onSpeedUpdate: setCurrentSpeedKmh,
      });

      try {
        await bleService.sendStart();
      } catch (error) {
        trackerRef.current.stop();
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
  }, []);

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

    // GPS 기록은 이미 폰에 다 있으니 여기서 멈춰도 됨 — 이후엔 파이 이벤트만 받으면 됨.
    trackerRef.current.stop();

    try {
      await ensureConnected();
      setPhase("receiving");
      const piSummary = await bleService.stopRideAndReceiveData();
      liveStatusSubscriptionRef.current?.remove();
      liveStatusSubscriptionRef.current = null;

      const gps = trackerRef.current.getSummary();
      const events = attachLocationToEvents(piSummary.events, gps.points);

      const rideId = await saveRide({
        client_ride_uuid: piSummary.client_ride_uuid,
        started_at: piSummary.started_at,
        ended_at: piSummary.ended_at,
        duration_sec: piSummary.duration_sec,
        safety_score: piSummary.safety_score,
        distance_km: gps.distance_km,
        avg_speed_kmh: gps.avg_speed_kmh,
        max_speed_kmh: gps.max_speed_kmh,
        hard_brake_count: gps.hard_brake_count,
        points: gps.points,
        events,
      });
      navigation.replace("RideDetail", { rideId });
    } catch (e) {
      if (e instanceof RideDataStalledError) {
        Alert.alert("전송 중단", "주행기록 수신이 끊겼습니다. 종료를 다시 눌러 재시도해주세요.");
        setPhase("riding");
        return;
      }

      Alert.alert("종료 실패", e instanceof Error ? e.message : String(e));
      setPhase("riding");
    }
  }, [ensureConnected, navigation]);

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
      {phase === "riding" && <Text style={styles.speed}>{currentSpeedKmh.toFixed(1)} km/h</Text>}
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
  speed: { color: colors.accent, fontSize: 20, fontWeight: "700" },
  mac: { color: colors.textMuted, fontSize: 13 },
  startButton: { backgroundColor: colors.accent, paddingVertical: 18, paddingHorizontal: 48, borderRadius: 100 },
  startButtonText: { color: "#04222b", fontWeight: "800", fontSize: 18 },
  stopButton: { backgroundColor: colors.danger, paddingVertical: 18, paddingHorizontal: 48, borderRadius: 100 },
  stopButtonText: { color: "white", fontWeight: "800", fontSize: 18 },
  center: { alignItems: "center", gap: 12 },
  text: { color: colors.textMuted },
});
