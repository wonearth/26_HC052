import { useCallback, useState } from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "@react-navigation/native";
import { getNickname, getSummaryStats, saveRide, setNickname, type SummaryStats } from "../db/database";
import { generateMockRide } from "../mock/mockRide";
import { colors } from "../theme/colors";
import type { MainTabScreenProps } from "../navigation/types";
import NicknameModal from "../components/NicknameModal";

type Props = MainTabScreenProps<"Home">;

// 닉네임 입력을 "나중에"로 넘겼을 때, 홈 탭에 다시 올 때마다 팝업이 또 뜨지 않도록
// 이 세션에서 한 번 물어봤는지만 기억해둔다 (앱을 껐다 켜면 다시 물어봄).
let hasPromptedNicknameThisSession = false;

export default function HomeScreen({ navigation }: Props) {
  const [stats, setStats] = useState<SummaryStats | null>(null);
  const [nickname, setNicknameState] = useState<string | null>(null);
  const [checkedNickname, setCheckedNickname] = useState(false);
  const [nicknameModalVisible, setNicknameModalVisible] = useState(false);

  useFocusEffect(
    useCallback(() => {
      getSummaryStats().then(setStats).catch(() => {});
      getNickname().then((n) => {
        setNicknameState(n);
        setCheckedNickname(true);
        if (!n && !hasPromptedNicknameThisSession) {
          hasPromptedNicknameThisSession = true;
          setNicknameModalVisible(true);
        }
      });
    }, [])
  );

  const handleSaveNickname = async (value: string) => {
    await setNickname(value);
    setNicknameState(value);
    setNicknameModalVisible(false);
  };

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>PM ADAS</Text>
        <Pressable onPress={() => navigation.navigate("Settings")} hitSlop={12}>
          <Ionicons name="settings-outline" size={24} color={colors.textMuted} />
        </Pressable>
      </View>

      {checkedNickname && (
        <Pressable onPress={() => setNicknameModalVisible(true)}>
          <Text style={styles.greeting}>
            {nickname ? `${nickname}님, 오늘도 안전 라이딩!` : "라이더님, 오늘도 안전 라이딩!"}
          </Text>
        </Pressable>
      )}

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

      <NicknameModal
        visible={nicknameModalVisible}
        initialValue={nickname ?? ""}
        onSave={handleSaveNickname}
        onClose={() => setNicknameModalVisible(false)}
      />
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
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  title: { color: colors.text, fontSize: 26, fontWeight: "800" },
  greeting: { color: colors.textMuted, fontSize: 14, marginTop: -8 },
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
