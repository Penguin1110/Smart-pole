# Smart Pole PM2.5 補值套件

11 個演算法(Phase 1 ~ Phase 3),統一介面。專為「儀表板補值」場景設計:

> 使用者選一根目標竿體 + K 根鄰居 + 時間點 → 系統把目標當下值「藏起來」,
> 跑所有演算法,回傳每個演算法的 `prediction` / `ground_truth` / `absolute_error` / `train_mae`。

---

## 5 分鐘上手

```bash
# 1. 安裝(套件本身 + 依賴一次裝完)
cd smart_pole_imputation
pip install -e .

# 2. 跑範例
jupyter notebook example.ipynb
```

或直接 Python:

```python
from smart_pole_imputation import load_pole_hourly, impute_single, summarize

dataset = load_pole_hourly(
    "sample_data/pole_hourly_sample.parquet",
    station_info_path="sample_data/MOENV_iot_station.csv",
)

results = impute_single(
    dataset,
    target_id="7527275539",                              # 使用者點選要消失的竿體
    neighbor_ids=["7527351738", "7527563599", "..."],    # 使用者選的 K 根鄰居
    target_time="2026-01-30 07:00",                      # 使用者選的時間點
    skip_gpu=True,                                       # 若無 GPU,先跳 st_gp
)

print(summarize(results))
# →           model  prediction  ground_truth  absolute_error  train_mae  elapsed_s
#               gls      16.251        16.240           0.011      0.639      0.198
#    weighted_ridge      16.254        16.240           0.013      0.950      0.619
#     timelag_ridge      16.203        16.240           0.037      0.628      0.002
#     ...
```

---

## API 一覽

### `load_pole_hourly(parquet_path, *, start=None, end=None, station_info_path=None)`

讀資料,回傳 `PoleDataset(timestamps, station_ids, values, coords)`。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `timestamps` | `pd.DatetimeIndex` | shape `(T,)` |
| `station_ids` | `list[str]` | length `S` |
| `values` | `np.ndarray (T, S)` | PM2.5 µg/m³,NaN 表缺值 |
| `coords` | `dict[str, (lon, lat)]` | None 時 distance/kriging/GP 不可用 |

### `impute_single(dataset, target_id, neighbor_ids, target_time, ...)`

主要 entry point。回傳 `dict[algo_name → result_dict]`,每個 result_dict:

```python
{
    "prediction":      float,       # 演算法在 t* 預測的 PM2.5 (µg/m³),NaN 表失敗
    "ground_truth":    float,       # dataset 中該格真值
    "absolute_error":  float,       # |pred - true|
    "train_mae":       float,       # 該演算法在訓練集的 MAE(DINEOF/ST-GP 為 NaN)
    "elapsed_s":       float,       # fit + predict 牆鐘時間
    "explain":         dict | None, # BaseImputer.explain():weights / variogram / 等可讀資訊
    "error":           str | None,  # 該模型若整段拋例外,訊息在這
}
```

完整參數見 `pipeline.py` docstring。常用 kwargs:

- `models=None` → 跑全部;傳 `["mean", "elastic_net"]` 只跑指定模型
- `skip_gpu=True` → 跳過 `st_gp`(沒 GPU 時用)
- `feature_lags=[1, 2, 3, 6, 24]` / `feature_rolling=[3, 6, 24]` → 給 Phase 3c 線性模型的時空特徵
- `model_params={"elastic_net": {"alpha": 0.1}}` → 覆寫單一模型超參

### `summarize(results) → pd.DataFrame`

把 `impute_single` 結果整理成 DataFrame,按 `absolute_error` 升序排。

### `list_models()` / `REGISTRY`

```python
>>> from smart_pole_imputation import list_models
>>> list_models()
['corr_weighted', 'dineof', 'elastic_net', 'gaussian_kernel', 'gls',
 'idw', 'idw_optimal', 'kriging', 'mean', 'spatial_gp', 'st_gp',
 'timelag_ridge', 'weighted_ridge']
```

直接拿 class:

```python
from smart_pole_imputation import REGISTRY
ElasticNet = REGISTRY["elastic_net"]
imputer = ElasticNet(alpha=0.05, l1_ratio=0.5, max_iter=5000, min_train=24)
# 自行 fit/predict —— 詳見 BaseImputer 契約
```

---

## 演算法清單

| Name | Tier | Explain | Phase | 備註 |
|---|:---:|:---:|:---:|---|
| `mean` | 1 | 10 | P1 | K 鄰站算術平均 |
| `idw` | 2 | 10 | P2 | `1/(d+eps)^power` 加權 |
| `corr_weighted` | 2 | 10 | P2 | `max(0, Pearson r)` 加權 |
| `gaussian_kernel` | 2 | 9 | P2 | `exp(-d²/2σ²)` 加權 |
| `weighted_ridge` | 2 | 8 | P2 | Ridge with optional dist/corr scaling |
| `idw_optimal` | 3 | 10 | P3a | CV-tuned power IDW |
| `kriging` | 3 | 9 | P3a | Ordinary Kriging (`gstools`) |
| `spatial_gp` | 3 | 8 | P3a | gpytorch ExactGP (Matern52 / RBF) |
| `timelag_ridge` | 3 | 10 | P3c | Ridge + lag/rolling/target_lag |
| `elastic_net` | 3 | 10 | P3c | L1+L2 自動挑 feature |
| `gls` | 3 | 9 | P3c | statsmodels OLS / GLSAR |
| `dineof` | 3 | 9 | P3b | SVD-iterative on full (T, S) matrix |
| `st_gp` | 3 | 8 | P3b | Separable ST-GP **(需 GPU)** |

Phase 3 全 11 模型可解釋性 ≥ 8,符合論文要求。

---

## 速度參考(K=5、336 hr 資料)

| 等級 | 模型 | 耗時 |
|---|---|---|
| 快(<10ms) | `mean`, `idw`, `corr_weighted`, `gaussian_kernel`, `idw_optimal`, `timelag_ridge`, `elastic_net`, `dineof` | < 0.02s |
| 中(0.1~1s) | `kriging`, `gls` | ~0.2s |
| 慢(>1s) | `spatial_gp`, `weighted_ridge`(K 大時), `st_gp` | 0.6 ~ 3s |

**串行全跑大約 4~6 秒**;1287 站 full dataset 時 spatial_gp / kriging 會慢一些(各約 2~5s),預估全跑 ~10~15s。

### 加速建議(給儀表板團隊)

1. **預設只跑快檔 8 個,慢檔讓使用者勾選才跑**(最簡單)
2. **fit 結果可 pickle cache**:同 target × 同鄰居 × 同 train window 跑過一次後快取
3. **async / streaming**:先回快的、慢的後補

---

## 目錄結構

```
smart_pole_imputation/
├── README.md              ← 你正在看
├── pyproject.toml         ← 依賴宣告(uv / pip 都能裝)
├── __init__.py            ← public API export
├── imputers.py            ← BaseImputer + 11 個演算法 class
├── features.py            ← TemporalFeatureBuilder(Phase 3c 模型用)
├── data_io.py             ← load_pole_hourly + haversine
├── pipeline.py            ← impute_single() / summarize()
├── example.ipynb          ← 5 分鐘範例(用 sample_data 跑)
└── sample_data/
    ├── pole_hourly_sample.parquet     ← 60 站 × 2 週
    └── MOENV_iot_station.csv          ← 對應座標
```

---

## 環境

- Python ≥ 3.11
- CPU 即可(`st_gp` 需要 GPU,沒 GPU 用 `skip_gpu=True` 跳掉)
- 依賴:`numpy / pandas / pyarrow / scikit-learn / statsmodels / gstools / gpytorch / torch`

---

## 注意事項

1. **`target_id` 不可同時在 `neighbor_ids` 裡**——會拋例外
2. **`target_time` 必須在 dataset 時間範圍內**——不在會拋例外
3. **K 太小(<3)時 `kriging` / `spatial_gp` 容易 fallback 到 uniform mean**——這時 `explain` 會有 `error` 欄位
4. **`feature_lags=[24]` 需要至少 24 hr 歷史**——若 dataset 不夠長,前 24 row 的 features 是 NaN(Ridge 會 drop)
5. **`dineof` / `st_gp` 的 `train_mae` 是 NaN**——這兩個模型不在「per-row train MAE」的框架下,要算的話得另外做 CV

---

## 把這份程式接到生產資料

1. 把 `sample_data/` 換成 prod 路徑(完整 `pole_hourly.parquet` + `MOENV_iot_station.csv`)
2. 或者讓 caller 直接傳 `PoleDataset(timestamps, station_ids, values, coords)`——不一定要從 parquet 讀

---

## 來源

來自 `smart_pole/` 主專案 Phase 1-3 實驗成果,演算法選擇與預設超參皆通過
1287 站 × 1456 hr 高雄 PM2.5 實驗驗證(best:`elastic_net @ K=5` MAE 1.017)。
