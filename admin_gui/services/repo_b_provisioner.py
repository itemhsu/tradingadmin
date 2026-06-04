"""admin_gui/services/repo_b_provisioner.py — 一鍵建立 Repo B 薄殼（兩 repo GUI G2）。

純 API（不 clone）：建 private repo → 推範本檔（含巢狀 daily.yml）→ 放 vendored wheel。
不寫入任何金鑰（金鑰另由 gh secret set 設）。runner 可注入。
"""
from __future__ import annotations

import base64
import json
import subprocess
from typing import Callable, Dict

# 薄殼 daily.yml：手動觸發、dry_run 預設 true（設好金鑰前不自動跑、不下單）
_DAILY_YML = """name: Daily rebalance (thin shell)
on:
  # 對帳通過前先「只手動觸發」；通過後取消下面 schedule 註解即啟用每日自動。
  # schedule:
  #   - cron: '15 21 * * 1-5'
  workflow_dispatch:
    inputs:
      dry_run: {{ description: 'dry-run（不下單）', type: boolean, default: true }}
      force:   {{ description: '強制再平衡（覆蓋頻率守門）', type: boolean, default: false }}
permissions:
  contents: write
jobs:
  daily:
    runs-on: ubuntu-latest
    env:
      TR_WORKDIR: ${{{{ github.workspace }}}}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {{ python-version: "3.11" }}
      - name: Install engine (public repo, no token)
        run: pip install "tech-rebalance @ git+https://github.com/itemhsu/tech-rebalance-pub@{version}"
      - name: Run all accounts
        env:
          ACC1_ALPACA_KEY:    ${{{{ secrets.ACC1_ALPACA_KEY }}}}
          ACC1_ALPACA_SECRET: ${{{{ secrets.ACC1_ALPACA_SECRET }}}}
          EMAIL_SENDER:       ${{{{ secrets.EMAIL_SENDER }}}}
          EMAIL_PASSWORD:     ${{{{ secrets.EMAIL_PASSWORD }}}}
          EMAIL_RECIPIENT:    ${{{{ secrets.EMAIL_RECIPIENT }}}}
          FORCE_REBALANCE:    ${{{{ inputs.force }}}}
        run: |
          if [ "${{{{ inputs.dry_run }}}}" = "true" ]; then
            run-account --account all --dry-run
          else
            run-account --account all
          fi
      - name: Commit data
        if: ${{{{ inputs.dry_run != true }}}}   # dry-run 不 commit（避免污染冪等守門）
        run: |
          git config user.name  "Daily Bot"
          git config user.email "bot@users.noreply.github.com"
          git add data/
          git diff --staged --quiet && exit 0
          git commit -m "chore(daily): $(date -u +%Y-%m-%d)"
          git pull --rebase --autostash -X theirs origin main
          git push
"""


def build_template_files(engine_version: str,
                         account_id: str = "1", strategy: str = "top10",
                         email: str = "you@example.com") -> Dict[str, bytes]:
    """組出 Repo B 初始檔案（path → bytes）。引擎用 git+ 從公開 repo 安裝，無金鑰、無 wheel。"""
    accounts = {
        "accounts": [{
            "id": account_id, "strategy": strategy, "label": "我的帳戶",
            "broker": "alpaca", "environment": "paper",
            "secret_prefix": f"ACC{account_id}", "enabled": True,
            "data_dir": f"data/{account_id}",
            "email_recipients": [email],
        }]
    }
    daily = _DAILY_YML.format(version=engine_version)
    return {
        "accounts.json": (json.dumps(accounts, ensure_ascii=False, indent=2) + "\n").encode(),
        "data/.gitkeep": b"",
        ".github/workflows/daily.yml": daily.encode(),
        "README.md": "# Repo B - thin shell\n\n引擎以 git+ 從 tech-rebalance-pub 安裝（免 token）。\n".encode(),
    }


def provision(slug: str, files: Dict[str, bytes], *, private: bool = True,
              runner: Callable = subprocess.run) -> dict:
    """建 repo + 推檔。回 {ok, created, files:{path:bool}, error}。"""
    cr = runner(["gh", "repo", "create", slug,
                 "--private" if private else "--public"],
                capture_output=True, text=True)
    created = getattr(cr, "returncode", 1) == 0
    if not created and "already exists" not in (getattr(cr, "stderr", "") or "").lower():
        return {"ok": False, "created": False, "files": {},
                "error": (getattr(cr, "stderr", "") or "repo create 失敗")[:200]}

    results: Dict[str, bool] = {}
    for path, content in files.items():
        payload = json.dumps({
            "message": f"init {path}",
            "content": base64.b64encode(content).decode(),
        })
        r = runner(["gh", "api", "-X", "PUT",
                    f"repos/{slug}/contents/{path}", "--input", "-"],
                   input=payload, capture_output=True, text=True)
        results[path] = getattr(r, "returncode", 1) == 0
    return {"ok": all(results.values()), "created": created,
            "files": results, "error": ""}
