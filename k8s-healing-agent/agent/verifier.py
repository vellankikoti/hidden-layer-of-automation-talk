"""
K8s Healing Agent — Verifier Module

VERIFY phase of the Agent Loop.

Polls the cluster until the target pod is Running and Ready (or until a
timeout expires), then reports the outcome.
"""

import time
from typing import Optional

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from agent.display import (
    print_phase, print_info, print_success, print_error,
    print_waiting, Color, _c
)
from agent.executor import ExecutionResult


class VerificationResult:
    """Outcome of the VERIFY phase."""

    def __init__(
        self,
        success: bool,
        pod_name: str,
        message: str,
        elapsed: float,
    ) -> None:
        self.success  = success
        self.pod_name = pod_name
        self.message  = message
        self.elapsed  = elapsed

    def __repr__(self) -> str:
        return (
            f"VerificationResult(success={self.success}, "
            f"pod={self.pod_name!r}, elapsed={self.elapsed:.1f}s)"
        )


class Verifier:
    """
    Polls pod state after a fix has been applied and confirms health.

    Attributes
    ----------
    core_v1:
        Kubernetes CoreV1Api client.
    namespace:
        Target namespace.
    """

    def __init__(
        self,
        core_v1: client.CoreV1Api,
        namespace: str = "default",
    ) -> None:
        self.core_v1   = core_v1
        self.namespace = namespace

    def verify(
        self,
        deployment_name: str,
        exec_result: ExecutionResult,
        timeout: int = 120,
        poll_interval: int = 3,
    ) -> VerificationResult:
        """
        Wait for a pod belonging to *deployment_name* to become Running and Ready.

        Parameters
        ----------
        deployment_name:
            Name of the Kubernetes Deployment to monitor.
        exec_result:
            The result from the Executor (used to short-circuit if the fix failed).
        timeout:
            Maximum seconds to wait for the pod to become healthy.
        poll_interval:
            Seconds between status checks.
        """
        time.sleep(1)
        print_phase("VERIFY", "✅", "Checking pod status...")

        if not exec_result.success:
            msg = "Skipping verification — fix was not applied successfully"
            print_error(msg)
            return VerificationResult(
                success=False,
                pod_name="",
                message=msg,
                elapsed=0.0,
            )

        start    = time.time()
        deadline = start + timeout
        label_sel = f"app={deployment_name}"

        print_waiting(f"Waiting for deployment/{deployment_name} to be healthy...")

        while time.time() < deadline:
            pods = self._list_pods(label_sel)
            for pod in pods:
                name  = pod.metadata.name
                phase = (pod.status.phase or "") if pod.status else ""

                if phase != "Running":
                    continue

                # Ensure all containers are Ready
                statuses = (pod.status.container_statuses or []) if pod.status else []
                if not statuses:
                    continue

                all_ready = all(cs.ready for cs in statuses)
                if all_ready:
                    elapsed = time.time() - start
                    ready_count = f"{len(statuses)}/{len(statuses)}"
                    print_success(f"Pod is healthy!")
                    print_info(f"New pod:           {name}")
                    print_info(f"Status:            Running ✅")
                    print_info(f"Ready:             True ✅")
                    print_info(f"Containers Ready:  {ready_count}")
                    return VerificationResult(
                        success=True,
                        pod_name=name,
                        message="Pod is Running and Ready",
                        elapsed=elapsed,
                    )

            time.sleep(poll_interval)

        elapsed = time.time() - start
        msg = f"Pod did not become Ready within {timeout}s"
        print_error(msg)
        return VerificationResult(
            success=False,
            pod_name="",
            message=msg,
            elapsed=elapsed,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _list_pods(self, label_selector: str):
        """Return a list of pod objects matching the label selector."""
        try:
            result = self.core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=label_selector,
            )
            return result.items
        except ApiException:
            return []
