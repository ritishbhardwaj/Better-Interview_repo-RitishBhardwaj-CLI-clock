# Alarm Clock

Set alarms from your terminal. When time is up, you get an on-screen alert and **beeps through your speakers** (Windows).

---

## Quick start

**Need:** [Python 3.8+](https://www.python.org/downloads/) · Windows for sound · Volume up

```bash
cd "Better OA"
pip install -r requirements.txt
python AlarmClock.py
```

**30-second demo:** Press `1` → type `5` → Enter → Press `5` → wait for beeps → Ctrl+C → `6` to quit.

**Test sound only:**

```bash
python -c "from alarm_core import play_alarm_sound; play_alarm_sound()"
```

---

## Menu

| Key | Action |
|-----|--------|
| 1 | Alarm in X seconds |
| 2 | Alarm at HH:MM (24-hour) |
| 3 | List alarms |
| 4 | Remove alarm |
| 5 | Start clock (stay on this screen until alarm rings) |
| 6 | Quit |

---

## No sound?

- Turn up Windows volume · check headphones/speakers · Python not muted in Volume Mixer
- Run the **test sound** command above

---

## More (optional)

**Script mode** (no menu):

```bash
python AlarmClock.py add --in 10 --label "tea"
python AlarmClock.py list
python AlarmClock.py run
```

**Tests** (from parent folder):

```bash
python -m unittest test_alarm.py test_alarm_cli.py -v
```

**Files:** `AlarmClock.py` (run this) · `alarm_core.py` · `cli.py` · `.alarms.json` (auto-created)
