"""env_fix 的 Windows 行為（隱藏 subprocess 主控台、補 gh 路徑）。非 Windows 不得有副作用。"""
import os
import subprocess

from admin_gui.services import env_fix


def test_hide_console_noop_off_windows(monkeypatch):
    if os.name == "nt":
        return
    orig = subprocess.Popen.__init__
    assert env_fix.hide_subprocess_console() is False
    assert subprocess.Popen.__init__ is orig


def test_hide_console_adds_no_window_flag(monkeypatch):
    seen = {}

    def fake_init(self, *a, **kw):
        seen.update(kw)

    monkeypatch.setattr(env_fix.os, "name", "nt")
    monkeypatch.setattr(subprocess.Popen, "__init__", fake_init)
    assert env_fix.hide_subprocess_console() is True
    subprocess.Popen.__init__(object.__new__(subprocess.Popen), ["gh"], creationflags=0x10)
    assert seen["creationflags"] & 0x08000000
    assert seen["creationflags"] & 0x10, "保留呼叫端自帶的旗標"
    # 冪等：再套一次不會包兩層
    patched = subprocess.Popen.__init__
    assert env_fix.hide_subprocess_console() is True
    assert subprocess.Popen.__init__ is patched
