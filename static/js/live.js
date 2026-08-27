(function () {
  const timerEl = document.getElementById("timer");
  const speedEl = document.getElementById("stat-speed");
  const distanceEl = document.getElementById("stat-distance");
  const gpsStatusEl = document.getElementById("gps-status");
  const riskBanner = document.getElementById("risk-banner");
  const riskT1 = riskBanner.querySelector(".t1");
  const riskT2 = riskBanner.querySelector(".t2");
  const eventsEl = document.getElementById("stat-events");
  const endBtn = document.getElementById("end-ride-btn");
  const dangerFlash = document.getElementById("danger-flash");

  const startedAtIso = new Date().toISOString();
  const startTime = Date.now();
  let totalDistanceKm = 0;
  let currentSpeedKmh = 0;
  let lastPosition = null;
  let lastRisk = "safe";
  let eventCount = 0;
  let lastBeepTime = 0;

  let audioCtx = null;
  function unlockAudio() {
    if (audioCtx) {
      if (audioCtx.state === "suspended") audioCtx.resume();
      return;
    }
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (Ctx) audioCtx = new Ctx();
  }
  document.addEventListener("touchstart", unlockAudio, { once: true });
  document.addEventListener("click", unlockAudio, { once: true });

  function playAlertBeep() {
    if (!audioCtx) return;
    const now = audioCtx.currentTime;
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "square";
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.25, now + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.18);
    osc.connect(gain).connect(audioCtx.destination);
    osc.start(now);
    osc.stop(now + 0.2);
  }

  const points = [];
  const events = [];

  function generateUuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }
  const rideUuid = generateUuid();

  const PENDING_KEY = "pmadas-pending-rides";

  function loadPending() {
    try {
      return JSON.parse(localStorage.getItem(PENDING_KEY) || "[]");
    } catch (e) {
      return [];
    }
  }

  function savePending(list) {
    try {
      localStorage.setItem(PENDING_KEY, JSON.stringify(list));
    } catch (e) {
      /* localStorage 사용 불가 — 이번 저장만 재시도 큐 없이 진행됨 */
    }
  }

  function queuePendingRide(payload) {
    const list = loadPending();
    list.push(payload);
    savePending(list);
  }

  function removePendingRide(clientRideId) {
    savePending(loadPending().filter((p) => p.client_ride_id !== clientRideId));
  }

  async function uploadRide(payload, attempts) {
    for (let i = 0; i < attempts; i++) {
      try {
        const res = await fetch(window.RIDE_UPLOAD_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          keepalive: true,
          body: JSON.stringify(payload),
        });
        if (res.ok) return true;
      } catch (e) {
        /* 재시도 */
      }
      if (i < attempts - 1) await new Promise((r) => setTimeout(r, 1000 * (i + 1)));
    }
    return false;
  }

  async function flushPendingRides() {
    for (const payload of loadPending()) {
      if (payload.client_ride_id === rideUuid) continue; // 이번 라이딩은 endRide()가 처리
      const ok = await uploadRide(payload, 1);
      if (ok) removePendingRide(payload.client_ride_id);
    }
  }

  if (window.RIDE_TOKEN) flushPendingRides();

  function formatElapsed(ms) {
    const totalSec = Math.floor(ms / 1000);
    const m = String(Math.floor(totalSec / 60)).padStart(2, "0");
    const s = String(totalSec % 60).padStart(2, "0");
    return `${m}:${s}`;
  }

  function toRad(deg) {
    return (deg * Math.PI) / 180;
  }

  function haversineKm(a, b) {
    const R = 6371;
    const dLat = toRad(b.lat - a.lat);
    const dLng = toRad(b.lng - a.lng);
    const lat1 = toRad(a.lat);
    const lat2 = toRad(b.lat);
    const h =
      Math.sin(dLat / 2) ** 2 +
      Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }

  function setGpsStatus(text, level) {
    gpsStatusEl.textContent = text;
    gpsStatusEl.classList.remove("neutral", "safe", "danger");
    gpsStatusEl.classList.add(level);
  }

  timerEl.textContent = formatElapsed(0);
  setInterval(() => {
    timerEl.textContent = formatElapsed(Date.now() - startTime);
  }, 1000);

  if ("geolocation" in navigator) {
    navigator.geolocation.watchPosition(
      (pos) => {
        setGpsStatus("GPS 연결됨", "safe");

        const { latitude, longitude, speed } = pos.coords;
        const here = { lat: latitude, lng: longitude };

        if (lastPosition) {
          const deltaKm = haversineKm(lastPosition, here);
          if (deltaKm > 0.001) {
            totalDistanceKm += deltaKm;
            distanceEl.textContent = totalDistanceKm.toFixed(1);
          }
        }
        lastPosition = here;

        const kmh = speed != null && speed >= 0 ? speed * 3.6 : null;
        currentSpeedKmh = kmh != null ? kmh : currentSpeedKmh;
        speedEl.textContent = kmh != null ? kmh.toFixed(1) : "-";

        points.push({
          lat: latitude,
          lng: longitude,
          recorded_at: new Date().toISOString(),
          risk_level: lastRisk,
        });
      },
      (err) => {
        setGpsStatus(
          err.code === err.PERMISSION_DENIED ? "GPS 권한 필요" : "GPS 오류",
          "danger"
        );
      },
      { enableHighAccuracy: true, maximumAge: 1000, timeout: 10000 }
    );
  } else {
    setGpsStatus("GPS 미지원 브라우저", "danger");
  }

  async function pollLiveState() {
    try {
      const res = await fetch("/api/live_state");
      const data = await res.json();

      riskBanner.classList.remove("safe", "caution", "warning", "danger");
      riskBanner.classList.add(data.risk);
      riskT1.textContent = data.title;
      riskT2.textContent = data.message;

      if (data.risk === "danger") {
        dangerFlash.classList.add("active");
        if (Date.now() - lastBeepTime >= 3000) {
          playAlertBeep();
          lastBeepTime = Date.now();
        }
      } else {
        dangerFlash.classList.remove("active");
      }

      if (data.risk !== "safe" && lastRisk === "safe") {
        eventCount += 1;
        eventsEl.textContent = eventCount;
        events.push({
          occurred_at: new Date().toISOString(),
          risk_level: data.risk,
          object_class: data.class_name || null,
          distance_m: data.distance_m,
          ttc_sec: data.ttc_sec,
          in_collision_zone: !!data.in_collision_zone,
          lat: lastPosition ? lastPosition.lat : null,
          lng: lastPosition ? lastPosition.lng : null,
        });
      }
      lastRisk = data.risk;
    } catch (e) {
      /* 다음 폴링에서 재시도 */
    }
  }

  pollLiveState();
  setInterval(pollLiveState, 1500);

  async function endRide() {
    endBtn.disabled = true;
    endBtn.textContent = "저장 중...";

    const durationSec = Math.max(1, Math.floor((Date.now() - startTime) / 1000));
    const avgSpeedKmh = totalDistanceKm > 0 ? totalDistanceKm / (durationSec / 3600) : 0;

    if (window.RIDE_TOKEN) {
      const payload = {
        token: window.RIDE_TOKEN,
        client_ride_id: rideUuid,
        started_at: startedAtIso,
        ended_at: new Date().toISOString(),
        distance_km: totalDistanceKm,
        duration_sec: durationSec,
        avg_speed_kmh: avgSpeedKmh,
        hard_brake_count: 0,
        points: points,
        events: events,
      };
      // 네트워크가 끊겨도 데이터가 사라지지 않도록 먼저 로컬에 저장해두고,
      // 성공하면 지운다. 여기서 실패해도 다음 라이딩 시작할 때 자동 재시도된다.
      queuePendingRide(payload);
      const ok = await uploadRide(payload, 3);
      if (ok) removePendingRide(rideUuid);
    }

    window.location.href = window.WEB_APP_URL;
  }

  endBtn.addEventListener("click", endRide);
})();
