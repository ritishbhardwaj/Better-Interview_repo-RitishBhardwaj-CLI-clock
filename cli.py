"""
CLI layer for the Alarm Clock application.

Run with no arguments for an interactive menu:
    python AlarmClock.py
"""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path
from typing import Optional

from alarm_core import (
    AlarmEngine,
    AlarmStore,
    StdoutNotifier,
    SystemClock,
    parse_at,
    parse_in,
)

_STORE: Optional[AlarmStore] = None
_STORE_PATH = Path(__file__).resolve().parent / ".alarms.json"

MENU = """
========================================
           ALARM CLOCK
========================================
  1  Add alarm (rings in X seconds)
  2  Add alarm (rings at HH:MM today/tomorrow)
  3  List my alarms
  4  Remove an alarm
  5  Start the clock (wait for alarms)
  6  Quit
========================================
"""


def get_store() -> AlarmStore:
    global _STORE
    if _STORE is None:
        _STORE = AlarmStore.load(_STORE_PATH)
    return _STORE


def persist_store() -> None:
    get_store().save(_STORE_PATH)


def add_alarm_in(seconds: float, label: str = "") -> int:
    clock = SystemClock()
    try:
        fire_at = clock.now() + parse_in(seconds)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2
    alarm = get_store().add(fire_at, label)
    persist_store()
    print(f"Added {alarm.id} — rings at {alarm.fire_at.strftime('%H:%M:%S')} ({label or 'Alarm'})")
    return 0


def add_alarm_at(time_str: str, label: str = "") -> int:
    clock = SystemClock()
    try:
        fire_at = parse_at(time_str, clock.now())
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2
    alarm = get_store().add(fire_at, label)
    persist_store()
    print(f"Added {alarm.id} — rings at {alarm.fire_at.strftime('%Y-%m-%d %H:%M:%S')} ({label or 'Alarm'})")
    return 0


def show_alarms() -> None:
    pending = get_store().list_pending()
    if not pending:
        print("No alarms set.")
        return
    print("\nYour alarms:")
    for alarm in pending:
        print(
            f"  {alarm.id}  |  {alarm.fire_at.strftime('%Y-%m-%d %H:%M:%S')}  |  {alarm.label}"
        )
    print()


def remove_alarm(alarm_id: str) -> int:
    if not get_store().remove(alarm_id):
        print(f"Error: no alarm with id '{alarm_id}'")
        return 1
    persist_store()
    print(f"Removed {alarm_id}")
    return 0


def start_clock() -> int:
    store = get_store()
    clock = SystemClock()
    notifier = StdoutNotifier()
    stop_event = __import__("threading").Event()
    engine = AlarmEngine(store, clock, notifier, poll_interval=0.2, stop_event=stop_event)

    def handle_signal(_signum, _frame):
        print("\nStopping clock...")
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)

    pending = store.list_pending()
    print(f"\nClock is running. {len(pending)} alarm(s) waiting.")
    print("Leave this window open. Press Ctrl+C when you are done.\n")
    engine.start()
    try:
        while not stop_event.is_set():
            stop_event.wait(timeout=0.5)
    finally:
        engine.stop()
        persist_store()
    return 0


def run_interactive() -> int:
    print("Welcome! Choose a number from the menu.\n")
    while True:
        print(MENU)
        choice = input("Enter choice (1-6): ").strip()

        if choice == "1":
            raw = input("Ring in how many seconds? (e.g. 5): ").strip()
            try:
                seconds = float(raw)
            except ValueError:
                print("Please enter a number.\n")
                continue
            label = input("Label (optional, press Enter to skip): ").strip()
            add_alarm_in(seconds, label)
            print()

        elif choice == "2":
            time_str = input("Ring at what time? (HH:MM, 24-hour, e.g. 09:30): ").strip()
            label = input("Label (optional, press Enter to skip): ").strip()
            add_alarm_at(time_str, label)
            print()

        elif choice == "3":
            show_alarms()

        elif choice == "4":
            show_alarms()
            alarm_id = input("Alarm id to remove (e.g. alarm-1): ").strip()
            if alarm_id:
                remove_alarm(alarm_id)
            print()

        elif choice == "5":
            if not get_store().list_pending():
                print("No alarms yet. Use option 1 or 2 first.\n")
                continue
            start_clock()
            print()

        elif choice == "6":
            print("Goodbye!")
            return 0

        else:
            print("Invalid choice. Pick 1 through 6.\n")


# --- argparse (optional, for scripts/tests) ---

def cmd_add(args: argparse.Namespace) -> int:
    if args.at is not None:
        return add_alarm_at(args.at, args.label or "")
    if args.in_seconds is not None:
        return add_alarm_in(args.in_seconds, args.label or "")
    print("error: specify --at HH:MM or --in SECONDS", file=sys.stderr)
    return 2


def cmd_list(_args: argparse.Namespace) -> int:
    show_alarms()
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    return remove_alarm(args.id)


def cmd_run(args: argparse.Namespace) -> int:
    store = get_store()
    clock = SystemClock()
    notifier = StdoutNotifier()
    stop_event = __import__("threading").Event()
    poll_sec = max(args.poll_ms / 1000.0, 0.05)
    engine = AlarmEngine(store, clock, notifier, poll_interval=poll_sec, stop_event=stop_event)

    def handle_signal(_signum, _frame):
        print("\nShutting down...")
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)

    pending = store.list_pending()
    print(f"Alarm clock running ({len(pending)} pending). Press Ctrl+C to stop.")
    engine.start()
    try:
        while not stop_event.is_set():
            stop_event.wait(timeout=0.5)
    finally:
        engine.stop()
        persist_store()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="One-time alarm clock CLI.")
    sub = parser.add_subparsers(dest="command")

    add_p = sub.add_parser("add", help="Schedule a one-time alarm")
    add_p.add_argument("--at", metavar="HH:MM", help="Absolute local time (24h)")
    add_p.add_argument("--in", dest="in_seconds", type=float, metavar="SECONDS", help="Relative delay")
    add_p.add_argument("--label", default="", help="Optional label")
    add_p.set_defaults(func=cmd_add)

    list_p = sub.add_parser("list", help="List pending alarms")
    list_p.set_defaults(func=cmd_list)

    remove_p = sub.add_parser("remove", help="Cancel a pending alarm")
    remove_p.add_argument("id", help="Alarm id (e.g. alarm-1)")
    remove_p.set_defaults(func=cmd_remove)

    run_p = sub.add_parser("run", help="Start background monitor until Ctrl+C")
    run_p.add_argument("--poll-ms", type=int, default=200, help="Poll interval in milliseconds")
    run_p.set_defaults(func=cmd_run)

    return parser


def main(argv: Optional[list] = None) -> int:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    if not args_list:
        return run_interactive()

    parser = build_parser()
    ns = parser.parse_args(args_list)
    if not hasattr(ns, "func"):
        parser.print_help()
        return 2
    return ns.func(ns)


if __name__ == "__main__":
    sys.exit(main())
