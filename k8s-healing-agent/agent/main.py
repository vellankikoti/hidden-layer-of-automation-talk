"""
K8s Healing Agent — Main Entry Point

Provides a CLI interface for running individual healing scenarios or the
full agent loop on a live Kubernetes cluster.
"""

import argparse
import os
import sys
import time
from typing import Optional

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

# Ensure the package root is on sys.path when invoked directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.display import (
    print_error, print_info, print_success, print_waiting,
    print_scenario_header, print_section_header, print_scenario_complete,
    Color, _c
)
from agent.observer  import Observer
from agent.reasoner  import Reasoner
from agent.planner   import Planner
from agent.executor  import Executor
from agent.verifier  import Verifier
from agent.learner   import Learner


# ── Kubernetes client bootstrap ───────────────────────────────────────────────

def load_k8s_config() -> str:
    """
    Load Kubernetes configuration from in-cluster or kubeconfig.

    Returns a string indicating the source used.
    Raises RuntimeError if no cluster connection can be established.
    """
    try:
        config.load_incluster_config()
        return "in-cluster"
    except config.ConfigException:
        pass

    try:
        config.load_kube_config()
        return "kubeconfig"
    except config.ConfigException:
        raise RuntimeError(
            "Cannot connect to Kubernetes cluster. "
            "Ensure kubectl is configured and a cluster is accessible."
        )


# ── Scenario definitions ──────────────────────────────────────────────────────

SCENARIOS = {
    1: {
        "title":            "ImagePullBackOff",
        "deployment_name":  "web-frontend",
        "manifest":         "scenarios/01-imagepull-broken.yaml",
        "expected_reasons": ["ImagePullBackOff", "ErrImagePull"],
        "failure_type":     "imagepull",
        "story": (
            "A developer pushed a new deployment with a typo in the image tag. "
            "Kubernetes is trying to pull 'nginx:1.99.99-nonexistent' from Docker Hub "
            "and failing. PagerDuty just fired. The agent will fix it automatically."
        ),
    },
    2: {
        "title":            "CrashLoopBackOff",
        "deployment_name":  "api-server",
        "manifest":         "scenarios/02-crashloop-broken.yaml",
        "expected_reasons": ["CrashLoopBackOff"],
        "failure_type":     "crashloop",
        "story": (
            "A developer configured a liveness probe pointing to '/healthz' but nginx "
            "doesn't serve that path — it returns 404. Kubernetes keeps killing the "
            "container. The agent will diagnose the 404 and fix the probe path."
        ),
    },
    3: {
        "title":            "OOMKilled",
        "deployment_name":  "data-processor",
        "manifest":         "scenarios/03-oomkill-broken.yaml",
        "expected_reasons": ["CrashLoopBackOff", "OOMKilled"],
        "failure_type":     "oomkill",
        "story": (
            "The data-processor has a memory limit of 32Mi but allocates ~50MB at "
            "startup. The Linux OOM killer terminates it immediately. The agent will "
            "detect the OOMKill reason and increase the memory limit."
        ),
    },
    4: {
        "title":            "CreateContainerConfigError",
        "deployment_name":  "config-service",
        "manifest":         "scenarios/04-configerror-broken.yaml",
        "expected_reasons": ["CreateContainerConfigError", "CreateContainerError"],
        "failure_type":     "configerror",
        "story": (
            "The config-service references a ConfigMap named 'app-config' that doesn't "
            "exist. The pod is stuck in CreateContainerConfigError and can never start. "
            "The agent will detect the missing ConfigMap and create it."
        ),
    },
    5: {
        "title":            "Pending Pod",
        "deployment_name":  "ml-worker",
        "manifest":         "scenarios/05-pending-broken.yaml",
        "expected_reasons": ["Pending"],
        "failure_type":     "pending",
        "story": (
            "The ml-worker requests 100 CPU cores — more than any node in the cluster "
            "has. The pod is stuck in Pending state forever with no logs. The agent "
            "will read scheduling events and right-size the CPU request."
        ),
    },
}


# ── Core agent loop ────────────────────────────────────────────────────────────

def run_scenario(
    scenario_num: int,
    namespace: str,
    core_v1: client.CoreV1Api,
    apps_v1: client.AppsV1Api,
    learner: Learner,
    skip_deploy: bool = False,
) -> bool:
    """
    Execute the full Agent Loop for a single scenario.

    Parameters
    ----------
    scenario_num:
        Which scenario to run (1-5).
    namespace:
        Target Kubernetes namespace.
    core_v1, apps_v1:
        Kubernetes API clients.
    learner:
        Shared Learner instance for this session.
    skip_deploy:
        If True, skip applying the broken manifest (assume it's already deployed).

    Returns True if the scenario resolved successfully.
    """
    scenario = SCENARIOS[scenario_num]
    title    = scenario["title"]
    depl     = scenario["deployment_name"]

    print_scenario_header(scenario_num, title)
    print_info(scenario["story"])
    print()

    start_time = time.time()

    # ── Apply broken manifest ─────────────────────────────────────────────────
    if not skip_deploy:
        manifest_path = _resolve_manifest(scenario["manifest"])
        if not _apply_manifest(manifest_path, namespace):
            print_error(f"Failed to apply manifest: {manifest_path}")
            return False
        time.sleep(2)

    # ── Instantiate agent components ──────────────────────────────────────────
    observer = Observer(core_v1, namespace)
    reasoner = Reasoner(core_v1, apps_v1, namespace)
    planner  = Planner(core_v1, namespace)
    executor = Executor(core_v1, apps_v1, namespace)
    verifier = Verifier(core_v1, namespace)

    # ── OBSERVE: wait for failure ─────────────────────────────────────────────
    print_section_header("AGENT LOOP ACTIVATED")

    obs = None
    if scenario_num == 5:
        # Pending pod — wait for it to be stuck in Pending
        obs = observer.wait_for_pending(depl, min_seconds=10, timeout=120)
    else:
        # Use a longer timeout for OOMKill (scenario 3) because the python:3.12-slim
        # image may need to be pulled first, and OOMKill only happens after startup
        wait_timeout = 180 if scenario_num == 3 else 120
        obs = observer.wait_for_failure(depl, scenario["expected_reasons"], timeout=wait_timeout)

    if obs is None:
        print_error("Timed out waiting for failure state. Scenario aborted.")
        return False

    observer.print_observation(obs)
    time.sleep(1)

    # ── REASON ────────────────────────────────────────────────────────────────
    diag = reasoner.analyze(obs)
    if diag is None:
        print_error("Could not identify root cause — no runbook pattern matched.")
        return False

    time.sleep(1)

    # ── PLAN ──────────────────────────────────────────────────────────────────
    plan = planner.plan(diag)
    if plan is None:
        print_error("Could not generate an action plan.")
        return False

    time.sleep(1)

    # ── EXECUTE ───────────────────────────────────────────────────────────────
    exec_result = executor.execute(plan)

    time.sleep(1)

    # ── VERIFY ────────────────────────────────────────────────────────────────
    verify_result = verifier.verify(depl, exec_result, timeout=180)

    # ── LEARN ─────────────────────────────────────────────────────────────────
    record = learner.record(
        scenario_num    = scenario_num,
        scenario_title  = title,
        deployment_name = depl,
        namespace       = namespace,
        diag            = diag,
        exec_result     = exec_result,
        verify_result   = verify_result,
        start_time      = start_time,
    )

    elapsed = time.time() - start_time
    if verify_result.success:
        print_scenario_complete(scenario_num, title, elapsed)
    else:
        print_error(f"Scenario {scenario_num} did not resolve within the timeout period.")

    return verify_result.success


# ── Utilities ─────────────────────────────────────────────────────────────────

def _resolve_manifest(relative_path: str) -> str:
    """Resolve a manifest path relative to the project root."""
    # Try relative to the script, then CWD
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(base, relative_path)
    if os.path.exists(candidate):
        return candidate
    if os.path.exists(relative_path):
        return relative_path
    return candidate  # return anyway and let the caller fail with a clear message


def _apply_manifest(manifest_path: str, namespace: str) -> bool:
    """Apply a YAML manifest using kubectl (fallback for complex YAML)."""
    import subprocess
    try:
        result = subprocess.run(
            ["kubectl", "apply", "-f", manifest_path, "-n", namespace],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            print_success(f"Manifest applied: {os.path.basename(manifest_path)}")
            return True
        else:
            print_error(f"kubectl apply failed: {result.stderr.strip()}")
            return False
    except FileNotFoundError:
        print_error("kubectl not found in PATH")
        return False
    except subprocess.TimeoutExpired:
        print_error("kubectl apply timed out")
        return False


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="K8s Healing Agent — Autonomous Kubernetes remediation demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m agent.main --scenario 1
  python -m agent.main --scenario all
  python -m agent.main --scenario 3 --namespace demo
  python -m agent.main --preflight
        """,
    )
    parser.add_argument(
        "--scenario",
        choices=["1", "2", "3", "4", "5", "all"],
        default="all",
        help="Which scenario to run (default: all)",
    )
    parser.add_argument(
        "--namespace", "-n",
        default=os.environ.get("K8S_NAMESPACE", "default"),
        help="Kubernetes namespace (default: 'default')",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Run a pre-flight connectivity check only, then exit",
    )
    parser.add_argument(
        "--skip-deploy",
        action="store_true",
        help="Skip applying broken manifests (assume already deployed)",
    )
    return parser


def preflight_check(namespace: str, core_v1: client.CoreV1Api) -> bool:
    """Verify cluster connectivity and report basic info."""
    from agent.display import print_preflight_header
    print_preflight_header()

    try:
        nodes = core_v1.list_node()
        node_count = len(nodes.items)
        print_success(f"Kubernetes cluster connected")
        print_info(f"Nodes: {node_count}")
        for node in nodes.items:
            alloc = node.status.allocatable if node.status else {}
            cpu = alloc.get("cpu", "?")
            mem = alloc.get("memory", "?")
            print_info(f"  {node.metadata.name}  cpu={cpu}  memory={mem}")
        print_info(f"Namespace: {namespace}")
        return True
    except ApiException as exc:
        print_error(f"Cluster connection failed: {exc.reason}")
        return False


def main() -> int:
    """Entry point — returns 0 on success, 1 on failure."""
    parser = build_parser()
    args   = parser.parse_args()

    # ── Load Kubernetes config ─────────────────────────────────────────────────
    try:
        source = load_k8s_config()
        print_info(f"Kubernetes config loaded from: {source}")
    except RuntimeError as exc:
        print_error(str(exc))
        return 1

    core_v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()

    # ── Preflight ──────────────────────────────────────────────────────────────
    if args.preflight:
        ok = preflight_check(args.namespace, core_v1)
        return 0 if ok else 1

    # ── Select scenarios ───────────────────────────────────────────────────────
    if args.scenario == "all":
        selected = list(SCENARIOS.keys())
    else:
        selected = [int(args.scenario)]

    learner = Learner()
    all_ok  = True

    for num in selected:
        try:
            ok = run_scenario(
                scenario_num = num,
                namespace    = args.namespace,
                core_v1      = core_v1,
                apps_v1      = apps_v1,
                learner      = learner,
                skip_deploy  = args.skip_deploy,
            )
            if not ok:
                all_ok = False
        except KeyboardInterrupt:
            print()
            print_info("Interrupted by user.")
            break
        except Exception as exc:  # noqa: BLE001
            print_error(f"Scenario {num} failed unexpectedly: {exc}")
            all_ok = False

    learner.print_session_summary()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
