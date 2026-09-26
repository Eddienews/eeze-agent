"""Tunnel PID reuse must never kill an unrelated desktop process."""
import json
from types import SimpleNamespace

from eeze_agent.api import tunnel


def test_process_identity_requires_cloudflared_local_quick_tunnel(monkeypatch):
    row = {
        "Name": "cloudflared.exe",
        "ExecutablePath": "C:\\tools\\cloudflared.exe",
        "CommandLine": '"C:\\tools\\cloudflared.exe" tunnel --url http://127.0.0.1:8765 --no-autoupdate',
        "CreationDate": "2026-09-24T10:00:00",
    }
    monkeypatch.setattr(tunnel.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps(row)))
    identity = tunnel._tunnel_identity(1234)
    assert identity == (row["CreationDate"], row["ExecutablePath"].casefold(), row["CommandLine"])
    row["CommandLine"] = '"C:\\tools\\cloudflared.exe" tunnel --url https://evil.example --no-autoupdate'
    assert tunnel._tunnel_identity(1234) is None
    row["Name"] = "msedge.exe"
    row["CommandLine"] = '"C:\\tools\\cloudflared.exe" tunnel --url http://127.0.0.1:8765 --no-autoupdate'
    assert tunnel._tunnel_identity(1234) is None


def test_process_inspection_parse_failure_fails_closed(monkeypatch):
    monkeypatch.setattr(tunnel.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="[]"))
    assert tunnel._tunnel_identity(1234) is None


def test_start_records_process_identity_before_reporting_started(tmp_path, monkeypatch):
    monkeypatch.setattr(tunnel, "HOME", tmp_path)
    monkeypatch.setattr(tunnel, "PID_FILE", tmp_path / "tunnel.pid")
    monkeypatch.setattr(tunnel, "IDENTITY_FILE", tmp_path / "tunnel.identity.json")
    monkeypatch.setattr(tunnel, "URL_FILE", tmp_path / "tunnel.url")
    monkeypatch.setattr(tunnel, "LOG_FILE", tmp_path / "tunnel.log")
    monkeypatch.setattr(tunnel, "find_cloudflared", lambda: "C:/tools/cloudflared.exe")
    identity = ("birth-1234", "c:/tools/cloudflared.exe", "quick-tunnel")
    monkeypatch.setattr(tunnel, "_tunnel_identity", lambda pid: identity)
    monkeypatch.setattr(tunnel.subprocess, "Popen", lambda *a, **k: SimpleNamespace(pid=1234))

    assert tunnel.start(timeout_s=0)["status"] == "no_url_yet"
    assert tunnel.PID_FILE.read_text(encoding="utf-8") == "1234"
    saved = tunnel.IDENTITY_FILE.read_text(encoding="utf-8")
    assert "quick-tunnel" not in saved and tunnel._owned_tunnel(1234) == identity


def test_start_refuses_url_after_process_identity_changes(tmp_path, monkeypatch):
    for name, filename in (("HOME", tmp_path), ("PID_FILE", tmp_path / "tunnel.pid"),
                           ("IDENTITY_FILE", tmp_path / "tunnel.identity.json"),
                           ("URL_FILE", tmp_path / "tunnel.url"),
                           ("LOG_FILE", tmp_path / "tunnel.log")):
        monkeypatch.setattr(tunnel, name, filename)
    monkeypatch.setattr(tunnel, "find_cloudflared", lambda: "C:/tools/cloudflared.exe")
    original = ("birth-A", "c:/tools/cloudflared.exe", "quick tunnel")
    active = {"value": True}
    monkeypatch.setattr(tunnel, "_tunnel_identity", lambda _: original if active["value"] else None)
    monkeypatch.setattr(tunnel.subprocess, "Popen", lambda *a, **k: SimpleNamespace(pid=1234))
    monkeypatch.setattr(tunnel.api_daemon, "pid_alive", lambda _: True)

    def identity_drift(_):
        active["value"] = False
        tunnel.LOG_FILE.write_text("https://recycled.trycloudflare.com", encoding="utf-8")

    monkeypatch.setattr(tunnel.time, "sleep", identity_drift)
    assert tunnel.start(timeout_s=5)["status"] == "identity_changed"
    assert not tunnel.URL_FILE.exists()


def test_stop_refuses_matching_but_untracked_cloudflared(tmp_path, monkeypatch):
    pid_file = tmp_path / "tunnel.pid"
    url_file = tmp_path / "tunnel.url"
    pid_file.write_text("1234", encoding="utf-8")
    url_file.write_text("https://saved.trycloudflare.com", encoding="utf-8")
    monkeypatch.setattr(tunnel, "PID_FILE", pid_file)
    monkeypatch.setattr(tunnel, "URL_FILE", url_file)
    monkeypatch.setattr(tunnel, "IDENTITY_FILE", tmp_path / "tunnel.identity.json", raising=False)
    monkeypatch.setattr(tunnel, "_tunnel_identity", lambda pid: ("creation-A", "cloudflared.exe", "quick-tunnel"))
    monkeypatch.setattr(tunnel.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("untracked PID must never be terminated")))
    assert tunnel.stop()["status"] == "identity_unverified"
    assert pid_file.exists() and url_file.exists()


def test_url_does_not_advertise_recycled_pid_as_running(tmp_path, monkeypatch):
    pid_file = tmp_path / "tunnel.pid"
    url_file = tmp_path / "tunnel.url"
    pid_file.write_text("15472", encoding="utf-8")
    url_file.write_text("https://stale.trycloudflare.com", encoding="utf-8")
    monkeypatch.setattr(tunnel, "PID_FILE", pid_file)
    monkeypatch.setattr(tunnel, "URL_FILE", url_file)
    monkeypatch.setattr(tunnel.api_daemon, "pid_alive", lambda pid: True)
    monkeypatch.setattr(tunnel, "_tunnel_identity", lambda pid: None)
    assert tunnel.url() == {"running": False, "pid": 15472, "url": None}
    assert url_file.exists()  # reporting must not mutate live metadata


def test_start_refuses_unverified_live_pid_instead_of_claiming_tunnel(monkeypatch):
    monkeypatch.setattr(tunnel, "find_cloudflared", lambda: "cloudflared.exe")
    monkeypatch.setattr(tunnel, "read_pid", lambda: 15472)
    monkeypatch.setattr(tunnel.api_daemon, "pid_alive", lambda pid: True)
    monkeypatch.setattr(tunnel, "_tunnel_identity", lambda pid: None)
    monkeypatch.setattr(tunnel.subprocess, "Popen", lambda *a, **k: None)
    assert tunnel.start(timeout_s=0)["status"] == "identity_unverified"


def test_stop_owned_tunnel_terminates_only_the_recorded_instance(tmp_path, monkeypatch):
    pid = 1234
    identity = ("birth-A", "c:/tools/cloudflared.exe", "quick tunnel")
    pid_file = tmp_path / "tunnel.pid"
    url_file = tmp_path / "tunnel.url"
    identity_file = tmp_path / "tunnel.identity.json"
    pid_file.write_text(str(pid), encoding="utf-8")
    url_file.write_text("https://owned.trycloudflare.com", encoding="utf-8")
    identity_file.write_text(json.dumps({"pid": pid, "fingerprint": tunnel._fingerprint(identity)}),
                             encoding="utf-8")
    monkeypatch.setattr(tunnel, "PID_FILE", pid_file)
    monkeypatch.setattr(tunnel, "URL_FILE", url_file)
    monkeypatch.setattr(tunnel, "IDENTITY_FILE", identity_file)
    killed = []
    monkeypatch.setattr(tunnel, "_tunnel_identity", lambda _: None if killed else identity)
    monkeypatch.setattr(tunnel.api_daemon, "pid_alive", lambda _: False)

    def fake_run(argv, **kwargs):
        killed.append(argv)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(tunnel.subprocess, "run", fake_run)
    assert tunnel.url()["running"] is True
    assert tunnel.stop()["status"] == "stopped"
    assert killed == [["taskkill", "/F", "/T", "/PID", str(pid)]]
    assert not any(path.exists() for path in (pid_file, url_file, identity_file))


def test_stop_keeps_identity_if_pid_still_exists_after_taskkill(tmp_path, monkeypatch):
    pid_file = tmp_path / "tunnel.pid"
    identity_file = tmp_path / "tunnel.identity.json"
    pid_file.write_text("1234", encoding="utf-8")
    original = ("birth-A", "c:/tools/cloudflared.exe", "quick tunnel")
    identity_file.write_text(json.dumps({"pid": 1234, "fingerprint": tunnel._fingerprint(original)}),
                             encoding="utf-8")
    monkeypatch.setattr(tunnel, "PID_FILE", pid_file)
    monkeypatch.setattr(tunnel, "IDENTITY_FILE", identity_file)
    monkeypatch.setattr(tunnel, "URL_FILE", tmp_path / "tunnel.url")
    snapshots = iter((original, original, None))
    monkeypatch.setattr(tunnel, "_tunnel_identity", lambda _: next(snapshots))
    monkeypatch.setattr(tunnel.api_daemon, "pid_alive", lambda _: True)
    monkeypatch.setattr(tunnel.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    assert tunnel.stop()["status"] == "stop_unverified"
    assert pid_file.exists() and identity_file.exists()


def test_stop_refuses_identity_change_before_kill(tmp_path, monkeypatch):
    pid_file = tmp_path / "tunnel.pid"
    identity_file = tmp_path / "tunnel.identity.json"
    pid_file.write_text("1234", encoding="utf-8")
    original = ("birth-A", "c:/tools/cloudflared.exe", "quick tunnel")
    identity_file.write_text(json.dumps({"pid": 1234, "fingerprint": tunnel._fingerprint(original)}),
                             encoding="utf-8")
    monkeypatch.setattr(tunnel, "PID_FILE", pid_file)
    monkeypatch.setattr(tunnel, "IDENTITY_FILE", identity_file)
    monkeypatch.setattr(tunnel, "URL_FILE", tmp_path / "tunnel.url")
    snapshots = iter((original, ("birth-B", *original[1:])))
    monkeypatch.setattr(tunnel, "_tunnel_identity", lambda _: next(snapshots))
    monkeypatch.setattr(tunnel.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("identity drift must not kill a process")))
    assert tunnel.stop()["status"] == "identity_changed"
    assert pid_file.exists() and identity_file.exists()


def test_stop_refuses_recycled_browser_pid_without_deleting_evidence(tmp_path, monkeypatch):
    pid_file = tmp_path / "tunnel.pid"
    url_file = tmp_path / "tunnel.url"
    pid_file.write_text("15472", encoding="utf-8")
    url_file.write_text("https://old.example.trycloudflare.com", encoding="utf-8")
    monkeypatch.setattr(tunnel, "PID_FILE", pid_file)
    monkeypatch.setattr(tunnel, "URL_FILE", url_file)
    monkeypatch.setattr(tunnel.api_daemon, "pid_alive", lambda pid: True)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        # The PID is alive, but process inspection cannot establish tunnel identity.
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(tunnel.subprocess, "run", fake_run)
    result = tunnel.stop()
    assert result["status"] == "identity_unverified"
    assert pid_file.exists() and url_file.exists()
    assert not any("taskkill" in str(argv[0]).lower() for argv in calls)
