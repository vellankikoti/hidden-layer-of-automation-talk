"""
K8s Healing Agent — Runbook Module

Pattern database that maps error signatures to root-cause diagnoses and
remediation plans. Each entry describes a known failure mode, how to
detect it, and the exact fix to apply.
"""

from typing import Any, Dict, List, Optional

# ── Type alias ────────────────────────────────────────────────────────────────
RunbookEntry = Dict[str, Any]

# ── Master runbook ─────────────────────────────────────────────────────────────
RUNBOOK: List[RunbookEntry] = [
    # ── Scenario 1: ImagePullBackOff ──────────────────────────────────────────
    {
        "pattern_id": "imagepull-invalid-tag",
        "scenario": 1,
        "trigger": {
            "pod_status_reasons": [
                "ImagePullBackOff",
                "ErrImagePull",
            ],
            "event_message_contains": [
                "manifest for",
                "manifest unknown",
                "not found",
                "no such image",
                "toomanyrequests",
                "unauthorized",
                "tag does not exist",
            ],
        },
        "diagnosis": {
            "summary": "Image tag does not exist in container registry",
            "detail": (
                "The deployment references image tag '{tag}' which cannot be found. "
                "This is typically caused by a typo in the tag name or the tag not "
                "being pushed to the registry."
            ),
            "category": "DEPLOYMENT_ERROR",
            "confidence": "HIGH",
        },
        "fix": {
            "type": "PATCH_DEPLOYMENT_IMAGE",
            "description": "Roll back to known-good image tag",
            "risk": "LOW",
            "action": "patch_image_tag",
            "params": {
                "image_map": {
                    "nginx": "nginx:1.27-alpine",
                    "python": "python:3.12-slim",
                    "redis": "redis:7-alpine",
                    "postgres": "postgres:16-alpine",
                    "node":    "node:20-alpine",
                },
                "default_fallback_suffix": ":latest",
            },
        },
    },

    # ── Scenario 2: CrashLoopBackOff — bad liveness probe ────────────────────
    {
        "pattern_id": "crashloop-bad-liveness-probe",
        "scenario": 2,
        "trigger": {
            "pod_status_reasons": [
                "CrashLoopBackOff",
            ],
            "event_message_contains": [
                "Liveness probe failed",
                "probe failed",
                "statuscode: 404",
                "connection refused",
                "liveness",
            ],
            "min_restart_count": 1,
        },
        "diagnosis": {
            "summary": "Liveness probe endpoint returns non-200 status (likely 404)",
            "detail": (
                "The pod's liveness probe is configured to check path '{probe_path}' "
                "but the endpoint does not exist. Kubernetes kills and restarts the "
                "container each time the probe fails, causing CrashLoopBackOff."
            ),
            "category": "CONFIGURATION_ERROR",
            "confidence": "HIGH",
        },
        "fix": {
            "type": "PATCH_DEPLOYMENT_LIVENESS_PROBE",
            "description": "Fix liveness probe path to a valid endpoint",
            "risk": "LOW",
            "action": "patch_liveness_probe",
            "params": {
                "image_probe_defaults": {
                    "nginx":   "/",
                    "apache":  "/",
                    "httpd":   "/",
                    "python":  "/",
                    "node":    "/health",
                },
                "default_path": "/",
            },
        },
    },

    # ── Scenario 3: OOMKilled ─────────────────────────────────────────────────
    {
        "pattern_id": "oomkilled-memory-limit-low",
        "scenario": 3,
        "trigger": {
            "pod_status_reasons": [
                "OOMKilled",
                "CrashLoopBackOff",
            ],
            "terminated_reason": "OOMKilled",
            "event_message_contains": [
                "OOMKilled",
                "OOM",
                "memory",
                "killed",
            ],
        },
        "diagnosis": {
            "summary": "Container killed by OOM killer — memory limit too low",
            "detail": (
                "The container exceeded its memory limit of '{memory_limit}' and was "
                "killed by the Linux OOM killer. The process requires more memory than "
                "the limit allows."
            ),
            "category": "RESOURCE_ERROR",
            "confidence": "HIGH",
        },
        "fix": {
            "type": "PATCH_DEPLOYMENT_MEMORY",
            "description": "Increase memory limit and request",
            "risk": "MEDIUM",
            "action": "patch_memory_limit",
            "params": {
                "multiplier": 4,       # multiply current limit by 4
                "minimum_limit": "128Mi",
                "minimum_request": "64Mi",
            },
        },
    },

    # ── Scenario 4: CreateContainerConfigError — missing ConfigMap ────────────
    {
        "pattern_id": "configerror-missing-configmap",
        "scenario": 4,
        "trigger": {
            "pod_status_reasons": [
                "CreateContainerConfigError",
                "CreateContainerError",
            ],
            "event_message_contains": [
                "configmap",
                "not found",
                "secret",
                "referenced",
                "does not exist",
            ],
        },
        "diagnosis": {
            "summary": "Referenced ConfigMap does not exist in namespace",
            "detail": (
                "The deployment references ConfigMap '{configmap_name}' which does not "
                "exist in namespace '{namespace}'. This is often caused by config drift "
                "between environments or a missing pre-deployment step."
            ),
            "category": "CONFIG_DRIFT",
            "confidence": "HIGH",
        },
        "fix": {
            "type": "CREATE_CONFIGMAP",
            "description": "Create the missing ConfigMap with sensible defaults",
            "risk": "MEDIUM",
            "action": "create_configmap",
            "params": {
                "default_data": {
                    "APP_ENV":    "production",
                    "LOG_LEVEL":  "info",
                    "DEBUG":      "false",
                    "PORT":       "8080",
                    "TIMEOUT":    "30",
                },
            },
        },
    },

    # ── Scenario 5: Pending — impossible resource request ─────────────────────
    {
        "pattern_id": "pending-insufficient-cpu",
        "scenario": 5,
        "trigger": {
            "pod_phase": "Pending",
            "event_message_contains": [
                "Insufficient cpu",
                "Insufficient memory",
                "Unschedulable",
                "nodes are available",
                "didn't match",
            ],
            "pending_seconds_threshold": 30,
        },
        "diagnosis": {
            "summary": "Pod cannot be scheduled — resource request exceeds node capacity",
            "detail": (
                "The pod requests {cpu_request} CPU cores but no node in the cluster "
                "has that much allocatable CPU. Kubernetes cannot schedule the pod and "
                "it remains in Pending state indefinitely."
            ),
            "category": "SCHEDULING_ERROR",
            "confidence": "HIGH",
        },
        "fix": {
            "type": "PATCH_DEPLOYMENT_CPU",
            "description": "Right-size CPU request to fit available node capacity",
            "risk": "MEDIUM",
            "action": "patch_cpu_request",
            "params": {
                "target_cpu_request": "500m",
                "target_cpu_limit":   "1000m",
            },
        },
    },
]


def find_pattern(
    pod_status_reason: str = "",
    terminated_reason: str = "",
    event_messages: List[str] = None,
    pod_phase: str = "",
    restart_count: int = 0,
    pending_seconds: float = 0,
) -> Optional[RunbookEntry]:
    """
    Match cluster observations against runbook patterns.

    Returns the first matching RunbookEntry, or None if no pattern matches.

    Parameters
    ----------
    pod_status_reason:
        The waiting.reason or containerStatus reason (e.g. "ImagePullBackOff").
    terminated_reason:
        The lastState.terminated.reason (e.g. "OOMKilled").
    event_messages:
        List of event message strings from ``kubectl get events``.
    pod_phase:
        Pod phase string (e.g. "Pending", "Running").
    restart_count:
        Number of container restarts.
    pending_seconds:
        How long the pod has been in Pending state.
    """
    if event_messages is None:
        event_messages = []

    combined_events = " ".join(event_messages).lower()

    for entry in RUNBOOK:
        trigger = entry["trigger"]

        # ── Check pod-phase-based triggers (Scenario 5) ───────────────────────
        if "pod_phase" in trigger:
            if pod_phase != trigger["pod_phase"]:
                continue
            threshold = trigger.get("pending_seconds_threshold", 0)
            if pending_seconds < threshold:
                continue
            # Also require at least one event keyword match
            keywords = trigger.get("event_message_contains", [])
            if keywords and not any(kw.lower() in combined_events for kw in keywords):
                continue
            return entry

        # ── Check terminated-reason (OOMKilled) ───────────────────────────────
        if "terminated_reason" in trigger:
            if terminated_reason == trigger["terminated_reason"]:
                return entry

        # ── Check waiting/status reason ───────────────────────────────────────
        status_reasons = trigger.get("pod_status_reasons", [])
        if status_reasons and pod_status_reason not in status_reasons:
            continue

        # ── Check event keywords ──────────────────────────────────────────────
        event_keywords = trigger.get("event_message_contains", [])
        if event_keywords and not any(kw.lower() in combined_events for kw in event_keywords):
            continue

        # ── Check min restart count ───────────────────────────────────────────
        min_restarts = trigger.get("min_restart_count", 0)
        if restart_count < min_restarts:
            continue

        return entry

    return None
