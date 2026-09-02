import type { RideEvent, RidePoint } from "../types/ride";
import { colors, riskColor } from "../theme/colors";

interface RiskSegment {
  risk: string;
  points: RidePoint[];
}

export function groupPointsByRisk(points: RidePoint[]): RiskSegment[] {
  const segments: RiskSegment[] = [];
  for (const point of points) {
    const last = segments[segments.length - 1];
    if (last && last.risk === point.risk_level) {
      last.points.push(point);
    } else {
      segments.push({
        risk: point.risk_level,
        points: last ? [last.points[last.points.length - 1], point] : [point],
      });
    }
  }
  return segments;
}

/**
 * 웹 리포트(web/templates/report_detail.html)와 같은 방식 — 무료 OSM 타일 + Leaflet.
 * react-native-maps(Google Maps) 대신 웹뷰로 띄워서 API 키/결제 등록이 전혀 필요 없음.
 */
export function buildRideMapHtml(points: RidePoint[], events: RideEvent[]): string {
  const segments = groupPointsByRisk(points).map((seg) => ({
    risk: seg.risk,
    latlngs: seg.points.map((p) => [p.lat, p.lng]),
  }));
  const eventPins = events.map((e) => ({
    lat: e.lat,
    lng: e.lng,
    risk: e.risk_level,
    desc: `${e.risk_level} · ${e.object_class} · ${e.distance_m.toFixed(1)}m`,
  }));

  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
  integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<style>
  html, body, #map { height: 100%; margin: 0; background: ${colors.background}; }
  .leaflet-tile-pane { filter: invert(1) hue-rotate(180deg) brightness(0.92) contrast(0.9) saturate(0.8); }
  .leaflet-control-attribution { font-size: 9px; }
</style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
  integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
(function () {
  const segments = ${JSON.stringify(segments)};
  const events = ${JSON.stringify(eventPins)};
  const riskColors = ${JSON.stringify({
    안전: colors.safe,
    주의: colors.caution,
    경고: colors.warning,
    위험: colors.danger,
  })};

  const map = L.map("map", { zoomControl: false, attributionControl: true });

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 19,
  }).addTo(map);

  const allLatLngs = [];
  segments.forEach((seg) => {
    L.polyline(seg.latlngs, {
      color: riskColors[seg.risk] || "${colors.accent}",
      weight: 4,
      lineCap: "round",
    }).addTo(map);
    allLatLngs.push(...seg.latlngs);
  });

  events.forEach((e) => {
    L.circleMarker([e.lat, e.lng], {
      radius: 6,
      color: riskColors[e.risk] || "${colors.danger}",
      fillColor: riskColors[e.risk] || "${colors.danger}",
      fillOpacity: 0.9,
      weight: 2,
    }).bindPopup(e.desc).addTo(map);
  });

  if (allLatLngs.length > 0) {
    map.fitBounds(allLatLngs, { padding: [16, 16] });
  }
})();
</script>
</body>
</html>`;
}
