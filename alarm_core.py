"""
Alarm Clock core: domain model, thread-safe store, background engine, and ports.

MVP: one-time alarms, in-memory store, poll-based firing, injectable clock for tests.
v2: persistence, recurring alarms, missed-alarm reconciliation on startup.
"""

from __future__ import annotations

import json
import math
import struct
import sys
import tempfile
import threading
import time
import wave
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Literal, Optional, Protocol

AlarmStatus = Literal["PENDING", "FIRED", "CANCELLED"]


@dataclass
class Alarm:
    id: str
    fire_at: datetime
    label: str
    status: AlarmStatus = "PENDING"


class ClockProvider(Protocol):
    def now(self) -> datetime: ...


class Notifier(Protocol):
    def notify(self, alarm: Alarm) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now()


class FakeClock:
    """Injectable clock for tests and fast-forward demos."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)

    def set(self, moment: datetime) -> None:
        self._now = moment


def _write_beep_wav(
    path: str,
    *,
    duration: float = 0.45,
    frequency: int = 880,
    sample_rate: int = 44100,
    volume: float = 0.9,
) -> None:
    """Write a short sine-wave WAV file (plays through normal speakers/headphones)."""
    n_samples = int(sample_rate * duration)
    with wave.open(path, "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n_samples):
            t = i / sample_rate
            sample = volume * math.sin(2 * math.pi * frequency * t)
            frames.extend(struct.pack("<h", int(sample * 32767)))
        wav_file.writeframes(frames)


def _play_wav_windows(path: str) -> bool:
    import winsound

    winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_SYNC)
    return True


def _play_windows_system_sounds() -> bool:
    """Windows notification sounds (use the normal volume mixer)."""
    import winsound

    for sound_name in ("SystemExclamation", "SystemHand", "SystemQuestion"):
        try:
            winsound.PlaySound(sound_name, winsound.SND_ALIAS | winsound.SND_SYNC)
            time.sleep(0.15)
        except RuntimeError:
            continue
    try:
        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass
    return True


def play_alarm_sound() -> None:
    """
    Play an audible alarm through speakers/headphones.
    On Windows: generated WAV (reliable on laptops) then system sounds.
    """
    if sys.platform == "win32":
        try:
            import winsound

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                wav_path = tmp.name
            try:
                for cycle, freq in enumerate((880, 988, 880, 1046), start=1):
                    _write_beep_wav(wav_path, duration=0.4, frequency=freq)
                    _play_wav_windows(wav_path)
                    if cycle < 4:
                        time.sleep(0.12)
                return
            finally:
                try:
                    import os

                    os.unlink(wav_path)
                except OSError:
                    pass
        except Exception:
            try:
                _play_windows_system_sounds()
                return
            except Exception:
                try:
                    import winsound

                    for _ in range(3):
                        winsound.Beep(880, 400)
                        time.sleep(0.1)
                    return
                except Exception:
                    pass

    print("\a", end="", flush=True)


class StdoutNotifier:
    def notify(self, alarm: Alarm) -> None:
        print()
        print("=" * 50)
        print(f"  ALARM: {alarm.label}  (id={alarm.id})")
        print(f"  Scheduled for {alarm.fire_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 50)
        play_alarm_sound()


def parse_at(time_str: str, now: datetime) -> datetime:
    """
    Parse HH:MM (24h) into the next occurrence in local time.
    If that time already passed today, schedule for tomorrow.
    """
    parts = time_str.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time '{time_str}': expected HH:MM")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"Invalid time '{time_str}': expected HH:MM") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time '{time_str}': hour must be 0-23, minute 0-59")

    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def parse_in(seconds: float) -> timedelta:
    if seconds <= 0:
        raise ValueError("Duration must be positive")
    return timedelta(seconds=seconds)


class AlarmStore:
    """Thread-safe in-memory alarm registry."""

    def __init__(self) -> None:
        self._alarms: List[Alarm] = []
        self._lock = threading.Lock()
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"alarm-{self._counter}"

    def add(self, fire_at: datetime, label: str = "") -> Alarm:
        with self._lock:
            alarm = Alarm(id=self._next_id(), fire_at=fire_at, label=label or "Alarm")
            self._alarms.append(alarm)
            return alarm

    def list_pending(self) -> List[Alarm]:
        with self._lock:
            pending = [a for a in self._alarms if a.status == "PENDING"]
            return sorted(pending, key=lambda a: a.fire_at)

    def list_all(self) -> List[Alarm]:
        with self._lock:
            return sorted(self._alarms, key=lambda a: a.fire_at)

    def remove(self, alarm_id: str) -> bool:
        with self._lock:
            for alarm in self._alarms:
                if alarm.id == alarm_id:
                    alarm.status = "CANCELLED"
                    return True
            return False

    def get_due(self, now: datetime) -> List[Alarm]:
        """Return pending alarms that should fire at or before now."""
        with self._lock:
            return [a for a in self._alarms if a.status == "PENDING" and a.fire_at <= now]

    def mark_fired(self, alarm_id: str) -> None:
        with self._lock:
            for alarm in self._alarms:
                if alarm.id == alarm_id:
                    alarm.status = "FIRED"
                    return

    def save(self, path: Path) -> None:
        with self._lock:
            payload = {
                "counter": self._counter,
                "alarms": [
                    {
                        **asdict(a),
                        "fire_at": a.fire_at.isoformat(),
                    }
                    for a in self._alarms
                ],
            }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "AlarmStore":
        store = cls()
        if not path.exists():
            return store
        data = json.loads(path.read_text(encoding="utf-8"))
        store._counter = int(data.get("counter", 0))
        for item in data.get("alarms", []):
            store._alarms.append(
                Alarm(
                    id=item["id"],
                    fire_at=datetime.fromisoformat(item["fire_at"]),
                    label=item.get("label", ""),
                    status=item.get("status", "PENDING"),
                )
            )
        return store


class AlarmEngine:
    """
    Poll-based background worker. Copies due alarms under lock, then notifies
    outside the lock to avoid holding the lock during I/O.
    """

    def __init__(
        self,
        store: AlarmStore,
        clock: ClockProvider,
        notifier: Notifier,
        poll_interval: float = 0.2,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._notifier = notifier
        self._poll_interval = poll_interval
        self._stop_event = stop_event or threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    def tick(self) -> None:
        now = self._clock.now()
        due = self._store.get_due(now)
        for alarm in due:
            self._store.mark_fired(alarm.id)
            self._notifier.notify(alarm)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self.tick()
            self._stop_event.wait(timeout=self._poll_interval)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, name="alarm-engine", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
