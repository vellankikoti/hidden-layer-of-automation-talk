"""
K8s Healing Agent — Planner Module

PLAN phase of the Agent Loop.

Takes a Diagnosis and produces an ActionPlan: the concrete Kubernetes
operation(s) to perform, with a risk assessment and human-readable
description.
"""

import time
from typing import Any, Dict, Optional

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from agent.display import print_phase, print_info, Color, _c
from agent.reasoner import Diagnosis


class ActionPlan:
    """Describes the remediation action to be carried out by the Executor."""

    def __init__(
        self,
        action_type: str,
        description: str,
        risk: str,
        params: Dict[str, Any],
        deployment_name: str,
        namespace: str,
        context: Dict[str, Any],
    ) -> None:
        self.action_type     = action_type
        self.description     = description
        self.risk            = risk
        self.params          = params
        self.deployment_name = deployment_name
        self.namespace       = namespace
        self.context         = context

    def __repr__(self) -> str:
        return (
            f"ActionPlan(action_type={self.action_type!r}, "
            f"deployment={self.deployment_name!r}, risk={self.risk!r})"
        )


class Planner:
    """
    Generates an ActionPlan from a Diagnosis.

    Attributes
    ----------
    core_v1:
        Kubernetes CoreV1Api client (used to query node capacity for Scenario 5).
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

    def plan(self, diag: Diagnosis) -> Optional[ActionPlan]:
        """
        Produce an ActionPlan for the given Diagnosis.

        Returns None if the fix type is unrecognised.
        """
        time.sleep(1)
        fix        = diag.runbook_entry["fix"]
        action     = fix["action"]
        params     = dict(fix["params"])  # copy so we can augment
        context    = diag.context
        deployment = context.get("deployment_name", "unknown")

        plan: Optional[ActionPlan] = None

        if action == "patch_image_tag":
            plan = self._plan_image_tag(fix, params, context, deployment)

        elif action == "patch_liveness_probe":
            plan = self._plan_liveness_probe(fix, params, context, deployment)

        elif action == "patch_memory_limit":
            plan = self._plan_memory(fix, params, context, deployment)

        elif action == "create_configmap":
            plan = self._plan_configmap(fix, params, context, deployment)

        elif action == "patch_cpu_request":
            plan = self._plan_cpu(fix, params, context, deployment)

        if plan:
            self._print_plan(plan, context)

        return plan

    # ── Private planning helpers ──────────────────────────────────────────────

    def _plan_image_tag(
        self,
        fix: Dict[str, Any],
        params: Dict[str, Any],
        context: Dict[str, Any],
        deployment: str,
    ) -> ActionPlan:
        """Determine the correct image to fall back to."""
        image_name = context.get("image_name", "nginx")
        image_map  = params.get("image_map", {})

        # Find a matching base image (e.g. "nginx" in "my-registry/nginx")
        good_image = None
        for base, good in image_map.items():
            if base in image_name:
                good_image = good
                break

        if not good_image:
            good_image = f"{image_name}:latest"

        params["new_image"] = good_image
        return ActionPlan(
            action_type     = fix["type"],
            description     = fix["description"],
            risk            = fix["risk"],
            params          = params,
            deployment_name = deployment,
            namespace       = self.namespace,
            context         = context,
        )

    def _plan_liveness_probe(
        self,
        fix: Dict[str, Any],
        params: Dict[str, Any],
        context: Dict[str, Any],
        deployment: str,
    ) -> ActionPlan:
        """Determine the correct liveness probe path."""
        image_name     = context.get("image_name", "nginx")
        probe_defaults = params.get("image_probe_defaults", {})
        default_path   = params.get("default_path", "/")

        new_path = default_path
        for base, path in probe_defaults.items():
            if base in image_name.lower():
                new_path = path
                break

        params["new_probe_path"] = new_path
        return ActionPlan(
            action_type     = fix["type"],
            description     = fix["description"],
            risk            = fix["risk"],
            params          = params,
            deployment_name = deployment,
            namespace       = self.namespace,
            context         = context,
        )

    def _plan_memory(
        self,
        fix: Dict[str, Any],
        params: Dict[str, Any],
        context: Dict[str, Any],
        deployment: str,
    ) -> ActionPlan:
        """Calculate new memory limit."""
        current_limit = context.get("memory_limit", "32Mi")
        new_limit     = _multiply_memory(current_limit, params.get("multiplier", 4))
        minimum       = params.get("minimum_limit", "128Mi")

        # Use the larger of (multiplied) and (minimum)
        if _parse_mi(new_limit) < _parse_mi(minimum):
            new_limit = minimum

        params["new_memory_limit"]   = new_limit
        params["new_memory_request"] = params.get("minimum_request", "64Mi")
        return ActionPlan(
            action_type     = fix["type"],
            description     = fix["description"],
            risk            = fix["risk"],
            params          = params,
            deployment_name = deployment,
            namespace       = self.namespace,
            context         = context,
        )

    def _plan_configmap(
        self,
        fix: Dict[str, Any],
        params: Dict[str, Any],
        context: Dict[str, Any],
        deployment: str,
    ) -> ActionPlan:
        """Plan ConfigMap creation."""
        params["configmap_name"] = context.get("configmap_name", "app-config")
        return ActionPlan(
            action_type     = fix["type"],
            description     = fix["description"],
            risk            = fix["risk"],
            params          = params,
            deployment_name = deployment,
            namespace       = self.namespace,
            context         = context,
        )

    def _plan_cpu(
        self,
        fix: Dict[str, Any],
        params: Dict[str, Any],
        context: Dict[str, Any],
        deployment: str,
    ) -> ActionPlan:
        """Right-size CPU request based on real node capacity."""
        node_max_cpu = self._get_max_node_cpu()
        if node_max_cpu:
            # Use half the node's allocatable CPU as a safe request
            cores         = _parse_cpu_cores(node_max_cpu)
            safe_request  = max(0.5, cores * 0.25)
            safe_limit    = max(1.0, cores * 0.5)
            params["new_cpu_request"] = f"{int(safe_request * 1000)}m"
            params["new_cpu_limit"]   = f"{int(safe_limit * 1000)}m"
        else:
            params["new_cpu_request"] = params.get("target_cpu_request", "500m")
            params["new_cpu_limit"]   = params.get("target_cpu_limit", "1000m")

        return ActionPlan(
            action_type     = fix["type"],
            description     = fix["description"],
            risk            = fix["risk"],
            params          = params,
            deployment_name = deployment,
            namespace       = self.namespace,
            context         = context,
        )

    def _get_max_node_cpu(self) -> Optional[str]:
        """Return the allocatable CPU of the node with the most CPU."""
        try:
            nodes = self.core_v1.list_node()
            max_cpu = ""
            max_cores = 0.0
            for node in nodes.items:
                allocatable = node.status.allocatable if node.status else {}
                cpu = allocatable.get("cpu", "0")
                cores = _parse_cpu_cores(cpu)
                if cores > max_cores:
                    max_cores = cores
                    max_cpu   = cpu
            return max_cpu or None
        except ApiException:
            return None

    def _print_plan(self, plan: ActionPlan, context: Dict[str, Any]) -> None:
        """Print the PLAN phase output."""
        print_phase("PLAN", "📝", "Remediation strategy:")
        print_info(f"→ Action:  {plan.description}")
        print_info(f"  Risk:    {plan.risk}")

        if plan.action_type == "PATCH_DEPLOYMENT_IMAGE":
            print_info(f"  From:    {context.get('image', '?')}")
            print_info(f"  To:      {plan.params.get('new_image', '?')}")

        elif plan.action_type == "PATCH_DEPLOYMENT_LIVENESS_PROBE":
            print_info(f"  From:    {context.get('probe_path', '?')}")
            print_info(f"  To:      {plan.params.get('new_probe_path', '?')}")

        elif plan.action_type == "PATCH_DEPLOYMENT_MEMORY":
            print_info(f"  From:    {context.get('memory_limit', '?')}")
            print_info(f"  To:      {plan.params.get('new_memory_limit', '?')}")

        elif plan.action_type == "CREATE_CONFIGMAP":
            print_info(f"  Name:    {plan.params.get('configmap_name', '?')}")
            data = plan.params.get("default_data", {})
            for k, v in data.items():
                print_info(f"           {k}={v}")

        elif plan.action_type == "PATCH_DEPLOYMENT_CPU":
            print_info(f"  From:    {context.get('cpu_request', '?')}")
            print_info(f"  To:      {plan.params.get('new_cpu_request', '?')}")


# ── Utility functions ─────────────────────────────────────────────────────────

def _parse_mi(value: str) -> int:
    """Convert a Kubernetes memory string (e.g. '128Mi') to mebibytes (int)."""
    value = value.strip()
    if value.endswith("Mi"):
        return int(value[:-2])
    if value.endswith("Gi"):
        return int(float(value[:-2]) * 1024)
    if value.endswith("Ki"):
        return max(1, int(value[:-2]) // 1024)
    if value.endswith("M"):
        return int(float(value[:-1]) * 1000 // (1024 * 1024) + 1)
    try:
        return int(value) // (1024 * 1024) or 1
    except ValueError:
        return 64  # safe default


def _multiply_memory(value: str, multiplier: int) -> str:
    """Multiply a memory string by multiplier and return Mi string."""
    mi = _parse_mi(value)
    return f"{mi * multiplier}Mi"


def _parse_cpu_cores(value: str) -> float:
    """Convert a Kubernetes CPU string to a float representing cores."""
    value = str(value).strip()
    if value.endswith("m"):
        return float(value[:-1]) / 1000
    try:
        return float(value)
    except ValueError:
        return 1.0
