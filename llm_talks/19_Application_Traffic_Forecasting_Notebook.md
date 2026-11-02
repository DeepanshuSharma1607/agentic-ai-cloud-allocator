# Application Traffic Forecasting Notebook Using Application Metrics

**Source conversation:** `Create Traffic Forecasting Notebook`  
**Conversation date:** 29 October 2026  
**Scope:** Rebuilding an existing Azure Functions forecasting notebook using the user's own application-traffic CSV and only the `minute` and `requests` data.

## Objective

The user supplied:

- `metrics_combined.csv`, containing application-generated traffic records and many additional metrics.
- `lstm_model(1).ipynb`, an older notebook trained on Azure Functions data.

The request was to create a new notebook that followed the older notebook's analysis/training workflow but removed dependence on the Azure dataset and used only the user's own `minute` and `requests` fields. The user wanted cell outputs visible in the notebook.

## Input data and time interpretation

The supplied CSV contained **20,160 raw rows**. The timestamps were typically about **five seconds apart**, even though the `minute` column increased sequentially for each row.

To form one-minute request totals, the new notebook grouped every **12 consecutive five-second samples** and summed their `requests` values. This yielded:

- **1,680 aggregated one-minute rows**.
- A forecast horizon of **10 minutes** in the aggregated sequence.

The processing followed sample order. It did not use wall-clock timestamps to repair gaps, because the requested modeling inputs were restricted to `minute` and `requests`. The conversation explicitly distinguished the `minute` index from a verified real-world minute timestamp.

## Notebook workflow

The new notebook was based on the previous notebook's workflow and included:

1. Data loading and cleaning using only `minute` and `requests`.
2. Traffic statistics, data-quality checks, and exploratory plots.
3. Chronological **70/30 train/test split**.
4. Naive and moving-average baselines.
5. Gradient Boosting and 90th-percentile Gradient Boosting.
6. PyTorch LSTM and 90th-percentile LSTM.
7. Evaluation using WAPE, MAE, RMSE, under-prediction rate, and over-prediction rate.
8. Actual-versus-predicted plots and saved model artifacts.

The notebook was delivered as `application_traffic_forecasting.ipynb`, with executed outputs saved in the cells. The conversation stated that all **15 code cells** had been executed successfully on the supplied CSV, with evaluation tables and plots present.

A separate ZIP, `traffic_forecaster_artifacts.zip`, was provided with the selected model, metadata, comparison metrics, and test predictions.

## Reported experiment result

In the reference run, **Gradient Boosting achieved approximately 24.52% WAPE**, the lowest WAPE among the trainable models in that comparison, and was saved in the artifacts ZIP.

The conversation did not provide the complete numeric score table for every model in the new notebook, so no other exact metrics are recorded here.

## Important limitations

- The one-minute series was created by summing 12 consecutive five-second rows; this assumes the rows represent the intended regular sequence.
- Aggregation was based on row order, not wall-clock gap correction.
- The modeling input was intentionally limited to the user's `minute` and `requests` values; the other CSV metrics were not used as model inputs.
- Similarity of CSV structure to the Azure-oriented workflow does not imply that the new application traffic follows the Azure Functions distribution.

## Delivered outputs and pending use

**Delivered**
- `application_traffic_forecasting.ipynb` — notebook with saved cell outputs.
- `traffic_forecaster_artifacts.zip` — selected model and evaluation artifacts.

**Recommended use**
- Place the notebook alongside `metrics_combined.csv`, or upload the CSV when prompted in Google Colab.
- Run cells from top to bottom to repeat the training on the supplied application traffic.

The conversation did not describe a later deployment integration of the selected Gradient Boosting artifact; the delivered work was the training/evaluation notebook and its artifact bundle.
