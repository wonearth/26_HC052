import { useCallback, useState } from "react";
import { View, Text, StyleSheet, Alert, Pressable, ActivityIndicator } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import type { RootStackParamList } from "../navigation/types";
import { parsePiMacFromQr } from "../ble/protocol";
import { bleService } from "../ble/BleService";
import { colors } from "../theme/colors";

type Props = NativeStackScreenProps<RootStackParamList, "Scan">;

export default function ScanScreen({ navigation }: Props) {
  const [permission, requestPermission] = useCameraPermissions();
  const [connecting, setConnecting] = useState(false);
  const [scanned, setScanned] = useState(false);

  const handleScanned = useCallback(
    async ({ data }: { data: string }) => {
      if (scanned || connecting) return;
      const mac = parsePiMacFromQr(data);
      if (!mac) {
        Alert.alert("QR 인식 실패", "PM ADAS 킥보드의 QR코드가 아닙니다.");
        return;
      }
      setScanned(true);
      setConnecting(true);
      try {
        const granted = await bleService.requestAndroidPermissions();
        if (!granted) throw new Error("블루투스 권한이 필요합니다");
        await bleService.connectByMac(mac);
        navigation.replace("Ride", { mac });
      } catch (e) {
        Alert.alert("연결 실패", e instanceof Error ? e.message : String(e));
        setScanned(false);
      } finally {
        setConnecting(false);
      }
    },
    [scanned, connecting, navigation]
  );

  if (!permission) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  if (!permission.granted) {
    return (
      <View style={styles.center}>
        <Text style={styles.text}>QR 스캔을 위해 카메라 권한이 필요합니다</Text>
        <Pressable style={styles.button} onPress={requestPermission}>
          <Text style={styles.buttonText}>권한 허용</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <CameraView
        style={StyleSheet.absoluteFill}
        barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
        onBarcodeScanned={scanned ? undefined : handleScanned}
      />
      <View style={styles.overlay} pointerEvents="none">
        <View style={styles.frame} />
        <Text style={styles.hint}>
          {connecting ? "파이에 연결하는 중..." : "킥보드의 QR코드를 프레임 안에 맞춰주세요"}
        </Text>
        {connecting && <ActivityIndicator color={colors.accent} style={{ marginTop: 12 }} />}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "black" },
  center: {
    flex: 1,
    backgroundColor: colors.background,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    gap: 16,
  },
  overlay: { flex: 1, alignItems: "center", justifyContent: "center" },
  frame: { width: 240, height: 240, borderWidth: 3, borderColor: colors.accent, borderRadius: 16 },
  hint: { color: "white", marginTop: 20, fontSize: 15, textAlign: "center", paddingHorizontal: 24 },
  text: { color: colors.text, fontSize: 16, textAlign: "center" },
  button: { backgroundColor: colors.accent, paddingVertical: 12, paddingHorizontal: 24, borderRadius: 10 },
  buttonText: { color: "#04222b", fontWeight: "700" },
});
