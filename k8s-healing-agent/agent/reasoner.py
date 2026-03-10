"""
K8s Healing Agent — Reasoner Module

ANALYZE + REASON phases of the Agent Loop.

Pulls pod events and logs, matches them against the runbook, and produces
a human-readable root-cause diagnosis with supporting evidence.
"""

import re
import time
from typing import Any, Dict, List, Optional

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from agent.display import (
    Color, _c, print_phase, print_info, print_detail
)
from agent.observer import PodObservation
from agent import runbook as rb


class Diagnosis:
    """Result of the REASON phase."""

    def __init__(
        self,
        pattern_id: str,
        summary: str,
        detail: str,
        category: str,
        confidence: str,
        evidence: List[str],
        runbook_entry: rb.RunbookEntry,
        context: Dict[str, Any],
    ) -> None:
        self.pattern_id    = pattern_id
        self.summary       = summary
        self.detail        = detail
        self.category      = category
        self.confidence    = confidence
        self.evidence      = evidence
        self.runbook_entry = runbook_entry
        self.context       = context  # extra data for the executor

    def __repr__(self) -> str:
        return f"Diagnosis(pattern_id={self.pattern_id!r}, summary={self.summary!r})"


class Reasoner:
    """
    Analyses a failing PodObservation and produces a Diagnosis.

    Attributes
    ----------
    core_v1:
        Kubernetes CoreV1Api client.
    apps_v1:
        Kubernetes AppsV1Api client.
    namespace:
        Namespace of the pod.
    """

    def __init__(
        self,
        core_v1: client.CoreV1Api,
        apps_v1: client.AppsV1Api,
        namespace: str = "default",
    ) -> None:
        self.core_v1   = core_v1
        self.apps_v1   = apps_v1
        self.namespace = namespace

    # ── Public entry point ────────────────────────────────────────────────────

    def analyze(self, obs: PodObservation) -> Optional[Diagnosis]:
        """
        Run the ANALYZE + REASON phases on *obs*.

        Returns a Diagnosis, or None if no runbook pattern matched.
        """
        # ── ANALYZE: gather events ────────────────────────────────────────────
        time.sleep(1)
        print_phase("ANALYZE", "📋", "Reading pod events...")
        events = self._get_pod_events(obs.name)
        event_messages = [e.message for e in events if e.message]

        for msg in event_messages[:5]:
            print_info(f"Event: \"{msg}\"")

        # ── Try to get container logs (previous run) ──────────────────────────
        logs = self._get_container_logs(obs.name, obs.container_name, previous=True)
        if logs:
            snippet = logs.splitlines()[-3:]  # last 3 lines
            for line in snippet:
                if line.strip():
                    print_info(f"Log:   {line.strip()}")

        # ── Build context dict used for detail substitution + executor ────────
        context = self._build_context(obs, event_messages)

        # ── Match runbook pattern ─────────────────────────────────────────────
        entry = rb.find_pattern(
            pod_status_reason  = obs.status_reason,
            terminated_reason  = obs.terminated_reason,
            event_messages     = event_messages,
            pod_phase          = obs.pod_phase,
            restart_count      = obs.restart_count,
            pending_seconds    = obs.pending_seconds,
        )

        if entry is None:
            return None

        # ── REASON ────────────────────────────────────────────────────────────
        time.sleep(1)
        diag = self._build_diagnosis(entry, context, event_messages)
        self._print_reason(diag)
        return diag

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_pod_events(self, pod_name: str) -> List[Any]:
        """Return events for a specific pod."""
        try:
            events = self.core_v1.list_namespaced_event(
                namespace=self.namespace,
                field_selector=f"involvedObject.name={pod_name}",
            )
            return events.items
        except ApiException:
            return []

    def _get_container_logs(
        self,
        pod_name: str,
        container_name: str,
        previous: bool = False,
    ) -> str:
        """Return last 50 log lines from a container (or its previous run)."""
        try:
            return self.core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=self.namespace,
                container=container_name,
                tail_lines=50,
                previous=previous,
            )
        except ApiException:
            return ""

    def _get_deployment_spec(self, deployment_name: str) -> Optional[Any]:
        """Return the Deployment object or None."""
        try:
            return self.apps_v1.read_namespaced_deployment(
                name=deployment_name,
                namespace=self.namespace,
            )
        except ApiException:
            return None

    def _build_context(
        self,
        obs: PodObservation,
        event_messages: List[str],
    ) -> Dict[str, Any]:
        """
        Extract structured context values from the observation and events.

        This dict is passed to the Executor so it has all the data it needs.
        """
        ctx: Dict[str, Any] = {
            "pod_name":        obs.name,
            "container_name":  obs.container_name,
            "image":           obs.image,
            "namespace":       self.namespace,
            "restart_count":   obs.restart_count,
            "status_reason":   obs.status_reason,
            "terminated_reason": obs.terminated_reason,
        }

        # Image tag parsing
        image = obs.image or ""
        if ":" in image:
            ctx["image_name"], ctx["tag"] = image.rsplit(":", 1)
        else:
            ctx["image_name"] = image
            ctx["tag"]        = "latest"

        # Infer deployment name from pod name (strip ReplicaSet suffix)
        # Pod names look like: <deployment>-<rs-hash>-<pod-hash>
        parts = obs.name.rsplit("-", 2)
        ctx["deployment_name"] = parts[0] if len(parts) >= 2 else obs.name

        # Liveness probe path (from pod spec)
        probe_path = "/"
        if obs.pod.spec and obs.pod.spec.containers:
            for ctr in obs.pod.spec.containers:
                if ctr.name == obs.container_name:
                    lp = ctr.liveness_probe
                    if lp and lp.http_get:
                        probe_path = lp.http_get.path or "/"
                    break
        ctx["probe_path"] = probe_path

        # Memory limit (from pod spec)
        memory_limit = "unknown"
        if obs.pod.spec and obs.pod.spec.containers:
            for ctr in obs.pod.spec.containers:
                if ctr.name == obs.container_name:
                    if ctr.resources and ctr.resources.limits:
                        memory_limit = ctr.resources.limits.get("memory", "unknown")
                    break
        ctx["memory_limit"] = memory_limit

        # CPU request (from pod spec)
        cpu_request = "unknown"
        if obs.pod.spec and obs.pod.spec.containers:
            for ctr in obs.pod.spec.containers:
                if ctr.name == obs.container_name:
                    if ctr.resources and ctr.resources.requests:
                        cpu_request = ctr.resources.requests.get("cpu", "unknown")
                    break
        ctx["cpu_request"] = cpu_request

        # ConfigMap name from events
        configmap_name = ""
        combined = " ".join(event_messages)
        cm_match = re.search(r'configmap\s+"?([a-z0-9\-]+)"?', combined, re.IGNORECASE)
        if cm_match:
            configmap_name = cm_match.group(1)
        # Also try from pod spec envFrom
        if not configmap_name and obs.pod.spec and obs.pod.spec.containers:
            for ctr in obs.pod.spec.containers:
                if ctr.env_from:
                    for ef in ctr.env_from:
                        if ef.config_map_ref and ef.config_map_ref.name:
                            configmap_name = ef.config_map_ref.name
                            break
        ctx["configmap_name"] = configmap_name or "app-config"

        return ctx

    def _build_diagnosis(
        self,
        entry: rb.RunbookEntry,
        context: Dict[str, Any],
        event_messages: List[str],
    ) -> Diagnosis:
        """Construct a Diagnosis from a runbook entry and context."""
        detail_template = entry["diagnosis"]["detail"]
        try:
            detail = detail_template.format(**context)
        except KeyError:
            detail = detail_template

        return Diagnosis(
            pattern_id    = entry["pattern_id"],
            summary       = entry["diagnosis"]["summary"],
            detail        = detail,
            category      = entry["diagnosis"]["category"],
            confidence    = entry["diagnosis"]["confidence"],
            evidence      = event_messages[:5],
            runbook_entry = entry,
            context       = context,
        )

    def _print_reason(self, diag: Diagnosis) -> None:
        """Print the REASON phase output."""
        print_phase("REASON", "🧠", "Root cause identified:")
        print_info(f"→ {diag.summary}")
        print_info(f"  {diag.detail}")
        print_info(f"  Category:   {diag.category}")
        print_info(f"  Confidence: {diag.confidence}")
