import { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Dimensions } from "react-native";
import { WebView } from "react-native-webview";
import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import type { RootStackParamList } from "../navigation/types";
import { getRideDetail } from "../db/database";
import type { RideEvent, RidePoint, RideSummary } from "../types/ride";
import { colors, riskColor } from "../theme/colors";
import { buildRideMapHtml } from "../map/buildRideMapHtml";

type Props = NativeStackScreenProps<RootStackParamList, "RideDetail">;
type RideDetail = { summary: RideSummary; points: RidePoint[]; events: RideEvent[] };

export default function RideDetailScreen({ route }: Props) {
  const { rideId } = route.params;
  const [data, setData] = useState<RideDetail | null>(null);

  useEffect(() => {
    getRideDetail(rideId).then(setData);
  }, [rideId]);

  if (!data) {
    return (
      <View style={styles.center}>
        <Text style={styles.text}>불러오는 중...</Text>
      </View>
    );
  }

  const { summary, points, events } = data;

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ paddingBottom: 40 }}>
      {points.length > 0 && (
        <WebView
          style={styles.map}
          originWhitelist={["*"]}
          source={{ html: buildRideMapHtml(points, events) }}
          scrollEnabled={false}
        />
      )}

      <View style={styles.statsGrid}>
        <Stat label="거리" value={`${summary.distance_km.toFixed(1)}km`} />
        <Stat label="시간" value={formatDuration(summary.duration_sec)} />
        <Stat label="평균속도" value={`${summary.avg_speed_kmh.toFixed(1)}km/h`} />
        <Stat label="최고속도" value={`${summary.max_speed_kmh.toFixed(1)}km/h`} />
        <Stat label="급정거" value={`${summary.hard_brake_count}회`} />
        <Stat label="안전점수" value={String(summary.safety_score)} />
      </View>

      <Text style={styles.sectionTitle}>위험 이벤트 ({events.length})</Text>
      {events.map((event, i) => (
        <View key={i} style={styles.eventRow}>
          <View style={[styles.eventDot, { backgroundColor: riskColor[event.risk_level] }]} />
          <Text style={styles.eventText}>
            {event.risk_level} · {event.object_class} · {event.distance_m.toFixed(1)}m ·{" "}
            {new Date(event.occurred_at).toLocaleTimeString()}
          </Text>
        </View>
      ))}
    </ScrollView>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.statCard}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

function formatDuration(totalSec: number): string {
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}분 ${s}초`;
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, backgroundColor: colors.background, alignItems: "center", justifyContent: "center" },
  text: { color: colors.textMuted },
  map: { width: Dimensions.get("window").width, height: 260, backgroundColor: colors.background },
  statsGrid: { flexDirection: "row", flexWrap: "wrap", padding: 16, gap: 10 },
  statCard: {
    width: "31%",
    backgroundColor: colors.surface,
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    gap: 4,
  },
  statValue: { color: colors.text, fontWeight: "800", fontSize: 16 },
  statLabel: { color: colors.textMuted, fontSize: 11 },
  sectionTitle: { color: colors.textMuted, fontSize: 13, paddingHorizontal: 16, marginTop: 8, marginBottom: 6 },
  eventRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 16, paddingVertical: 8 },
  eventDot: { width: 10, height: 10, borderRadius: 5 },
  eventText: { color: colors.text, fontSize: 13, flex: 1 },
});
