import { useCallback, useState } from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import { getSummaryStats, saveRide, type SummaryStats } from "../db/database";
import { generateMockRide } from "../mock/mockRide";
import { colors } from "../theme/colors";
import type { MainTabScreenProps } from "../navigation/types";

type Props = MainTabScreenProps<"Home">;

export default function HomeScreen({ navigation }: Props) {
  const [stats, setStats] = useState<SummaryStats | null>(null);

  useFocusEffect(
    useCallback(() => {
      getSummaryStats().then(setStats).catch(() => {});
    }, [])
  );

  return (
    <View style={styles.container}>
      <Text style={styles.title}>PM ADAS</Text>

      <View style={styles.statsRow}>
        <Stat label="총 라이딩" value={String(stats?.rideCount ?? 0)} />
        <Stat label="총 거리" value={`${(stats?.totalDistanceKm ?? 0).toFixed(1)}km`} />
        <Stat label="평균 안전점수" value={String(stats?.avgSafetyScore ?? "-")} />
      </View>

      <Pressable style={styles.primaryButton} onPress={() => navigation.navigate("Scan")}>
        <Text style={styles.primaryButtonText}>QR 스캔하고 새 라이딩 시작</Text>
      </Pressable>

      {__DEV__ && (
        <Pressable
          style={styles.devButton}
          onPress={async () => {
            const rideId = await saveRide(generateMockRide());
            navigation.navigate("RideDetail", { rideId });
          }}
        >
          <Text style={styles.devButtonText}>(개발용) 더미 라이딩으로 화면 확인</Text>
        </Pressable>
      )}
    </View>
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

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, padding: 20, paddingTop: 24, gap: 16 },
  title: { color: colors.text, fontSize: 26, fontWeight: "800" },
  statsRow: { flexDirection: "row", gap: 10 },
  statCard: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    paddingVertical: 14,
    alignItems: "center",
    gap: 4,
  },
  statValue: { color: colors.accent, fontWeight: "800", fontSize: 17 },
  statLabel: { color: colors.textMuted, fontSize: 11 },
  primaryButton: { backgroundColor: colors.accent, paddingVertical: 16, borderRadius: 14, alignItems: "center" },
  primaryButtonText: { color: "#04222b", fontWeight: "800", fontSize: 15 },
  devButton: { borderWidth: 1, borderColor: colors.border, paddingVertical: 10, borderRadius: 10, alignItems: "center" },
  devButtonText: { color: colors.textMuted, fontSize: 12 },
});
