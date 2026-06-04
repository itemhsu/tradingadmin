"""admin_gui/services/manifest.py — 抓引擎 manifest（兩 repo GUI G2）。

Repo B 不含 strategies/ brokers/（在 wheel 裡）；GUI 改從引擎 Release 的
manifest.json 取策略/券商清單與必填 secret。runner 可注入便於單測。
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List, Optional

ENGINE_REPO = "itemhsu/tech-rebalance-pub"
_CACHE: dict = {}


def parse_manifest(text: str) -> dict:
    m = json.loads(text)
    return {
        "manifest_version": m.get("manifest_version", "1"),
        "engine_version": m.get("engine_version", ""),
        "data_schema": m.get("data_schema", ""),
        "strategies": list(m.get("strategies") or []),
        "brokers": dict(m.get("brokers") or {}),
    }


def fetch_manifest(version: str = "latest", repo: str = ENGINE_REPO,
                   runner: Callable = subprocess.run, use_cache: bool = True) -> Optional[dict]:
    """從引擎 Release 抓 manifest.json；失敗回 None（GUI 降級用快取/空清單）。"""
    key = (repo, version)
    if use_cache and key in _CACHE:
        return _CACHE[key]
    with tempfile.TemporaryDirectory() as td:
        args = ["gh", "release", "download"]
        if version and version != "latest":
            args.append(version)
        args += ["--repo", repo, "--pattern", "manifest.json", "--dir", td]
        r = runner(args, capture_output=True, text=True)
        if getattr(r, "returncode", 1) != 0:
            return None
        p = Path(td) / "manifest.json"
        if not p.exists():
            return None
        m = parse_manifest(p.read_text(encoding="utf-8"))
    if use_cache:
        _CACHE[key] = m
    return m


def strategies(manifest: dict) -> List[str]:
    return list(manifest.get("strategies") or [])


def brokers(manifest: dict) -> List[str]:
    return list((manifest.get("brokers") or {}).keys())


def required_secrets(manifest: dict, broker: str, prefix: str) -> List[str]:
    b = (manifest.get("brokers") or {}).get(broker) or {}
    return [e.replace("{PREFIX}", prefix) for e in b.get("required_env", [])]


def broker_environments(manifest: dict, broker: str) -> List[str]:
    b = (manifest.get("brokers") or {}).get(broker) or {}
    return list(b.get("environments") or [])
