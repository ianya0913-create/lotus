# LoTUS-BF 本地替代後端

用 `neurosynth_dataset.pkl.gz` 轉出的資料，在自己電腦上提供和老師伺服器相同的 API。

## 使用方式
1. 把整個 `local_api` 資料夾放在 `lotus-bf` 專案旁邊（或任何地方）
2. 開一個新的終端機：
   ```
   cd local_api
   python server.py
   ```
   看到 `LoTUS-BF local API running at http://localhost:5050` 就成功了（這個視窗要一直開著）
3. 用這裡的 `vite.config.js` 取代 `lotus-bf/vite.config.js`，然後重新啟動 `npm run dev`

前端會優先使用老師的伺服器；連不上（4 秒沒回應或回傳 5xx）時才自動改用本地後端，
之後 60 秒內都直接用本地，再自動重試老師的伺服器。

## 需要
- Python 3.8 以上
- numpy（`pip install numpy`）
- scipy 可有可無（有的話平滑比較快）

## 資料夾內容
- `server.py`：後端程式（只用 Python 標準函式庫 + numpy）
- `data/metadata.json`：14,371 篇論文的作者、期刊、年份、標題
- `data/terms.npz`：3,228 個詞彙的 TF-IDF 標註（只存非零值）
- `data/coords.npz`：507,891 個報告座標
