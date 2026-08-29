import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import HomeScreen from "../screens/HomeScreen";
import ReportScreen from "../screens/ReportScreen";
import { colors } from "../theme/colors";
import type { MainTabParamList } from "./types";

const Tab = createBottomTabNavigator<MainTabParamList>();

export default function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.textMuted,
        tabBarStyle: { backgroundColor: colors.surface, borderTopColor: colors.border },
      }}
    >
      <Tab.Screen name="Home" component={HomeScreen} options={{ title: "홈" }} />
      <Tab.Screen name="Report" component={ReportScreen} options={{ title: "리포트" }} />
    </Tab.Navigator>
  );
}
