import { useEffect, useState } from "react";
import { Modal, View, Text, TextInput, Pressable, StyleSheet, KeyboardAvoidingView, Platform } from "react-native";
import { colors } from "../theme/colors";

interface Props {
  visible: boolean;
  onSave: (currentPassword: string, newPassword: string) => Promise<void>;
  onClose: () => void;
}

export default function ChangePasswordModal({ visible, onSave, onClose }: Props) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (visible) {
      setCurrent("");
      setNext("");
      setConfirm("");
      setError(null);
    }
  }, [visible]);

  const handleSave = async () => {
    if (!current || !next) {
      setError("모든 칸을 입력해주세요.");
      return;
    }
    if (next.length < 4) {
      setError("새 비밀번호는 4자 이상으로 해주세요.");
      return;
    }
    if (next !== confirm) {
      setError("새 비밀번호가 서로 달라요.");
      return;
    }
    setError(null);
    setSaving(true);
    try {
      await onSave(current, next);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <KeyboardAvoidingView style={styles.backdrop} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={styles.card}>
          <Text style={styles.title}>비밀번호 변경</Text>
          <TextInput
            style={styles.input}
            value={current}
            onChangeText={setCurrent}
            placeholder="현재 비밀번호"
            placeholderTextColor={colors.textMuted}
            secureTextEntry
          />
          <TextInput
            style={styles.input}
            value={next}
            onChangeText={setNext}
            placeholder="새 비밀번호"
            placeholderTextColor={colors.textMuted}
            secureTextEntry
          />
          <TextInput
            style={styles.input}
            value={confirm}
            onChangeText={setConfirm}
            placeholder="새 비밀번호 확인"
            placeholderTextColor={colors.textMuted}
            secureTextEntry
          />
          {error && <Text style={styles.error}>{error}</Text>}
          <View style={styles.buttonRow}>
            <Pressable style={styles.secondaryButton} onPress={onClose}>
              <Text style={styles.secondaryButtonText}>취소</Text>
            </Pressable>
            <Pressable style={styles.primaryButton} onPress={handleSave} disabled={saving}>
              <Text style={styles.primaryButtonText}>변경</Text>
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
  title: { color: colors.text, fontSize: 17, fontWeight: "800", marginBottom: 4 },
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
  primaryButton: { backgroundColor: colors.accent, paddingVertical: 10, paddingHorizontal: 20, borderRadius: 10 },
  primaryButtonText: { color: "#04222b", fontWeight: "800", fontSize: 14 },
});
