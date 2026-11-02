# Dataset Preparation and Forecasting

## 1. Dataset Overview

The dataset was finalized with hashed application names converted into readable identifiers (`app_1`, `app_2`, etc.).

Dataset characteristics:
- 318 applications.
- 14 days of traffic data.
- No missing values or missing time intervals.
- Wide-format structure with one `minute` column and individual application columns.

## 2. EDA and Visualization

An EDA and forecasting notebook, `aegiscloud_day3_eda_forecaster.ipynb`, was prepared.

The notebook includes:
- Dataset health checks.
- Per-application statistics: mean, maximum, burstiness (CV), peak-to-mean ratio and zero-traffic percentage.
- Total traffic over time.
- Traffic patterns for six sample applications.
- Average daily traffic patterns.
- Mean versus burstiness analysis.
- Actual versus predicted traffic visualization.

The goal was to understand application behaviour and identify smooth and bursty applications for later simulation.

## 3. Forecasting Approach

The forecasting task was defined as predicting traffic 10 minutes ahead.

Five methods were compared:

1. `naive`: Uses current traffic as the future prediction.
2. `moving_avg`: Uses the average of the previous 10 minutes.
3. `yesterday`: Uses traffic from the same time on the previous day.
4. `gbm`: Uses HistGradientBoostingRegressor.
5. `gbm_q90`: Uses quantile regression at the 90th percentile for safer, higher-side predictions.

The GBM uses lag features, recent averages, traffic variation, previous-day traffic and time-of-day features.

Important training decisions:
- Chronological 70/30 train-test split.
- No future information leakage.
- Log-transformed traffic.
- Training targets restricted to avoid crossing into the test period.

Evaluation metrics:
- WAPE: Overall forecasting error.
- `under_10pct`: Percentage of predictions more than 10% below actual traffic.
- `over_10pct`: Percentage of predictions more than 10% above actual traffic.

## 4. Experimental Results

Overall results:
- GBM achieved approximately 19.1% WAPE.
- Baselines achieved approximately 35.6–36.1% WAPE.
- GBM_Q90 reduced underprediction from 6.9% to 1.9%.
- Its overprediction increased from 14.4% to 25.8%.

However, app_185 heavily distorted the aggregate results because it had long zero-traffic periods followed by large, periodic spikes.

After excluding app_185:

| Model | WAPE |
|---|---:|
| GBM | 3.0% |
| Moving Average | 3.5% |
| Naive | 3.6% |
| GBM_Q90 | 4.4% |
| Yesterday | 6.5% |

Only app_248 showed a noticeable daily traffic pattern. Most applications had relatively flat behaviour.

## 5. Key Conclusions

- GBM provides a useful forecasting baseline but its improvement over simple methods is modest on smooth applications.
- GBM_Q90 offers a safer prediction at the cost of additional resource usage.
- App_185 is an important difficult case for evaluating forecasting and autoscaling.
- Per-application and median metrics are more informative than aggregate averages alone.

## 6. Pending Work

- Compare a PyTorch LSTM against GBM using the same applications, time split, prediction horizon and evaluation metrics.
- Consider predicting the maximum traffic over the next 10 minutes instead of only the traffic at t+10.
- Save predictions for use in the autoscaling simulator.
- Compare threshold-based, target-tracking and forecast-based scaling policies.

The conversation ends with a request for a PyTorch LSTM implementation; the actual implementation is not included in this exported conversation.
