#!/usr/bin/env python3
"""
K8s Healing Agent — Interactive Demo Runner

This is the MAIN file used during the live conference talk.
Run it with:  python3 demo.py

It provides an interactive menu to deploy broken scenarios and watch the
healing agent fix them in real time.
"""

import os
import subprocess
import sys
import time
from typing import Optional

# ── Python version check (before any other imports) ──────────────────────────
if sys.version_info < (3, 9):
    print("❌ Python 3.9 or later is required.")
    sys.exit(1)

# ── Verify kubernetes library ─────────────────────────────────────────────────
try:
    from kubernetes import client, config
    from kubernetes.client.exceptions import ApiException
except ImportError:
    print("❌ The 'kubernetes' Python library is not installed.")
    print("   Run:  pip install kubernetes")
    sys.exit(1)

# Add the project root to sys.path so 'agent' package is importable
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agent.display import (
    Color, _c, print_main_menu, print_scenario_header,
    print_preflight_header, print_info, print_success,
    print_error, print_waiting, print_section_header,
    print_broken, print_detect, spin_wait,
)
from agent.main import (
    load_k8s_config, run_scenario, SCENARIOS, preflight_check,
    _apply_manifest, _resolve_manifest,
)
from agent.learner import Learner


# ── Cluster info helpers ──────────────────────────────────────────────────────

def _detect_cluster_type(context_name: str) -> str:
    """Guess the cluster type from the current kubectl context name."""
    ctx = (context_name or "").lower()
    if "docker" in ctx or "docker-desktop" in ctx:
        return "Docker Desktop"
    if "minikube" in ctx:
        return "minikube"
    if "kind" in ctx:
        return "kind"
    if "eks" in ctx or "amazonaws" in ctx:
        return "AWS EKS"
    if "gke" in ctx:
        return "Google GKE"
    if "aks" in ctx or "azure" in ctx:
        return "Azure AKS"
    return "Kubernetes cluster"


def _get_kubectl_context() -> str:
    """Return the current kubectl context name, or empty string on failure."""
    try:
        result = subprocess.run(
            ["kubectl", "config", "current-context"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def _check_kubectl() -> bool:
    """Return True if kubectl is accessible and a cluster is reachable."""
    try:
        result = subprocess.run(
            ["kubectl", "cluster-info"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _cleanup_all(namespace: str) -> None:
    """Delete all demo deployments and ConfigMaps."""
    print_section_header("CLEANUP")
    deployments = [s["deployment_name"] for s in SCENARIOS.values()]
    for depl in deployments:
        _kubectl_delete("deployment", depl, namespace)
    _kubectl_delete("configmap", "app-config", namespace)
    # Belt-and-suspenders: delete by label
    _kubectl_delete_by_label("all", "demo=k8s-healing-agent", namespace)
    print_success("Cleanup complete — cluster is clean")


def _kubectl_delete(kind: str, name: str, namespace: str) -> None:
    """kubectl delete <kind> <name> --ignore-not-found."""
    try:
        subprocess.run(
            ["kubectl", "delete", kind, name,
             "-n", namespace, "--ignore-not-found",
             "--timeout=30s"],
            capture_output=True, text=True, timeout=40,
        )
    except Exception:  # noqa: BLE001
        pass


def _kubectl_delete_by_label(kind: str, label: str, namespace: str) -> None:
    """kubectl delete <kind> -l <label> --ignore-not-found."""
    try:
        subprocess.run(
            ["kubectl", "delete", kind,
             "-l", label, "-n", namespace,
             "--ignore-not-found", "--timeout=30s"],
            capture_output=True, text=True, timeout=40,
        )
    except Exception:  # noqa: BLE001
        pass


# ── Preflight banner ──────────────────────────────────────────────────────────

def run_preflight(namespace: str, core_v1: client.CoreV1Api) -> bool:
    """Run pre-flight checks and print a beautiful status summary."""
    print_preflight_header()

    # Python version
    pv = sys.version_info
    print_success(f"Python {pv.major}.{pv.minor}.{pv.micro}")

    # kubernetes library
    import kubernetes
    print_success(f"kubernetes library v{kubernetes.__version__}")

    # kubectl
    if _check_kubectl():
        ctx = _get_kubectl_context()
        cluster_type = _detect_cluster_type(ctx)
        print_success(f"kubectl connected  ({cluster_type}: {ctx})")
    else:
        print_error("kubectl not connected to any cluster")
        return False

    # Cluster info via Python client
    try:
        nodes = core_v1.list_node()
        count = len(nodes.items)
        print_success(f"Cluster nodes: {count}")
        for node in nodes.items:
            alloc = node.status.allocatable if node.status else {}
            cpu   = alloc.get("cpu", "?")
            mem   = alloc.get("memory", "?")
            print_info(f"  • {node.metadata.name}  cpu={cpu}  memory={mem}")
    except ApiException as exc:
        print_error(f"Cannot list nodes: {exc.reason}")
        return False

    print_info(f"  Namespace: {namespace}")
    print()
    return True


# ── Scenario flow (with storytelling) ────────────────────────────────────────

def _print_story(scenario_num: int) -> None:
    """Print the story/intro for a scenario before deploying the broken manifest."""
    s = SCENARIOS[scenario_num]
    print()
    print(_c(Color.CYAN, "  📖 SCENARIO STORY"))
    print(_c(Color.WHITE, f"  {s['story']}"))
    print()


def _wait_for_keypress(message: str = "Press Enter to return to the menu...") -> None:
    """Pause and wait for the speaker to press Enter."""
    try:
        input(f"\n  {_c(Color.YELLOW, message)}\n")
    except (EOFError, KeyboardInterrupt):
        pass


# ── Interactive demo loop ─────────────────────────────────────────────────────

def demo_loop(namespace: str, core_v1: client.CoreV1Api, apps_v1: client.AppsV1Api) -> None:
    """Run the interactive menu loop."""
    learner = Learner()

    while True:
        print_main_menu()
        try:
            choice = input("  Enter your choice: ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            choice = "Q"

        if choice == "Q":
            print()
            print_info("👋  Thanks for watching!  —  AI DevCon India 2026")
            print()
            break

        elif choice == "C":
            _cleanup_all(namespace)
            _wait_for_keypress()

        elif choice == "A":
            for num in range(1, 6):
                _print_story(num)
                try:
                    run_scenario(
                        scenario_num=num,
                        namespace=namespace,
                        core_v1=core_v1,
                        apps_v1=apps_v1,
                        learner=learner,
                    )
                except KeyboardInterrupt:
                    print_info("Skipping to next scenario...")
                    continue
                except Exception as exc:  # noqa: BLE001
                    print_error(f"Scenario {num} failed: {exc}")
            learner.print_session_summary()
            _wait_for_keypress()

        elif choice in ("1", "2", "3", "4", "5"):
            num = int(choice)
            _print_story(num)
            try:
                run_scenario(
                    scenario_num=num,
                    namespace=namespace,
                    core_v1=core_v1,
                    apps_v1=apps_v1,
                    learner=learner,
                )
            except KeyboardInterrupt:
                print_info("Scenario interrupted.")
            except Exception as exc:  # noqa: BLE001
                print_error(f"Scenario {num} failed: {exc}")
            _wait_for_keypress()

        else:
            print_error(f"Unknown choice: {choice!r}. Please enter 1-5, A, C, or Q.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="K8s Healing Agent — Interactive Demo Runner"
    )
    parser.add_argument(
        "--namespace", "-n",
        default=os.environ.get("K8S_NAMESPACE", "default"),
        help="Kubernetes namespace to use (default: 'default')",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Run pre-flight checks only, then exit",
    )
    args = parser.parse_args()

    # ── Load K8s config ────────────────────────────────────────────────────────
    try:
        load_k8s_config()
    except RuntimeError as exc:
        print_error(str(exc))
        sys.exit(1)

    core_v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()

    # ── Pre-flight ─────────────────────────────────────────────────────────────
    ok = run_preflight(args.namespace, core_v1)
    if not ok:
        print_error("Pre-flight checks failed. Fix the issues above and try again.")
        sys.exit(1)

    if args.preflight:
        print_success("Pre-flight checks passed!")
        sys.exit(0)

    # ── Interactive demo ───────────────────────────────────────────────────────
    demo_loop(args.namespace, core_v1, apps_v1)


if __name__ == "__main__":
    main()
