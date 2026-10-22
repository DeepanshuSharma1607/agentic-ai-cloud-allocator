# AegisCloud: Traffic Forecaster (Phase 1, Day 3)

AegisCloud is an agentic autoscaler for any containerized app. This notebook covers the **forecaster**: it predicts how much traffic an app will get 10 minutes from now, so the autoscaler can add replicas before the load arrives.

**Notebook:** `aegiscloud.ipynb` (runs on Google Colab, GPU optional)

---

## 1. Result in one paragraph

On real traffic from 6 apps, a PyTorch LSTM and a gradient boosting model (GBM) are **tied**. The LSTM has the lowest mean error (WAPE 0.189 vs 0.191), but the gap is 0.002 and comes from one seed and 6 apps. That is not a clear win. Both beat the simple baselines on average (about 0.36). For an autoscaler that must not under-provision, the 90th-percentile GBM (`gbm_q90`) is the safest option: it is under-predicted by more than 10% in only 1.9% of minutes.

---

## 2. Data

| Item | Value |
|---|---|
| Source | Azure Functions invocation counts, per minute, one column per app |
| File | `azure_functions_ranked_timeseries.csv` |
| Shape | 20,160 minutes x 318 apps (14 days) |
| Quality checks | 0 missing values, 0 negative values, minutes continuous |
| Apps used | 6, picked from busy to quiet: `app_1, app_62, app_123, app_185, app_248, app_318` |

Findings from the exploration pictures:
- Apps are very different. Mean traffic ranges from about 72 to 89,300 per minute, and burstiness (cv) ranges from 0.01 to 9.46.
- Some apps repeat a daily pattern, some are spiky and unpredictable.
- Always check the column layout of the original Azure trace before reusing this file elsewhere.

---

## 3. Forecasting task and fair-test rules

- **Task:** at minute `t`, predict traffic at `t + 10`. A new replica takes about 2 minutes to start, so acting 10 minutes ahead leaves time to react.
- **Split:** first 70% of time = train, last 30% = test. No shuffling.
- **No peeking:** features use only data up to minute `t`. Train rows are only those whose target is still inside the first 70%.
- **Same rows for all models:** every method is scored on the exact same test minutes (6,038 per app; 12,662 train rows per app).

---

## 4. Methods compared

| Method | What it does |
|---|---|
| `naive` | Traffic in 10 min = traffic now |
| `moving_avg` | Average of the last 10 minutes |
| `yesterday` | Traffic at the same minute yesterday |
| `gbm` | Gradient boosting on recent lags, rolling mean/std, yesterday's value, time of day |
| `gbm_q90` | Same GBM, trained for the 90th percentile (errs on the high side) |
| `lstm` | PyTorch LSTM, trained with MSE |
| `lstm_q90` | Same LSTM, trained with pinball loss at 0.9 |

**GBM:** `HistGradientBoostingRegressor`, 300 iterations, learning rate 0.05, depth 6. Works on `log1p(traffic)`.

**LSTM:**
- Input: last 60 minutes of `log1p(traffic)`, plus yesterday's value, yesterday's change, and sin/cos of time of day
- Architecture: 1-layer LSTM (hidden 64), then a small head (64, ReLU, 1)
- Predicts the change in log traffic from now, scaled by the training spread, then converted back
- Training: Adam, lr 0.002, batch 256, up to 40 epochs. The last 10% of the training rows (in time order) is used as validation, and the best epoch is kept
- One model per app, seed 0

---

## 5. Metrics

- **WAPE** = total absolute error / total traffic. Lower is better.
- **under_10pct** = share of minutes predicted more than 10% too low. This is the risky side: users would see slowness.
- **over_10pct** = share of minutes predicted more than 10% too high. This is the wasteful side: extra cost.

---

## 6. Results

### Average over 6 apps

| Method | WAPE | under_10pct | over_10pct |
|---|---|---|---|
| lstm | **0.189** | 0.068 | 0.139 |
| gbm | 0.191 | 0.069 | 0.144 |
| gbm_q90 | 0.308 | **0.019** | 0.258 |
| moving_avg | 0.356 | 0.064 | 0.174 |
| yesterday | 0.359 | 0.157 | 0.188 |
| naive | 0.361 | 0.102 | 0.109 |
| lstm_q90 | 0.472 | **0.014** | 0.266 |

### WAPE per app

| App | gbm | gbm_q90 | lstm | lstm_q90 | moving_avg | naive | yesterday |
|---|---|---|---|---|---|---|---|
| app_1 | 0.038 | 0.061 | 0.038 | 0.063 | 0.034 | 0.045 | 0.133 |
| app_123 | 0.011 | 0.015 | 0.011 | 0.015 | 0.009 | 0.011 | 0.016 |
| app_185 | 0.992 | 1.630 | 0.984 | 2.599 | 1.960 | 1.985 | 1.829 |
| app_248 | 0.056 | 0.099 | 0.058 | 0.098 | 0.077 | 0.063 | 0.131 |
| app_318 | 0.022 | 0.007 | 0.015 | 0.009 | 0.014 | 0.015 | 0.012 |
| app_62 | 0.025 | 0.037 | 0.027 | 0.046 | 0.039 | 0.048 | 0.031 |

---

## 7. Honest reading of the results

1. **LSTM vs GBM is a tie.** `app_185` is a very bursty app (WAPE near 1.0 for every method) and dominates the average. Without it, LSTM = 0.030 and GBM = 0.030. The GBM wins on 2 apps, the LSTM on 2, and 2 are level.
2. **Simple baselines are enough on smooth apps.** On `app_1` and `app_123`, `moving_avg` beats both learned models. A model only pays off on harder apps.
3. **`app_185` is not solved.** Both models roughly halve the baseline error, but a WAPE near 1.0 is still poor. This is the case where the agent layer (escalation, safe fallback) matters more than the forecaster.
4. **Quantile models trade cost for safety.** `gbm_q90` and `lstm_q90` almost never under-predict, but over-predict in 26% of minutes, which means paying for unused replicas. `lstm_q90` is clearly worse than `gbm_q90` here (WAPE 0.472 vs 0.308), mostly because of `app_185` (2.6 vs 1.6).
5. **Model choice.** The LSTM was selected because it has the lowest mean WAPE and its weights were exported. But the project rule was to keep the LSTM only if it **clearly** beats the simple model. It does not. The GBM trains faster, is easier to explain, and performs the same. Decide with the simulator (cost and SLO-miss), not with WAPE alone.

---

## 8. Limitations

- Only 6 of 318 apps tested. Results may change on other apps.
- Single seed, single 70/30 split. No error bars yet.
- 14 days of data, so only about 9 days of training after the 1-day warm-up for the "yesterday" features.
- WAPE is a forecasting score, not a business score. The real test is replica-minutes (cost) and SLO-miss minutes inside the simulator.
- The data is replayed history. Scaling decisions cannot change user behavior.

---

## 9. Files

| File | Purpose |
|---|---|
| `aegiscloud.ipynb` | Exploration, 5 pictures, baselines, GBM, LSTM, comparison |
| `aegiscloud_best_lstm.zip` | One saved LSTM per app (`<app>.pt`) plus `meta.json` |

Loading a saved LSTM (the `LSTMForecaster` class is defined in the notebook):

```python
import torch
ckpt = torch.load('app_62.pt', map_location='cpu')
model = LSTMForecaster(ckpt['n_static'])
model.load_state_dict(ckpt['state'])
model.eval()
# ckpt also holds mu, sd, dsd (scaling), W (window = 60) and H (horizon = 10)
```

---

## 10. Next steps

1. Plug the forecaster into the simulator (with a 2-minute replica start-up delay).
2. Compare policies by cost and SLO-miss: threshold rule, target tracking, forecast + schedule.
3. Run over several trace slices and report the spread, not one number.
4. Decide GBM vs LSTM from the simulator results.
5. Phase 2: rule-based controller, then the LLM governor with a code guardrail and audit log.
