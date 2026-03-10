#!/usr/bin/env python3
"""
K8s Healing Agent — Interactive Demo Runner (Speaker-Controlled)

==============================================================================
  PURPOSE:
    This script is designed for LIVE CONFERENCE TALKS where the speaker wants
    the audience to SEE the problem BEFORE the agent fixes it.

  HOW IT WORKS:
    1. Speaker picks a scenario (or runs all 5 sequentially)
    2. The broken manifest is deployed to the cluster
    3. The agent DETECTS and DIAGNOSES the issue — audience sees the failure
    4. *** PAUSE *** — The speaker is asked: "Apply fix? (yes/no)"
    5. Only after the speaker says YES, the agent applies the fix
    6. The agent verifies the pod is healthy and records the outcome

  VS demo.py:
    demo.py runs the full agent loop WITHOUT any human intervention — it is
    the "fully autonomous" version shown AFTER this interactive walkthrough.

  USAGE:
    python3 interactive-demo.py                    # interactive menu
    python3 interactive-demo.py --preflight        # check cluster connectivity
    python3 interactive-demo.py --namespace dev    # use a specific namespace
==============================================================================
"""

import os
import subprocess
import sys
import time
from typing import Optional

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║  STEP 0: Environment & Dependency Checks                                ║
# ║  Before we do anything, make sure Python >= 3.9 and kubernetes library   ║
# ║  are available. Fail fast with clear error messages.                     ║
# ╚════════════════════════════════════════════════════════════════════════════╝

if sys.version_info < (3, 9):
    print("Python 3.9 or later is required.")
    sys.exit(1)

try:
    from kubernetes import client, config
    from kubernetes.client.exceptions import ApiException
except ImportError:
    print("The 'kubernetes' Python library is not installed.")
    print("   Run:  pip install kubernetes")
    sys.exit(1)

# ── Ensure the 'agent' package is importable from this directory ─────────────
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agent.display import (
    Color, _c, _ts, _supports_color,
    print_main_menu, print_scenario_header,
    print_preflight_header, print_info, print_success,
    print_error, print_waiting, print_section_header,
    print_broken, print_detect, print_phase, spin_wait,
    print_scenario_complete,
)
from agent.main import (
    load_k8s_config, SCENARIOS, preflight_check,
    _apply_manifest, _resolve_manifest,
)
from agent.observer  import Observer
from agent.reasoner  import Reasoner
from agent.planner   import Planner
from agent.executor  import Executor
from agent.verifier  import Verifier
from agent.learner   import Learner


# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                                                                          ║
# ║                    VISUAL HELPERS & TERMINAL ART                         ║
# ║                                                                          ║
# ║  All the functions here produce rich, color-coded terminal output to     ║
# ║  make the live demo visually stunning for a conference audience.         ║
# ║                                                                          ║
# ╚════════════════════════════════════════════════════════════════════════════╝

def _print_banner() -> None:
    """
    Print the grand opening banner for the interactive demo.
    This is the FIRST thing the audience sees when the script starts.
    """
    banner = r"""
 ╔═══════════════════════════════════════════════════════════════════════════╗
 ║                                                                         ║
 ║     ██╗  ██╗ █████╗ ███████╗    ██╗  ██╗███████╗ █████╗ ██╗     ██╗    ║
 ║     ██║ ██╔╝██╔══██╗██╔════╝    ██║  ██║██╔════╝██╔══██╗██║     ██║    ║
 ║     █████╔╝ ╚█████╔╝███████╗    ███████║█████╗  ███████║██║     ██║    ║
 ║     ██╔═██╗ ██╔══██╗╚════██║    ██╔══██║██╔══╝  ██╔══██║██║     ██║    ║
 ║     ██║  ██╗╚█████╔╝███████║    ██║  ██║███████╗██║  ██║███████╗██║    ║
 ║     ╚═╝  ╚═╝ ╚════╝ ╚══════╝    ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝╚═╝    ║
 ║                                                                         ║
 ║          🤖  I N T E R A C T I V E   D E M O   M O D E  🤖             ║
 ║                  "The Hidden Layer of Automation"                        ║
 ║                     AI DevCon India 2026                                 ║
 ║                                                                         ║
 ║   In this mode, the agent will DETECT and DIAGNOSE issues, then WAIT    ║
 ║   for YOUR command before applying any fix. The audience sees the       ║
 ║   problem first, then watches the agent heal it on your signal.         ║
 ║                                                                         ║
 ╚═══════════════════════════════════════════════════════════════════════════╝
"""
    print(_c(Color.CYAN, banner))


def _print_interactive_menu() -> None:
    """
    Print the interactive demo menu.
    Each option is clearly labeled so the speaker can navigate quickly.
    """
    lines = [
        ("", ""),
        ("╔══════════════════════════════════════════════════════════════════╗", Color.CYAN),
        ("║     🤖 K8s Healing Agent — INTERACTIVE Demo (Speaker Mode)     ║", Color.CYAN),
        ("║     Agent detects & diagnoses, then YOU decide when to fix.     ║", Color.CYAN),
        ("╠══════════════════════════════════════════════════════════════════╣", Color.CYAN),
        ("║                                                                ║", Color.CYAN),
        ("║  [1] 🖼️  Scenario 1: ImagePullBackOff  (Wrong Image Tag)      ║", Color.WHITE),
        ("║  [2] 🔄 Scenario 2: CrashLoopBackOff  (Bad Health Check)      ║", Color.WHITE),
        ("║  [3] 💾 Scenario 3: OOMKilled          (Memory Limit Too Low) ║", Color.WHITE),
        ("║  [4] 📄 Scenario 4: ConfigMap Missing  (Env Config Drift)     ║", Color.WHITE),
        ("║  [5] ⏳ Scenario 5: Pending Pod        (Impossible CPU Req)   ║", Color.WHITE),
        ("║                                                                ║", Color.CYAN),
        ("║  [A] 🚀 Run ALL scenarios sequentially                        ║", Color.YELLOW),
        ("║  [C] 🧹 Cleanup all demo resources                            ║", Color.YELLOW),
        ("║  [Q] 👋 Quit                                                  ║", Color.YELLOW),
        ("║                                                                ║", Color.CYAN),
        ("╚══════════════════════════════════════════════════════════════════╝", Color.CYAN),
        ("", ""),
    ]
    for text, color in lines:
        if not text:
            print()
        else:
            print(_c(color, text))


def _print_story(scenario_num: int) -> None:
    """
    Print the narrative intro for a scenario.
    This sets the stage for the audience — what went wrong and why.
    """
    s = SCENARIOS[scenario_num]
    print()
    print(_c(Color.CYAN, "  ╭────────────────────────────────────────────────────────────╮"))
    print(_c(Color.CYAN, "  │  📖 SCENARIO STORY                                        │"))
    print(_c(Color.CYAN, "  ╰────────────────────────────────────────────────────────────╯"))

    # Word-wrap the story to ~60 chars for clean display
    story = s["story"]
    words = story.split()
    line = "  "
    for word in words:
        if len(line) + len(word) + 1 > 68:
            print(_c(Color.WHITE, line))
            line = "  " + word
        else:
            line += " " + word if line.strip() else "  " + word
    if line.strip():
        print(_c(Color.WHITE, line))
    print()


def _print_issue_dashboard(scenario_num: int, obs, diag, plan) -> None:
    """
    Print a comprehensive ISSUE DASHBOARD that visually summarizes everything
    the agent found. This is the "pause point" — the audience sees this before
    the speaker decides to fix.

    The dashboard shows:
      - What pod is broken and how
      - The root cause the agent identified
      - The proposed fix and its risk level
      - A clear visual separator before the fix prompt
    """
    s = SCENARIOS[scenario_num]

    print()
    print(_c(Color.RED,     "  ╔════════════════════════════════════════════════════════════════╗"))
    print(_c(Color.RED,     "  ║           🚨  ISSUE DETECTED — AWAITING APPROVAL  🚨          ║"))
    print(_c(Color.RED,     "  ╠════════════════════════════════════════════════════════════════╣"))

    # ── What's broken ────────────────────────────────────────────────────────
    print(_c(Color.RED,     "  ║                                                              ║"))
    print(_c(Color.YELLOW,  f"  ║  📛 Deployment:  {s['deployment_name']:<43}║"))
    print(_c(Color.YELLOW,  f"  ║  🔴 Status:      {obs.status_reason:<43}║"))
    print(_c(Color.YELLOW,  f"  ║  📦 Container:   {obs.container_name:<43}║"))
    print(_c(Color.YELLOW,  f"  ║  🐳 Image:       {obs.image:<43}║"))
    print(_c(Color.YELLOW,  f"  ║  🔁 Restarts:    {str(obs.restart_count):<43}║"))

    # ── Root cause ───────────────────────────────────────────────────────────
    print(_c(Color.RED,     "  ║                                                              ║"))
    print(_c(Color.RED,     "  ╠──────────────── ROOT CAUSE ANALYSIS ─────────────────────────╣"))
    print(_c(Color.RED,     "  ║                                                              ║"))
    print(_c(Color.WHITE,   f"  ║  🧠 Diagnosis:   {diag.summary[:43]:<43}║"))
    print(_c(Color.WHITE,   f"  ║  📁 Category:    {diag.category:<43}║"))
    print(_c(Color.WHITE,   f"  ║  📊 Confidence:  {diag.confidence:<43}║"))

    # ── Proposed fix ─────────────────────────────────────────────────────────
    print(_c(Color.RED,     "  ║                                                              ║"))
    print(_c(Color.RED,     "  ╠──────────────── PROPOSED REMEDIATION ────────────────────────╣"))
    print(_c(Color.RED,     "  ║                                                              ║"))
    print(_c(Color.GREEN,   f"  ║  🔧 Action:      {plan.description[:43]:<43}║"))
    print(_c(Color.GREEN,   f"  ║  ⚠️  Risk Level:  {plan.risk:<43}║"))

    # ── Show what will change (scenario-specific details) ────────────────────
    if plan.action_type == "PATCH_DEPLOYMENT_IMAGE":
        old = obs.image
        new = plan.params.get("new_image", "?")
        change = f"{old} → {new}"
        print(_c(Color.GREEN,   f"  ║  📌 From:        {old:<43}║"))
        print(_c(Color.GREEN,   f"  ║     To:          {new:<43}║"))
    elif plan.action_type == "PATCH_DEPLOYMENT_LIVENESS_PROBE":
        old = plan.context.get("probe_path", "?")
        new = plan.params.get("new_probe_path", "?")
        change = f"{old} → {new}"
        print(_c(Color.GREEN,   f"  ║  📌 Probe path:  {change:<43}║"))
    elif plan.action_type == "PATCH_DEPLOYMENT_MEMORY":
        old = plan.context.get("memory_limit", "?")
        new = plan.params.get("new_memory_limit", "?")
        change = f"{old} → {new}"
        print(_c(Color.GREEN,   f"  ║  📌 Memory:      {change:<43}║"))
    elif plan.action_type == "CREATE_CONFIGMAP":
        cm = plan.params.get("configmap_name", "?")
        cm_str = f"ConfigMap/{cm}"
        print(_c(Color.GREEN,   f"  ║  📌 Create:      {cm_str:<43}║"))
    elif plan.action_type == "PATCH_DEPLOYMENT_CPU":
        old = plan.context.get("cpu_request", "?")
        new = plan.params.get("new_cpu_request", "?")
        change = f"{old} → {new}"
        print(_c(Color.GREEN,   f"  ║  📌 CPU:         {change:<43}║"))

    print(_c(Color.RED,     "  ║                                                              ║"))
    print(_c(Color.RED,     "  ╚════════════════════════════════════════════════════════════════╝"))
    print()


def _prompt_fix() -> bool:
    """
    Ask the speaker whether to proceed with the fix.

    Returns True if the speaker says yes, False otherwise.
    This is the KEY DIFFERENTIATOR from demo.py — it gives the speaker
    full control over when the fix is applied, so the audience can
    absorb the problem before seeing the solution.
    """
    print(_c(Color.YELLOW,
        "  ┌──────────────────────────────────────────────────────────────┐"))
    print(_c(Color.YELLOW,
        "  │  🤖 Agent is ready to apply the fix.                       │"))
    print(_c(Color.YELLOW,
        "  │                                                            │"))
    print(_c(Color.YELLOW,
        "  │  Type 'yes' or 'fix' to proceed, anything else to skip.   │"))
    print(_c(Color.YELLOW,
        "  └──────────────────────────────────────────────────────────────┘"))
    print()

    try:
        answer = input(f"  {_c(Color.BOLD, 'Apply fix? [yes/no]: ')}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    return answer in ("yes", "y", "fix", "proceed", "do it", "go")


def _print_fix_skipped() -> None:
    """
    Print a clear message when the speaker chooses NOT to apply the fix.
    """
    print()
    print(_c(Color.YELLOW, "  ╭────────────────────────────────────────────────────────────╮"))
    print(_c(Color.YELLOW, "  │  ⏭️  Fix SKIPPED — issue remains in the cluster.           │"))
    print(_c(Color.YELLOW, "  │  The deployment is still broken. You can fix it later     │"))
    print(_c(Color.YELLOW, "  │  or clean up with option [C] from the menu.               │"))
    print(_c(Color.YELLOW, "  ╰────────────────────────────────────────────────────────────╯"))
    print()


def _print_fix_approved() -> None:
    """
    Print a visual confirmation that the fix is being applied.
    Adds dramatic flair for the audience.
    """
    print()
    print(_c(Color.GREEN, "  ╭────────────────────────────────────────────────────────────╮"))
    print(_c(Color.GREEN, "  │  ✅  FIX APPROVED — Agent is applying the remediation...  │"))
    print(_c(Color.GREEN, "  ╰────────────────────────────────────────────────────────────╯"))
    print()


def _print_healing_complete_celebration(scenario_num: int, title: str, elapsed: float) -> None:
    """
    Print an enhanced celebration banner when a scenario is healed.
    Bigger and more visual than the standard print_scenario_complete.
    """
    elapsed_str = f"{elapsed:.0f} seconds"
    print()
    print(_c(Color.GREEN, "  ╔════════════════════════════════════════════════════════════════╗"))
    print(_c(Color.GREEN, "  ║                                                              ║"))
    print(_c(Color.GREEN, f"  ║   🎉 SCENARIO {scenario_num} HEALED SUCCESSFULLY!                        ║"))
    print(_c(Color.GREEN, f"  ║   {title:<60}║"))
    print(_c(Color.GREEN, f"  ║   Resolved in {elapsed_str:<48}║"))
    print(_c(Color.GREEN, "  ║                                                              ║"))
    print(_c(Color.GREEN, "  ║   The agent detected the issue, diagnosed the root cause,    ║"))
    print(_c(Color.GREEN, "  ║   proposed a fix, applied it, and verified the pod is        ║"))
    print(_c(Color.GREEN, "  ║   healthy — all without any manual kubectl commands.         ║"))
    print(_c(Color.GREEN, "  ║                                                              ║"))
    print(_c(Color.GREEN, "  ╚════════════════════════════════════════════════════════════════╝"))
    print()


def _wait_for_keypress(message: str = "Press Enter to return to the menu...") -> None:
    """Pause and wait for the speaker to press Enter."""
    try:
        input(f"\n  {_c(Color.DIM, message)}\n")
    except (EOFError, KeyboardInterrupt):
        pass


# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                                                                          ║
# ║               CLUSTER HELPERS & PREFLIGHT CHECKS                         ║
# ║                                                                          ║
# ║  These functions verify cluster connectivity, detect the cluster type,   ║
# ║  and handle cleanup of demo resources.                                   ║
# ║                                                                          ║
# ╚════════════════════════════════════════════════════════════════════════════╝

def _detect_cluster_type(context_name: str) -> str:
    """
    Guess the cluster type from the current kubectl context name.
    Used in the preflight banner to show the audience what cluster we're on.
    """
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
    except Exception:
        return ""


def _check_kubectl() -> bool:
    """Return True if kubectl is accessible and a cluster is reachable."""
    try:
        result = subprocess.run(
            ["kubectl", "cluster-info"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


def _cleanup_all(namespace: str) -> None:
    """
    Delete all demo deployments and ConfigMaps.
    Ensures a clean slate before/after running scenarios.
    """
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
    except Exception:
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
    except Exception:
        pass


# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                                                                          ║
# ║               PREFLIGHT CHECK — Cluster Connectivity                     ║
# ║                                                                          ║
# ╚════════════════════════════════════════════════════════════════════════════╝

def run_preflight(namespace: str, core_v1: client.CoreV1Api) -> bool:
    """
    Run pre-flight checks and print a beautiful status summary.
    This gives confidence to the speaker that everything is connected.
    """
    print_preflight_header()

    # Python version
    pv = sys.version_info
    print_success(f"Python {pv.major}.{pv.minor}.{pv.micro}")

    # kubernetes library
    import kubernetes
    print_success(f"kubernetes library v{kubernetes.__version__}")

    # kubectl connectivity
    if _check_kubectl():
        ctx = _get_kubectl_context()
        cluster_type = _detect_cluster_type(ctx)
        print_success(f"kubectl connected  ({cluster_type}: {ctx})")
    else:
        print_error("kubectl not connected to any cluster")
        return False

    # Cluster node info via Python client
    try:
        nodes = core_v1.list_node()
        count = len(nodes.items)
        print_success(f"Cluster nodes: {count}")
        for node in nodes.items:
            alloc = node.status.allocatable if node.status else {}
            cpu   = alloc.get("cpu", "?")
            mem   = alloc.get("memory", "?")
            print_info(f"  {node.metadata.name}  cpu={cpu}  memory={mem}")
    except ApiException as exc:
        print_error(f"Cannot list nodes: {exc.reason}")
        return False

    print_info(f"  Namespace: {namespace}")
    print()
    return True


# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                                                                          ║
# ║          CORE: INTERACTIVE SCENARIO RUNNER (Speaker-Controlled)          ║
# ║                                                                          ║
# ║  This is the heart of the interactive demo. It runs each agent phase     ║
# ║  (OBSERVE → REASON → PLAN) to show the audience what's wrong, then      ║
# ║  PAUSES and asks the speaker for permission before EXECUTE → VERIFY.    ║
# ║                                                                          ║
# ║  Flow:                                                                   ║
# ║    1. Deploy broken manifest        → audience sees kubectl apply        ║
# ║    2. OBSERVE: detect failure       → audience sees the pod failing      ║
# ║    3. REASON: diagnose root cause   → audience sees the analysis         ║
# ║    4. PLAN: propose remediation     → audience sees what WILL happen     ║
# ║    5. *** DASHBOARD + PROMPT ***    → speaker decides: fix or skip       ║
# ║    6. EXECUTE: apply the fix        → audience watches the patch         ║
# ║    7. VERIFY: confirm pod healthy   → audience sees green status         ║
# ║    8. LEARN: record the outcome     → agent logs what it learned         ║
# ║                                                                          ║
# ╚════════════════════════════════════════════════════════════════════════════╝

def run_interactive_scenario(
    scenario_num: int,
    namespace: str,
    core_v1: client.CoreV1Api,
    apps_v1: client.AppsV1Api,
    learner: Learner,
) -> bool:
    """
    Run a single scenario in INTERACTIVE mode.

    The agent detects and diagnoses the issue, then PAUSES for the speaker
    to approve the fix before applying it. This lets the audience see the
    problem before the solution.

    Parameters
    ----------
    scenario_num : int
        Which scenario to run (1-5).
    namespace : str
        Target Kubernetes namespace.
    core_v1 : CoreV1Api
        Kubernetes core API client.
    apps_v1 : AppsV1Api
        Kubernetes apps API client.
    learner : Learner
        Shared Learner instance for recording outcomes.

    Returns
    -------
    bool
        True if the scenario was fixed successfully, False otherwise.
    """
    scenario = SCENARIOS[scenario_num]
    title    = scenario["title"]
    depl     = scenario["deployment_name"]

    # ── Print scenario header with visual flair ──────────────────────────────
    print_scenario_header(scenario_num, title)
    print_info(scenario["story"])
    print()

    start_time = time.time()

    # ╭──────────────────────────────────────────────────────────────────────╮
    # │  STEP 1: Deploy the BROKEN manifest to the cluster                  │
    # │  This creates a real Kubernetes deployment with a deliberate bug.    │
    # ╰──────────────────────────────────────────────────────────────────────╯
    manifest_path = _resolve_manifest(scenario["manifest"])
    if not _apply_manifest(manifest_path, namespace):
        print_error(f"Failed to apply manifest: {manifest_path}")
        return False

    # Give Kubernetes a moment to create the pod
    time.sleep(2)

    # ── Instantiate agent components ─────────────────────────────────────────
    observer = Observer(core_v1, namespace)
    reasoner = Reasoner(core_v1, apps_v1, namespace)
    planner  = Planner(core_v1, namespace)
    executor = Executor(core_v1, apps_v1, namespace)
    verifier = Verifier(core_v1, namespace)

    # ╭──────────────────────────────────────────────────────────────────────╮
    # │  STEP 2: OBSERVE — Wait for the pod to enter the failure state      │
    # │  The agent polls the cluster until it detects the expected error.    │
    # ╰──────────────────────────────────────────────────────────────────────╯
    print_section_header("AGENT LOOP ACTIVATED — INTERACTIVE MODE")

    obs = None
    if scenario_num == 5:
        # Scenario 5: Pending pod — wait for it to be stuck in Pending state
        obs = observer.wait_for_pending(depl, min_seconds=10, timeout=120)
    else:
        # All other scenarios: wait for the expected failure reason
        obs = observer.wait_for_failure(depl, scenario["expected_reasons"], timeout=120)

    if obs is None:
        print_error("Timed out waiting for failure state. Scenario aborted.")
        return False

    # Show the observation details — the audience sees what pod is broken
    observer.print_observation(obs)
    time.sleep(1)

    # ╭──────────────────────────────────────────────────────────────────────╮
    # │  STEP 3: REASON — Analyze events and logs, identify root cause      │
    # │  The agent reads K8s events, matches against its runbook, and       │
    # │  produces a diagnosis with category and confidence level.           │
    # ╰──────────────────────────────────────────────────────────────────────╯
    diag = reasoner.analyze(obs)
    if diag is None:
        print_error("Could not identify root cause — no runbook pattern matched.")
        return False

    time.sleep(1)

    # ╭──────────────────────────────────────────────────────────────────────╮
    # │  STEP 4: PLAN — Generate the remediation strategy                   │
    # │  The agent determines the exact Kubernetes operation to perform     │
    # │  and assesses the risk level.                                       │
    # ╰──────────────────────────────────────────────────────────────────────╯
    plan = planner.plan(diag)
    if plan is None:
        print_error("Could not generate an action plan.")
        return False

    time.sleep(1)

    # ╔══════════════════════════════════════════════════════════════════════╗
    # ║  STEP 5: *** PAUSE — SHOW THE ISSUE DASHBOARD ***                  ║
    # ║                                                                    ║
    # ║  This is the KEY moment in the interactive demo. The audience has  ║
    # ║  now seen:                                                         ║
    # ║    - The broken deployment in the cluster                          ║
    # ║    - The agent's detection and diagnosis                           ║
    # ║    - The proposed fix                                              ║
    # ║                                                                    ║
    # ║  Now we PAUSE and let the speaker decide when to apply the fix.   ║
    # ║  This gives time for explanation, Q&A, or dramatic effect.        ║
    # ╚══════════════════════════════════════════════════════════════════════╝
    _print_issue_dashboard(scenario_num, obs, diag, plan)

    # ── Ask the speaker: "Should the agent fix this?" ────────────────────────
    if not _prompt_fix():
        # Speaker chose NOT to fix — log it and move on
        _print_fix_skipped()
        return False

    # ╭──────────────────────────────────────────────────────────────────────╮
    # │  STEP 6: EXECUTE — Apply the fix to the cluster                     │
    # │  Speaker said YES — the agent now patches/creates resources.        │
    # ╰──────────────────────────────────────────────────────────────────────╯
    _print_fix_approved()
    time.sleep(1)

    exec_result = executor.execute(plan)
    time.sleep(1)

    # ╭──────────────────────────────────────────────────────────────────────╮
    # │  STEP 7: VERIFY — Confirm the pod is now Running and Ready          │
    # │  The agent polls until the new pod passes all health checks.        │
    # ╰──────────────────────────────────────────────────────────────────────╯
    verify_result = verifier.verify(depl, exec_result, timeout=180)

    # ╭──────────────────────────────────────────────────────────────────────╮
    # │  STEP 8: LEARN — Record the outcome for session summary             │
    # │  In production, this would feed a database or ML model.            │
    # ╰──────────────────────────────────────────────────────────────────────╯
    learner.record(
        scenario_num    = scenario_num,
        scenario_title  = title,
        deployment_name = depl,
        namespace       = namespace,
        diag            = diag,
        exec_result     = exec_result,
        verify_result   = verify_result,
        start_time      = start_time,
    )

    # ── Final celebration or failure notice ───────────────────────────────────
    elapsed = time.time() - start_time
    if verify_result.success:
        _print_healing_complete_celebration(scenario_num, title, elapsed)
    else:
        print_error(f"Scenario {scenario_num} did not resolve within the timeout period.")

    return verify_result.success


# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                                                                          ║
# ║                    INTERACTIVE DEMO LOOP                                 ║
# ║                                                                          ║
# ║  The main menu loop. Speaker picks scenarios, watches the diagnosis,     ║
# ║  and controls when fixes are applied.                                    ║
# ║                                                                          ║
# ╚════════════════════════════════════════════════════════════════════════════╝

def demo_loop(namespace: str, core_v1: client.CoreV1Api, apps_v1: client.AppsV1Api) -> None:
    """Run the interactive menu loop."""
    learner = Learner()

    while True:
        _print_interactive_menu()
        try:
            choice = input("  Enter your choice: ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            choice = "Q"

        if choice == "Q":
            # ── Quit ─────────────────────────────────────────────────────────
            print()
            print(_c(Color.CYAN,
                "  ╔════════════════════════════════════════════════════════════╗"))
            print(_c(Color.CYAN,
                "  ║  👋 Thanks for watching!                                  ║"))
            print(_c(Color.CYAN,
                "  ║  Next: Run 'python3 demo.py' to see the FULLY AUTONOMOUS ║"))
            print(_c(Color.CYAN,
                "  ║  mode — zero human intervention, agent fixes everything.  ║"))
            print(_c(Color.CYAN,
                "  ║                                                          ║"))
            print(_c(Color.CYAN,
                "  ║  AI DevCon India 2026 — The Hidden Layer of Automation   ║"))
            print(_c(Color.CYAN,
                "  ╚════════════════════════════════════════════════════════════╝"))
            print()
            break

        elif choice == "C":
            # ── Cleanup all demo resources ───────────────────────────────────
            _cleanup_all(namespace)
            _wait_for_keypress()

        elif choice == "A":
            # ── Run ALL 5 scenarios sequentially ─────────────────────────────
            print()
            print(_c(Color.MAGENTA, "  ═══ Running ALL 5 scenarios in interactive mode ═══"))
            print(_c(Color.MAGENTA, "  Each scenario will pause for your approval before fixing."))
            print()
            for num in range(1, 6):
                _print_story(num)
                try:
                    run_interactive_scenario(
                        scenario_num=num,
                        namespace=namespace,
                        core_v1=core_v1,
                        apps_v1=apps_v1,
                        learner=learner,
                    )
                except KeyboardInterrupt:
                    print_info("Skipping to next scenario...")
                    continue
                except Exception as exc:
                    print_error(f"Scenario {num} failed: {exc}")
            learner.print_session_summary()
            _wait_for_keypress()

        elif choice in ("1", "2", "3", "4", "5"):
            # ── Run a single scenario ────────────────────────────────────────
            num = int(choice)
            _print_story(num)
            try:
                run_interactive_scenario(
                    scenario_num=num,
                    namespace=namespace,
                    core_v1=core_v1,
                    apps_v1=apps_v1,
                    learner=learner,
                )
            except KeyboardInterrupt:
                print_info("Scenario interrupted.")
            except Exception as exc:
                print_error(f"Scenario {num} failed: {exc}")
            _wait_for_keypress()

        else:
            print_error(f"Unknown choice: {choice!r}. Please enter 1-5, A, C, or Q.")


# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                                                                          ║
# ║                         ENTRY POINT                                      ║
# ║                                                                          ║
# ║  Parse CLI args, connect to the cluster, run preflight, launch the       ║
# ║  interactive demo loop.                                                  ║
# ║                                                                          ║
# ╚════════════════════════════════════════════════════════════════════════════╝

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="K8s Healing Agent — Interactive Demo (Speaker-Controlled)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script pauses AFTER diagnosis and BEFORE applying fixes.
Use demo.py for the fully autonomous version.

Examples:
  python3 interactive-demo.py                   # launch interactive menu
  python3 interactive-demo.py --preflight       # check cluster only
  python3 interactive-demo.py -n staging        # use 'staging' namespace
        """,
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

    # ── Print the grand opening banner ────────────────────────────────────────
    _print_banner()

    # ── Load Kubernetes configuration ─────────────────────────────────────────
    try:
        load_k8s_config()
    except RuntimeError as exc:
        print_error(str(exc))
        sys.exit(1)

    core_v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()

    # ── Pre-flight checks ─────────────────────────────────────────────────────
    ok = run_preflight(args.namespace, core_v1)
    if not ok:
        print_error("Pre-flight checks failed. Fix the issues above and try again.")
        sys.exit(1)

    if args.preflight:
        print_success("Pre-flight checks passed!")
        sys.exit(0)

    # ── Launch the interactive demo loop ──────────────────────────────────────
    demo_loop(args.namespace, core_v1, apps_v1)


if __name__ == "__main__":
    main()
