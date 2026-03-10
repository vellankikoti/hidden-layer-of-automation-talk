"""
K8s Healing Agent — Observer Module

OBSERVE phase of the Agent Loop.

Watches pods in a namespace, detects anomalies, and classifies pod health
so the rest of the pipeline can act on the findings.
"""

import time
from typing import Any, Dict, List, Optional, Tuple

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from agent.display import (
    Color, _c, print_phase, print_info, print_detail, print_waiting, print_detect
)


# ── Health classification constants ───────────────────────────────────────────
HEALTHY       = "HEALTHY"
FAILING       = "FAILING"      # CrashLoopBackOff, OOMKilled, Error
STUCK         = "STUCK"        # ImagePullBackOff, CreateContainerConfigError
UNSCHEDULABLE = "UNSCHEDULABLE" # Pending with scheduling events
UNKNOWN       = "UNKNOWN"

# Waiting reasons that indicate the pod is stuck (never started)
STUCK_REASONS = {
    "ImagePullBackOff",
    "ErrImagePull",
    "CreateContainerConfigError",
    "CreateContainerError",
    "InvalidImageName",
}

# Waiting / terminated reasons that indicate active failure
FAILING_REASONS = {
    "CrashLoopBackOff",
    "OOMKilled",
    "Error",
    "RunContainerError",
    "PostStartHookError",
}


class PodObservation:
    """Encapsulates all observed state for a single pod."""

    def __init__(
        self,
        pod: Any,
        health: str,
        status_reason: str,
        terminated_reason: str,
        restart_count: int,
        container_name: str,
        image: str,
        pod_phase: str,
        first_seen_pending: Optional[float] = None,
    ) -> None:
        self.pod               = pod
        self.name              = pod.metadata.name
        self.namespace         = pod.metadata.namespace
        self.health            = health
        self.status_reason     = status_reason
        self.terminated_reason = terminated_reason
        self.restart_count     = restart_count
        self.container_name    = container_name
        self.image             = image
        self.pod_phase         = pod_phase
        self.first_seen_pending = first_seen_pending or time.time()

    @property
    def pending_seconds(self) -> float:
        """Seconds the pod has been in Pending state."""
        if self.pod_phase == "Pending":
            return time.time() - self.first_seen_pending
        return 0.0

    def __repr__(self) -> str:
        return (
            f"PodObservation(name={self.name!r}, health={self.health!r}, "
            f"reason={self.status_reason!r})"
        )


def _classify_pod(pod: Any) -> Tuple[str, str, str, int, str, str]:
    """
    Classify a pod and extract key state information.

    Returns
    -------
    (health, status_reason, terminated_reason, restart_count, container_name, image)
    """
    phase = (pod.status.phase or "Unknown") if pod.status else "Unknown"

    if phase == "Running":
        # Check if all containers are really ready
        if pod.status.container_statuses:
            for cs in pod.status.container_statuses:
                if not cs.ready:
                    # Check waiting reason (e.g. CrashLoopBackOff, ImagePullBackOff)
                    if cs.state and cs.state.waiting and cs.state.waiting.reason:
                        reason = cs.state.waiting.reason
                        # Also capture terminated reason from last_state for OOMKilled detection
                        term_reason = ""
                        if cs.last_state and cs.last_state.terminated and cs.last_state.terminated.reason:
                            term_reason = cs.last_state.terminated.reason
                        if reason in STUCK_REASONS:
                            return (STUCK, reason, term_reason, cs.restart_count or 0,
                                    cs.name, cs.image or "")
                        if reason in FAILING_REASONS:
                            return (FAILING, reason, term_reason, cs.restart_count or 0,
                                    cs.name, cs.image or "")
                    # Check if the container is currently terminated (between restarts,
                    # before CrashLoopBackOff kicks in — e.g. OOMKilled)
                    if cs.state and cs.state.terminated and cs.state.terminated.reason:
                        term_reason = cs.state.terminated.reason
                        if term_reason in FAILING_REASONS:
                            return (FAILING, term_reason, term_reason, cs.restart_count or 0,
                                    cs.name, cs.image or "")
                    # Check last_state.terminated even if current state is unclear
                    # (catches OOMKilled after container has been restarted)
                    if cs.last_state and cs.last_state.terminated and cs.last_state.terminated.reason:
                        term_reason = cs.last_state.terminated.reason
                        if term_reason in FAILING_REASONS:
                            return (FAILING, term_reason, term_reason, cs.restart_count or 0,
                                    cs.name, cs.image or "")
        return (HEALTHY, "Running", "", 0,
                pod.status.container_statuses[0].name if pod.status.container_statuses else "",
                pod.status.container_statuses[0].image if pod.status.container_statuses else "")

    if phase == "Pending":
        if pod.status.container_statuses:
            for cs in pod.status.container_statuses:
                waiting = cs.state.waiting if cs.state else None
                term_reason = ""
                if cs.last_state and cs.last_state.terminated and cs.last_state.terminated.reason:
                    term_reason = cs.last_state.terminated.reason
                if waiting and waiting.reason:
                    r = waiting.reason
                    if r in STUCK_REASONS:
                        return (STUCK, r, term_reason, cs.restart_count or 0, cs.name, cs.image or "")
                    if r in FAILING_REASONS:
                        return (FAILING, r, term_reason, cs.restart_count or 0, cs.name, cs.image or "")
                # Container may be terminated (e.g. OOMKilled) while pod is still Pending
                if cs.state and cs.state.terminated and cs.state.terminated.reason:
                    tr = cs.state.terminated.reason
                    if tr in FAILING_REASONS:
                        return (FAILING, tr, tr, cs.restart_count or 0, cs.name, cs.image or "")
                if term_reason and term_reason in FAILING_REASONS:
                    return (FAILING, term_reason, term_reason, cs.restart_count or 0, cs.name, cs.image or "")
        return (UNSCHEDULABLE, "Pending", "", 0,
                pod.spec.containers[0].name if pod.spec.containers else "",
                pod.spec.containers[0].image if pod.spec.containers else "")

    if phase in ("Failed", "Unknown"):
        if pod.status.container_statuses:
            cs = pod.status.container_statuses[0]
            terminated = cs.last_state.terminated if cs.last_state else None
            term_reason = (terminated.reason or "") if terminated else ""
            waiting = cs.state.waiting if cs.state else None
            wait_reason = (waiting.reason or "") if waiting else ""
            reason = wait_reason or term_reason or phase
            health = FAILING if reason in FAILING_REASONS else UNKNOWN
            return (health, reason, term_reason, cs.restart_count or 0,
                    cs.name, cs.image or "")
        return (UNKNOWN, phase, "", 0,
                pod.spec.containers[0].name if pod.spec.containers else "",
                pod.spec.containers[0].image if pod.spec.containers else "")

    # Unexpected phase
    return (UNKNOWN, phase, "", 0,
            pod.spec.containers[0].name if pod.spec.containers else "",
            pod.spec.containers[0].image if pod.spec.containers else "")


class Observer:
    """
    Observes Kubernetes pod state in a namespace.

    Attributes
    ----------
    core_v1:
        Kubernetes CoreV1Api client.
    namespace:
        Namespace to watch.
    """

    def __init__(self, core_v1: client.CoreV1Api, namespace: str = "default") -> None:
        self.core_v1   = core_v1
        self.namespace = namespace
        # Track when each pod first appeared in Pending state
        self._pending_since: Dict[str, float] = {}

    def observe_pods(self, label_selector: str = "") -> List[PodObservation]:
        """
        List all pods (filtered by label_selector) and classify their health.

        Parameters
        ----------
        label_selector:
            Optional Kubernetes label selector string (e.g. ``"app=web-frontend"``).
        """
        try:
            pods = self.core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=label_selector or None,
            )
        except ApiException as exc:
            raise RuntimeError(f"Failed to list pods: {exc.reason}") from exc

        observations: List[PodObservation] = []
        for pod in pods.items:
            health, status_reason, term_reason, restart_count, container_name, image = (
                _classify_pod(pod)
            )
            phase = (pod.status.phase or "Unknown") if pod.status else "Unknown"

            # Track pending time
            pod_name = pod.metadata.name
            if phase == "Pending":
                if pod_name not in self._pending_since:
                    self._pending_since[pod_name] = time.time()
            else:
                self._pending_since.pop(pod_name, None)

            obs = PodObservation(
                pod=pod,
                health=health,
                status_reason=status_reason,
                terminated_reason=term_reason,
                restart_count=restart_count,
                container_name=container_name,
                image=image,
                pod_phase=phase,
                first_seen_pending=self._pending_since.get(pod_name),
            )
            observations.append(obs)

        return observations

    def wait_for_failure(
        self,
        deployment_name: str,
        expected_reasons: List[str],
        timeout: int = 120,
        poll_interval: int = 3,
    ) -> Optional[PodObservation]:
        """
        Poll until a pod matching *deployment_name* enters one of the expected
        failure states, or until *timeout* seconds have elapsed.

        Returns the failing PodObservation, or None on timeout.
        """
        print_waiting(f"Waiting for failure state ({', '.join(expected_reasons)})...")
        deadline = time.time() + timeout
        label_sel = f"app={deployment_name}"

        while time.time() < deadline:
            try:
                observations = self.observe_pods(label_selector=label_sel)
            except RuntimeError:
                time.sleep(poll_interval)
                continue

            for obs in observations:
                # Match on status_reason (e.g. CrashLoopBackOff) or
                # terminated_reason (e.g. OOMKilled) for early detection
                matched_reason = ""
                if obs.status_reason in expected_reasons:
                    matched_reason = obs.status_reason
                elif obs.terminated_reason in expected_reasons:
                    matched_reason = obs.terminated_reason

                if matched_reason:
                    print_detect(
                        f"DETECTED: Pod {obs.name}"
                    )
                    print_info(f"Status: {matched_reason}")
                    if obs.terminated_reason and obs.terminated_reason != matched_reason:
                        print_info(f"Terminated reason: {obs.terminated_reason}")
                    if obs.pod.status and obs.pod.status.container_statuses:
                        cs = obs.pod.status.container_statuses[0]
                        waiting = cs.state.waiting if cs.state else None
                        if waiting and waiting.message:
                            print_info(f"Message: {waiting.message}")
                    return obs

            time.sleep(poll_interval)

        return None

    def wait_for_pending(
        self,
        deployment_name: str,
        min_seconds: int = 10,
        timeout: int = 120,
        poll_interval: int = 3,
    ) -> Optional[PodObservation]:
        """
        Poll until a pod is in Pending state for at least *min_seconds*.
        """
        print_waiting(f"Waiting for pod to enter Pending state...")
        deadline = time.time() + timeout
        label_sel = f"app={deployment_name}"

        while time.time() < deadline:
            try:
                observations = self.observe_pods(label_selector=label_sel)
            except RuntimeError:
                time.sleep(poll_interval)
                continue

            for obs in observations:
                if obs.pod_phase == "Pending":
                    pending_secs = obs.pending_seconds
                    if pending_secs >= min_seconds:
                        print_detect(f"DETECTED: Pod {obs.name} stuck in Pending")
                        print_info(f"Pending for: {pending_secs:.0f}s")
                        return obs

            time.sleep(poll_interval)

        return None

    def print_observation(self, obs: PodObservation) -> None:
        """Pretty-print a PodObservation in OBSERVE phase format."""
        print_phase("OBSERVE", "🔍", f"Pod {_c(Color.YELLOW, obs.name)}")
        print_info(f"Status:        {obs.status_reason}")
        print_info(f"Container:     {obs.container_name}")
        print_info(f"Image:         {obs.image}")
        print_info(f"Restarts:      {obs.restart_count}")
        print_info(f"Phase:         {obs.pod_phase}")
        if obs.terminated_reason:
            print_info(f"Last reason:   {obs.terminated_reason}")
