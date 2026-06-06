"""admin_gui/services/async_task.py — 把耗時工作丟背景執行緒的通用小元件。

原則：主執行緒只負責畫面；網路 / gh / SMTP 一律在背景跑，完成用 signal 回 UI。
用法：
    from admin_gui.services.async_task import run_async
    run_async(self,
              lambda report: do_slow(report),     # 背景跑；report(i,n,label) 回報進度
              on_done=lambda result: ...,         # 主執行緒
              on_failed=lambda err: ...,
              on_progress=lambda i, n, label: ...)
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QThread, Signal


class Task(QThread):
    progress = Signal(int, int, str)   # done, total, label
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            # 傳一個可呼叫的 report 給工作函式（要回報進度才用，不用可忽略）
            def report(i: int, n: int, label: str = ""):
                self.progress.emit(i, n, label)
            result = self._fn(report)
            self.done.emit(result)
        except Exception as e:   # noqa: BLE001  背景例外不可讓程式崩，回傳給 UI
            self.failed.emit(f"{type(e).__name__}: {e}")


def run_async(owner, fn: Callable,
              on_done: Optional[Callable] = None,
              on_failed: Optional[Callable] = None,
              on_progress: Optional[Callable] = None) -> Task:
    """在背景跑 fn(report)，完成/失敗/進度回主執行緒。owner 需是 QObject（持有參考避免被 GC）。"""
    t = Task(fn)            # 不掛 Qt parent，改用 owner._async_tasks 持有參考
    if on_done:
        t.done.connect(on_done)
    if on_failed:
        t.failed.connect(on_failed)
    if on_progress:
        t.progress.connect(on_progress)
    # 持有參考，避免 QThread 被回收；結束後移除
    if not hasattr(owner, "_async_tasks"):
        owner._async_tasks = []
    owner._async_tasks.append(t)

    def _cleanup():
        try:
            owner._async_tasks.remove(t)
        except (ValueError, AttributeError):
            pass
    t.finished.connect(_cleanup)
    t.start()
    return t
