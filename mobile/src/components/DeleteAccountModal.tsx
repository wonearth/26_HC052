import { useEffect, useState } from "react";
import { Modal, View, Text, TextInput, Pressable, StyleSheet, KeyboardAvoidingView, Platform } from "react-native";
import { colors } from "../theme/colors";

interface Props {
  visible: boolean;
  onConfirm: (password: string) => Promise<void>;
  onClose: () => void;
}

export default function DeleteAccountModal({ visible, onConfirm, onClose }: Props) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (visible) {
      setPassword("");
      setError(null);
    }
  }, [visible]);

  const handleConfirm = async () => {
    if (!password) {
      setError("비밀번호를 입력해주세요.");
      return;
    }
    setError(null);
    setDeleting(true);
    try {
      await onConfirm(password);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <KeyboardAvoidingView style={styles.backdrop} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={styles.card}>
          <Text style={styles.title}>정말 계정을 삭제할까요?</Text>
          <Text style={styles.subtitle}>이 작업은 되돌릴 수 없어요. 저장된 라이딩 기록은 이 폰에 그대로 남아요.</Text>
          <TextInput
            style={styles.input}
            value={password}
            onChangeText={setPassword}
            placeholder="비밀번호 확인"
            placeholderTextColor={colors.textMuted}
            secureTextEntry
          />
          {error && <Text style={styles.error}>{error}</Text>}
          <View style={styles.buttonRow}>
            <Pressable style={styles.secondaryButton} onPress={onClose}>
              <Text style={styles.secondaryButtonText}>취소</Text>
            </Pressable>
            <Pressable style={styles.dangerButton} onPress={handleConfirm} disabled={deleting}>
              <Text style={styles.dangerButtonText}>삭제</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", alignItems: "center", justifyContent: "center", padding: 24 },
  card: {
    width: "100%",
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 20,
    gap: 10,
    borderWidth: 1,
    borderColor: colors.border,
  },
  title: { color: colors.text, fontSize: 17, fontWeight: "800" },
  subtitle: { color: colors.textMuted, fontSize: 13, marginBottom: 4 },
  input: {
    backgroundColor: colors.surfaceAlt,
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: colors.text,
    fontSize: 15,
    borderWidth: 1,
    borderColor: colors.border,
  },
  error: { color: colors.danger, fontSize: 12 },
  buttonRow: { flexDirection: "row", justifyContent: "flex-end", gap: 10, marginTop: 4 },
  secondaryButton: { paddingVertical: 10, paddingHorizontal: 14 },
  secondaryButtonText: { color: colors.textMuted, fontSize: 14, fontWeight: "600" },
  dangerButton: { backgroundColor: colors.danger, paddingVertical: 10, paddingHorizontal: 20, borderRadius: 10 },
  dangerButtonText: { color: "#fff", fontWeight: "800", fontSize: 14 },
});
