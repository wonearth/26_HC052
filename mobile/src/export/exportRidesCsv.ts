import * as FileSystem from "expo-file-system/legacy";
import * as Sharing from "expo-sharing";
import { listRides } from "../db/database";

const CSV_HEADER = ["날짜", "거리(km)", "시간(분)", "평균속도(km/h)", "최고속도(km/h)", "급정거(회)", "안전점수"];

function formatDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(
    d.getHours()
  ).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** 라이딩 기록을 한 건당 한 줄인 CSV로 만들어 폰의 공유하기 메뉴로 내보낸다. */
export async function exportRidesAsCsv(): Promise<void> {
  const rides = await listRides();
  if (rides.length === 0) {
    throw new Error("내보낼 라이딩 기록이 없습니다.");
  }

  const rows = rides.map((r) =>
    [
      formatDate(r.started_at),
      r.distance_km.toFixed(2),
      (r.duration_sec / 60).toFixed(1),
      r.avg_speed_kmh.toFixed(1),
      r.max_speed_kmh.toFixed(1),
      String(r.hard_brake_count),
      String(r.safety_score),
    ].join(",")
  );
  const csv = [CSV_HEADER.join(","), ...rows].join("\n");

  const fileUri = `${FileSystem.cacheDirectory}pmadas_rides.csv`;
  await FileSystem.writeAsStringAsync(fileUri, csv, { encoding: "utf8" });

  const canShare = await Sharing.isAvailableAsync();
  if (!canShare) {
    throw new Error("이 기기에서는 공유하기를 지원하지 않습니다.");
  }
  await Sharing.shareAsync(fileUri, {
    mimeType: "text/csv",
    dialogTitle: "라이딩 기록 내보내기",
    UTI: "public.comma-separated-values-text",
  });
}
