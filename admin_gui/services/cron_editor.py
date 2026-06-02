"""admin_gui/services/cron_editor.py — workflow YAML 的 cron 排程讀寫 + 人類可讀互轉。

純文字操作（不靠 yaml dump，避免破壞既有格式/註解）：定位 `- cron: '...'` 行，
就地替換。提供 cron ↔ 可讀字串、UTC ↔ 本地時區換算。純邏輯，可單測。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

_CRON_LINE = re.compile(r"^(?P<indent>\s*-\s*cron:\s*)(['\"]?)(?P<expr>[^'\"]+)\2\s*$")

_DOW = {"0": "日", "1": "一", "2": "二", "3": "三", "4": "四", "5": "五", "6": "六", "7": "日"}


@dataclass
class CronEntry:
    raw: str            # 原始 cron 字串，如 "30 21 * * 1-5"
    minute: str
    hour: str
    dom: str
    month: str
    dow: str

    @classmethod
    def parse(cls, expr: str) -> "CronEntry":
        parts = expr.split()
        if len(parts) != 5:
            raise ValueError(f"cron 必須是 5 欄：{expr!r}")
        return cls(expr, *parts)

    def to_expr(self) -> str:
        return f"{self.minute} {self.hour} {self.dom} {self.month} {self.dow}"

    def human(self, tz_offset_hours: int = 0) -> str:
        """回傳人類可讀（含時區換算）。tz_offset_hours：本地相對 UTC（台灣=+8）。"""
        days = _human_dow(self.dow)
        try:
            h = int(self.hour); m = int(self.minute)
            utc = f"{h:02d}:{m:02d} UTC"
            if tz_offset_hours:
                lh = (h + tz_offset_hours) % 24
                crossed = (h + tz_offset_hours) >= 24
                local = f"{lh:02d}:{m:02d}" + ("（隔日）" if crossed else "")
                return f"{days} {utc}（本地 {local}）"
            return f"{days} {utc}"
        except ValueError:
            return f"{days} {self.hour}:{self.minute}（非固定時刻）"


def _human_dow(dow: str) -> str:
    if dow == "*":
        return "每天"
    m = re.fullmatch(r"(\d)-(\d)", dow)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return "週" + "".join(_DOW.get(str(d), "?") for d in range(a, b + 1))
    return "週" + "".join(_DOW.get(d, "?") for d in dow.split(","))


def read_crons_text(yaml_text: str) -> List[CronEntry]:
    """從 workflow YAML 文字抽出所有 cron 行。"""
    out: List[CronEntry] = []
    for line in (yaml_text or "").splitlines():
        m = _CRON_LINE.match(line)
        if m:
            try:
                out.append(CronEntry.parse(m.group("expr").strip()))
            except ValueError:
                pass
    return out


def read_crons(yaml_path: Path) -> List[CronEntry]:
    """從 workflow YAML 檔抽出所有 cron 行。"""
    return read_crons_text(Path(yaml_path).read_text(encoding="utf-8"))


def replace_cron(yaml_text: str, old_expr: str, new_expr: str) -> str:
    """就地替換一行 cron 表達式（保留縮排與引號風格），回傳新文字。

    找不到 old_expr 會 raise，避免靜默無效。
    """
    CronEntry.parse(new_expr)   # 先驗證新值合法
    lines = yaml_text.splitlines(keepends=True)
    done = False
    for i, line in enumerate(lines):
        m = _CRON_LINE.match(line.rstrip("\n"))
        if m and m.group("expr").strip() == old_expr.strip():
            nl = "\n" if line.endswith("\n") else ""
            lines[i] = f"{m.group('indent')}'{new_expr}'{nl}"
            done = True
            break
    if not done:
        raise ValueError(f"找不到 cron 行：{old_expr!r}")
    return "".join(lines)
