import { useCallback, useState } from "react";
import { View, Text, Pressable, StyleSheet, ScrollView, Alert, ActivityIndicator, Linking, Platform, PermissionsAndroid } from "react-native";
import * as Location from "expo-location";
import { useFocusEffect } from "@react-navigation/native";
import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import type { RootStackParamList } from "../navigation/types";
import { getNickname, setNickname, clearAllRides } from "../db/database";
import { exportRidesAsCsv } from "../export/exportRidesCsv";
import { colors } from "../theme/colors";
import NicknameModal from "../components/NicknameModal";
// eslint-disable-next-line @typescript-eslint/no-var-requires
const pkg = require("../../package.json");

type Props = NativeStackScreenProps<RootStackParamList, "Settings">;

interface PermissionRow {
  label: string;
  granted: boolean;
}

export default function SettingsScreen({}: Props) {
  const [nickname, setNicknameState] = useState<string | null>(null);
  const [nicknameModalVisible, setNicknameModalVisible] = useState(false);
  const [permissions, setPermissions] = useState<PermissionRow[]>([]);
  const [exporting, setExporting] = useState(false);

  const loadPermissions = useCallback(async () => {
    const rows: PermissionRow[] = [];
    if (Platform.OS === "android") {
      if (Platform.Version >= 31) {
        const scan = await PermissionsAndroid.check(PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN);
        const connect = await PermissionsAndroid.check(PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT);
        rows.push({ label: "블루투스 스캔", granted: scan });
        rows.push({ label: "블루투스 연결", granted: connect });
      }
      const location = await PermissionsAndroid.check(PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION);
      rows.push({ label: "위치(GPS)", granted: location });
    } else {
      const location = await Location.getForegroundPermissionsAsync();
      rows.push({ label: "위치(GPS)", granted: location.status === "granted" });
    }
    setPermissions(rows);
  }, []);

  useFocusEffect(
    useCallback(() => {
      getNickname().then(setNicknameState);
      loadPermissions();
    }, [loadPermissions])
  );

  const handleOpenSettings = async () => {
    try {
      await Linking.openSettings();
    } catch {
      Alert.alert("설정을 열 수 없어요", "폰의 설정 앱에서 직접 권한을 확인해주세요.");
    }
  };

  const handleSaveNickname = async (value: string) => {
    await setNickname(value);
    setNicknameState(value);
    setNicknameModalVisible(false);
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      await exportRidesAsCsv();
    } catch (e) {
      Alert.alert("내보내기 실패", e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  };

  const handleClearAll = () => {
    Alert.alert(
      "라이딩 기록 전체 삭제",
      "저장된 모든 라이딩 기록이 삭제돼요. 이 작업은 되돌릴 수 없어요.",
      [
        { text: "취소", style: "cancel" },
        {
          text: "삭제",
          style: "destructive",
          onPress: async () => {
            await clearAllRides();
            Alert.alert("삭제 완료", "모든 라이딩 기록이 삭제됐어요.");
          },
        },
      ]
    );
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ padding: 20, gap: 20 }}>
      <Section title="프로필">
        <Row label="닉네임" value={nickname ?? "설정 안 함"} onPress={() => setNicknameModalVisible(true)} />
      </Section>

      <Section title="권한 상태">
        {permissions.map((p) => (
          <View key={p.label} style={styles.permissionRow}>
            <Text style={styles.rowLabel}>{p.label}</Text>
            <Text style={[styles.permissionValue, { color: p.granted ? colors.safe : colors.danger }]}>
              {p.granted ? "허용됨" : "허용 안 됨"}
            </Text>
          </View>
        ))}
        <Pressable style={styles.outlineButton} onPress={handleOpenSettings}>
          <Text style={styles.outlineButtonText}>폰 설정에서 권한 변경하기</Text>
        </Pressable>
      </Section>

      <Section title="데이터">
        <Pressable style={styles.outlineButton} onPress={handleExport} disabled={exporting}>
          {exporting ? (
            <ActivityIndicator color={colors.accent} />
          ) : (
            <Text style={styles.outlineButtonText}>라이딩 기록 내보내기 (CSV)</Text>
          )}
        </Pressable>
        <Pressable style={styles.dangerButton} onPress={handleClearAll}>
          <Text style={styles.dangerButtonText}>라이딩 기록 전체 삭제</Text>
        </Pressable>
      </Section>

      <Section title="앱 정보">
        <Row label="버전" value={pkg.version} />
      </Section>

      <NicknameModal
        visible={nicknameModalVisible}
        initialValue={nickname ?? ""}
        onSave={handleSaveNickname}
        onClose={() => setNicknameModalVisible(false)}
      />
    </ScrollView>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.sectionCard}>{children}</View>
    </View>
  );
}

function Row({ label, value, onPress }: { label: string; value: string; onPress?: () => void }) {
  const Wrapper = onPress ? Pressable : View;
  return (
    <Wrapper style={styles.row} onPress={onPress}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value}</Text>
    </Wrapper>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  section: { gap: 8 },
  sectionTitle: { color: colors.textMuted, fontSize: 12, fontWeight: "700" },
  sectionCard: {
    backgroundColor: colors.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 4,
    gap: 4,
  },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 12, paddingHorizontal: 12 },
  rowLabel: { color: colors.text, fontSize: 14, fontWeight: "600" },
  rowValue: { color: colors.textMuted, fontSize: 14 },
  permissionRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 10, paddingHorizontal: 12 },
  permissionValue: { fontSize: 13, fontWeight: "700" },
  outlineButton: {
    margin: 8,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  outlineButtonText: { color: colors.accent, fontSize: 14, fontWeight: "700" },
  dangerButton: { margin: 8, marginTop: 0, borderRadius: 10, paddingVertical: 12, alignItems: "center" },
  dangerButtonText: { color: colors.danger, fontSize: 14, fontWeight: "700" },
});
