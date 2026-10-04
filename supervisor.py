"""
스레드 감시: 센서/통신 스레드가 예외로 죽거나 그냥 반환해도 로그를 남기고 자동으로 다시 시작한다.

- 재시작 간격은 1초, 2초, 4초 ... 최대 10초로 늘어난다 (제대로 오래 돌았으면 다시 1초부터).
- 60초 안에 5번 이상 죽으면 "failed"로 표시하고 30초 간격으로 천천히 계속 재시도한다
  (USB를 다시 꽂는 등 하드웨어가 돌아오면 사람이 손대지 않아도 복구되게 하려고 완전히 멈추진 않음).
"""
import threading
import time
import traceback
from collections import deque

_health = {}
_health_lock = threading.Lock()


def _set_health(name, **fields):
    with _health_lock:
        entry = _health.setdefault(name, {"state": "starting", "restarts": 0, "last_error": None})
        entry.update(fields)


def get_health():
    with _health_lock:
        return {name: dict(entry) for name, entry in _health.items()}


def run_supervised(
    name, target, args=(), kwargs=None, *,
    min_backoff=1.0, max_backoff=10.0,
    crash_window=60.0, crash_limit=5, slow_retry=30.0,
    log=print,
):
    kwargs = kwargs or {}

    def runner():
        crashes = deque()
        backoff = min_backoff
        restarts = 0
        _set_health(name, state="running", restarts=0, last_error=None)
        while True:
            started = time.monotonic()
            error = None
            try:
                target(*args, **kwargs)
                error = "반환됨 (이 스레드는 계속 돌아야 함)"
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                log(f"❌ [{name}] 스레드 예외:\n{traceback.format_exc()}")

            now = time.monotonic()
            if now - started >= crash_window:  # 오래 정상 동작했으면 실패 기록 초기화
                crashes.clear()
                backoff = min_backoff
            crashes.append(now)
            while crashes and now - crashes[0] > crash_window:
                crashes.popleft()

            restarts += 1
            if len(crashes) >= crash_limit:
                delay = slow_retry
                _set_health(name, state="failed", restarts=restarts, last_error=error)
                log(f"🚨 [{name}] {crash_window:.0f}초 안에 {len(crashes)}번 종료 — {delay:.0f}초 간격으로 천천히 재시도")
            else:
                delay = backoff
                backoff = min(backoff * 2, max_backoff)
                _set_health(name, state="restarting", restarts=restarts, last_error=error)
                log(f"🔄 [{name}] {delay:.0f}초 후 재시작 ({error})")

            time.sleep(delay)
            _set_health(name, state="running")

    thread = threading.Thread(target=runner, daemon=True, name=f"supervised-{name}")
    thread.start()
    return thread
