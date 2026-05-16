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

**Phase 3 額外硬規定:可解釋性 ≥ 8/10**。
所有 Phase 3 模型必須是線性 / 高斯 / 矩陣分解類,**禁止 XGBoost / LightGBM / Random Forest / NN**。
ML 模型整批延後到 Phase 4(若有需要)。

## 現在的進度

- ✅ `data_gathering.py` → `data/pole_hourly.parquet` (canonical 資料)
- ✅ `notebook.ipynb` (EDA) → EPA 12 站平均 vs 竿體跨裝置平均,Pearson r = 0.941
- ✅ `data/MOENV_iot_station.csv` → 全國 IoT 測站表,**高雄 1287 站與 parquet 完全對齊**
- ✅ **Phase 1**:Tier 1 baseline(`mean`)+ distance/correlation selector,**best MAE 3.38**
- ✅ **Phase 2**:Tier 2 weighted(idw/corr/gaussian/ridge)+ 4 selector ablation,
   **best `ridge × correlation × K=20` MAE 1.61**(改善 52.5%)
- ✅ **Phase 3**:全數學時空模型,8 個 Tier 3 模型全綠,**best `elastic_net × correlation × K=5` MAE 1.017**
   (改善 P2 ridge 36.7%);完整結果見 **@docs/PHASE_3_RESULTS.md**
- ⏳ Phase 4(暫定):ML 模型(XGBoost / LightGBM)—— 只有當 Phase 3 撞牆時才開
- ⏳ Phase 5(暫定):Attention(Transformer / GAT / ST-GAT)—— **暫時別碰**

## 已知發現

詳細結果(含表格、模型清單、可解釋性分數、findings 列表)見:

**@docs/PHASE_1_2_RESULTS.md**(Phase 1+2 + Stream -1 ridge sanity)
**@docs/PHASE_3_RESULTS.md**(Phase 3a + 3b + 3c)

進 Phase 3 前要記住的三件事:

1. **Weighting > Selector**:Phase 2 ablation 顯示 weighting 軸的天花板比 selector 高
2. **`mean` 模型結構性沒 U 形;`ridge` 加了正則化也沒看到反曲**——Ridge 強到要懷疑
3. **Ridge MAE 1.61 必須先做 sanity check**(Phase 3 Stream -1 第一件事)

### Phase 3 已知發現(Phase 4 開不開的判斷依據)

1. **時空冠軍 `elastic_net @ K=5` MAE 1.017**——已逼近 PM2.5 量測下限(~1 µg/m³),
   進 Phase 4 (XGBoost) 邊際收益小,**暫不建議開 Phase 4**
2. **`tgt_t-1` 被 100% target 保留**——PM2.5 強局部自迴歸,
   任何時空模型沒吃 target 自身歷史 → 結構性劣勢
3. **加 lag 後 K 越大越糟**——最佳 K 從 P2 的 20 掉到 P3c 的 3–5,
   高密度感測網路 + 時間 lag 的組合天然壓 K
4. **GLS AR(1) ρ ≈ 0**——加 lag 後殘差已白,任何「殘差協方差校正」類模型
   (含 ST-Kriging)在這條 pipeline 都是 no-op
5. **Kriging 46% fallback、ST-GP 退化到 prior**——
   傳統地理統計 / GP 在這個資料密度下表現差於 IDW;
   論文必須講清楚「方法選擇要看資料尺度」
6. **DINEOF 5 modes 解釋 85% 變動**——PM2.5 (T, S) 動態本質低秩,
   未來若做 whole_station masking,DINEOF 是首選
7. **Phase 3 全 11 模型 `explainability ≥ 8`**——
   registry 把關有效,Phase 4 ML 模型若要進入須先解決 explainability 問題

## 環境

- Container:`nvidia/cuda:12.9.0-cudnn-runtime-ubuntu24.04`
- Python:3.13.13(`.python-version`),`uv` 管套件
- GPU:2× NVIDIA RTX 6000 Ada,~49 GB VRAM each
- **Phase 3 GPU 使用**:`gpytorch` 跑 ST-GP 才用 GPU,其他模型 CPU 即可

### 套件管理

```bash
uv add <package>          # 加依賴(同時更新 pyproject.toml 和 uv.lock)
uv sync                   # 從 lock 還原環境
uv run python <script>    # 跑東西
uv run pytest tests/      # 跑測試
```

**不要直接 `pip install`**——會繞過 lock 檔。

### Phase 3 新依賴(預計)

```bash
uv add gstools           # ST-Kriging 主用
uv add scikit-gstat      # variogram 視覺化備援
uv add gpytorch          # ST-GP
uv add statsmodels       # GLS / DLM
```

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
| metrics、loaders、scripts | Sanity check / 可解釋性分析 |
| 任何會被 import 的東西 | |
| 任何訓練超過 5 分鐘的任務 | |

**禁止**:
- ✗ 在 notebook 裡定義 model class
- ✗ 在 notebook 裡跑 multi-run sweep
- ✗ 把模型訓練程式碼複製到 notebook 「快速測試」——改成 `tests/` 裡寫測試

## 目錄

```
smart_pole/
├── data/                          ← read-only
│   ├── 高雄資料/                   ← raw 竿體
│   ├── epa_data/                  ← raw EPA
│   ├── MOENV_iot_station.csv      ← 全國 IoT 測站表,座標來源
│   └── pole_hourly.parquet        ← canonical
├── data_gathering.py              ← 已完成,別動
├── notebook.ipynb                 ← EDA,別動
├── NotoSansCJKtc-Regular.otf      ← matplotlib 中文字型
├── docs/                          ← 階段性結果文件
│   ├── PHASE_1_2_RESULTS.md       ← Phase 1+2 完整結果
│   └── PHASE_3_RESULTS.md         ← Phase 3 結束時產出
├── configs/                       ← 一個 YAML = 一個實驗
│   ├── base.yaml
│   └── experiments/
├── src/smart_pole/                ← 框架本體
│   ├── data/                      ← 從 parquet 切資料
│   ├── features/                  ← Phase 3 新增,時空特徵工程
│   │   └── temporal.py            ← lag / rolling feature builder
│   ├── masking/                   ← random_point / block / whole_station
│   ├── neighbors/                 ← 5 種 selector (Phase 2 已完成)
│   ├── models/
│   │   ├── base.py                ← BaseImputer 契約
│   │   ├── registry.py            ← @register decorator
│   │   ├── baseline/              ← Tier 1 (完成)
│   │   ├── weighted/              ← Tier 2 (完成)
│   │   ├── mathematical/          ← Tier 3 (Phase 3 進行中)
│   │   │   ├── kriging.py         ← Ordinary Kriging
│   │   │   ├── gp_spatial.py      ← spatial GP
│   │   │   ├── idw_optimal.py     ← IDW with CV power
│   │   │   ├── timelag_ridge.py   ← 時空線性 (3c)
│   │   │   ├── elastic_net.py     ← 時空線性 (3c)
│   │   │   ├── gls.py             ← 時空線性 (3c)
│   │   │   ├── st_kriging.py      ← 時空 Kriging
│   │   │   ├── st_gp.py           ← 時空 GP (gpytorch)
│   │   │   └── dineof.py          ← 矩陣分解
│   │   ├── ml/                    ← Tier 4 (Phase 4,暫不開)
│   │   └── attention/             ← Tier 5 (Phase 5,暫不開)
│   ├── evaluation/                ← metrics + reporter
│   ├── visualization/             ← plots + maps
│   └── runner/                    ← experiment.py,主入口
├── scripts/                       ← CLI 腳本
├── results/runs/                  ← 每跑一次一個資料夾
├── notebooks/                     ← 結果分析 notebooks
└── tests/
```

## BaseImputer 契約

**所有模型必須繼承這個**。Runner 假設介面長這樣,改 signature 整個 pipeline 都壞。

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
              (Phase 3 feature.enabled=true 時 shape 變 (n_samples, K * (1 + L + R)))
        y:    shape (n_samples,)
        meta: dict,含:
            - target_station_id:    str
            - neighbor_station_ids: list[str]
            - distances:            np.ndarray, shape (n_samples, K)
            - timestamps:           pd.DatetimeIndex
            - target_coord:         tuple[float, float]  (lon, lat)
            - neighbor_coords:      np.ndarray, shape (K, 2)
            - feature_names:        list[str]  (Phase 3 新增,enabled=true 時必填)
    """
    name: str = "base"
    tier: int = 0
    requires_gpu: bool = False
    explainability: int = 0       # Phase 3 新增,1–10,< 8 不能進 Phase 3 model registry

    def __init__(self, **params: Any) -> None:
        self.params = params
        self._fitted = False

    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray, meta: dict[str, Any]) -> "BaseImputer": ...

    @abstractmethod
    def predict(self, X: np.ndarray, meta: dict[str, Any]) -> np.ndarray: ...

    def get_config(self) -> dict[str, Any]:
        return {"name": self.name, "tier": self.tier,
                "explainability": self.explainability, "params": self.params}

    def explain(self) -> dict[str, Any] | None:
        """Phase 3 模型必須實作,回傳「為什麼這樣預測」的可讀資訊。
        例如 ridge 回傳 {weights, intercept};kriging 回傳 {variogram_params}。
        None 表示這個模型本來就是 closed-form 不需解釋。"""
        return None
```

### 違反契約的行為

- ✗ 在 `fit` / `predict` 加自訂位置參數——一律走 `meta` dict
- ✗ 在 model class 內部讀檔——資料一律外部傳入
- ✗ 把超參寫死——透過 `__init__(**params)` 傳,讓 config 控
- ✗ 在 model 裡 `print()`——用 `logging.getLogger(__name__)`
- ✗ **Phase 3 模型 `explainability < 8`**——直接拒絕進 registry

## Config Schema

```yaml
# configs/experiments/exp_<id>.yaml
experiment_id: exp_<id>
seeds: [1, 2, 3, 4, 5]      # multi-seed 標配

data:
  cache_path: data/pole_hourly.parquet
  station_info_path: data/MOENV_iot_station.csv
  target_var: pm25
  start: 2025-12-01
  end:   2026-02-08
  freq: 1h

masking:
  strategy: random_point      # random_point | block | whole_station
  ratio: 0.20
  block_hours: 6

neighbors:
  selector: correlation       # distance | correlation | diverse | wind_aligned | hybrid
  k_list: [30, 20, 10, 5, 3, 1]

split:
  method: time_based          # time_based | random
  train_ratio: 0.8

# Phase 3 新增:時空特徵
features:
  enabled: false              # Phase 3a/3b 關;3c 起開
  lags: [1, 2, 3, 6, 24]      # 小時
  rolling: [3, 6, 24]         # 小時

model:
  name: ridge
  params: {alpha: 1.0}

evaluation:
  metrics: [mae, rmse, r2]
  plots: [scatter, residual_ts, k_curve, spatial_error]
  explain: true               # Phase 3 預設要產 explain.json
```

## Results Folder Schema

```
results/runs/{experiment_id}_{model}_K{K}_seed{seed}_{YYYYMMDD-HHMMSS}/
├── config.yaml          ← resolved 完整 config
├── metrics.json
├── predictions.parquet  ← columns: [timestamp, station_id, y_true, y_pred, residual]
├── explain.json         ← Phase 3 新增,BaseImputer.explain() 的結果
├── log.txt
└── plots/
```

## 風格規則(只列非 default 的)

- 註解、docstring、log 訊息一律**繁體中文**
- `from __future__ import annotations` + 型別標註
- 路徑一律 `pathlib.Path`
- 時間戳一律 `pd.Timestamp`,UTC
- 任何隨機操作必須吃 `seed: int`,**沒有 default seed**
- 用 `logging.getLogger(__name__)`,不要 `print`(notebook 例外)
- matplotlib 畫圖前先設中文字型(`NotoSansCJKtc-Regular.otf`)
- **Phase 3 模型必須實作 `.explain()`**,回傳 JSON-serializable dict

## GPU

- Phase 3 只有 `st_gp.py` (gpytorch) 用 GPU,其他全 CPU
- `requires_gpu = True` 的模型,runner 自動 set `CUDA_VISIBLE_DEVICES`
- 想分流兩張卡跑同模型不同 K:`CUDA_VISIBLE_DEVICES=0 uv run ... --k_list 30,20,10`
  另一張 `=1 uv run ... --k_list 5,3,1`
- 不要在 model class 裡寫死 device

## 動之前要問的檔

| 檔案 | 為什麼小心 |
|---|---|
| `data_gathering.py` | 生 canonical parquet |
| `data/` 下任何東西 | read-only,動了重現性掛掉 |
| `src/smart_pole/models/base.py` | 介面動了所有 model 都要改 |
| `pyproject.toml` | 用 `uv add`,不要手改 |
| `notebook.ipynb` | EDA 已定格 |
| `docs/PHASE_*.md` | 階段性事實記錄,動了論文對不起來 |

## 給 Claude Code 的指示

1. 改程式碼前先看現有的同類檔
2. 加新模型一定走 `BaseImputer` + `@register`
3. **Phase 3 模型 `explainability < 8` 直接拒絕**,跟人討論可解釋性怎麼提到 8 再說
4. 框架程式碼裡發現要加 magic number / 寫死路徑——**停下來問人**
5. 不要建 `xxx_v2.py` / `xxx_new.py`
6. 結束 task 前跑 `uv run pytest tests/`

---

## Phase 3 具體 TODO

**Phase 3 = 全數學時空路線**,不碰 ML。預計 6 天。
分 6 個 stream,**按順序做,不要平行開**。

### Stream -1:Ridge Sanity Check + 可解釋性分析(0.5 天)

開新模型前必做。Phase 2 best MAE 1.61 太強,要先排除 leakage。

1. [ ] `notebooks/phase2_ridge_sanity.ipynb`:
       - 確認 `split.method=time_based` 在 ridge config 真的生效(印出 train/test timestamps 邊界)
       - 確認 neighbor selection 完全排除 target station 自己
       - 跑 ridge × K=1,看 R²(> 0.95 → leakage)
       - 若有 leakage:**先修再說,Phase 3 暫停**
2. [ ] `notebooks/phase2_ridge_explainability.ipynb`:
       - 對 10 個隨機 target,印 K=10 的 $w_i$ 分佈
       - $w_i$ vs $d_i$、$w_i$ vs $r_i$ 的 scatter
       - 截距 $b$ 的分佈
       - 結論寫進 `docs/PHASE_1_2_RESULTS.md` 的附錄

**Stream -1 驗收**:`docs/PHASE_1_2_RESULTS.md` 多一段 ~100 字的「Ridge 為什麼這麼強」解釋,
Phase 3 設計才有依據。

### Stream 0:時空 Feature Builder(0.5 天)

Phase 3 所有時空模型共用的工具。**寫一次,後面 3c/3b 都用同一份**。

3. [ ] `src/smart_pole/features/temporal.py`:
       ```python
       class TemporalFeatureBuilder:
           def __init__(self, lags: list[int], rolling: list[int]) -> None: ...
           def build(self, X: np.ndarray, timestamps: pd.DatetimeIndex,
                     target_history: np.ndarray) -> tuple[np.ndarray, list[str]]:
               """回傳 X_aug shape (n, K * (1 + len(lags) + len(rolling)) + len(lags))
               最後 +len(lags) 是 target 自己的歷史"""
       ```
4. [ ] `tests/test_temporal_features.py`:`lags=[], rolling=[]` 退化成 Phase 2 行為
5. [ ] **跑 PM2.5 ACF 確認 lag 範圍**:在 `notebooks/eda_acf.ipynb` 畫 ACF,
       看 24 小時、72 小時、168 小時的自相關有沒有意義,才能定 `lags` 預設值

**Stream 0 驗收**:`features.enabled=false` 跑出來 metrics 與 Phase 2 完全一致;
ACF 圖確認 PM2.5 在 lag=24 仍有顯著自相關。

### Phase 3a:Tier 3 純空間模型(1 天)

論文 baseline,不期待效能突破,但**「我試過經典空間方法」這件事必須有**。
`features.enabled=false`。

6. [ ] `models/mathematical/idw_optimal.py` — `IDWOptimalImputer()`
       - CV 自動找 power(原 IDW 是手設)
       - 可解釋性:10/10
7. [ ] `models/mathematical/kriging.py` — `OrdinaryKrigingImputer(variogram_model)`
       - `gstools` 套件
       - `variogram_model` ∈ {`spherical`, `exponential`, `gaussian`}
       - **variogram 全期 fit**(逐時太貴,結果差不多)
       - `.explain()` 回傳 variogram 參數 (sill, range, nugget)
       - 可解釋性:9/10(variogram 圖人可讀)
8. [ ] `models/mathematical/gp_spatial.py` — `SpatialGPImputer(kernel, lengthscale_init)`
       - `gpytorch`,純空間 GP(時間軸先不上)
       - kernel:RBF / Matern52
       - `.explain()` 回傳 learned lengthscale、noise variance
       - 可解釋性:8/10
       - `requires_gpu = True`

**Phase 3a 驗收**:
- 3 個模型 × correlation selector × 6 K × 5 seed = 90 runs 全綠
- K-curve 對比圖:Phase 2 ridge vs IDW_optimal vs Kriging vs GP
- **預期結果**:三個都打不過 Phase 2 ridge(這是合理的負結果,寫進論文)

### Phase 3c:時空線性模型(1 天,先做!)

3c 之所以提前到 3b 之前,是因為**這條最便宜也最可能贏**。
如果 ridge + 時間 lag 直接壓到 MAE < 1.0,後面 ST-Kriging / ST-GP 要超過會非常難。
**`features.enabled=true`,所有模型吃時空特徵向量**。

9. [ ] `models/mathematical/timelag_ridge.py` — `TimeLagRidgeImputer(alpha)`
       - Phase 2 ridge 的時空升級,結構完全一樣只是 X 變寬
       - 可解釋性:10/10($w_i$ 直接可讀,每個 lag/rolling feature 一個權重)
       - `.explain()` 回傳完整 weight vector + feature_names
10. [ ] `models/mathematical/elastic_net.py` — `ElasticNetImputer(alpha, l1_ratio)`
        - L1 + L2,自動選 lag(L1 把不重要的 lag 權重壓 0)
        - 可解釋性:10/10(權重稀疏,挑出最重要的 features)
        - `.explain()` 回傳非零 weights + 對應 feature_names
11. [ ] `models/mathematical/gls.py` — `GLSImputer(cov_structure)`
        - Generalized Least Squares,殘差協方差矩陣校正
        - 本質上是線性 ST-Kriging
        - `statsmodels.regression.linear_model.GLS`
        - 可解釋性:9/10

**Phase 3c 驗收**:
- 3 個模型 × correlation selector × K=10 固定 × 5 seed × 多組 lag 設定
- **若 `timelag_ridge` 已壓到 MAE < 1.5**:停下來討論是否還要做 3b
- **若 `elastic_net` 自動選出的 lag 集中在某幾個**:這就是論文很漂亮的 finding
- 出一張圖:Phase 2 ridge(純空間)vs timelag_ridge(時空)的 K-curve

### Phase 3b:時空數學模型(2.5 天)

如果 3c 還沒打穿天花板,進 3b。**`features.enabled=true`**。

12. [ ] `models/mathematical/st_kriging.py` — `STKrigingImputer(variogram_model)`
        - `gstools` 的時空 variogram(product-sum 或 metric)
        - 比 spatial-only Kriging 多一個 time scaling 參數
        - 可解釋性:9/10(variogram 圖 2D → 3D,還是看得懂)
13. [ ] `models/mathematical/st_gp.py` — `STGPImputer(kernel_type)`
        - `gpytorch` 的 spatio-temporal GP
        - kernel:separable (RBF_s × RBF_t) 或 non-separable (Gneiting)
        - 可解釋性:8/10(spatial lengthscale + temporal lengthscale 都可讀)
        - `requires_gpu = True`,可能要 batch 才能跑大 K
14. [ ] `models/mathematical/dineof.py` — `DINEOFImputer(n_modes, max_iter)`
        - **先用 sklearn `IterativeImputer + TruncatedSVD` 簡化版**(等價於 DINEOF 的核心思路)
        - 真正的 DINEOF 算法後續再說
        - 可解釋性:9/10(空間模態圖、時間係數曲線可畫出來)
        - 對 `whole_station` masking 特別強(連續缺值是它的主場)

**Phase 3b 驗收**:
- 每個模型 × correlation selector × K=10 × 5 seed
- ST-GP OOM 時降到 K ≤ 20
- DINEOF 在 random_point 跟 whole_station 兩種 mask 各跑一次
- notebook 對比圖:Phase 2 ridge vs Phase 3c timelag_ridge vs Phase 3b 三模型

### Stream Z:Phase 3 收尾(0.5 天)

15. [ ] `docs/PHASE_3_RESULTS.md`(對齊 `PHASE_1_2_RESULTS.md` 格式):
        - 所有模型結果表
        - 「**weighting × time** 的天花板在哪」
        - 每個模型的 `.explain()` 範例輸出
        - 可解釋性總表(8 個模型 + Phase 1/2 的 5 個)
16. [ ] 更新 `CLAUDE.md`:加「Phase 3 已知發現」,Phase 4 該不該開的判斷
17. [ ] `uv run pytest tests/` 全綠

**完成 Phase 3 後停下來給人 review。**

## Phase 3 開工前要決定的事

1. **Stream -1 必做**——Ridge 解釋分析是 Phase 3 設計的依據,不要跳
2. **計算量 sanity check**:Phase 3 大約 90 (3a) + 60 (3c) + 60 (3b) ≈ 210 runs。
   每 run 若 2 分鐘,~7 小時;若 10 分鐘,~1.5 天。
   GP 可能單 run 就 30 分鐘,要先測一次再決定要不要降 seed 數
3. **Lag 範圍依 Stream 0 ACF 圖決定**——預設 `[1, 2, 3, 6, 24]`,
   但若 ACF 在 168 小時(週週期)仍顯著,加進來
4. **3c 表現太強的話 3b 怎麼辦?**
   - 如果 `timelag_ridge` MAE < 1.0:3b 改成只跑 ST-GP(因為理論最完整),
     Kriging 跟 DINEOF 留到撰寫論文時再看要不要補
   - 如果 `timelag_ridge` MAE 1.0–1.4:3b 三個全做
   - 如果 `timelag_ridge` MAE > 1.4:可能 ACF 沒抓對,先回 Stream 0 檢查