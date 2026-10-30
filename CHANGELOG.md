# Changelog / 更新紀錄

## 0.1.0 — 2026-10-30

- 將個人工具整理為可安裝的 Python 套件，保留舊啟動入口。 Package the tool with compatibility launchers.
- 新增中英文文件、設定範例與不含個資的離線示範。 Add bilingual documentation, example settings, and an anonymous offline demo.
- 重整桌面介面，新增背景作業、進度、每日明細與預覽後送出流程。 Redesign the GUI with background work, progress, daily rows, and preview-before-apply.
- 加入完整分頁、回應驗證、HTTPS 限制及保守的寫入錯誤處理。 Add pagination, response validation, HTTPS requirements, and conservative write handling.
- 修正查詢失敗導致誤補及失敗時數被算為成功的問題。 Fix filling after failed reads and counting failed writes as successful hours.
- 改用完整日期的行事曆，支援補班日並預設排除未來日期。 Introduce year-specific calendars, working-day overrides, and future-date exclusion.
- 新增離線測試與跨平台 CI 設定。 Add offline tests and cross-platform CI configuration.
