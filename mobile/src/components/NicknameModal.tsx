import { useEffect, useState } from "react";
import { Modal, View, Text, TextInput, Pressable, StyleSheet, KeyboardAvoidingView, Platform } from "react-native";
import { colors } from "../theme/colors";

interface Props {
  visible: boolean;
  initialValue?: string;
  onSave: (nickname: string) => void;
  onClose?: () => void;
}

export default function NicknameModal({ visible, initialValue, onSave, onClose }: Props) {
  const [value, setValue] = useState(initialValue ?? "");

  useEffect(() => {
    if (visible) setValue(initialValue ?? "");
  }, [visible, initialValue]);

  const handleSave = () => {
    const trimmed = value.trim();
    if (!trimmed) return;
    onSave(trimmed);
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={styles.backdrop}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <View style={styles.card}>
          <Text style={styles.title}>닉네임을 알려주세요</Text>
          <Text style={styles.subtitle}>홈 화면 인사말에 쓰여요</Text>
          <TextInput
            style={styles.input}
            value={value}
            onChangeText={setValue}
            placeholder="예: 지원"
            placeholderTextColor={colors.textMuted}
            maxLength={12}
            autoFocus
            returnKeyType="done"
            onSubmitEditing={handleSave}
          />
          <View style={styles.buttonRow}>
            {onClose && (
              <Pressable style={styles.secondaryButton} onPress={onClose}>
                <Text style={styles.secondaryButtonText}>나중에</Text>
              </Pressable>
            )}
            <Pressable
              style={[styles.primaryButton, !value.trim() && styles.primaryButtonDisabled]}
              onPress={handleSave}
              disabled={!value.trim()}
            >
              <Text style={styles.primaryButtonText}>완료</Text>
            </Pressable>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  card: {
    width: "100%",
    backgroundColor: colors.surface,
    borderRadius: 16,
    padding: 20,
    gap: 12,
    borderWidth: 1,
    borderColor: colors.border,
  },
  title: { color: colors.text, fontSize: 17, fontWeight: "800" },
  subtitle: { color: colors.textMuted, fontSize: 12, marginTop: -8 },
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
  buttonRow: { flexDirection: "row", justifyContent: "flex-end", gap: 10, marginTop: 4 },
  secondaryButton: { paddingVertical: 10, paddingHorizontal: 14 },
  secondaryButtonText: { color: colors.textMuted, fontSize: 14, fontWeight: "600" },
  primaryButton: { backgroundColor: colors.accent, paddingVertical: 10, paddingHorizontal: 20, borderRadius: 10 },
  primaryButtonDisabled: { opacity: 0.4 },
  primaryButtonText: { color: "#04222b", fontWeight: "800", fontSize: 14 },
});
