# Dataset Selection and Provenance

## 1. Initial Dataset: Azure Functions Trace 2019

The first candidate was the Azure Functions 2019 invocation trace. It contains 14 daily CSV files, one row per function and one column for each minute (1–1440), with identifiers such as `HashOwner`, `HashApp`, `HashFunction`, `Trigger`, and per-minute invocation counts.

To form an application-level series, function rows are grouped by `HashApp` and their minute counts summed. Concatenating 14 days gives 20,160 minutes. The conversation identified the trace as serverless invocation counts rather than container request/CPU measurements; therefore per-replica capacity would need a separate assumption. Many functions are low-traffic timer triggers, so busy and variable HTTP/queue applications should be selected.

The user initially found the many 0/1 values confusing. The explanation was that cells are invocation counts, not binary flags; quiet functions may have mostly zeroes and ones. Summing functions by app and inspecting totals/variation is needed before selecting useful series.

## 2. NASA Web Server Logs as an Easier Debug Trace

NASA Kennedy Space Center July 1995 access logs were proposed because they contain one line per HTTP request with timestamps, request path, status and bytes. Counting log lines per minute creates a straightforward request-rate series.

The July file was described as about 31 days (roughly 44,640 minutes). August was avoided because a hurricane caused a server outage in the trace. The discussion acknowledged that NASA is old and calm compared with modern traffic; its proposed role was an easy-to-understand debug trace, with injected spikes clearly labelled as synthetic. WorldCup98 was mentioned as a possible later, much larger trace but with a more difficult binary format.

## 3. Other Candidates Examined

**NAB realAWSCloudwatch:** includes real AWS CloudWatch metrics such as CPU, network and ELB request count. The ELB request-count file was considered relevant, but the files were described as short (roughly two weeks at five-minute intervals) and not yet inspected at that point. It was proposed as an extra trace, not the primary training source.

**Claimed AWS 2019 Kaggle dataset:** not identified or verified. The conversation asked for the exact link/name and warned that a Kaggle title alone does not establish provenance.

**Google ClusterData 2019 Kaggle sample:** identified as a third-party sample of real Google Borg data, not AWS. The sample had about 406,000 rows and appeared to contain randomly selected task/window records across clusters, rather than a continuous per-task series. It was considered a weak fit for request-level autoscaling without a defensible aggregation method and provenance for the sample.

Several Kaggle load-balancing/task-scheduling datasets were rejected as likely synthetic. The cited reasons included impossible negative resource values, uniform or bell-shaped generated distributions, highly regular timestamps, artificial outcome labels, unexplained derived scores and no source/paper. One 5,000-row task dataset had one task per minute, making its aggregate count effectively flat and unsuitable as a traffic-forecasting trace.

## 4. Stronger Modern Candidate: UFCG Private-Cloud Dataset

A paper/data record titled **“Dataset on resource allocation and usage for a private cloud”** was identified through Data in Brief and Mendeley Data.

The conversation reported:
- OpenStack private cloud at the Distributed Systems Laboratory, Federal University of Campina Grande, Brazil.
- Data spanning 23 May 2024 to 16 May 2025.
- Seven CSV tables and more than 64 million records.
- About 30 projects, 160 users and 1,193+ servers.
- Five-minute sampling and a reported 0.39% missing-data share.
- CC BY 4.0 license and DOI `10.17632/trvb5k4x5m.1`.

The central table was `servers_utilization`, with `timestamp`, `server_id`, `vcpu_utilization`, `ram_utilization` and `host_id`. The discussion noted that the irregular timestamps should be placed on a clean five-minute grid and that VM vCPU counts from the specifications/flavors tables are needed to derive CPU-core demand.

The authors' stated limitation was also highlighted: the trace represents long-running research workloads in a university lab, not web-scale SaaS, microservices, serverless or rapid-scaling workloads. Some servers created and deleted between samples are absent. It may therefore provide a slow/steady cloud-demand regime rather than a bursty web-traffic regime.

The proposed analysis used DuckDB to inspect the large `servers_utilization.csv` without loading the entire file into memory, aggregate fleet CPU by five-minute bucket, and plot average utilization and reporting-server counts.

## 5. Dataset Strategy Proposed

The discussion proposed using complementary traces rather than treating one dataset as representative of every workload:

| Trace | Proposed role |
|---|---|
| NASA July 1995 | Simple request-level debug/web-traffic trace |
| Azure Functions 2019 | Modern serverless invocation trace |
| UFCG private cloud 2024–2025 | Modern VM CPU/RAM utilization and slower cloud workload |
| NAB AWS CloudWatch | Optional short AWS-specific extra trace |

The later suggestion was to prioritize NASA plus UFCG and park Azure temporarily to reduce scope. However, the UFCG files and utilization plots had not yet been inspected in the conversation, so its suitability for the forecasting experiments remained pending.

## 6. Data-Quality Rule Established

The recurring selection rule was to require a named original source or paper, physically plausible metrics, ordered timestamps with a meaningful sampling interval, realistic non-uniform patterns, clear units and a license/provenance trail. The conversation repeatedly distinguished real traces from synthetic datasets and required synthetic burst injections to be labelled explicitly.
