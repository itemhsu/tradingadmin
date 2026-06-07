"""tests/admin_gui/conftest.py — GUI 測試共用設定。

把 async_task.run_async 改成「同步執行」：測試環境不起真背景 QThread，
避免 headless CI 在 teardown 時因 QThread 被銷毀而 abort（exit 134）；
同時讓背景邏輯在測試中可同步斷言。
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _run_async_sync(monkeypatch):
    try:
        import admin_gui.services.async_task as at
    except Exception:   # noqa: BLE001  沒有 PySide6 的環境直接略過
        return

    def _sync(owner, fn, on_done=None, on_failed=None, on_progress=None):
        try:
            result = fn(lambda *a, **k: None)   # report no-op
            if on_done:
                on_done(result)
        except Exception as e:   # noqa: BLE001
            if on_failed:
                on_failed(f"{type(e).__name__}: {e}")
        return None

    monkeypatch.setattr(at, "run_async", _sync, raising=False)
