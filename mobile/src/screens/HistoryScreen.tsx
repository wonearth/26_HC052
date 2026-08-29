import { useCallback, useState } from "react";
import { View, Text, FlatList, Pressable, StyleSheet } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import type { RootStackParamList } from "../navigation/types";
import { listRides, saveRide } from "../db/database";
import { generateMockRide } from "../mock/mockRide";
import type { RideSummary } from "../types/ride";
import { colors } from "../theme/colors";

type Props = NativeStackScreenProps<RootStackParamList, "History">;

export default function HistoryScreen({ navigation }: Props) {
  const [rides, setRides] = useState<RideSummary[]>([]);

  useFocusEffect(
    useCallback(() => {
      listRides()
        .then(setRides)
        .catch(() => {});
    }, [])
  );

  return (
    <View style={styles.container}>
      <Text style={styles.title}>PM ADAS</Text>

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

      <Text style={styles.sectionTitle}>지난 라이딩</Text>
      <FlatList
        data={rides}
        keyExtractor={(item) => String(item.id)}
        contentContainerStyle={{ gap: 10, paddingBottom: 24 }}
        ListEmptyComponent={<Text style={styles.empty}>아직 저장된 라이딩이 없습니다</Text>}
        renderItem={({ item }) => (
          <Pressable
            style={styles.rideCard}
            onPress={() => navigation.navigate("RideDetail", { rideId: item.id })}
          >
            <Text style={styles.rideDate}>{formatDate(item.started_at)}</Text>
            <View style={styles.rideStatsRow}>
              <Text style={styles.rideStat}>{item.distance_km.toFixed(1)}km</Text>
              <Text style={styles.rideStat}>안전점수 {item.safety_score}</Text>
              <Text style={styles.rideStat}>급정거 {item.hard_brake_count}회</Text>
            </View>
          </Pressable>
        )}
      />
    </View>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${String(d.getHours()).padStart(2, "0")}:${String(
    d.getMinutes()
  ).padStart(2, "0")}`;
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, padding: 20, paddingTop: 64, gap: 14 },
  title: { color: colors.text, fontSize: 26, fontWeight: "800" },
  primaryButton: { backgroundColor: colors.accent, paddingVertical: 16, borderRadius: 14, alignItems: "center" },
  primaryButtonText: { color: "#04222b", fontWeight: "800", fontSize: 15 },
  devButton: { borderWidth: 1, borderColor: colors.border, paddingVertical: 10, borderRadius: 10, alignItems: "center" },
  devButtonText: { color: colors.textMuted, fontSize: 12 },
  sectionTitle: { color: colors.textMuted, fontSize: 13, marginTop: 8 },
  empty: { color: colors.textMuted, fontSize: 13, paddingVertical: 20, textAlign: "center" },
  rideCard: {
    backgroundColor: colors.surface,
    borderRadius: 14,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 8,
  },
  rideDate: { color: colors.text, fontWeight: "700", fontSize: 15 },
  rideStatsRow: { flexDirection: "row", gap: 16 },
  rideStat: { color: colors.textMuted, fontSize: 13 },
});
