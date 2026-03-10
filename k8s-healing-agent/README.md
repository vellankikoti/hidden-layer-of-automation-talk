# 🤖 K8s Healing Agent — The Hidden Layer of Automation

> **Live demo system for AI DevCon India 2026**
> A production-grade, autonomous Kubernetes healing agent that detects real-world pod failures and fixes them — in seconds, with zero human intervention.

---

## What Is This?

The **K8s Healing Agent** is a self-healing automation system for Kubernetes. It implements a classic **Observe → Reason → Plan → Execute → Learn** agent loop to diagnose root causes of pod failures and apply precise fixes — automatically.

This project powers a live, interactive conference demo showing 5 real-world production Kubernetes failure scenarios being healed autonomously in front of a live audience.

---

## Quick Start

```bash
# 1. Install dependencies
pip install kubernetes

# 2. Make sure kubectl is connected to any cluster
kubectl get nodes

# 3. Run the interactive demo
python3 demo.py
```

Or use the setup script for a full environment check:

```bash
./setup.sh
python3 demo.py
```

---

## Requirements

| Requirement | Version |
|-------------|---------|
| Python | 3.9+ |
| kubernetes (pip) | ≥ 28.1.0 |
| kubectl | Any recent version |
| Kubernetes cluster | Any (see below) |

**Zero internet required during demo** — all container images (`nginx`, `python:3.12-slim`) are standard Docker Hub images that can be pulled in advance.

---

## Supported Clusters

| Cluster | Status |
|---------|--------|
| Docker Desktop | ✅ Supported |
| minikube | ✅ Supported |
| kind (Kubernetes in Docker) | ✅ Supported |
| AWS EKS | ✅ Supported |
| Google GKE | ✅ Supported |
| Azure AKS | ✅ Supported |
| Any cluster with `kubectl` | ✅ Supported |

The agent auto-detects in-cluster vs kubeconfig configuration.

---

## The 5 Scenarios

| # | Failure Type | Deployment | Root Cause | Agent Fix |
|---|-------------|------------|------------|-----------|
| 1 | ImagePullBackOff | `web-frontend` | Typo in image tag (`nginx:1.99.99-nonexistent`) | Patch image to `nginx:1.27-alpine` |
| 2 | CrashLoopBackOff | `api-server` | Liveness probe on `/healthz` returns 404 | Patch probe path to `/` |
| 3 | OOMKilled | `data-processor` | Memory limit 32Mi too low (needs ~50MB) | Increase memory limit to 128Mi |
| 4 | CreateContainerConfigError | `config-service` | ConfigMap `app-config` missing | Create ConfigMap with defaults |
| 5 | Pending (Unschedulable) | `ml-worker` | CPU request of 100 cores — impossible | Reduce CPU request to 500m |

---

## Usage

### Interactive Demo (Recommended for talks)

```bash
python3 demo.py
```

You'll see:

```
╔══════════════════════════════════════════════════════════════╗
║        🤖 K8s Healing Agent — AI DevCon India Demo          ║
║        "The Hidden Layer of Automation"                      ║
╠══════════════════════════════════════════════════════════════╣
║  [1] 🖼️  Scenario 1: ImagePullBackOff (Wrong Image Tag)     ║
║  [2] 🔄 Scenario 2: CrashLoopBackOff (Bad Health Check)    ║
║  [3] 💾 Scenario 3: OOMKilled (Memory Limit Too Low)       ║
║  [4] 📄 Scenario 4: ConfigMap Missing (Env Config Drift)   ║
║  [5] ⏳ Scenario 5: Pending Pod (Impossible CPU Request)   ║
║  [A] 🚀 Run ALL scenarios sequentially                      ║
║  [C] 🧹 Cleanup all demo resources                          ║
║  [Q] 👋 Quit                                                ║
╚══════════════════════════════════════════════════════════════╝
```

### CLI (Direct scenario runner)

```bash
# Run a specific scenario
python -m agent.main --scenario 1

# Run all scenarios
python -m agent.main --scenario all

# Use a custom namespace
python -m agent.main --scenario 3 --namespace demo

# Pre-flight check only
python -m agent.main --preflight
```

### Pre-flight Check (Before going on stage)

```bash
python3 demo.py --preflight
```

This verifies:
- Python version ≥ 3.9
- `kubernetes` library installed
- `kubectl` connected to a cluster
- Node count and allocatable resources

### Cleanup

```bash
./cleanup.sh

# Or with a custom namespace:
NAMESPACE=demo ./cleanup.sh
```

---

## Project Structure

```
k8s-healing-agent/
│
├── README.md                    # This file
├── requirements.txt             # Python dependencies (kubernetes only)
├── setup.sh                     # One-command setup script
├── cleanup.sh                   # Remove all demo resources
│
├── scenarios/                   # Broken Kubernetes manifests
│   ├── 01-imagepull-broken.yaml
│   ├── 02-crashloop-broken.yaml
│   ├── 03-oomkill-broken.yaml
│   ├── 04-configerror-broken.yaml
│   └── 05-pending-broken.yaml
│
├── agent/                       # The healing agent
│   ├── __init__.py
│   ├── main.py                  # CLI entry point
│   ├── observer.py              # OBSERVE: detect anomalies
│   ├── reasoner.py              # REASON: root cause analysis
│   ├── planner.py               # PLAN: remediation strategy
│   ├── executor.py              # EXECUTE: apply K8s patches
│   ├── verifier.py              # VERIFY: confirm the fix worked
│   ├── learner.py               # LEARN: record outcomes
│   ├── display.py               # Terminal UI: colors, emojis
│   └── runbook.py               # Pattern database: known issues → fixes
│
└── demo.py                      # Interactive demo runner
```

---

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │          K8s Healing Agent               │
                    │                                          │
  Kubernetes        │   ┌──────────┐    ┌──────────────────┐  │
  Cluster  ─────────┼──▶│ OBSERVE  │───▶│     REASON       │  │
                    │   │(observer)│    │(reasoner+runbook) │  │
                    │   └──────────┘    └────────┬─────────┘  │
                    │                            │             │
                    │   ┌──────────┐    ┌────────▼─────────┐  │
  Kubernetes ◀──────┼───│ EXECUTE  │◀───│      PLAN        │  │
  Cluster           │   │(executor)│    │    (planner)     │  │
                    │   └────┬─────┘    └──────────────────┘  │
                    │        │                                  │
                    │   ┌────▼─────┐    ┌──────────────────┐  │
                    │   │  VERIFY  │───▶│      LEARN       │  │
                    │   │(verifier)│    │    (learner)     │  │
                    │   └──────────┘    └──────────────────┘  │
                    └─────────────────────────────────────────┘
```

---

## How It Works

### Phase 1 — OBSERVE 🔍
The agent lists all pods in the target namespace and classifies each pod:
- **HEALTHY**: Running + all containers Ready
- **FAILING**: CrashLoopBackOff, OOMKilled, Error
- **STUCK**: ImagePullBackOff, ErrImagePull, CreateContainerConfigError
- **UNSCHEDULABLE**: Pending with scheduling failure events

### Phase 2 — REASON 🧠
For each unhealthy pod, the agent:
1. Reads Kubernetes events (equivalent to `kubectl describe pod`)
2. Reads previous container logs (if available)
3. Matches the findings against the **Runbook** — a pattern database of known failure signatures
4. Produces a structured `Diagnosis` with root cause, category, and confidence level

### Phase 3 — PLAN 📝
The agent selects the appropriate fix from the Runbook and enriches it with real cluster data:
- For CPU issues → queries actual node capacity to calculate a safe CPU request
- For memory issues → reads current limit and calculates a safe multiplier
- For image issues → selects a known-good image tag from the image map

### Phase 4 — EXECUTE 🔧
The agent applies the fix using the official **kubernetes-python client**:
- Deployment patches: `apps_v1.patch_namespaced_deployment()`
- ConfigMap creation: `core_v1.create_namespaced_config_map()`

All fixes are **idempotent** — running them twice does not break anything.

### Phase 5 — LEARN 📚
Every incident is recorded with: timestamp, root cause, fix applied, success/failure, and time to resolution. A session summary is printed at the end.

---

## Customization

### Adding a New Scenario

1. Create a broken manifest in `scenarios/`
2. Add a new entry to `RUNBOOK` in `agent/runbook.py`
3. Add the scenario definition to `SCENARIOS` in `agent/main.py`
4. Implement a new `_fix_*` method in `agent/executor.py`

### Adding a New Runbook Pattern

```python
# In agent/runbook.py
{
    "pattern_id": "my-new-pattern",
    "scenario": 6,
    "trigger": {
        "pod_status_reasons": ["SomeReason"],
        "event_message_contains": ["some error text"],
    },
    "diagnosis": {
        "summary": "Short description",
        "detail": "Detailed explanation with {context_variable} substitution",
        "category": "MY_CATEGORY",
        "confidence": "HIGH",
    },
    "fix": {
        "type": "MY_FIX_TYPE",
        "description": "What the fix does",
        "risk": "LOW",
        "action": "my_fix_action",
        "params": {},
    },
}
```

### Using a Custom Namespace

```bash
# Environment variable
K8S_NAMESPACE=my-ns python3 demo.py

# CLI flag
python3 demo.py --namespace my-ns
python -m agent.main --scenario all --namespace my-ns

# Cleanup
NAMESPACE=my-ns ./cleanup.sh
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `Cannot connect to Kubernetes cluster` | Run `kubectl cluster-info` to check connectivity |
| `kubernetes` library not found | Run `pip install kubernetes` |
| Scenario times out waiting for failure | The image pull may be slow — increase the timeout in `observer.py` |
| OOMKill scenario never triggers | Ensure the node has enough memory to *start* the container (it needs ~32Mi to be allocated before OOMKill) |
| Pending scenario resolves on its own | Your node has more than 100 CPU cores — this is unusual; check `kubectl get nodes` |
| `kubectl` not in PATH | Install kubectl: https://kubernetes.io/docs/tasks/tools/ |

---

## Terminal Output Example

```
╔══════════════════════════════════════════════════════════════╗
║  🤖 K8s Healing Agent — Scenario 1: ImagePullBackOff        ║
╚══════════════════════════════════════════════════════════════╝

  ⏳ [12:04:02] Waiting for failure state...
  ⚠️  [12:04:08] DETECTED: Pod web-frontend-7d4b8c9f5-x2k9m
     Status: ImagePullBackOff

  ─────── AGENT LOOP ACTIVATED ───────

  🔍 [12:04:08] [OBSERVE] Pod web-frontend-7d4b8c9f5-x2k9m
     Status:    ImagePullBackOff
     Container: web-frontend
     Image:     nginx:1.99.99-nonexistent

  📋 [12:04:09] [ANALYZE] Reading pod events...
     Event: "Failed to pull image nginx:1.99.99-nonexistent: not found"

  🧠 [12:04:09] [REASON] Root cause identified:
     → Image tag does not exist in container registry

  📝 [12:04:10] [PLAN] Remediation strategy:
     → Action:  Roll back to known-good image tag
       From:    nginx:1.99.99-nonexistent
       To:      nginx:1.27-alpine

  🔧 [12:04:10] [EXECUTE] Applying fix...
     ✅ Deployment patched successfully → nginx:1.27-alpine

  ✅ [12:04:15] [VERIFY] Checking pod status...
     ✅ Pod is healthy!

  📚 [12:04:15] [LEARN] Outcome recorded:
     Fix:      Patched image to nginx:1.27-alpine
     Result:   SUCCESS
     Duration: 7 seconds

╔══════════════════════════════════════════════════════════════╗
║  🎉 SCENARIO 1 COMPLETE — ImagePullBackOff resolved in 7s   ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Credits

Built for **AI DevCon India 2026** — "The Hidden Layer of Automation"

> *Demonstrating how autonomous AI agents can replace manual on-call responses for the most common Kubernetes production failures.*
