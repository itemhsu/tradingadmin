"""Phase C 測試：cron_editor（G-07/G-08）。純邏輯，不啟動 GUI。

註：git_ops 已移除（純 API 模式改用 GitHub Contents API 直接 commit），
原 G-09 token-scan 測試一併刪除。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from admin_gui.services import cron_editor as ce


# ── G-07：cron 改寫後 YAML 仍有效、只動目標行 ────────────────────────────
def test_G07_replace_cron_keeps_rest():
    yaml = (
        "on:\n"
        "  schedule:\n"
        "    - cron: '30 21 * * 1-5'\n"
        "    - cron: '0 22 * * 1-5'\n"
        "jobs:\n"
    )
    out = ce.replace_cron(yaml, "30 21 * * 1-5", "45 13 * * 1-5")
    assert "45 13 * * 1-5" in out
    assert "0 22 * * 1-5" in out          # 另一行不動
    assert out.count("- cron:") == 2      # 行數不變
    assert "jobs:" in out


def test_G07b_replace_missing_raises():
    with pytest.raises(ValueError):
        ce.replace_cron("- cron: '0 0 * * *'\n", "1 1 * * *", "2 2 * * *")


def test_G07c_invalid_new_expr_raises():
    with pytest.raises(ValueError):
        ce.replace_cron("- cron: '0 0 * * *'\n", "0 0 * * *", "bad expr")


# ── G-08：cron ↔ 可讀 + 時區換算 ─────────────────────────────────────────
def test_G08_human_with_tz():
    c = ce.CronEntry.parse("30 21 * * 1-5")
    h = c.human(tz_offset_hours=8)
    assert "21:30 UTC" in h
    assert "05:30" in h and "隔日" in h   # 21:30 UTC +8 → 隔日 05:30
    assert "週一二三四五" in h


def test_G08b_parse_roundtrip():
    assert ce.CronEntry.parse("0 22 * * 1-5").to_expr() == "0 22 * * 1-5"


# ── 新增：從 YAML 文字（非檔案）讀 cron，給純 API 模式用 ───────────────────
def test_read_crons_text():
    yaml = (
        "on:\n  schedule:\n"
        "    - cron: '30 21 * * 1-5'\n"
        "    - cron: '0 22 * * 1-5'\n"
    )
    crons = ce.read_crons_text(yaml)
    assert [c.to_expr() for c in crons] == ["30 21 * * 1-5", "0 22 * * 1-5"]
