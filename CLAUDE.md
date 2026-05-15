# Smart Pole — 高雄 PM2.5 補值研究

> Claude Code 每次啟動會自動讀本檔。請把它當作這個專案的「規範與契約」,
> 而不是 README——README 給人看,CLAUDE.md 給 AI 看。

## 研究目標

用高雄智慧竿體 + EPA 大測站,系統性評估各種模型在 PM2.5 補值的效果。
核心實驗:**隨機抽掉一根竿體當下值,用鄰近 K 根去補,K 從 30 掃到 1,看誤差曲線**。

**範圍邊界(別擴張)**:
- 變數:只做 **PM2.5**。其他污染物以後再說。
- 區域:只做 **高雄**。不做跨域、不和台北比較。
- 時間頻率:固定 **1 小時**。EdiBox 原本 20–30 分鐘的已對齊到小時。
- 指標:**MAE / RMSE / R²**,先這三個就好。

## 現在的進度

- ✅ `data_gathering.py` → 產出 `data/pole_hourly.parquet` (canonical 資料)
- ✅ `notebook.ipynb` (EDA) → EPA 12 站平均 vs 竿體跨裝置平均,Pearson r = 0.941
- ✅ `data/MOENV_iot_station.csv` → 全國 10999 站 IoT 測站表,**高雄 1287 站與 parquet 完全對齊**
- ✅ **Phase 1 完成**:框架骨架 + Tier 1 baseline(`mean`,搭配 `distance` / `correlation` 兩種 selector)
   跑通 6 個 K、12 個 run,`pytest` 12/12 全綠
- ✅ **Phase 2 完成**:多 seed 聚合 + block masking + CWA loader 骨架(Stream 0);
   4 個 weighted imputer(idw / corr_weighted / weighted_ridge / gaussian_kernel,Stream A);
   3 個 selector(diverse / wind_aligned / hybrid,Stream B);
   16 cell 4×4 ablation + analysis notebook(Stream C–D)。
   **Phase 2 best:correlation × weighted_ridge,MAE 1.61 @ K=20**(改善 52.5%)。
   `pytest` 46 全綠。
- ⏳ Phase 3:Tier 3 mathematical(Ordinary Kriging、Gaussian Process)
- ⏳ Phase 4:Tier 4 ML(XGBoost、LightGBM、Random Forest)
- ⏳ Phase 5:Tier 5 attention——很後面再說,**不要先開**

## Phase 1 已知發現(進 Phase 2 前先讀)

跑完 `mean` baseline 在兩種 selector 上的 K-curve,結論如下:

| K | corr MAE | dist MAE | corr R² | dist R² |
|---|---|---|---|---|
| 1  | 4.02 | 5.42 | 0.45 | 0.24 |
| 3  | 3.46 | 4.37 | 0.63 | 0.49 |
| 5  | 3.39 | 4.12 | 0.66 | 0.55 |
| 10 | **3.38** | 4.01 | **0.67** | 0.57 |
| 20 | 3.41 | 3.96 | 0.67 | 0.59 |
| 30 | 3.47 | 3.90 | 0.66 | 0.60 |

**三個關鍵 finding**(直接影響 Phase 2 設計):

1. **correlation selector 全面打敗 distance selector**(MAE 低 0.4–1.4)。
   1287 根竿體大部分擠在高雄市區,「最近 K 站」常常落在污染源相似但訊號冗餘的範圍。
   **在高密度感測網路,距離不是好的相似性指標**——這本身就是論文等級的結論。

2. **K-curve 形狀不同**:correlation 在 K=10 觸底然後微升(典型 bias-variance);
   distance 從 K=1 到 K=30 單調下降,沒看到反曲點。distance 還沒到底,
   Phase 2 開始前要先延伸 `k_list=[50, 100, 200]` 補完曲線。

3. **`mean` 本來就不該有 U 形**——它沒擬合任何東西。
   Phase 2 的 weighted / ridge 模型應該開始在 distance selector 上**也出現反曲點**——
   這是檢驗 Phase 2 模型有沒有真的學東西的 sanity check。

**Phase 2 假設**:在 weighted / kriging / ML 把 distance 的劣勢補回來之前,
correlation selector 會持續是強 baseline。「selection」與「weighting」的交互作用本身是研究核心,
所以 Phase 2 必須做 selector × weighting 的 ablation,**不能只換模型**。

## Phase 2 已知發現(進 Phase 3 前先讀)

### Stream 0 補完曲線後修正 Phase 1 finding

- **distance K-curve 在 K≈50 觸底再上升**(MAE 3.900 @ K=50,3.968 @ K=200)。
  Phase 1 的「distance 單調下降沒看到反曲」是 K=30 沒走遠;**distance 也有 U 形**,
  只是底部比 correlation 高 ~0.5 MAE 且偏右。
- **block masking vs random_point 差距很小**(K=10:3.42 vs 3.40,< 1%)。
  Phase 2 後續 ablation 因此**只跑 random_point**,不必開 block 軸。
- 5 seed 重跑後 MAE 標準差約 0.007–0.015,**seed-to-seed 變異極低**——
  Phase 1 的 single-seed 數字本身已穩,但帶狀圖讓 small-effect 差異變得可解釋。

### Stream A–C 4×4 ablation(K=10、5 seeds、random_point 0.2):

| selector \ weighting | mean | idw | corr | ridge |
|---|---|---|---|---|
| distance    | 4.01 | 4.14 | 3.97 | **2.08** |
| correlation | 3.39 | 3.71 | 3.39 | **1.62** ← Phase 2 best |
| diverse     | 4.65 | 5.41 | 4.46 | 2.34 |
| hybrid      | 3.45 | 3.76 | 3.45 | 2.02 |

**五個 Phase 2 finding**(直接影響 Phase 3 設計):

1. **Phase 2 best = correlation × weighted_ridge,MAE 1.606 @ K=20**
   (Phase 1 best MAE 3.39 @ K=5/10;**改善 52.5%、絕對 -1.78 MAE**)。
   Ridge 學到的 β 比距離 / 相關度的固定加權有效得多。
2. **weighting 比 selector 重要**:固定 selector 換 weighting 平均改 2.0 MAE;
   固定 weighting 換 selector 平均只改 1.0 MAE。
   **Ridge 在任一 selector 上都能壓到 2.3 內**——選錯也救得回來;
   反之挑到 correlation 但只用 mean / IDW 的話天花板就是 3.4。
3. **diverse selector 是 Phase 2 最差**:跨所有 weighting 都比 distance 還爛。
   Phase 1 的「強制空間分散能看到更多獨立訊號」假設**被否決**——
   高密度 PM2.5 網路裡,把鄰居推遠等於選到不相關的站。
4. **hybrid ≈ correlation**:correlation 挑大池子再 farthest-point 過濾沒帶來增益。
   Top-K 高相關鄰居的冗餘沒嚴重到要再多樣化。
5. **改善天花板未見頂**:Phase 2 best K-curve 在 K=20 觸底(1.606),
   K=5–20 形成 1.62±0.02 的平台,K=30 才微升到 1.635。
   還有 0.1–0.3 MAE 的空間給 Phase 3 吃。

### Phase 3 開工輸入

- **優先擴展 weighting 軸**:Phase 2 best vs worst 在 weighting 軸上的 swing(2.0–3.0)
  遠大於 selector 軸的 swing(1.0)。Phase 3 的 Kriging / GP 應該對標 ridge,
  目標把 MAE 從 1.61 壓到 1.3–1.5 區間。Selector 軸暫時固定用 correlation 即可。
- **Ridge 在 distance selector 上 K=10、K=20 的 RMSE 飆高(5–7)而 MAE 仍低**——
  代表有重尾錯誤、alpha=1.0 沒充分正則化。Phase 3 處理空間相依時記得用 cross-validation 選 α。
- **wind_aligned 沒進 Phase 2 ablation**(暫無 CWA 歷史風資料,scaffold 已寫好等資料補上)。
  若 Phase 3 拿到,優先做 wind_aligned × kriging 看是否能突破 1.6。
- **diverse / hybrid 進 Phase 3 的優先級低**:既然 diverse 拖後腿、hybrid 沒增益,
  Phase 3 不必再投資這兩個 selector,除非 wind_aligned 改變局勢。

## 環境

- Container:`nvidia/cuda:12.9.0-cudnn-runtime-ubuntu24.04`
- Python:3.13.13(`.python-version`),`uv` 管套件
- GPU:2× NVIDIA RTX 6000 Ada,~49 GB VRAM each。Tier 1–4 都用 CPU 就好,**Tier 5 才碰 GPU**。

### 套件管理

```bash
uv add <package>          # 加依賴(同時更新 pyproject.toml 和 uv.lock)
uv sync                   # 從 lock 還原環境
uv run python <script>    # 跑東西
uv run pytest tests/      # 跑測試
```

**不要直接 `pip install`**——會繞過 lock 檔,別人 clone 下來就不一樣。

### 跑實驗

```bash
# 單一實驗
uv run python scripts/run_experiment.py --config configs/experiments/exp01_mean.yaml

# 批次掃
bash scripts/run_all.sh

# 聚合結果
uv run python scripts/aggregate_results.py
```

## `.py` 還是 `.ipynb`?

**這是這個專案最重要的一條規則,違反它整個系統就會亂。**

| 用 `.py` | 用 `.ipynb` |
|---|---|
| 所有 model class | EDA(現有的 `notebook.ipynb`) |
| `BaseImputer`、registry、runner | 最終結果分析(`notebooks/analysis_*.ipynb`) |
| metrics、loaders、scripts | |
| 任何會被 import 的東西 | |
| 任何訓練超過 5 分鐘的任務 | |

**禁止**:
- ✗ 在 notebook 裡定義 model class
- ✗ 在 notebook 裡跑 multi-run sweep
- ✗ 把模型訓練程式碼複製到 notebook 「快速測試」——改成 `tests/` 裡寫測試

## 目錄

只列**框架相關**的;其他資料夾(`.venv/`、`.copilot/` 等)Claude 自己 `ls` 就好。

```
smart_pole/
├── data/                          ← read-only,別寫進去
│   ├── 高雄資料/                   ← raw 竿體
│   ├── epa_data/                  ← raw EPA
│   ├── MOENV_iot_station.csv      ← 全國 IoT 測站表,座標來源
│   └── pole_hourly.parquet        ← canonical,所有後續從這讀
├── data_gathering.py              ← 已完成,別動,動了 downstream 全爛
├── notebook.ipynb                 ← EDA,定格在當下進度,別當框架的一部分
├── NotoSansCJKtc-Regular.otf      ← matplotlib 中文字型,記得載入
├── configs/                       ← 一個 YAML = 一個實驗
│   ├── base.yaml
│   └── experiments/
├── src/smart_pole/                ← 框架本體 (package)
│   ├── data/                      ← 從 parquet 切資料
│   ├── masking/                   ← 製造缺失 (random_point / block / whole_station)
│   ├── neighbors/                 ← 挑鄰站 (distance / correlation / diverse / wind_aligned / hybrid)
│   ├── models/
│   │   ├── base.py                ← BaseImputer 契約,動了所有 model 都要改
│   │   ├── registry.py            ← @register decorator
│   │   ├── baseline/              ← Tier 1 (完成)
│   │   ├── weighted/              ← Tier 2 (Phase 2 進行中)
│   │   ├── mathematical/          ← Tier 3
│   │   ├── ml/                    ← Tier 4
│   │   └── attention/             ← Tier 5(暫時別碰)
│   ├── evaluation/                ← metrics + reporter
│   ├── visualization/             ← plots + maps
│   └── runner/                    ← experiment.py,主入口
├── scripts/                       ← CLI 腳本,被人/cron 呼叫
├── results/runs/                  ← 每跑一次一個資料夾(見下方 schema)
├── notebooks/                     ← 結果分析 notebooks(跟 EDA 分開)
└── tests/
```

## BaseImputer 契約

**所有模型必須繼承這個,不能為了方便擴充參數簽名**。Runner 假設介面長這樣,改 signature 整個 pipeline 都壞。

```python
# src/smart_pole/models/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
import numpy as np

class BaseImputer(ABC):
    """所有補值模型的統一介面。

    參數慣例:
        X:    shape (n_samples, K) — K 個鄰站當下的 PM2.5 值
        y:    shape (n_samples,)   — 目標站的真值
        meta: dict,含:
            - target_station_id:    str
            - neighbor_station_ids: list[str]
            - distances:            np.ndarray, shape (n_samples, K)  鄰站距離(公尺)
            - timestamps:           pd.DatetimeIndex
            - target_coord:         tuple[float, float]  (lon, lat)
            - neighbor_coords:      np.ndarray, shape (K, 2)
    """
    name: str = "base"          # 唯一識別,registry 用
    tier: int = 0               # 1..5
    requires_gpu: bool = False  # True 時 runner 會 set CUDA_VISIBLE_DEVICES

    def __init__(self, **params: Any) -> None:
        self.params = params
        self._fitted = False

    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "BaseImputer": ...

    @abstractmethod
    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray: ...

    def get_config(self) -> dict[str, Any]:
        return {"name": self.name, "tier": self.tier, "params": self.params}
```

### 寫一個新模型 = 三件事

1. 在對應 tier 資料夾下新增一個檔,繼承 `BaseImputer`,實作 `fit` / `predict`
2. 用 `@register` decorator 註冊
3. 在 `configs/experiments/` 加一個 YAML

範例:

```python
# src/smart_pole/models/baseline/mean.py
from __future__ import annotations
import numpy as np
from ..base import BaseImputer
from ..registry import register

@register
class MeanImputer(BaseImputer):
    """最廢的 baseline:K 個鄰站當下值的算術平均。"""
    name = "mean"
    tier = 1

    def fit(self, X, y, meta):
        self._fitted = True
        return self

    def predict(self, X, meta):
        return np.nanmean(X, axis=1)
```

### 違反契約的行為

- ✗ 在 `fit` / `predict` 加自訂位置參數——一律走 `meta` dict
- ✗ 在 model class 內部讀檔——資料一律外部傳入
- ✗ 把超參寫死——透過 `__init__(**params)` 傳,讓 config 控
- ✗ 在 model 裡 `print()`——用 `logging.getLogger(__name__)`

## Config Schema

```yaml
# configs/experiments/exp01_mean.yaml
experiment_id: exp01_mean
seeds: [42]                 # list 讓 runner sweep,輸出 mean ± std

data:
  cache_path: data/pole_hourly.parquet
  station_info_path: data/MOENV_iot_station.csv   # 座標來源
  target_var: pm25
  start: 2025-12-01           # ISO 8601
  end:   2026-02-08
  freq: 1h

masking:
  strategy: random_point      # random_point | block | whole_station
  ratio: 0.20
  block_hours: 6              # 只 block 用

neighbors:
  selector: correlation       # distance | correlation | diverse | wind_aligned | hybrid
  k_list: [30, 20, 10, 5, 3, 1]   # runner 會 sweep,不要在程式碼裡寫迴圈
  params: {}                  # selector 客製參數(例:wind_aligned 的 wind_dir_deg / alpha / beta)

split:
  method: time_based          # time_based | random
  train_ratio: 0.8

model:
  name: mean                  # 必須等於某個 @register 過的 BaseImputer.name
  params: {}                  # 對應 __init__ 的 kwargs

evaluation:
  metrics: [mae, rmse, r2]
  plots: [scatter, residual_ts, k_curve, spatial_error]
```

新增實驗 = 加 YAML,**永遠不要在 runner 或 model 裡硬寫超參**。

## Results Folder Schema

每個 run 必須產出:

```
results/runs/{experiment_id}_{model}_K{K}_seed{seed}_{YYYYMMDD-HHMMSS}/
├── config.yaml          ← resolved 完整 config(含 base.yaml 的 default)
├── metrics.json         ← {"mae": ..., "rmse": ..., "r2": ...}
├── predictions.parquet  ← columns: [timestamp, station_id, y_true, y_pred, residual]
├── log.txt              ← 訓練 log
└── plots/
    ├── scatter.png
    ├── residual_ts.png
    └── spatial_error.png
```

`aggregate_results.py` 只認這個 schema。**不要把結果寫去其他地方**。

## 風格規則(只列非 default 的)

- 註解、docstring、log 訊息一律**繁體中文**(對齊現有 `data_gathering.py` / `notebook.ipynb`)
- `from __future__ import annotations` + 型別標註
- 路徑一律 `pathlib.Path`,不拼字串
- 時間戳一律 `pd.Timestamp`,UTC 不要本地
- 任何隨機操作必須吃 `seed: int` 參數,**沒有 default seed**
- 用 `logging.getLogger(__name__)`,不要 `print`(notebook 例外)
- matplotlib 畫圖前先設中文字型,字型檔在專案根目錄 `NotoSansCJKtc-Regular.otf`

## GPU

- Tier 1–4 全用 CPU(夠快了,GPU 浪費)
- Tier 5 才用 GPU。屆時:
  - 先檢查 `torch.cuda.is_available()`,False 就 fallback CPU 並警告
  - 想分流兩張卡:`CUDA_VISIBLE_DEVICES=0 uv run ...` 跑一半 K,`=1` 跑另一半
- 不要在 model class 裡寫死 device,讓 runner 注入

## 動之前要問的檔

| 檔案 | 為什麼小心 |
|---|---|
| `data_gathering.py` | 生 canonical parquet,改了 downstream 全爛 |
| `data/` 下任何東西 | read-only,動了重現性掛掉 |
| `src/smart_pole/models/base.py` | 介面動了所有 model 都要改 |
| `pyproject.toml` | 用 `uv add`,不要手改;手改容易跟 lock 不同步 |
| `notebook.ipynb` | EDA 已定格,動了會跟論文/報告對不起來 |

## 給 Claude Code 的指示

1. 改程式碼前先看現有的同類檔——不要憑直覺重新發明結構
2. 加新模型一定走 `BaseImputer` + `@register`,**不要繞過**
3. 如果發現要在框架程式碼裡加 magic number / 寫死路徑——**停下來問人**,通常是 config 沒設計好
4. 任何新增 top-level 資料夾的需求——**先問**
5. 不要建 `xxx_v2.py` / `xxx_new.py`——改舊的,讓 git 記錄
6. 結束 task 前跑 `uv run pytest tests/` 確認沒打壞既有測試

## Phase 2 具體 TODO(目前要做的)

Phase 1 finding 告訴我們「**選誰**」和「**怎麼加權**」要一起研究。
Phase 2 不是「換 mean 變 weighted」這麼簡單,分成 4 個 stream + 1 個收尾。
**按 Stream 順序做,不要平行開**——Stream 0 的方法學基礎沒打好,後面跑出來的數字沒法比較。

### Stream 0:方法學清掃(寫模型前先做,0.5 天)

不寫任何新模型,只動 runner / loader / config。做完 Phase 2 軸數爆炸後才有 error bar 可比較。

1. [ ] `runner/experiment.py` 支援 `seeds: list[int]`,自動跑完聚合 mean ± std
2. [ ] `visualization/plots.py` K-curve 改成帶狀圖(中線 mean、半透明帶 ±1 std)
3. [ ] `masking/block.py` 補完(連續 N 小時缺失,模擬真實 EdiBox 故障)
4. [ ] `data/cwa_loader.py` 載入 CWA 風速風向(為 Stream B 的 `wind_aligned` 暖身)
5. [ ] 補跑 Phase 1 distance K-curve:`k_list=[50, 100, 200]`,確認 distance 最低點在哪

**Stream 0 驗收**:任一 Phase 1 實驗用 `seeds: [1,2,3,4,5]` 重跑,plot 出現帶狀;
block masking 至少一組對比 random_point 跑出來。

### Stream A:Weighted 模型(1 天)

四個 weighted imputer,全部繼承 `BaseImputer`,放 `src/smart_pole/models/weighted/`:

6. [ ] `idw.py` — `IDWImputer(power)`,經典 $w_i = 1/d_i^p$
7. [ ] `corr_weighted.py` — `CorrWeightedImputer()`,$w_i = \max(0, r_i)$ 標準化加權
8. [ ] `weighted_ridge.py` — `WeightedRidgeImputer(alpha)`,Ridge 線性回歸,
       樣本權重可選 distance / correlation
9. [ ] `gaussian_kernel.py` — `GaussianKernelImputer(sigma)`,$w_i = \exp(-d_i^2/2\sigma^2)$;
       Phase 3 Kriging 的前奏

**每個模型必須**:
- 沒有 default 超參(透過 `__init__(**params)` 由 YAML 傳入)
- 通過 `tests/test_base_imputer.py` 的契約測試
- 自己一份 `configs/experiments/exp_<model>.yaml`

**Stream A 驗收**:4 個模型 × 2 個 selector(distance + correlation)× 6 個 K × 5 個 seed = 240 runs 全綠;
`weighted_ridge` 在 distance selector 上的 K-curve **出現 U 形**(若沒有,代表正則化太強或實作有問題)。

### Stream B:Selector(1 天)

Phase 1 finding 直接逼出來的新軸,放 `src/smart_pole/neighbors/`:

10. [ ] `diverse.py` — `select_diverse(target, K)`,
        K 個鄰站中強制最大化空間分散度(greedy farthest-point sampling)
11. [ ] `wind_aligned.py` — `select_wind_aligned(target, K, wind_dir)`,
        偏好上風 / 下風方向的站(風帶污染,上風 = 未來訊號)
12. [ ] `hybrid.py` — `select_hybrid(target, K)`,
        先用 correlation 挑 2K,再從中挑 K 個最分散的

**Stream B 驗收**:每個 selector 對任一目標站丟回 K 個 ID + 距離,
unit test 確認 (a) 不選到 target 自己 (b) 回傳數量正確 (c) 順序與 selector 語意一致。

### Stream C:Ablation(0.5 天)

Phase 2 的招牌產出。固定 K=10、`seeds=[1..5]`、`mask=random_point`、`ratio=0.2`:

13. [ ] `configs/experiments/ablation/sel_{distance,correlation,diverse,hybrid}_w_{mean,idw,corr,ridge}.yaml`
        共 16 個 config
14. [ ] `scripts/run_ablation.sh`:批次跑完 16 組
15. [ ] `notebooks/analysis_phase2.ipynb` 出三張圖:
        - (a) 4 × 4 selector × weighting heatmap(MAE,顏色越深越好)
        - (b) 同一個目標站,4 種 selector 挑出的鄰站視覺化地圖
        - (c) Phase 1 vs Phase 2 best 的 K-curve 對比
 
**Stream C 驗收**:16 個 cell 全跑完,heatmap 至少能回答
「**selection 還是 weighting 比較重要?**」notebook 末尾寫一段 5 行結論。

### Stream D:收尾(0.5 天)

16. [ ] `notebooks/analysis_phase2.ipynb` 寫結論段:
        - Phase 2 best 對 Phase 1 best 改善了多少(MAE 絕對值 + 百分比)
        - 改善天花板看起來在哪(best K-curve 還沒到底嗎?)
        - Phase 3 該優先解決什麼(用 ablation 的 worst cell 推)
17. [ ] 更新 `CLAUDE.md` 的「現在的進度」+「Phase 1 已知發現」段,
        加入「Phase 2 已知發現」作為 Phase 3 的輸入
18. [ ] `uv run pytest tests/` 全綠,所有新模型 / selector 都有 unit test

**完成 Phase 2 後停下來給人 review,確認方向 OK 再進 Phase 3。**

## Phase 2 開工前要決定的事

跑 Stream 0 之前先回答這三個,會決定 Stream B / Stream C 的工作量:

1. **CWA 風資料拿得到歷史小時值嗎?**
   拿不到的話,Stream B 的 `wind_aligned` 改成「用觀測時段內竿體之間的相位差推風向」——
   這會變成一個小研究而不是「直接用 wind 資料」。值不值得,你決定。

2. **計算量 sanity check**:Phase 2 大約 240 (Stream A) + 16 (Ablation) + 補跑 ≈ 280 runs。
   每 run 多久?Phase 1 單 run 若 1 分鐘,Phase 2 約 5 小時;若 10 分鐘,約 2 天。
   超過 1 天的話,把 `weighted_ridge` 的 seed 從 5 降到 3。

3. **Block masking 結果差距大不大?**
   Stream 0 跑出第一個 block vs random 對比後,若差距 > 20%,
   Stream C 的 ablation 要分別跑兩種 mask,工作量翻倍——這時候 ablation 只跑 random,
   block 改用「best weighted × 4 個 selector = 4 runs」的小 ablation 即可。
