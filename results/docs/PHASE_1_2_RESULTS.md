# Phase 1 + Phase 2 結果總覽

> 本檔是 Phase 1 / 2 的事實記錄(表格、findings、可解釋性)。Phase 3 開始引用本檔。
> 更新規則:**只追加不重寫**——已寫進來的數字是定錨,後續對比用。

## 1. 範圍與資料

- 區域:高雄,1287 根智慧竿體
- 時間:2025-12-04 ~ 2026-02-05(1456 小時,完整度 99.26%)
- 變數:PM2.5,小時對齊
- 切分:`time_based` 0.8/0.2 → train 1164 hr / test 292 hr
- 缺失策略:`random_point` ratio=0.20,seed ∈ {1, 2, 3, 4, 5}
- 指標:MAE / RMSE / R²

## 2. 模型清單與可解釋性

| Tier | 模型 | 來自 | 可解釋性 | 備註 |
|---:|:---|:---|:---:|:---|
| 1 | `mean` | Phase 1 | 10/10 | K 個鄰站算術平均;最廢 baseline |
| 2 | `idw` | Phase 2 | 10/10 | $w_i = 1/(d_i+\epsilon)^p$ |
| 2 | `corr_weighted` | Phase 2 | 10/10 | $w_i = \max(0, r_i)$,r 從 train 段算 |
| 2 | `gaussian_kernel` | Phase 2 | 9/10 | $w_i = \exp(-d_i^2/2\sigma^2)$,σ 手設 |
| 2 | `weighted_ridge` | Phase 2 | 8/10 | per-target Ridge,K 個鄰站當 features |

## 3. Selector 清單

| selector | 從 | 距離 proxy 單位 | 邏輯 |
|:---|:---|:---|:---|
| `distance` | Phase 1 | 公尺 | haversine 最近 K |
| `correlation` | Phase 1 | 公尺(Phase 2 統一) | train 段 \|r\| top-K |
| `diverse` | Phase 2 | 公尺 | greedy farthest-point sampling |
| `hybrid` | Phase 2 | 公尺 | 先 corr 挑 2K,再 farthest-point K |
| `wind_aligned` | Phase 2 (scaffold) | 公尺 | cos(2θ-θ_wind) − β·d;CWA 風資料缺,暫未 ablation |

## 4. Phase 1 結果

`mean` baseline 在 distance / correlation 兩種 selector 的 K-curve(seed=42 單跑):

| K | corr MAE | dist MAE | corr R² | dist R² |
|---:|---:|---:|---:|---:|
| 1  | 4.02 | 5.42 | 0.45 | 0.24 |
| 3  | 3.46 | 4.37 | 0.63 | 0.49 |
| 5  | 3.39 | 4.12 | 0.66 | 0.55 |
| 10 | **3.38** | 4.01 | **0.67** | 0.57 |
| 20 | 3.41 | 3.96 | 0.67 | 0.59 |
| 30 | 3.47 | 3.90 | 0.66 | 0.60 |

**三個 finding**:

1. correlation selector 全面打敗 distance(MAE 低 0.4–1.4)。在高密度感測網路,
   距離不是好的相似性指標——這本身就是論文等級結論。
2. K-curve 形狀:correlation 在 K=10 觸底再微升(典型 bias-variance);
   distance 從 K=1 到 K=30 還在下降。
3. `mean` 結構性沒 U 形——它沒擬合任何東西;有 U 形是 Phase 2 ridge 才有的事。

## 5. Phase 1 後續修正(Phase 2 Stream 0 補完曲線)

- **distance K-curve 在 K≈50 觸底再上升**:MAE 3.900 @ K=50 / 3.913 @ K=100 / 3.968 @ K=200。
  Phase 1「distance 單調下降沒看到反曲」是 K=30 還沒走遠;**distance 也有 U 形**,
  只是底部比 correlation 高 ~0.5 MAE 且偏右。
- **block masking vs random_point 差距很小**(K=10:3.42 vs 3.40,< 1%)。
  Phase 2 後續 ablation **只跑 random_point**,不開 block 軸。
- 5 seed 重跑後 MAE 標準差約 0.007–0.015,**seed-to-seed 變異極低**——Phase 1 single-seed 數字本身已穩。

## 6. Phase 2 結果

### 6.1 4×4 selector × weighting ablation(K=10、5 seeds、`random_point` 0.2)

MAE(越低越好):

| selector \\ weighting | mean | idw | corr | ridge |
|:---|---:|---:|---:|---:|
| distance    | 4.01 | 4.14 | 3.97 | **2.08** |
| correlation | 3.39 | 3.71 | 3.39 | **1.62** ← Phase 2 best |
| diverse     | 4.65 | 5.41 | 4.46 | 2.34 |
| hybrid      | 3.45 | 3.76 | 3.45 | 2.02 |

±std 在 0.005–0.020 之間,seed 變異遠小於 cell 間差距。

### 6.2 五個 Phase 2 finding

1. **Phase 2 best = `correlation × weighted_ridge`,MAE 1.606 @ K=20**
   (Phase 1 best MAE 3.387 @ K=5/10;**改善 52.5%、絕對 -1.78 MAE**)
2. **weighting > selector**:固定 selector 換 weighting 平均改 ~2.0 MAE;
   固定 weighting 換 selector 平均只改 ~1.0 MAE。Ridge 在任一 selector 上都能壓到 2.3 內,
   選錯也救得回來;反之挑到 correlation 但只用 mean / IDW / corr_weighted 的話天花板就是 3.4
3. **`diverse` 是 Phase 2 最差 selector**:跨所有 weighting 都比 distance 還爛。
   Phase 1 的「強制空間分散能看到更多獨立訊號」假設**被否決**——
   高密度 PM2.5 網路裡把鄰居推遠等於選到不相關的站
4. **`hybrid` ≈ `correlation`**:correlation 挑大池子再 farthest-point 過濾沒帶來增益。
   Top-K 高相關鄰居間的冗餘沒嚴重到要再多樣化
5. **改善天花板未見頂**:Phase 2 best K-curve 在 K=20 觸底(1.606),K=5–20 形成 1.62±0.02 平台,
   K=30 才微升到 1.635。**還有 0.1–0.3 MAE 空間給 Phase 3**

### 6.3 Phase 2 best K-curve(`weighted_ridge × correlation`,5 seeds)

| K | MAE | RMSE | R² |
|---:|---:|---:|---:|
| 1  | 1.881 ± 0.014 | 4.745 ± 0.247 | 0.707 ± 0.026 |
| 3  | 1.688 ± 0.014 | 4.243 ± 0.206 | 0.766 ± 0.019 |
| 5  | 1.643 ± 0.015 | 4.201 ± 0.222 | 0.770 ± 0.020 |
| 10 | 1.624 ± 0.015 | 4.311 ± 0.219 | 0.758 ± 0.020 |
| 20 | **1.606 ± 0.017** | 4.376 ± 0.221 | 0.751 ± 0.021 |
| 30 | 1.635 ± 0.013 | 4.616 ± 0.198 | 0.723 ± 0.020 |

---

## 附錄 A:Phase 2 best 的圖

- 4×4 ablation heatmap:`results/phase2_heatmap.png`
- 同一 target、4 種 selector 的鄰站視覺化:`results/phase2_selector_maps.png`
- Phase 1 vs Phase 2 best K-curve 對比:`results/phase2_kcurve_compare.png`

---

## 附錄 B:Ridge Sanity Check(Phase 3 Stream -1)

Phase 2 best MAE 從 3.39 砍到 1.61(改善 52.5%),數字太漂亮——Phase 3 開新模型前
必須先排除 leakage。三個必驗條件全過。

### B.1 Time-based split 不重疊

| 段 | 起 | 迄 | n |
|:---|:---|:---|---:|
| train | 2025-12-04 00:00 | 2026-01-23 18:00 | 1164 hr |
| test  | 2026-01-23 19:00 | 2026-02-04 23:00 |  292 hr |

`train.max() < test.min()` 為 True;`set(train_ts) ∩ set(test_ts)` size 為 0。

### B.2 Neighbor selection 排除 target

對 30 個隨機 target 用 `correlation × K=10` 跑 `_corr_table` 後檢查 ID 清單:
**0/30 包含 target 自己**。selector code 在計算前已把對角設為 NaN。

### B.3 K=1 R² 遠低於 leakage 警戒線

`weighted_ridge × correlation × K=1`,seed=1,random_point 0.20:

| MAE | RMSE | R² | n |
|---:|---:|---:|---:|
| 1.900 | 4.552 | 0.726 | 74,221 |

**R² = 0.726 < 0.95 警戒線**,沒有 leakage 路徑。K=1 能達 R² ≈ 0.73 的機制
不是「鄰站 = target」,而是 ridge 學了 per-station 截距 + 斜率:

對 200 個 target 各擬一個 K=1 ridge:

|  | mean | std | min | max |
|:---|---:|---:|---:|---:|
| slope $w$    | 0.957 | 0.191 | 0.49 | 1.53 |
| intercept $b$ | 1.170 | 1.891 | -4.32 | 7.71 |

`(slope mean - 1)/std = 0.23`、`(intercept mean - 0)/std = 0.62`——
平均看起來 (1, 0) 附近,但每個 target 各自的 (slope, intercept) 都有顯著偏移,
表示 ridge 做的是 **per-target calibration**。

> Source notebook:`notebooks/phase2_ridge_sanity.ipynb`(executed:`*_executed.ipynb`)

---

## 附錄 C:Ridge Explainability(Phase 3 Stream -1)

問:K=10 ridge 學到的權重 $w_i$ 跟距離 $d_i$ 或 Pearson $r_i$ 有什麼關係?
答:**幾乎沒有**——ridge 做的事不是 IDW、也不是 `corr_weighted` 的近親。

### C.1 10 個隨機 target 的 (Σwᵢ, b)

| target | Σ$w_i$ | $b$ |
|:---|---:|---:|
| 7489197922 | +0.815 | +2.688 |
| 7489589555 | +0.936 | -1.057 |
| 7490249046 | +1.126 | -1.250 |
| 7504124833 | +0.818 | +2.328 |
| 9016045275 | +0.869 | +0.757 |
| 9016750380 | +0.980 | -0.383 |
| 9080594470 | +1.289 | +1.600 |
| 9105098308 | +1.148 | +0.377 |
| 9115497491 | +0.845 | +1.594 |
| 9128728840 | +0.923 | +0.670 |
| **mean ± std** | **0.975 ± 0.161** | **+0.732 ± 1.349** |

- $\sum w_i \approx 1$(0.975 ± 0.16)→ ridge 的確在做「加權平均」,但允許某些 $w_i$ 是負的
  (range -0.6 ~ +0.7)以扣抵互相矛盾的鄰站
- intercept $b$ 範圍 **-1.25 ~ +2.69 µg/m³**——這就是 Phase 1 mean / Phase 2 IDW
  完全沒有的 per-target 系統性偏差校正

### C.2 $w_i$ 與 $d_i$、$r_i$ 的相關性

| 相關性 | Spearman ρ | p |
|:---|---:|---:|
| $w_i$ vs $r_i$(Pearson r) | +0.191 | 0.057 |
| $w_i$ vs $d_i$(距離) | -0.105 | 0.30 |

- ρ($w, r$) 邊緣顯著(p≈0.06)而且只有 +0.19——ridge **沒** 在做「越相關 weight 越大」
- ρ($w, d$) 不顯著——ridge **沒** 在做 IDW 的「越近 weight 越大」

→ 換句話說,ridge 不是 corr_weighted、不是 IDW 的學版本。它在學一個 **與簡單啟發式正交** 的結構,
   而那個結構主要由 per-target intercept 撐起來。

### C.3 視覺化

`results/ridge_explainability.png`:三張子圖
- (1) $w_i$ vs $d_i$ 散點(顏色 = target)
- (2) $w_i$ vs $r_i$ 散點(注意:K=10 corr 鄰居的 $r_i$ 全都集中在 0.84–0.98 區間)
- (3) intercept 直方圖

### C.4 對 Phase 3 的含義

1. **Per-target intercept 是免費 lunch**:任何 Phase 3 模型只要支援 per-station bias,
   就能拿到 ridge 一半左右的改善幅度;反過來也代表
   **Phase 3 Kriging / GP 不寫 per-target mean 校正就會輸 Phase 2 ridge**
2. **Ridge 的 weight 結構是「跨鄰站殘差扣抵」**——這正是空間殘差協方差能 model 的東西。
   Phase 3 OK / GP 把 ridge 的 b 拆成 OK 的 unbiased mean、把 ridge 的 w 結構拆成
   spatial covariance,理論上能贏(視 lengthscale 估準與否)
3. **Phase 3 第一個攻擊目標是 spatial residual 結構**——
   ridge 沒用到 (d_i, r_i) 兩個 prior,但其實這兩個 prior 都帶資訊。Kriging 把它們合成 variogram
   就是 prior 重新用回來的方式

> Source notebook:`notebooks/phase2_ridge_explainability.ipynb`(executed:`*_executed.ipynb`)

**結論:Phase 2 MAE 1.61 是真實成績,不是 leakage。Phase 3 可以放心往前。**
