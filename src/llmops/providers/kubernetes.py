"""Kubernetes provider: render and apply vLLM serving manifests.

Two surface areas:

- `K8sDeployment.render(...)` returns the manifest YAML as a string (no SDK
  required). Useful for `kubectl apply -f -` and for CI pipelines.
- `K8sDeployment.deploy(...)` actually applies the manifests via the
  kubernetes Python client. Requires the `k8s` extra.
"""
from __future__ import annotations

import os
import textwrap
from typing import Any

from llmops.common.errors import ProviderNotAvailableError
from llmops.common.logging import get_logger

log = get_logger(__name__)


def _import_k8s():
    try:
        from kubernetes import client, config  # type: ignore

        return client, config
    except ImportError as exc:  # pragma: no cover
        raise ProviderNotAvailableError(
            "kubernetes not installed. Install puffin-finetune-studio[k8s]."
        ) from exc


class K8sDeployment:
    name = "kubernetes"

    def __init__(
        self,
        namespace: str | None = None,
        context: str | None = None,
        serving_image: str | None = None,
    ) -> None:
        self.namespace = namespace or os.environ.get("PUFFIN_K8S_NAMESPACE", "puffin")
        self.context = context or os.environ.get("PUFFIN_K8S_CONTEXT")
        self.serving_image = serving_image or os.environ.get(
            "PUFFIN_K8S_SERVING_IMAGE", "puffin-serve:latest"
        )

    def render(
        self,
        *,
        model_ref: str,
        environment: str,
        traffic_pct: int = 100,
        replicas: int = 2,
        gpu: bool = False,
    ) -> str:
        """Return the YAML manifest (Deployment + Service + HPA) as a string."""
        app_name = f"puffin-{environment}"
        gpu_resource = "    nvidia.com/gpu: \"1\"\n" if gpu else ""
        node_selector = (
            "      nodeSelector:\n        cloud.google.com/gke-accelerator: nvidia-l4\n"
            if gpu
            else ""
        )
        return textwrap.dedent(
            f"""\
            ---
            apiVersion: apps/v1
            kind: Deployment
            metadata:
              name: {app_name}
              namespace: {self.namespace}
              labels:
                app: {app_name}
                puffin.env: {environment}
                puffin.model_ref: {model_ref.replace('/', '-')}
            spec:
              replicas: {replicas}
              selector:
                matchLabels:
                  app: {app_name}
              template:
                metadata:
                  labels:
                    app: {app_name}
                    puffin.env: {environment}
                spec:
            {node_selector}      containers:
                  - name: serve
                    image: {self.serving_image}
                    imagePullPolicy: IfNotPresent
                    args: ["python", "-m", "llmops.serving.app", "--config", "/app/configs/deploy.yaml"]
                    env:
                      - name: PUFFIN_SERVE_BACKEND
                        value: "vllm"
                      - name: PUFFIN_MODEL_REF
                        value: "{model_ref}"
                      - name: PUFFIN_ENV
                        value: "{environment}"
                    ports:
                      - containerPort: 8080
                        name: http
                    resources:
                      requests:
                        cpu: "1"
                        memory: 4Gi
                      limits:
                        cpu: "4"
                        memory: 16Gi
            {gpu_resource}        readinessProbe:
                      httpGet: {{ path: /ready, port: 8080 }}
                      initialDelaySeconds: 30
                      periodSeconds: 5
                    livenessProbe:
                      httpGet: {{ path: /health, port: 8080 }}
                      initialDelaySeconds: 60
                      periodSeconds: 10
            ---
            apiVersion: v1
            kind: Service
            metadata:
              name: {app_name}
              namespace: {self.namespace}
            spec:
              selector:
                app: {app_name}
              ports:
                - name: http
                  port: 80
                  targetPort: 8080
              type: ClusterIP
            ---
            apiVersion: autoscaling/v2
            kind: HorizontalPodAutoscaler
            metadata:
              name: {app_name}
              namespace: {self.namespace}
            spec:
              scaleTargetRef:
                apiVersion: apps/v1
                kind: Deployment
                name: {app_name}
              minReplicas: {max(1, replicas)}
              maxReplicas: {max(2, replicas * 5)}
              metrics:
                - type: Resource
                  resource:
                    name: cpu
                    target:
                      type: Utilization
                      averageUtilization: 70
            """
        )

    def deploy(self, model_ref: str, *, environment: str, traffic_pct: int = 100) -> str:
        client, config = _import_k8s()
        try:
            config.load_kube_config(context=self.context) if self.context else config.load_kube_config()
        except Exception:  # pragma: no cover
            config.load_incluster_config()

        manifest = self.render(model_ref=model_ref, environment=environment, traffic_pct=traffic_pct)
        # Apply via stream of YAML docs
        from kubernetes import utils  # type: ignore

        api_client = client.ApiClient()
        results = utils.create_from_yaml(api_client, yaml_objects=_load_yaml_docs(manifest), namespace=self.namespace)
        log.info("applied %d manifests to namespace %s", len(results), self.namespace)
        return f"k8s://{self.namespace}/puffin-{environment}"

    def rollback(self, environment: str) -> str:
        client, config = _import_k8s()
        config.load_kube_config(context=self.context) if self.context else config.load_kube_config()
        apps = client.AppsV1Api()
        body = {"spec": {"rollbackTo": {"revision": 0}}}
        apps.patch_namespaced_deployment(
            name=f"puffin-{environment}",
            namespace=self.namespace,
            body=body,
        )
        return f"rolled back k8s://{self.namespace}/puffin-{environment}"

    def get_endpoint_url(self, environment: str) -> str:
        return f"http://puffin-{environment}.{self.namespace}.svc.cluster.local"


def _load_yaml_docs(manifest: str) -> list[dict[str, Any]]:
    import yaml

    return [doc for doc in yaml.safe_load_all(manifest) if doc]
