# AegisCloud Project Status and Extended LSTM Evaluation Notebook

## 1. Project Context

The reviewed project is an **Agentic AI Cloud Resource Allocator** intended to forecast workload, detect overload and determine when application replicas should increase or decrease.

The discussed pipeline combined:
- FastAPI target application and traffic generator;
- metrics collection for requests, CPU, memory, latency, errors and timeouts;
- Prometheus and Grafana monitoring;
- LSTM traffic forecasting;
- LangGraph-based agent decisions;
- Docker/Kubernetes as a planned stage for actual resource scaling.

The review made an important distinction: the traffic pattern generator was synthetic, while application resource/performance metrics were measured from the running application.

## 2. Dataset and Notebook Status

At the time of the review:
- Traffic collection Part 1 contained **10,800 observations** in `metrics_20261027_1649.csv` and had been downloaded to the PC.
- Part 2 was still in progress; the latest recorded count was 152 of 9,360 observations, so the EC2 process needed to be checked.
- One real tick represented 5 seconds of wall-clock time and one simulated minute. The request metric was collected over the 5-second window, so time and rate units needed care when evaluating forecasts and scaling thresholds.
- The separate Azure Functions dataset contained 20,160 time steps and 318 applications. Six applications were used in the existing model comparisons.

Previously reported Azure results were mean WAPE of about 0.189 for LSTM and 0.191 for GBM. These were Azure-dataset results, **not results on the newly collected traffic-lab data**. Six `.pt` files represented application-specific LSTM checkpoints, not six different architectures. The notebook saved the selected model family but did not save the GBM models.

## 3. Review of the Main Project ZIP

The uploaded archive contained 67 files, including the notebook, dataset, six LSTM checkpoints, prediction utility, agent code, monitoring configuration and tests.

Checks reported in the conversation:
- ZIP integrity and Python syntax checks passed.
- The 24-cell notebook matched the separately uploaded notebook.
- All six LSTM checkpoints loaded through the existing prediction utility.
- The fake-LLM test passed.
- JSON and YAML configuration files parsed successfully.
- The existing prediction utility reproduced the documented mean Azure WAPE of approximately 0.189.

Per-application Azure WAPE values reported were:

| Application | WAPE |
|---|---:|
| `app_123` | 0.011 |
| `app_318` | 0.015 |
| `app_62` | 0.027 |
| `app_1` | 0.038 |
| `app_248` | 0.058 |
| `app_185` | 0.984 |

`app_185` was the major weak case.

Verification limits:
- The complete LangGraph run was not executed in the review environment because `langgraph` was unavailable there.
- Prometheus/Grafana could not be launched because Docker was unavailable.
- Real Gemini/Mistral calls and email delivery were not tested.
- `set_replicas()` was still a placeholder; calculated replica counts were recorded but not applied to Docker/Kubernetes resources.
- The separate `traffic_lab` application and its newly collected metrics CSVs were not inside the reviewed ZIP.

Therefore, the archive was considered intact and the forecast/model path was partly verified, but the complete system was **not** certified end to end.

## 4. Planned Notebook Extension

The user requested an extended notebook while keeping the original 24 cells unchanged. The resulting artifact was reported as:
- `lstm_model_extended.ipynb` — 43 cells total (24 original + 19 appended).
- `azure_lstm_checkpoints.zip` — separate bundle of the six existing Azure LSTM checkpoints and metadata.

The appended workflow was designed to:
1. Upload and validate the traffic CSV files, including Part 1 and Part 2.
2. Generate diagnostics and visualizations before additional training (traffic, CPU, memory, latency, failures, autocorrelation and capacity behaviour).
3. Evaluate all six Azure-trained LSTMs on the uploaded traffic as a cross-dataset/zero-shot comparison.
4. Create Azure GBM reference models for comparison, since the original notebook had not saved GBM checkpoints.
5. Train new GBM, GBM-q90, LSTM and LSTM-q90 models on the collected traffic.
6. Compare models on a shared chronological holdout using WAPE, MAE, RMSE and under/over-prediction measures.
7. Produce prediction plots, a replica-policy replay and downloadable metrics, figures, predictions and model artifacts.

## 5. Validation and Usage Status

The conversation reported that notebook structure was validated, the original 24 cells were unchanged, appended code compiled and the workflow was smoke-tested using synthetic data and supplied checkpoints.

The real traffic CSVs had not yet been uploaded into Colab during that conversation. Consequently, actual rankings, predictions and plots on the user's newly collected data were still pending. The replica-policy replay was a simulation, not actual Docker or Kubernetes scaling.

The suggested execution sequence was to open the extended notebook in Colab, manually run the appended bootstrap cell first, then run all cells and upload the traffic CSV(s) and checkpoint ZIP when prompted. Once Part 2 was complete, both CSV parts were to be uploaded together for the full experiment.

## 6. Main Conclusion

The project ZIP's Azure forecasting path and saved checkpoints were checked and appeared internally healthy, but the live traffic-lab integration, complete agent graph, monitoring deployment and real LLM/email paths still needed local verification. The extended notebook was prepared to make the new traffic comparison reproducible without altering the original notebook cells.
