import { useEffect, useState } from "react";
import { View, ActivityIndicator } from "react-native";
import { NavigationContainer, DarkTheme, type Theme } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { StatusBar } from "expo-status-bar";
import MainTabs from "./src/navigation/MainTabs";
import ScanScreen from "./src/screens/ScanScreen";
import RideScreen from "./src/screens/RideScreen";
import RideDetailScreen from "./src/screens/RideDetailScreen";
import LoginScreen from "./src/screens/LoginScreen";
import type { RootStackParamList } from "./src/navigation/types";
import { initDb } from "./src/db/database";
import { colors } from "./src/theme/colors";
import { AuthProvider, useAuth } from "./src/auth/AuthContext";

const Stack = createNativeStackNavigator<RootStackParamList>();

const navTheme: Theme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    background: colors.background,
    card: colors.surface,
    text: colors.text,
    border: colors.border,
    primary: colors.accent,
  },
};

function LoadingScreen() {
  return (
    <View style={{ flex: 1, backgroundColor: colors.background, alignItems: "center", justifyContent: "center" }}>
      <ActivityIndicator color={colors.accent} size="large" />
    </View>
  );
}

function RootNavigator() {
  const { user, loading } = useAuth();

  if (loading) return <LoadingScreen />;

  return (
    <Stack.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: colors.surface },
        headerTintColor: colors.text,
      }}
    >
      {user ? (
        <>
          <Stack.Screen name="Main" component={MainTabs} options={{ headerShown: false }} />
          <Stack.Screen name="Scan" component={ScanScreen} options={{ title: "QR 스캔" }} />
          <Stack.Screen name="Ride" component={RideScreen} options={{ title: "주행 중", headerBackVisible: false }} />
          <Stack.Screen name="RideDetail" component={RideDetailScreen} options={{ title: "라이딩 상세" }} />
        </>
      ) : (
        <Stack.Screen name="Login" component={LoginScreen} options={{ headerShown: false }} />
      )}
    </Stack.Navigator>
  );
}

export default function App() {
  const [dbReady, setDbReady] = useState(false);

  useEffect(() => {
    initDb().then(() => setDbReady(true));
  }, []);

  if (!dbReady) return <LoadingScreen />;

  return (
    <AuthProvider>
      <NavigationContainer theme={navTheme}>
        <StatusBar style="light" />
        <RootNavigator />
      </NavigationContainer>
    </AuthProvider>
  );
}
