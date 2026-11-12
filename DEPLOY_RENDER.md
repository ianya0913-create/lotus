# 部署到 Render（取得公開網址）

部署後會得到一個像 https://lotus-bf-xxxx.onrender.com/lotus-bf/ 的網址，
任何人、任何電腦都打得開。後端用 local_api（自帶資料），不需要老師的伺服器。

## 事前準備
- GitHub 帳號（免費）
- Render 帳號（免費，可用 GitHub 登入）

## 步驟

### 1. 先在自己電腦 build 前端
```
cd lotus-bf
npm install
npm run build        # 產生 lotus-bf/dist 資料夾
```
※ Render 不會幫你跑 npm，所以 dist 必須先 build 好、一起上傳。

### 2. 把整個資料夾推到 GitHub
在最外層（看得到 lotus-bf/ 和 local_api/ 的那層）：
```
git init
git add -A
git commit -m "LoTUS-BF"
```
到 github.com 建一個新的 repo（Public 或 Private 都可），照它給的指令：
```
git remote add origin https://github.com/你的帳號/你的repo.git
git branch -M main
git push -u origin main
```
※ 確認 dist 有被加進去（不要把它放進 .gitignore）。

### 3. 在 Render 建立服務
1. 登入 render.com → New → Blueprint
2. 選你剛剛的 GitHub repo
3. Render 會讀到 local_api/render.yaml，自動帶出設定，按 Apply
4. 等它 build + 啟動（第一次約 3–5 分鐘）

或手動（不用 Blueprint）：New → Web Service → 選 repo →
- Root Directory: `local_api`
- Build Command: `pip install -r requirements.txt`
- Start Command: `python server.py`
- Instance Type: Free

### 4. 取得網址
完成後 Render 會給你 `https://你的名字.onrender.com`。
你要交的網址是後面加上 /lotus-bf/：
```
https://你的名字.onrender.com/lotus-bf/
```
打開點一個詞彙，確認論文和腦圖都出得來。

## 注意
- **免費方案會休眠**：15 分鐘沒人用就睡著，下次打開要等 30–60 秒才醒來。
  第一次載入慢是正常的，不是壞掉。交作業前可以先打開一次把它叫醒。
- **記憶體**：免費方案 512MB，載入資料集後還夠用，但不要同時開太多查詢。
- 之後若改了程式，重新 `git push`，Render 會自動重新部署。
