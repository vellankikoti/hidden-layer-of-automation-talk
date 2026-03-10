"""
K8s Healing Agent — Display Module

Provides rich, color-coded terminal output with emojis, timestamps,
and Unicode box characters for a visually compelling demo experience.
"""

import sys
import time
from datetime import datetime
from typing import Optional


# ── ANSI color codes ──────────────────────────────────────────────────────────
class Color:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    RED     = "\033[91m"
    YELLOW  = "\033[93m"
    GREEN   = "\033[92m"
    CYAN    = "\033[96m"
    MAGENTA = "\033[95m"
    BLUE    = "\033[94m"
    WHITE   = "\033[97m"
    DIM     = "\033[2m"


def _ts() -> str:
    """Return current timestamp string [HH:MM:SS]."""
    return datetime.now().strftime("[%H:%M:%S]")


def _supports_color() -> bool:
    """Return True if the terminal supports ANSI colors."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(color: str, text: str) -> str:
    """Wrap text in ANSI color if supported."""
    if _supports_color():
        return f"{color}{text}{Color.RESET}"
    return text


# ── Public helpers ─────────────────────────────────────────────────────────────

def print_scenario_header(scenario_num: int, title: str) -> None:
    """Print a double-line box header for a scenario."""
    inner = f"  🤖 K8s Healing Agent — Scenario {scenario_num}: {title}  "
    width = max(len(inner), 62)
    bar   = "═" * width
    print()
    print(_c(Color.MAGENTA, f"╔{bar}╗"))
    print(_c(Color.MAGENTA, f"║{inner.ljust(width)}║"))
    print(_c(Color.MAGENTA, f"╚{bar}╝"))
    print()


def print_section_header(label: str) -> None:
    """Print a thin separator with a centered label."""
    pad = "─" * 5
    line = f"  {pad} {label} {pad}"
    print()
    print(_c(Color.MAGENTA, line))
    print()


def print_phase(phase: str, emoji: str, message: str, indent: int = 2) -> None:
    """Print an Agent Loop phase line."""
    prefix = " " * indent
    ts     = _c(Color.DIM, _ts())
    label  = _c(Color.MAGENTA, f"[{phase}]")
    print(f"{prefix}{emoji} {ts} {label} {message}")


def print_info(message: str, indent: int = 5) -> None:
    """Print an informational sub-line."""
    prefix = " " * indent
    print(f"{prefix}{_c(Color.WHITE, message)}")


def print_detect(message: str) -> None:
    """Print a DETECT / warning line."""
    ts = _c(Color.DIM, _ts())
    print(f"  ⚠️  {ts} {_c(Color.YELLOW, message)}")


def print_broken(message: str) -> None:
    """Print a broken-state line."""
    ts = _c(Color.DIM, _ts())
    print(f"  💀 {ts} {_c(Color.RED, message)}")


def print_success(message: str) -> None:
    """Print a success line."""
    ts = _c(Color.DIM, _ts())
    print(f"  ✅ {ts} {_c(Color.GREEN, message)}")


def print_error(message: str) -> None:
    """Print an error line."""
    ts = _c(Color.DIM, _ts())
    print(f"  ❌ {ts} {_c(Color.RED, message)}")


def print_waiting(message: str) -> None:
    """Print a waiting line."""
    ts = _c(Color.DIM, _ts())
    print(f"  ⏳ {ts} {_c(Color.CYAN, message)}")


def print_detail(key: str, value: str, indent: int = 5) -> None:
    """Print a key/value detail line."""
    prefix = " " * indent
    print(f"{prefix}{_c(Color.DIM, key + ':')} {_c(Color.WHITE, value)}")


def print_scenario_complete(scenario_num: int, title: str, elapsed: float) -> None:
    """Print the scenario completion celebration box."""
    elapsed_str = f"{elapsed:.0f} seconds"
    inner = f"  🎉 SCENARIO {scenario_num} COMPLETE — {title} resolved in {elapsed_str}  "
    width = max(len(inner), 62)
    bar   = "═" * width
    print()
    print(_c(Color.GREEN, f"╔{bar}╗"))
    print(_c(Color.GREEN, f"║{inner.ljust(width)}║"))
    print(_c(Color.GREEN, f"╚{bar}╝"))
    print()


def print_main_menu() -> None:
    """Print the main interactive menu."""
    lines = [
        ("", ""),
        ("╔══════════════════════════════════════════════════════════════╗", Color.CYAN),
        ("║        🤖 K8s Healing Agent — AI DevCon India Demo          ║", Color.CYAN),
        ('║        "The Hidden Layer of Automation"                      ║', Color.CYAN),
        ("╠══════════════════════════════════════════════════════════════╣", Color.CYAN),
        ("║                                                              ║", Color.CYAN),
        ("║  [1] 🖼️  Scenario 1: ImagePullBackOff (Wrong Image Tag)     ║", Color.WHITE),
        ("║  [2] 🔄 Scenario 2: CrashLoopBackOff (Bad Health Check)    ║", Color.WHITE),
        ("║  [3] 💾 Scenario 3: OOMKilled (Memory Limit Too Low)       ║", Color.WHITE),
        ("║  [4] 📄 Scenario 4: ConfigMap Missing (Env Config Drift)   ║", Color.WHITE),
        ("║  [5] ⏳ Scenario 5: Pending Pod (Impossible CPU Request)   ║", Color.WHITE),
        ("║                                                              ║", Color.CYAN),
        ("║  [A] 🚀 Run ALL scenarios sequentially                      ║", Color.YELLOW),
        ("║  [C] 🧹 Cleanup all demo resources                          ║", Color.YELLOW),
        ("║  [Q] 👋 Quit                                                ║", Color.YELLOW),
        ("║                                                              ║", Color.CYAN),
        ("╚══════════════════════════════════════════════════════════════╝", Color.CYAN),
        ("", ""),
    ]
    for text, color in lines:
        if not text:
            print()
        else:
            print(_c(color, text))


def print_preflight_header() -> None:
    """Print the preflight check header."""
    print()
    print(_c(Color.CYAN, "╔══════════════════════════════════════════════════════════════╗"))
    print(_c(Color.CYAN, "║           🔍 K8s Healing Agent — Pre-flight Check            ║"))
    print(_c(Color.CYAN, "╚══════════════════════════════════════════════════════════════╝"))
    print()


def spin_wait(message: str, seconds: float, step: float = 0.5) -> None:
    """
    Display an animated spinner while waiting.

    Falls back to a simple print if the terminal does not support
    carriage-return control (e.g. piped output).
    """
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    end_time = time.time() + seconds
    i = 0
    interactive = _supports_color()
    while time.time() < end_time:
        frame = frames[i % len(frames)]
        line  = f"  {frame} {_c(Color.CYAN, message)}"
        if interactive:
            print(f"\r{line}", end="", flush=True)
        else:
            print(line, flush=True)
        time.sleep(step)
        i += 1
    if interactive:
        print()  # newline after spinner
