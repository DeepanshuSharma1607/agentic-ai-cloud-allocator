"""
k8s_backend.py - replicas are Pods of one Deployment ("aegis-replica") in the namespace "aegis".

Works with k3d / k3s, Docker Desktop Kubernetes, minikube - anything `kubectl` can reach (kubeconfig is used).
  prepare   create namespace, ResourceQuota (the whole-namespace CPU / RAM cap), Deployment (0 replicas, requests = limits), NodePort Service
  scale_to  patch the Deployment's replica count (Kubernetes picks and starts / stops Pods)
  observe   Pod phase + Ready condition + creation time, so the real startup time is measured
  stats     Pod CPU / memory from metrics-server (k3s ships it). metrics-server refreshes about every 15-60 s, so these
            numbers are slower than the Docker backend's. The request latency / errors are measured by the gateway and are not affected.

The gateway sends requests to the Service (NodePort 30080 on localhost): kube-proxy balances over Ready Pods. For k3d create the cluster with
    k3d cluster create aegis -p "30080:30080@server:0"
and load the image with  k3d image import aegiscloud-replica:latest -c aegis
"""
from __future__ import annotations

import os
import time

from infra import config as C
from infra.backends.base import Backend, Pod, Stat
from infra.backends.process_backend import replica_env

NAMESPACE = "aegis"
DEPLOYMENT = "aegis-replica"
SERVICE = "aegis-replica"
NODE_PORT = 30080


def parse_cpu(text: str) -> float:
    """'123456n' / '250u' / '15m' / '1' -> cores."""
    text = str(text)
    for suffix, div in (("n", 1e9), ("u", 1e6), ("m", 1e3)):
        if text.endswith(suffix):
            return float(text[:-1]) / div
    return float(text)


def parse_mem_mb(text: str) -> float:
    """'104856Ki' / '128Mi' / '1Gi' / bytes -> MB."""
    text = str(text)
    units = {"Ki": 1024 / 1e6, "Mi": 1048576 / 1e6, "Gi": 1073741824 / 1e6, "K": 1e-3, "M": 1.0, "G": 1e3}
    for suffix, mult in units.items():
        if text.endswith(suffix):
            return float(text[:-len(suffix)]) * mult
    return float(text) / 1e6


class K8sBackend(Backend):
    name = "k8s"
    per_pod_routing = False
    isolated = True

    def __init__(self):
        try:
            from kubernetes import client, config
        except ImportError as e:
            raise RuntimeError("The 'kubernetes' Python package is missing: pip install kubernetes") from e
        try:
            config.load_kube_config()
        except Exception:
            try:
                config.load_incluster_config()
            except Exception as e:
                raise RuntimeError("No Kubernetes cluster found (kubeconfig missing). Start k3d / Docker Desktop Kubernetes first.") from e
        self.k = client
        self.core, self.apps, self.custom = client.CoreV1Api(), client.AppsV1Api(), client.CustomObjectsApi()
        self.service_url = os.getenv("AEGIS_K8S_SERVICE_URL", f"http://127.0.0.1:{NODE_PORT}")
        self._ready_seen: dict[str, float] = {}

    # ------------------------------------------------------------------ setup
    def _deployment(self, spec):
        k = self.k
        res = {"cpu": f"{int(spec['cpu_cores'] * 1000)}m", "memory": f"{int(spec['mem_mb'])}Mi"}
        env = [k.V1EnvVar(name=n, value=v) for n, v in replica_env(spec).items()]
        container = k.V1Container(
            name="app", image=C.IMAGE_NAME, image_pull_policy="IfNotPresent", env=env,
            ports=[k.V1ContainerPort(container_port=C.REPLICA_PORT)],
            resources=k.V1ResourceRequirements(requests=res, limits=res),
            readiness_probe=k.V1Probe(http_get=k.V1HTTPGetAction(path="/health", port=C.REPLICA_PORT), initial_delay_seconds=1, period_seconds=1))
        template = k.V1PodTemplateSpec(metadata=k.V1ObjectMeta(labels={"app": DEPLOYMENT, C.LABEL: "replica"}),
                                       spec=k.V1PodSpec(containers=[container], termination_grace_period_seconds=5))
        return k.V1Deployment(metadata=k.V1ObjectMeta(name=DEPLOYMENT, namespace=NAMESPACE),
                              spec=k.V1DeploymentSpec(replicas=0, selector=k.V1LabelSelector(match_labels={"app": DEPLOYMENT}), template=template))

    def _ensure(self, fn_create, fn_replace):
        try:
            fn_create()
        except self.k.ApiException as e:
            if e.status != 409:
                raise
            fn_replace()

    def prepare(self, spec, build=True):
        k = self.k
        try:
            self.core.list_namespace(limit=1)
        except Exception as e:
            raise RuntimeError(f"Kubernetes is not reachable: {e}") from e
        self._ensure(lambda: self.core.create_namespace(k.V1Namespace(metadata=k.V1ObjectMeta(name=NAMESPACE))), lambda: None)
        n = int(spec.get("max_replicas", 1))
        quota = {"requests.cpu": f"{int(n * spec['cpu_cores'] * 1000)}m", "limits.cpu": f"{int(n * spec['cpu_cores'] * 1000)}m",
                 "requests.memory": f"{n * int(spec['mem_mb'])}Mi", "limits.memory": f"{n * int(spec['mem_mb'])}Mi", "pods": str(n + 2)}
        rq = k.V1ResourceQuota(metadata=k.V1ObjectMeta(name="aegis-quota", namespace=NAMESPACE), spec=k.V1ResourceQuotaSpec(hard=quota))
        self._ensure(lambda: self.core.create_namespaced_resource_quota(NAMESPACE, rq),
                     lambda: self.core.replace_namespaced_resource_quota("aegis-quota", NAMESPACE, rq))
        dep = self._deployment(spec)
        self._ensure(lambda: self.apps.create_namespaced_deployment(NAMESPACE, dep),
                     lambda: self.apps.replace_namespaced_deployment(DEPLOYMENT, NAMESPACE, dep))
        svc = k.V1Service(metadata=k.V1ObjectMeta(name=SERVICE, namespace=NAMESPACE),
                          spec=k.V1ServiceSpec(type="NodePort", selector={"app": DEPLOYMENT},
                                               ports=[k.V1ServicePort(port=80, target_port=C.REPLICA_PORT, node_port=NODE_PORT)]))
        self._ensure(lambda: self.core.create_namespaced_service(NAMESPACE, svc),
                     lambda: self.core.patch_namespaced_service(SERVICE, NAMESPACE, svc))

    # ------------------------------------------------------------------ scaling and observing
    def scale_to(self, n, spec):
        self.apps.patch_namespaced_deployment_scale(DEPLOYMENT, NAMESPACE, {"spec": {"replicas": int(n)}})

    def create(self, count, spec):                 # not used: Kubernetes creates the Pods
        raise NotImplementedError

    def remove(self, name):                        # not used
        pass

    def observe(self):
        pods = []
        for p in self.core.list_namespaced_pod(NAMESPACE, label_selector=f"app={DEPLOYMENT}").items:
            name = p.metadata.name
            created = p.metadata.creation_timestamp.timestamp()
            ready = any(c.type == "Ready" and c.status == "True" for c in (p.status.conditions or []))
            if p.metadata.deletion_timestamp:
                state = "terminating"
            elif p.status.phase == "Failed":
                state = "failed"
            elif ready:
                state = "ready"
            else:
                state = "starting"
            pod = Pod(name=name, state=state, created_at=created)
            if ready:
                t = next((c.last_transition_time for c in p.status.conditions if c.type == "Ready"), None)
                pod.ready_at = t.timestamp() if t else self._ready_seen.setdefault(name, time.time())
            res = p.spec.containers[0].resources.limits or {}
            pod.cpu_limit_cores = parse_cpu(res["cpu"]) if "cpu" in res else None
            pod.mem_limit_mb = parse_mem_mb(res["memory"]) if "memory" in res else None
            pods.append(pod)
        return pods

    def stats(self):
        out = {}
        try:
            items = self.custom.list_namespaced_custom_object("metrics.k8s.io", "v1beta1", NAMESPACE, "pods").get("items", [])
        except Exception:
            return out                                  # metrics-server not ready: no data (never invented)
        for it in items:
            usage = (it.get("containers") or [{}])[0].get("usage", {})
            if "cpu" in usage and "memory" in usage:
                out[it["metadata"]["name"]] = Stat(cpu_pct=parse_cpu(usage["cpu"]) * 100.0, mem_mb=parse_mem_mb(usage["memory"]))
        return out

    def cleanup(self):
        try:
            self.scale_to(0, {})
        except Exception:
            pass
