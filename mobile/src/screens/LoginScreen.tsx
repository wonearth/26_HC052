import { useState } from "react";
import { View, Text, TextInput, Pressable, StyleSheet, Alert, KeyboardAvoidingView, Platform } from "react-native";
import { logIn, signUp } from "../db/database";
import { useAuth } from "../auth/AuthContext";
import { colors } from "../theme/colors";

type Mode = "login" | "signup";

export default function LoginScreen() {
  const { setUser } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [nickname, setNickname] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const resetFields = () => {
    setPassword("");
    setConfirmPassword("");
  };

  const handleSubmit = async () => {
    const trimmedNickname = nickname.trim();
    if (!trimmedNickname || !password) {
      Alert.alert("입력 확인", "닉네임과 비밀번호를 모두 입력해주세요.");
      return;
    }
    if (mode === "signup" && password !== confirmPassword) {
      Alert.alert("입력 확인", "비밀번호가 서로 달라요.");
      return;
    }
    if (mode === "signup" && password.length < 4) {
      Alert.alert("입력 확인", "비밀번호는 4자 이상으로 해주세요.");
      return;
    }

    setSubmitting(true);
    try {
      const user = mode === "login" ? await logIn(trimmedNickname, password) : await signUp(trimmedNickname, password);
      setUser(user);
    } catch (e) {
      Alert.alert(mode === "login" ? "로그인 실패" : "회원가입 실패", e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <Text style={styles.title}>PM ADAS</Text>
      <Text style={styles.subtitle}>{mode === "login" ? "다시 만나 반가워요" : "새 계정을 만들어요"}</Text>

      <View style={styles.form}>
        <TextInput
          style={styles.input}
          value={nickname}
          onChangeText={setNickname}
          placeholder="닉네임"
          placeholderTextColor={colors.textMuted}
          maxLength={12}
          autoCapitalize="none"
        />
        <TextInput
          style={styles.input}
          value={password}
          onChangeText={setPassword}
          placeholder="비밀번호"
          placeholderTextColor={colors.textMuted}
          secureTextEntry
        />
        {mode === "signup" && (
          <TextInput
            style={styles.input}
            value={confirmPassword}
            onChangeText={setConfirmPassword}
            placeholder="비밀번호 확인"
            placeholderTextColor={colors.textMuted}
            secureTextEntry
          />
        )}
      </View>

      <Pressable style={styles.primaryButton} onPress={handleSubmit} disabled={submitting}>
        <Text style={styles.primaryButtonText}>{mode === "login" ? "로그인" : "회원가입"}</Text>
      </Pressable>

      <Pressable
        onPress={() => {
          setMode(mode === "login" ? "signup" : "login");
          resetFields();
        }}
      >
        <Text style={styles.switchText}>
          {mode === "login" ? "계정이 없으신가요? 회원가입" : "이미 계정이 있으신가요? 로그인"}
        </Text>
      </Pressable>

      <Text style={styles.hint}>이 계정은 이 폰 안에만 저장돼요 (다른 기기와 공유되지 않아요)</Text>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
    alignItems: "center",
    justifyContent: "center",
    padding: 28,
    gap: 16,
  },
  title: { color: colors.text, fontSize: 30, fontWeight: "800" },
  subtitle: { color: colors.textMuted, fontSize: 14, marginTop: -8, marginBottom: 8 },
  form: { width: "100%", gap: 10 },
  input: {
    backgroundColor: colors.surface,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
    color: colors.text,
    fontSize: 15,
    borderWidth: 1,
    borderColor: colors.border,
    width: "100%",
  },
  primaryButton: {
    backgroundColor: colors.accent,
    borderRadius: 14,
    paddingVertical: 16,
    alignItems: "center",
    width: "100%",
    marginTop: 4,
  },
  primaryButtonText: { color: "#04222b", fontWeight: "800", fontSize: 15 },
  switchText: { color: colors.accent, fontSize: 13, fontWeight: "600", marginTop: 4 },
  hint: { color: colors.textMuted, fontSize: 11, marginTop: 24, textAlign: "center" },
});
