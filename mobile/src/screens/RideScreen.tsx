import { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, Pressable, Alert, ActivityIndicator } from "react-native";
import { useKeepAwake } from "expo-keep-awake";
import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import type { RootStackParamList } from "../navigation/types";
import { bleService, RideDataStalledError, type ImuStatus, type LiveStatus } from "../ble/BleService";
import { RISK_LEVEL_BY_CODE } from "../ble/protocol";
import { saveRide } from "../db/database";
import { colors, riskColor } from "../theme/colors";
import { RideGpsTracker } from "../gps/rideGpsTracker";
import { attachLocationToEvents } from "../gps/mergeEvents";
import { playRideAlert } from "../alert/rideAlert";
import type { RawRideEvent, RiskLevel } from "../types/ride";

type Props = NativeStackScreenProps<RootStackParamList, "Ride">;
type Phase = "connected" | "riding" | "reconnecting" | "receiving";

export default function RideScreen({ route, navigation }: Props) {
  useKeepAwake(); // 주행 화면에 있는 동안 화면이 꺼지지 않도록 (위험 배너/속도가 안 보이면 안 되니까)
  const { mac } = route.params;
  const [phase, setPhase] = useState<Phase>("connected");
  const [elapsedSec, setElapsedSec] = useState(0);
  const [liveStatus, setLiveStatus] = useState<LiveStatus | null>(null);
  const [imuStatus, setImuStatus] = useState<ImuStatus | null>(null);
  const [currentSpeedKmh, setCurrentSpeedKmh] = useState(0);
  const [currentDistanceKm, setCurrentDistanceKm] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const liveStatusSubscriptionRef = useRef<{ remove: () => void } | null>(null);
  const imuSubscriptionRef = useRef<{ remove: () => void } | null>(null);
  const trackerRef = useRef(new RideGpsTracker());
  const currentRiskRef = useRef<RiskLevel>("안전");
  const imuEventsRef = useRef<RawRideEvent[]>([]);
  const lastImpactRef = useRef(false);
  const lastRolloverRef = useRef(false);
  const lastAlertRiskRef = useRef(0);

  useEffect(() => {
    const riskIndex = liveStatus?.riskLevel ?? 0;
    currentRiskRef.current = RISK_LEVEL_BY_CODE[riskIndex] ?? "안전";

    // 경고(2)/위험(3) 단계로 "새로 진입"할 때만 알림 — 같은 단계 유지 중엔 계속 안 울림
    if (riskIndex > lastAlertRiskRef.current && riskIndex >= 2) {
      playRideAlert();
    }
    lastAlertRiskRef.current = riskIndex;
  }, [liveStatus]);

  const handleImuUpdate = useCallback((status: ImuStatus) => {
    setImuStatus(status);

    // impact/rollover가 false→true로 바뀌는 순간만 위험 이벤트로 기록 (계속 true인 동안 중복 방지)
    if (status.impact && !lastImpactRef.current) {
      imuEventsRef.current.push({
        occurred_at: new Date().toISOString(),
        risk_level: "위험",
        object_class: "impact",
        distance_m: 0,
        ttc_sec: 0,
      });
      playRideAlert([0, 300, 100, 300, 100, 300]);
    }
    if (status.rollover && !lastRolloverRef.current) {
      imuEventsRef.current.push({
        occurred_at: new Date().toISOString(),
        risk_level: "위험",
        object_class: "rollover",
        distance_m: 0,
        ttc_sec: 0,
      });
      playRideAlert([0, 300, 100, 300, 100, 300]);
    }
    lastImpactRef.current = status.impact;
    lastRolloverRef.current = status.rollover;
  }, []);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      trackerRef.current.stop();
      liveStatusSubscriptionRef.current?.remove();
      imuSubscriptionRef.current?.remove();
    };
  }, []);

  const handleStart = useCallback(async () => {
    try {
      // GPS는 블루투스 상태와 무관하게 폰이 스스로 계속 기록한다 (연결 끊겨도 안전).
      await trackerRef.current.start({
        getCurrentRisk: () => currentRiskRef.current,
        onSpeedUpdate: setCurrentSpeedKmh,
        onDistanceUpdate: setCurrentDistanceKm,
      });

      try {
        await bleService.sendStart();
      } catch (error) {
        trackerRef.current.stop();
        throw error;
      }

      setPhase("riding");
      setElapsedSec(0);
      setCurrentDistanceKm(0);
      imuEventsRef.current = [];
      lastImpactRef.current = false;
      lastRolloverRef.current = false;
      lastAlertRiskRef.current = 0;

      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = setInterval(() => setElapsedSec((s) => s + 1), 1000);

      liveStatusSubscriptionRef.current?.remove();
      liveStatusSubscriptionRef.current = bleService.subscribeLiveStatus(setLiveStatus);

      imuSubscriptionRef.current?.remove();
      imuSubscriptionRef.current = bleService.subscribeImu(handleImuUpdate);
    } catch (e) {
      Alert.alert("시작 실패", e instanceof Error ? e.message : String(e));
    }
  }, [handleImuUpdate]);

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
      imuSubscriptionRef.current?.remove();
      imuSubscriptionRef.current = null;

      const gps = trackerRef.current.getSummary();
      const rawEvents = [...piSummary.events, ...imuEventsRef.current].sort(
        (a, b) => new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime()
      );
      const events = attachLocationToEvents(rawEvents, gps.points);

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
  const imuAlert = imuStatus?.impact ? "충돌 감지!" : imuStatus?.rollover ? "전복 감지!" : null;

  return (
    <View style={styles.container}>
      {phase === "riding" && (
        <View style={[styles.banner, { backgroundColor: imuAlert ? colors.danger : riskColor[riskLabel] }]}>
          <Text style={styles.bannerText}>{imuAlert ?? riskLabel}</Text>
        </View>
      )}

      <Text style={styles.timer}>{formatElapsed(elapsedSec)}</Text>
      {phase === "riding" && (
        <Text style={styles.speed}>
          {currentSpeedKmh.toFixed(1)} km/h · {currentDistanceKm.toFixed(2)} km
        </Text>
      )}

      {(phase === "connected" || phase === "riding") && (
        <View style={styles.connectedBadge}>
          <View style={styles.connectedDot} />
          <Text style={styles.connectedText}>파이 연결됨</Text>
        </View>
      )}

      {phase === "riding" && imuStatus?.connected && (
        <Text style={styles.imuInfo}>
          IMU 연결됨 · 기울기 {imuStatus.roll.toFixed(0)}° / {imuStatus.pitch.toFixed(0)}°
        </Text>
      )}

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
  speed: { color: colors.accent, fontSize: 18, fontWeight: "700" },
  connectedBadge: { flexDirection: "row", alignItems: "center", gap: 6 },
  connectedDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.safe },
  connectedText: { color: colors.textMuted, fontSize: 13 },
  imuInfo: { color: colors.textMuted, fontSize: 12 },
  startButton: { backgroundColor: colors.accent, paddingVertical: 18, paddingHorizontal: 48, borderRadius: 100 },
  startButtonText: { color: "#04222b", fontWeight: "800", fontSize: 18 },
  stopButton: { backgroundColor: colors.danger, paddingVertical: 18, paddingHorizontal: 48, borderRadius: 100 },
  stopButtonText: { color: "white", fontWeight: "800", fontSize: 18 },
  center: { alignItems: "center", gap: 12 },
  text: { color: colors.textMuted },
});
