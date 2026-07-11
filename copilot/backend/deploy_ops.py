"""Execute a deployment target from the UI: render/setup, then run the deploy.

Each target is a short command sequence (e.g. build + run, or terraform init +
apply) spawned as one tracked subprocess with a live log, mirroring how
training/serving are managed. Inputs that land in a shell command are strictly
validated to prevent injection. Runs are dangerous-gated at the endpoint.

Targets that touch a cloud (terraform apply) provision real, billable
infrastructure -- the UI makes the user confirm before calling this.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SAFE = re.compile(r"^[A-Za-z0-9._:/-]+$")  # image ids, namespaces, tags


class DeployError(RuntimeError):
    """Bad deploy request; maps to HTTP 400."""


# target -> {cli, label, cloud, dir (cwd, optional), builder}
TARGETS: dict[str, dict[str, Any]] = {
    "kubernetes": {"cli": "kubectl", "label": "Kubernetes", "cloud": False},
    "docker": {"cli": "docker", "label": "Docker", "cloud": False},
    "aws": {"cli": "terraform", "label": "AWS", "cloud": True,
            "dir": "infra/terraform/aws"},
    "gcp": {"cli": "terraform", "label": "Google Cloud", "cloud": True,
            "dir": "infra/terraform/gcp"},
    "azure": {"cli": "terraform", "label": "Azure", "cloud": True,
              "dir": "infra/terraform/azure"},
}


def _which(cmd: str) -> str | None:
    import shutil
    return shutil.which(cmd)


def _state_path(repo_root: Path) -> Path:
    return Path(repo_root) / "artifacts" / "copilot" / "deploy.json"


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True


def preflight(repo_root: Path) -> dict[str, Any]:
    """Per-target readiness: is the CLI installed and the infra dir present."""
    out = []
    for tid, spec in TARGETS.items():
        cli = spec["cli"]
        d = spec.get("dir")
        dir_ok = True if not d else (Path(repo_root) / d).exists()
        out.append({
            "id": tid, "label": spec["label"], "cli": cli,
            "cli_installed": _which(cli) is not None,
            "cloud": spec["cloud"], "dir": d, "dir_exists": dir_ok,
        })
    return {"kind": "deploy_targets", "targets": out}


def _validate(value: str, field: str) -> str:
    if not value or not _SAFE.match(value):
        raise DeployError(f"invalid {field}: {value!r}")
    return value


def _build_plan(
    repo_root: Path, target: str, settings: dict[str, Any],
) -> tuple[list[str], Path]:
    """Return (command sequence, cwd) for a target, with settings validated."""
    spec = TARGETS[target]
    repo = Path(repo_root)
    if target == "kubernetes":
        from llmops.providers.kubernetes import K8sDeployment
        ns = _validate(str(settings.get("namespace") or "puffin"), "namespace")
        image = _validate(str(settings.get("serving_image") or "puffin-serve:latest"),
                          "serving_image")
        env = _validate(str(settings.get("environment") or "staging"), "environment")
        replicas = int(settings.get("replicas") or 2)
        if not 1 <= replicas <= 100:
            raise DeployError("replicas must be 1-100")
        gpu = bool(settings.get("gpu"))
        yaml_text = K8sDeployment(namespace=ns, serving_image=image).render(
            model_ref=str(settings.get("model_ref") or "puffin:latest"),
            environment=env, replicas=replicas, gpu=gpu)
        out = repo / "artifacts" / "copilot" / "deploy-manifest.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml_text, encoding="utf-8")
        rel = out.relative_to(repo).as_posix()
        return [f"kubectl apply -f {rel}"], repo
    if target == "docker":
        image = _validate(str(settings.get("serving_image") or "puffin-serve:latest"),
                          "serving_image")
        port = int(settings.get("port") or 8089)
        if not 1 <= port <= 65535:
            raise DeployError("port must be 1-65535")
        backend = str(settings.get("backend") or "transformers")
        if backend not in {"transformers", "vllm"}:
            raise DeployError(f"bad backend: {backend}")
        dockerfile = ("infra/docker/Dockerfile.serve.vllm" if backend == "vllm"
                      else "infra/docker/Dockerfile.serve")
        return [
            f"docker build -f {dockerfile} -t {image} .",
            f"docker rm -f puffin-serve",
            f"docker run -d --name puffin-serve -p {port}:8089 "
            f"-e PUFFIN_SERVE_BACKEND={backend} {image}",
        ], repo
    if spec.get("cloud"):
        d = repo / spec["dir"]
        if not d.exists():
            raise DeployError(f"{spec['dir']} not found")
        return ["terraform init -input=false",
                "terraform apply -auto-approve -input=false"], d
    raise DeployError(f"unknown target: {target}")


def read_state(repo_root: Path) -> dict[str, Any]:
    p = _state_path(repo_root)
    if not p.exists():
        return {"kind": "deploy_status", "running": False}
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"kind": "deploy_status", "running": False}
    st["kind"] = "deploy_status"
    st["running"] = _pid_alive(st.get("pid"))
    return st


async def run(repo_root: Path, *, target: str, settings: dict[str, Any]) -> dict[str, Any]:
    if target not in TARGETS:
        raise DeployError(f"unknown target: {target!r}")
    if _which(TARGETS[target]["cli"]) is None:
        raise DeployError(
            f"{TARGETS[target]['cli']} is not installed or not on PATH.")
    cur = read_state(repo_root)
    if cur.get("running"):
        raise DeployError("a deploy is already running; wait or cancel it first.")

    cmds, cwd = _build_plan(repo_root, target, settings)
    joined = " && ".join(cmds)
    if os.name == "nt":
        argv = ["cmd", "/d", "/c", joined]
    else:
        argv = ["bash", "-lc", joined]

    logs = Path(repo_root) / "artifacts" / "copilot" / "deploy-logs"
    logs.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    log_path = logs / f"deploy_{target}_{ts}.log"
    fh = log_path.open("wb")
    fh.write(f"$ {joined}\n\n".encode())
    fh.flush()

    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=str(cwd), env=os.environ.copy(),
        stdout=fh, stderr=asyncio.subprocess.STDOUT,
        start_new_session=os.name != "nt")
    proc._puffin_log_fh = fh  # type: ignore[attr-defined]

    rel = log_path.relative_to(repo_root).as_posix()
    state = {
        "kind": "deploy_status", "running": True, "pid": proc.pid,
        "target": target, "label": TARGETS[target]["label"],
        "cloud": TARGETS[target]["cloud"], "command": joined,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "log_path": rel,
    }
    sp = _state_path(repo_root)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return {**state, "message": f"Deploying to {TARGETS[target]['label']} (PID {proc.pid})."}


def cancel(repo_root: Path) -> dict[str, Any]:
    st = read_state(repo_root)
    pid = st.get("pid")
    if not st.get("running") or not isinstance(pid, int):
        return {"kind": "deploy_cancel", "cancelled": False, "message": "No deploy running."}
    try:
        if os.name == "nt":
            os.kill(pid, signal.SIGTERM)
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except ProcessLookupError:
                os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError) as exc:
        return {"kind": "deploy_cancel", "cancelled": False,
                "message": f"Couldn't cancel PID {pid}: {exc}"}
    return {"kind": "deploy_cancel", "cancelled": True, "message": f"Cancelled deploy (PID {pid})."}


def read_log(repo_root: Path, *, tail: int = 400) -> dict[str, Any]:
    rel = read_state(repo_root).get("log_path")
    repo = Path(repo_root)
    log: Path | None = None
    if rel and (repo / rel).exists():
        log = repo / rel
    else:
        logs = repo / "artifacts" / "copilot" / "deploy-logs"
        found = sorted(logs.glob("deploy_*.log")) if logs.exists() else []
        if found:
            log = found[-1]
    if log is None:
        return {"kind": "deploy_log", "present": False, "lines": [],
                "message": "No deploy log yet."}
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"kind": "deploy_log", "present": False, "lines": [],
                "message": f"Couldn't read log: {exc}"}
    lines = text.splitlines()
    tail = max(1, min(2000, tail))
    return {"kind": "deploy_log", "present": True,
            "log_path": log.relative_to(repo).as_posix(),
            "total_lines": len(lines), "lines": lines[-tail:]}
