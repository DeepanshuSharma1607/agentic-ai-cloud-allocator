# Project File Learning Order and Traffic Collection

## 1. Objective

The objective was to understand the complete AegisCloud project file by file, test every component independently and verify how data travels through the system.

The project was studied from the data layer upwards.

## 2. Recommended Learning Order

| Stage | Components | Purpose |
|---|---|---|
| 0 | README, settings.py, requirements.txt | Project setup and configuration |
| 1 | seed.py | Load historical traffic and initialize history |
| 2 | lstm_model.py, predictor.py, train_horizon.py | Understand and test the forecasting model |
| 3 | synthetic.py, training tools | Training and baseline comparison |
| 4 | target_app, loadgen, collector | Generate traffic and collect metrics |
| 5 | prediction/engine.py, server.py | Produce live forecasts |
| 6 | agent/state.py, nodes.py, llm.py, graph.py, run.py | Understand agent decisions and safety logic |
| 7 | frontend files | Understand dashboard and controls |
| 8 | run_all.py | Test the complete integrated system |

The recommended study method is to record three things for every file: input, output and one possible failure case.

## 3. System Architecture Verification

The ZIP project was compared against the proposed architecture.

The main flow is:

Traffic Generator → Target Application → Collector → LSTM Prediction Service → Prediction CSV → LangGraph Agent → Scaling Decision → Action Logs and Alerts.

The frontend controls the traffic generator and displays system information.

Important observations:
- The collector polls the target application every five seconds.
- Historical and live traffic are stored in CSV files.
- The prediction service generates +10-minute and +20-minute forecasts.
- The agent handles unusual events, timer-based decisions and automatic scaling.
- Email alerts are handled separately from ordinary scaling decisions.

Two major differences from the proposed architecture were identified:

1. `set_replicas()` was only a placeholder. Scaling decisions were logged but did not actually change application capacity.
2. The different CSV data stores were not merged into one final database.

## 4. Historical Traffic Collection

The existing EC2 collection consisted of:

| Part | Rows |
|---|---:|
| Part 1 | 10,800 |
| Part 2 | 9,360 |
| Total | 20,160 |

Part 3 was planned to continue from minute 20160.

The load generator supported continuation through `--start-tick`.

The approved configuration was:
- Starting minute: 20160.
- Duration: 28 hours.
- New random seed: 2027.
- Base traffic: 50.
- Output: `metrics_part_3.csv`.

The application process and its configuration were kept unchanged to maintain experimental consistency.

## 5. Part 3 Execution

The nohup/setsid command was successfully started on EC2.

Initial verification confirmed:
- Correct starting minute.
- Correct 14-day simulated position.
- One active load generator.
- Expected weekend-to-weekday traffic increase.
- Initially zero timeouts and stable memory usage.

The collection was expected to produce 20,160 additional rows, ending at minute 40319.

## 6. Final Dataset Plan

A `merge_final.py` script was prepared conceptually and tested using synthetic data.

Its intended responsibilities:
- Prevent merging while collection is active.
- Validate file headers and row counts.
- Detect missing or duplicate minutes.
- Check `tick == minute`.
- Detect missing numeric values.
- Merge all three collection parts.

Expected output:

- `final/metrics_combined_final.csv`
- `final/final_data.zip`
- A merge report and supporting collection files.

Expected final dataset size: 40,320 rows.

The last seven days, minutes 30240–40319, were designated as the held-out test set.

**Status at the end of the conversation:** Part 3 was running successfully. Final collection completion and real-data merging still required verification.
