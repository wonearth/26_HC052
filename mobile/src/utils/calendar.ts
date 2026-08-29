export function formatYearMonth(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function formatDateKey(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function shiftMonth(d: Date, delta: number): Date {
  return new Date(d.getFullYear(), d.getMonth() + delta, 1);
}

/** 7일씩 끊은 주 단위 배열. null은 그 달에 속하지 않는 빈 칸. */
export function getMonthMatrix(year: number, month: number): (number | null)[][] {
  const firstDay = new Date(year, month, 1);
  const startWeekday = firstDay.getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const cells: (number | null)[] = [];
  for (let i = 0; i < startWeekday; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);

  const weeks: (number | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}
