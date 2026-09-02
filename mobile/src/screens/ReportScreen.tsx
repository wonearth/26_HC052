import { useCallback, useEffect, useState } from "react";
import { View, Text, Pressable, StyleSheet, FlatList } from "react-native";
import { useFocusEffect } from "@react-navigation/native";
import {
  getRideDaysForMonth,
  listRidesForDate,
  type RideDaySummary,
} from "../db/database";
import type { RideSummary } from "../types/ride";
import { colors, riskColor } from "../theme/colors";
import { formatDateKey, formatYearMonth, getMonthMatrix, shiftMonth } from "../utils/calendar";
import type { MainTabScreenProps } from "../navigation/types";

type Props = MainTabScreenProps<"Report">;

const WEEKDAY_LABELS = ["일", "월", "화", "수", "목", "금", "토"];

export default function ReportScreen({ navigation }: Props) {
  const [month, setMonth] = useState(() => new Date());
  const [daySummaries, setDaySummaries] = useState<Map<string, RideDaySummary>>(new Map());
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [ridesForDate, setRidesForDate] = useState<RideSummary[]>([]);

  const loadMonth = useCallback(() => {
    getRideDaysForMonth(formatYearMonth(month)).then((rows) => {
      setDaySummaries(new Map(rows.map((r) => [r.date, r])));
    });
  }, [month]);

  useFocusEffect(
    useCallback(() => {
      loadMonth();
    }, [loadMonth])
  );

  useEffect(() => {
    if (!selectedDate) {
      setRidesForDate([]);
      return;
    }
    listRidesForDate(selectedDate).then(setRidesForDate);
  }, [selectedDate]);

  const weeks = getMonthMatrix(month.getFullYear(), month.getMonth());

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Pressable onPress={() => setMonth((m) => shiftMonth(m, -1))} hitSlop={12}>
          <Text style={styles.navArrow}>‹</Text>
        </Pressable>
        <Text style={styles.monthTitle}>
          {month.getFullYear()}년 {month.getMonth() + 1}월
        </Text>
        <Pressable onPress={() => setMonth((m) => shiftMonth(m, 1))} hitSlop={12}>
          <Text style={styles.navArrow}>›</Text>
        </Pressable>
      </View>

      <View style={styles.weekdayRow}>
        {WEEKDAY_LABELS.map((w) => (
          <Text key={w} style={styles.weekdayLabel}>
            {w}
          </Text>
        ))}
      </View>

      {weeks.map((week, wi) => (
        <View key={wi} style={styles.weekRow}>
          {week.map((day, di) => {
            if (day === null) return <View key={di} style={styles.dayCell} />;
            const dateKey = `${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
            const summary = daySummaries.get(dateKey);
            const isSelected = selectedDate === dateKey;
            return (
              <Pressable
                key={di}
                style={[styles.dayCell, isSelected && styles.dayCellSelected]}
                onPress={() => setSelectedDate(isSelected ? null : dateKey)}
              >
                <Text style={styles.dayNumber}>{day}</Text>
                {summary && (
                  <View style={[styles.dot, { backgroundColor: riskColor[summary.riskLevel] ?? colors.accent }]} />
                )}
              </Pressable>
            );
          })}
        </View>
      ))}

      <Text style={styles.sectionTitle}>
        {selectedDate ? `${selectedDate} 라이딩` : "날짜를 선택하면 그 날의 라이딩이 보여요"}
      </Text>

      <FlatList
        data={ridesForDate}
        keyExtractor={(item) => String(item.id)}
        contentContainerStyle={{ gap: 10, paddingBottom: 24 }}
        ListEmptyComponent={
          selectedDate ? <Text style={styles.emptyText}>이 날은 라이딩이 없어요</Text> : null
        }
        renderItem={({ item }) => (
          <Pressable
            style={styles.rideCard}
            onPress={() => navigation.navigate("RideDetail", { rideId: item.id })}
          >
            <Text style={styles.rideTime}>{new Date(item.started_at).toLocaleTimeString()}</Text>
            <View style={styles.rideStatsRow}>
              <Text style={styles.rideStat}>{item.distance_km.toFixed(1)}km</Text>
              <Text style={styles.rideStat}>안전점수 {item.safety_score}</Text>
              <Text style={styles.rideStat}>급정거 {item.hard_brake_count}회</Text>
            </View>
          </Pressable>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, padding: 20, paddingTop: 24 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 12 },
  navArrow: { color: colors.accent, fontSize: 24, fontWeight: "800", paddingHorizontal: 12 },
  monthTitle: { color: colors.text, fontSize: 17, fontWeight: "800" },
  weekdayRow: { flexDirection: "row", marginBottom: 4 },
  weekdayLabel: { flex: 1, textAlign: "center", color: colors.textMuted, fontSize: 11 },
  weekRow: { flexDirection: "row" },
  dayCell: { flex: 1, aspectRatio: 1, alignItems: "center", justifyContent: "center", borderRadius: 10, gap: 3 },
  dayCellSelected: { backgroundColor: colors.surfaceAlt },
  dayNumber: { color: colors.text, fontSize: 13 },
  dot: { width: 6, height: 6, borderRadius: 3 },
  sectionTitle: { color: colors.textMuted, fontSize: 13, marginTop: 16, marginBottom: 8 },
  emptyText: { color: colors.textMuted, fontSize: 13, paddingVertical: 20, textAlign: "center" },
  rideCard: {
    backgroundColor: colors.surface,
    borderRadius: 14,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 8,
  },
  rideTime: { color: colors.text, fontWeight: "700", fontSize: 15 },
  rideStatsRow: { flexDirection: "row", gap: 16 },
  rideStat: { color: colors.textMuted, fontSize: 13 },
});
