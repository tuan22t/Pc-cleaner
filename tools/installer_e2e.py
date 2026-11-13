"""Install, update and uninstall the packaged app on a clean CI machine.

Windows:  python tools/installer_e2e.py windows dist/PCCleaner-Setup-<v>.exe
macOS:    python tools/installer_e2e.py mac dist/PCCleaner-<v>.dmg

Checks the acceptance criteria of phase D that a machine can check:
  1. the installed app starts and answers;
  2. installing again over it (an update) keeps the quarantine and the log;
  3. after uninstalling, no scheduled task or LaunchAgent is left, the program
     is gone, and the user's data folder is still there.
Only files this script creates in a temporary folder are cleaned. Run it on a
throw-away CI machine, never on a computer in use: it installs, registers a
scheduled task and uninstalls for real.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

TOKEN = "e2e-" + os.urandom(8).hex()
PORT = 18765


def log(msg: str) -> None:
    print(f"[e2e] {msg}", flush=True)


def api(path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/{path}", data=data,
                                 headers={"X-Token": TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"null")


def wait_job():
    for _ in range(600):
        st = api("job")
        if st["state"] != "running":
            assert st["state"] == "done", st
            return st.get("result")
        time.sleep(0.1)
    raise AssertionError("job did not finish")


class App:
    """The installed app running headless, as the user's own account would run it."""

    def __init__(self, exe: list[str]):
        self.exe = exe
        self.proc = None

    def __enter__(self):
        env = dict(os.environ, PCCLEANER_TOKEN=TOKEN)
        env.pop("PCCLEANER_DATA_DIR", None)  # the real per-user data folder of this CI account
        self.proc = subprocess.Popen([*self.exe, "--headless", "--port", str(PORT)], env=env)
        for _ in range(120):
            try:
                info = api("info")
                log(f"app {info['version']} answers, data in {info['data_dir']}")
                return info
            except OSError:
                time.sleep(0.5)
        raise AssertionError("the installed app did not start")

    def __exit__(self, *exc):
        self.proc.terminate()
        try:
            self.proc.wait(30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        time.sleep(1)


def check_cycle(install, run_cmd, uninstall, schedule_present, program_present) -> None:
    work = Path(tempfile.mkdtemp(prefix="pcc-e2e-", dir=Path.home()))  # temp folders may count as system folders
    victim = work / "keep-me.bin"
    victim.write_bytes(os.urandom(4096))

    install()
    assert program_present(), "program not installed"
    with App(run_cmd()) as info:
        data_dir = Path(info["data_dir"])
        api("quarantine", {"paths": [str(victim)], "reason": "e2e"})
        batch = wait_job()["batch_id"]
        assert not victim.exists()
        api("schedule", {"enabled": True, "frequency": "weekly", "hour": 3, "junk": True, "purge_days": 0})
        assert api("schedule")["registered"], "scheduled task was not registered"
    assert schedule_present(), "scheduled task missing after registering"
    log("installed, one file quarantined, schedule registered")

    install()  # the same installer again: what an update does
    with App(run_cmd()):
        assert any(b["batch_id"] == batch and b["pending"] for b in api("batches")), "quarantine lost by the update"
        assert api("log"), "action log lost by the update"
        api("restore", {"batch_ids": [batch]})
        assert wait_job()["restored"] == 1
        assert victim.exists(), "file not restored after the update"
    log("update kept the quarantine and the log; file restored")

    uninstall()
    assert not schedule_present(), "scheduled task left behind after uninstall"
    assert not program_present(), "program files left behind after uninstall"
    assert data_dir.exists(), "uninstall removed the user's data"
    log("uninstalled: no task left, program gone, data kept")
    shutil.rmtree(work, ignore_errors=True)


def windows(setup: Path) -> None:
    app_dir = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "PC Cleaner"
    exe = app_dir / "PCCleaner.exe"

    def install():
        subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER"], check=True)

    def uninstall():
        unins = sorted(app_dir.glob("unins*.exe"))
        assert unins, "no uninstaller"
        subprocess.run([str(unins[-1]), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=True)
        for _ in range(60):  # the uninstaller finishes in a copy of itself
            if not app_dir.exists():
                break
            time.sleep(1)

    def schedule_present():
        return subprocess.run(["schtasks", "/Query", "/TN", r"PCCleaner\AutoClean"], capture_output=True).returncode == 0

    check_cycle(install, lambda: [str(exe)], uninstall, schedule_present, exe.exists)


def mac(dmg: Path) -> None:
    apps = Path.home() / "Applications"
    apps.mkdir(exist_ok=True)
    app = apps / "PC Cleaner.app"
    plist = Path.home() / "Library" / "LaunchAgents" / "com.pccleaner.autoclean.plist"
    exe = app / "Contents" / "MacOS" / "PCCleaner"

    def install():
        mnt = Path(tempfile.mkdtemp(prefix="pcc-dmg-"))
        subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mnt), str(dmg)], check=True)
        try:
            if app.exists():
                shutil.rmtree(app)
            subprocess.run(["ditto", str(mnt / "PC Cleaner.app"), str(app)], check=True)
        finally:
            subprocess.run(["hdiutil", "detach", str(mnt)], check=True)
        archs = subprocess.run(["lipo", "-archs", str(exe)], capture_output=True, text=True).stdout.split()
        log(f"main program architectures: {archs} (this machine: {platform.machine()})")
        assert {"x86_64", "arm64"} <= set(archs), "not a universal app"

    def uninstall():
        # macOS apps are removed by dragging them to the Trash; the app's own
        # "before uninstall" step (Settings) takes the LaunchAgent off first.
        subprocess.run([str(exe), "--before-uninstall"], check=True)
        shutil.rmtree(app)

    check_cycle(install, lambda: [str(exe)], uninstall, plist.exists, app.exists)


if __name__ == "__main__":
    kind, package = sys.argv[1], Path(sys.argv[2]).resolve()
    {"windows": windows, "mac": mac}[kind](package)
    log("all checks passed")
