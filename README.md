# 3ric Twitch 加權抽獎

## Render 環境變數
原本的 `TWITCH_CLIENT_ID`、`TWITCH_CLIENT_SECRET`、`TWITCH_REDIRECT_URI`、`FLASK_SECRET_KEY` 保留，再新增：

- `PUBLIC_URL=https://twitch-follower-lottery.onrender.com`
- `EVENTSUB_SECRET=` 請填一串至少 10~100 字元、自己產生的隨機秘密字串
- `DB_PATH=lottery.db`（測試可用；Render 免費服務重新部署/重啟可能遺失本機 SQLite 資料）

Twitch Developer Console 的 OAuth Redirect URL 保留網站的 `/callback`。

## 新版流程
1. Twitch 登入（會新增 `channel:manage:redemptions` 權限，因此第一次要重新授權）。
2. 更新追隨者：每位追隨者基本 1 張票。
3. 設定點數價格與每人額外票上限，按「建立點數抽獎券」。
4. 系統建立 Twitch 自訂頻道點數獎勵，並訂閱 EventSub webhook。
5. 觀眾兌換後，票數自動 +1；公開頁每 5 秒更新。
6. 管理員可手動改「總票數」，系統把差額記為 admin adjustment 並留下 audit log。
7. 抽獎依總票數加權，使用 Python `random.SystemRandom()`。

## 重要
正式長期使用前，建議把 SQLite 換成持久化資料庫（例如 PostgreSQL），否則 Render 免費 Web Service 的本機檔案不保證永久保存。

## 修改紀錄
管理頁新增「📋 修改紀錄」按鈕，可查看最近 200 筆手動票數修改，包含時間、觀眾、修改前/後票數、變動量與原因。紀錄儲存在同一個 PostgreSQL / SQLite 資料庫中。
