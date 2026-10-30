# 參與開發 / Contributing

歡迎提交可重現的問題與範圍明確的改進。請勿在 Issue、PR、截圖或測試資料中放入 API Key、內部網址或真實工時。

Reproducible issues and focused improvements are welcome. Do not include API keys, internal URLs, or real time entries in issues, pull requests, screenshots, or fixtures.

## 本機開發 / Local setup

```bash
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
ruff check .
ruff format --check .
python -m build
```

GUI 測試可在有桌面的環境設定 `RUN_GUI_TESTS=1` 執行；Linux 無桌面環境可用 `xvfb-run -a` 包覆測試指令。

Enable `RUN_GUI_TESTS=1` on a desktop to run GUI tests; on headless Linux, wrap the test command with `xvfb-run -a`.

## 修改原則 / Change guidelines

- 將 API 存取留在 `redmine.py`，計算留在 `service.py`，介面留在 `gui/` 或 `cli.py`。 Keep API access, business rules, and UI code in their respective modules.
- 工時採用 `Decimal`，不要把查詢錯誤當成零。 Use `Decimal`; never convert query failures into zero hours.
- 新增工時不可盲目重試；不明結果必須回報並停止。 Never blindly retry a write; report uncertainty and stop.
- 測試使用虛構回應，不連線至正式伺服器。 Use synthetic responses, not production servers.
- 功能與操作變更需同步更新 README 中英文說明。 Update both Chinese and English README instructions when behavior changes.

PR 請說明問題、修改後的行為、驗證方式與限制。GUI 修改請附離線示範截圖。

Describe the problem, resulting behavior, validation, and limitations in pull requests. For UI changes, include a screenshot from the offline demo.
