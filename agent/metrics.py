"""Prometheus metrics for the cloud allocator replay and the running Python agent.

Trace/allocator gauges describe the current historical replay minute and simulated replicas.
Process/host gauges are sampled live from the machine running the agent.
"""
from __future__ import annotations

import threading
import time

import psutil
from prometheus_client import Counter, Gauge, Histogram, start_http_server


class AllocatorMetrics:
    def __init__(self, app_name: str, provider: str = "unknown"):
        self.app_name = app_name
        self.provider = provider
        labels = ["app"]

        # Simulated allocator and dataset metrics. These are real observed values from
        # the replay, not measurements of a deployed Kubernetes/Docker workload.
        self.replicas = Gauge("cloud_allocator_replicas", "Current simulated replica count after the decision", labels)
        self.replicas_before = Gauge("cloud_allocator_replicas_before_decision", "Replicas at start of replay minute", labels)
        self.replicas_proposed = Gauge("cloud_allocator_replicas_proposed", "Replicas proposed before guardrails", labels)
        self.max_replicas = Gauge("cloud_allocator_max_replicas", "Maximum allowed simulated replica count", labels)
        self.traffic = Gauge("cloud_allocator_traffic_requests_per_minute", "Observed requests per minute from the selected dataset trace", labels)
        self.forecast = Gauge("cloud_allocator_forecast_requests_per_minute", "LSTM forecast requests per minute", labels)
        self.capacity_per_replica = Gauge("cloud_allocator_capacity_per_replica_requests_per_minute", "Configured capacity per simulated replica", labels)
        self.capacity_after = Gauge("cloud_allocator_total_capacity_requests_per_minute", "Simulated capacity after the decision", labels)
        self.utilization_after = Gauge("cloud_allocator_traffic_utilization_ratio", "Observed traffic divided by post-decision simulated capacity; 1.0 means 100 percent", labels)
        self.pre_scale_over_capacity = Gauge("cloud_allocator_pre_scale_over_capacity", "1 if current traffic exceeded capacity before this decision", labels)
        self.llm_error = Gauge("cloud_allocator_last_llm_error", "1 if the last decision reported an LLM error", labels)
        self.last_tick = Gauge("cloud_allocator_last_tick_timestamp_seconds", "Unix timestamp of last completed replay iteration", labels)
        self.last_alert = Gauge("cloud_allocator_last_alert_timestamp_seconds", "Unix timestamp of most recent agent alert", labels)

        # Live OS / process metrics. These are genuine measurements of the host and
        # the Python agent process, not the simulated application replicas.
        self.process_cpu = Gauge("cloud_allocator_agent_process_cpu_percent", "Live CPU percentage used by this Python agent process", labels)
        self.process_memory = Gauge("cloud_allocator_agent_process_memory_bytes", "Resident memory of this Python agent process in bytes", labels)
        self.process_threads = Gauge("cloud_allocator_agent_process_threads", "Number of OS threads in the Python agent process", labels)
        self.host_cpu = Gauge("cloud_allocator_host_cpu_percent", "Live total CPU utilization of the host running the agent", labels)
        self.host_mem_used = Gauge("cloud_allocator_host_memory_used_bytes", "Host memory in use in bytes", labels)
        self.host_mem_total = Gauge("cloud_allocator_host_memory_total_bytes", "Total host memory in bytes", labels)
        self.agent_uptime = Gauge("cloud_allocator_agent_uptime_seconds", "Seconds since this agent process started its metrics exporter", labels)

        # Counters for replay and agent behavior. Prometheus exposes these as *_total.
        self.minutes_processed = Counter("cloud_allocator_minutes_processed", "Replay minutes processed", labels)
        self.replica_minutes = Counter("cloud_allocator_replica_minutes", "Sum of replica count at the start of each replay minute", labels)
        self.minutes_over_capacity = Counter("cloud_allocator_minutes_over_capacity", "Replay minutes where pre-decision traffic exceeded current simulated capacity", labels)
        self.llm_calls = Counter("cloud_allocator_llm_calls", "Decision branch invocations; the provider label distinguishes fake from external LLMs", ["app", "mode", "provider"])
        self.llm_failures = Counter("cloud_allocator_llm_failures", "Decision calls that returned an error", labels)
        self.replica_changes = Counter("cloud_allocator_replica_changes", "Applied simulated replica-count changes", ["app", "direction"])
        self.decisions = Counter("cloud_allocator_decisions", "Applied decisions by mode and action", ["app", "mode", "action"])
        self.alerts = Counter("cloud_allocator_alerts", "Agent alerts generated", labels)
        self.email_attempts = Counter("cloud_allocator_email_attempts", "Alerts for which email delivery was enabled and attempted", labels)
        self.emails_sent = Counter("cloud_allocator_emails_sent", "Agent alert emails successfully sent via SMTP", labels)
        self.email_failures = Counter("cloud_allocator_email_failures", "Alert email delivery/configuration failures", labels)
        self.alerts_saved_only = Counter("cloud_allocator_alerts_saved_only", "Alerts saved to a file without sending email", labels)
        self.graph_duration = Histogram(
            "cloud_allocator_graph_invocation_duration_seconds",
            "Time spent invoking the full LangGraph workflow for one replay minute",
            labels,
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
        )

        self.server = None
        self.server_thread = None
        self._stop = threading.Event()
        self._started_monotonic = time.monotonic()
        self._process = psutil.Process()
        # Prime process CPU sampling so the first nonzero sample is meaningful.
        self._process.cpu_percent(interval=None)
        self._sample_thread = None

    def start(self, port: int = 8000) -> None:
        """Expose /metrics and continually sample live process/host resources."""
        self.server, self.server_thread = start_http_server(port, addr="0.0.0.0")
        self._sample_resources()
        self._sample_thread = threading.Thread(target=self._sample_loop, name="allocator-resource-metrics", daemon=True)
        self._sample_thread.start()

    def stop(self) -> None:
        """Stop the background resource sampler. The HTTP server is process-lifetime."""
        self._stop.set()

    def _sample_resources(self) -> None:
        label = self.app_name
        try:
            self.process_cpu.labels(label).set(self._process.cpu_percent(interval=None))
            self.process_memory.labels(label).set(self._process.memory_info().rss)
            self.process_threads.labels(label).set(self._process.num_threads())
            self.host_cpu.labels(label).set(psutil.cpu_percent(interval=None))
            vm = psutil.virtual_memory()
            self.host_mem_used.labels(label).set(vm.used)
            self.host_mem_total.labels(label).set(vm.total)
            self.agent_uptime.labels(label).set(time.monotonic() - self._started_monotonic)
        except (psutil.Error, OSError):
            # A transient OS metrics failure must never interrupt the allocator.
            pass

    def _sample_loop(self) -> None:
        while not self._stop.wait(1.0):
            self._sample_resources()

    def set_initial(self, state: dict) -> None:
        label = self.app_name
        self.replicas.labels(label).set(state["replicas"])
        self.replicas_before.labels(label).set(state["replicas"])
        self.replicas_proposed.labels(label).set(state["replicas"])
        self.max_replicas.labels(label).set(state["max_replicas"])
        self.capacity_per_replica.labels(label).set(state["capacity"])
        self.capacity_after.labels(label).set(state["replicas"] * state["capacity"])
        self.last_tick.labels(label).set(time.time())

    def record_tick(self, state: dict, before: int, duration_seconds: float, over_capacity_before: bool) -> None:
        label = self.app_name
        after = int(state.get("applied", state.get("replicas", before)))
        mode = str(state.get("mode", "unknown"))
        decision = state.get("decision") or {}
        proposed = int(decision.get("replicas", after))
        traffic = float(state.get("traffic_now", 0.0))
        forecast = float(state.get("forecast", 0.0))
        capacity = float(state.get("capacity", 0.0))
        decision_error = bool(decision.get("error"))
        alert_reason = str(state.get("alert_reason", "") or "")

        self.replicas.labels(label).set(after)
        self.replicas_before.labels(label).set(before)
        self.replicas_proposed.labels(label).set(proposed)
        self.max_replicas.labels(label).set(state.get("max_replicas", 0))
        self.traffic.labels(label).set(traffic)
        self.forecast.labels(label).set(forecast)
        self.capacity_per_replica.labels(label).set(capacity)
        self.capacity_after.labels(label).set(after * capacity)
        self.utilization_after.labels(label).set(traffic / (after * capacity) if after > 0 and capacity > 0 else 0.0)
        self.pre_scale_over_capacity.labels(label).set(1 if over_capacity_before else 0)
        self.llm_error.labels(label).set(1 if decision_error else 0)
        self.last_tick.labels(label).set(time.time())

        action = "scale_up" if after > before else "scale_down" if after < before else "hold"
        self.minutes_processed.labels(label).inc()
        self.replica_minutes.labels(label).inc(before)
        if over_capacity_before:
            self.minutes_over_capacity.labels(label).inc()
        if mode in ("unusual", "timer"):
            self.llm_calls.labels(label, mode, self.provider).inc()
        if decision_error:
            self.llm_failures.labels(label).inc()
        if action in ("scale_up", "scale_down"):
            self.replica_changes.labels(label, action).inc()
        self.decisions.labels(label, mode, action).inc()
        self.graph_duration.labels(label).observe(max(0.0, duration_seconds))

        if alert_reason:
            self.alerts.labels(label).inc()
            self.last_alert.labels(label).set(time.time())
            status = str(state.get("alert_status", "") or "").lower()
            if "email sending is off" in status:
                self.alerts_saved_only.labels(label).inc()
            else:
                self.email_attempts.labels(label).inc()
                if "sent to " in status:
                    self.emails_sent.labels(label).inc()
                else:
                    # Includes SMTP errors and missing email configuration.
                    self.email_failures.labels(label).inc()
