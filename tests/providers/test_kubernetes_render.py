from __future__ import annotations

import yaml

from llmops.providers.kubernetes import K8sDeployment


def test_render_yaml_documents():
    k = K8sDeployment(namespace="puffin-test", serving_image="puffin-serve:1.2.3")
    manifest = k.render(
        model_ref="my-model:v3",
        environment="staging",
        replicas=3,
    )
    docs = list(yaml.safe_load_all(manifest))
    docs = [d for d in docs if d]
    kinds = {d["kind"] for d in docs}
    assert kinds == {"Deployment", "Service", "HorizontalPodAutoscaler"}

    deployment = next(d for d in docs if d["kind"] == "Deployment")
    assert deployment["metadata"]["namespace"] == "puffin-test"
    assert deployment["spec"]["replicas"] == 3
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "puffin-serve:1.2.3"


def test_render_includes_gpu_when_requested():
    k = K8sDeployment()
    manifest = k.render(model_ref="m", environment="prod", gpu=True)
    assert "nvidia.com/gpu" in manifest


def test_render_no_gpu_by_default():
    k = K8sDeployment()
    manifest = k.render(model_ref="m", environment="prod")
    assert "nvidia.com/gpu" not in manifest


def test_endpoint_url_namespaced():
    k = K8sDeployment(namespace="my-ns")
    assert "my-ns.svc.cluster.local" in k.get_endpoint_url("prod")
