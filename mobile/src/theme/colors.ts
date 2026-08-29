// 웹(web/static/css/style.css)과 동일한 톤 — 다크 배경 + 사이언 블루 포인트
export const colors = {
  background: "#0B1220",
  surface: "#131B2C",
  surfaceAlt: "#1B2740",
  border: "#26324A",
  text: "#E7ECF7",
  textMuted: "#8B98B5",
  accent: "#22D3EE",
  accentSoft: "#0E3A45",
  safe: "#22C55E",
  caution: "#EAB308",
  warning: "#F97316",
  danger: "#EF4444",
};

export const riskColor: Record<string, string> = {
  안전: colors.safe,
  주의: colors.caution,
  경고: colors.warning,
  위험: colors.danger,
};
