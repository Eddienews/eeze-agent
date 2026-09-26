"""Diagnose unexpected keyboard input — hardware vs software attribution.

Two capture paths run together:

1. **Raw Input** (RIDEV_INPUTSINK): sees HARDWARE devices only; every keydown is
   attributed to a physical device (VID/PID). Software-injected keys never appear
   here.
2. **Low-level keyboard hook** (WH_KEYBOARD_LL): sees every keydown including
   injected ones; ``KBDLLHOOKSTRUCT.flags`` tells us: ``0x10`` (LLKHF_INJECTED) =
   software (SendInput), ``0x02`` = lower-IL injection, no flags = hardware path.

Cross-referencing the two gives a verdict for a key storm (e.g., the "v-storm",
2026-09-18 — see docs/SPIKES.md): a physical keyboard bouncing/stuck, or a software
process injecting keys.

Usage:
    python tools/diagnose_input.py --seconds 60 [--json out.json] [--key v]
    uv run eeze doctor input --seconds 60

Exit summary: counts, per-device attribution, max rate, verdict line.
Windows only.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import sys
import time
from collections import Counter
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

# ---- win32 constants ----------------------------------------------------------
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_INPUT = 0x00FF
PM_REMOVE = 0x0001
RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007
RIM_TYPEKEYBOARD = 1
RIDEV_INPUTSINK = 0x00000100
LLKHF_INJECTED = 0x10
LLKHF_LOWER_IL = 0x02
HWND_MESSAGE = ctypes.c_void_p(-3)


def _load_user32():
    if not IS_WINDOWS:
        raise RuntimeError("diagnose_input is Windows-only")
    return ctypes.windll.user32


if IS_WINDOWS:
    user32 = _load_user32()

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wt.DWORD),
            ("scanCode", wt.DWORD),
            ("flags", wt.DWORD),
            ("time", wt.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    class RAWINPUTDEVICE(ctypes.Structure):
        _fields_ = [
            ("usUsagePage", wt.USHORT),
            ("usUsage", wt.USHORT),
            ("dwFlags", wt.DWORD),
            ("hwndTarget", wt.HWND),
        ]

    class RAWINPUTHEADER(ctypes.Structure):
        _fields_ = [
            ("dwType", wt.DWORD),
            ("dwSize", wt.DWORD),
            ("hDevice", wt.HANDLE),
            ("wParam", wt.WPARAM),
        ]

    class RAWKEYBOARD(ctypes.Structure):
        _fields_ = [
            ("MakeCode", wt.USHORT),
            ("Flags", wt.USHORT),
            ("Reserved", wt.USHORT),
            ("VKey", wt.USHORT),
            ("Message", wt.UINT),
            ("ExtraInformation", wt.ULONG),
        ]

    class _RAWINPUT(ctypes.Structure):
        _fields_ = [("header", RAWINPUTHEADER), ("keyboard", RAWKEYBOARD)]

    HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)
    user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.GetRawInputData.argtypes = [
        wt.HANDLE, wt.UINT, ctypes.c_void_p, ctypes.POINTER(wt.UINT), wt.UINT,
    ]
    user32.GetRawInputData.restype = wt.UINT
    user32.GetRawInputDeviceInfoW.argtypes = [
        wt.HANDLE, wt.UINT, ctypes.c_void_p, ctypes.POINTER(wt.UINT),
    ]
    user32.GetRawInputDeviceInfoW.restype = wt.UINT
else:  # pragma: no cover - import-time guards for non-Windows dev
    KBDLLHOOKSTRUCT = RAWINPUTDEVICE = RAWINPUTHEADER = None  # type: ignore[assignment]
    RAWKEYBOARD = _RAWINPUT = HOOKPROC = None  # type: ignore[assignment]


def _device_name(handle) -> str:
    size = wt.UINT(0)
    user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, None, ctypes.byref(size))
    if not size.value:
        return "?"
    buf = ctypes.create_unicode_buffer(size.value)
    user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, buf, ctypes.byref(size))
    raw = buf.value
    for part in raw.split("#"):
        if part.upper().startswith("VID_"):
            return part
    return raw[:120]


def run_diagnosis(seconds: int = 60, key_vk: int = 0x56, key_name: str = "v") -> dict:
    """Capture keyboard events for ``seconds``; return a structured report."""
    if not IS_WINDOWS:
        return {"error": "Windows only"}

    ll_events: list[dict] = []
    raw_events: list[dict] = []
    ll_keydowns = 0
    t0 = time.time()

    def _hook_cb(n_code, w_param, l_param):
        nonlocal ll_keydowns
        if n_code == 0 and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
            ll_keydowns += 1
            ks = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT))[0]
            if int(ks.vkCode) == key_vk:
                flags = int(ks.flags)
                ll_events.append(
                    {
                        "t": round(time.time() - t0, 2),
                        "scan": int(ks.scanCode),
                        "flags": flags,
                        "injected": bool(flags & LLKHF_INJECTED),
                        "lower_il": bool(flags & LLKHF_LOWER_IL),
                    }
                )
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    # raw input target: message-only window
    hwnd = user32.CreateWindowExW(
        0, "STATIC", "eeze-diag", 0, 0, 0, 0, 0, HWND_MESSAGE, None, None, None
    )
    rid = RAWINPUTDEVICE(0x01, 0x06, RIDEV_INPUTSINK, hwnd)
    raw_ok = bool(
        user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE))
    )

    proc = HOOKPROC(_hook_cb)
    hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, None, 0)

    msg = wt.MSG()
    deadline = time.time() + seconds
    while time.time() < deadline:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            if msg.message == WM_INPUT:
                size = wt.UINT(0)
                user32.GetRawInputData(
                    msg.lParam, RID_INPUT, None, ctypes.byref(size),
                    ctypes.sizeof(RAWINPUTHEADER),
                )
                if size.value:
                    buf = ctypes.create_string_buffer(size.value)
                    user32.GetRawInputData(
                        msg.lParam, RID_INPUT, buf, ctypes.byref(size),
                        ctypes.sizeof(RAWINPUTHEADER),
                    )
                    ri = ctypes.cast(buf, ctypes.POINTER(_RAWINPUT)).contents
                    if ri.header.dwType == RIM_TYPEKEYBOARD:
                        kb = ri.keyboard
                        if int(kb.VKey) == key_vk and int(kb.Message) == WM_KEYDOWN:
                            raw_events.append(
                                {
                                    "t": round(time.time() - t0, 2),
                                    "make": int(kb.MakeCode),
                                    "device": _device_name(ri.header.hDevice),
                                }
                            )
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.015)

    user32.UnhookWindowsHookEx(hook)

    hw_events = [e for e in ll_events if not e["injected"]]
    inj_events = [e for e in ll_events if e["injected"]]
    per_second = Counter(int(e["t"]) for e in ll_events)
    max_rate = max(per_second.values()) if per_second else 0
    devices = Counter(e["device"] for e in raw_events)

    if raw_events:
        verdict = f"hardware:{devices.most_common(1)[0][0]}"
    elif inj_events:
        verdict = "software_injection"
    elif hw_events:
        verdict = "hardware_path_unattributed"  # e.g., raw registration failed
    else:
        verdict = "no_key_activity"

    return {
        "seconds": seconds,
        "key": key_name,
        "hook_installed": bool(hook),
        "raw_registered": raw_ok,
        "ll_keydowns_total": ll_keydowns,
        "key_events_ll": len(ll_events),
        "key_hardware_path": len(hw_events),
        "key_injected": len(inj_events),
        "key_events_raw": len(raw_events),
        "devices": dict(devices),
        "max_rate_per_s": max_rate,
        "verdict": verdict,
        "ll_detail": ll_events[:200],
        "raw_detail": raw_events[:200],
    }


def print_report(report: dict) -> None:
    if "error" in report:
        print("error:", report["error"])
        return
    print("== input diagnosis ==")
    print(f"window: {report['seconds']}s · key watched: '{report['key']}'")
    print(f"hook installed: {report['hook_installed']} · raw registered: {report['raw_registered']}")
    print(f"key events  — LL hook: {report['key_events_ll']} "
          f"(hardware-path {report['key_hardware_path']}, injected {report['key_injected']})"
          f" · raw input: {report['key_events_raw']}")
    print(f"max rate: {report['max_rate_per_s']}/s")
    if report["devices"]:
        print(f"devices seen: {report['devices']}")
    print(f"VERDICT: {report['verdict']}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Diagnose unexpected keyboard input (Windows)")
    p.add_argument("--seconds", type=int, default=60)
    p.add_argument("--key", default="v", help="key to watch (single character)")
    p.add_argument("--json", default=None, help="write the full report to this file")
    args = p.parse_args(argv)

    key_vk = ord(args.key.upper()[:1]) if args.key else 0x56
    report = run_diagnosis(seconds=args.seconds, key_vk=key_vk, key_name=args.key)
    print_report(report)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("saved:", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
