import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import type { BottomTabScreenProps } from "@react-navigation/bottom-tabs";
import type { CompositeScreenProps } from "@react-navigation/native";

export type MainTabParamList = {
  Home: undefined;
  Report: undefined;
};

export type RootStackParamList = {
  Main: undefined;
  Scan: undefined;
  Ride: { mac: string };
  RideDetail: { rideId: number };
  Settings: undefined;
};

export type MainTabScreenProps<T extends keyof MainTabParamList> = CompositeScreenProps<
  BottomTabScreenProps<MainTabParamList, T>,
  NativeStackScreenProps<RootStackParamList>
>;

export type RootStackScreenProps<T extends keyof RootStackParamList> = NativeStackScreenProps<
  RootStackParamList,
  T
>;
