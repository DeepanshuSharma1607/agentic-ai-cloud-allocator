"""get_backend(name) - imports only the backend that is asked for, so a missing docker / kubernetes package never breaks the others."""


def get_backend(name: str):
    name = (name or "docker").lower()
    if name == "process":
        from infra.backends.process_backend import ProcessBackend
        return ProcessBackend()
    if name == "docker":
        from infra.backends.docker_backend import DockerBackend
        return DockerBackend()
    if name in ("k8s", "kubernetes"):
        from infra.backends.k8s_backend import K8sBackend
        return K8sBackend()
    raise ValueError(f"unknown backend '{name}' (use docker, k8s or process)")
