"""
K8s Healing Agent — Executor Module

EXECUTE phase of the Agent Loop.

Applies Kubernetes patches and creates resources based on the ActionPlan.
All operations use the official kubernetes-python client; no subprocess
calls to kubectl are made for core fixes.
"""

import time
from typing import Any, Dict, Optional

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from agent.display import (
    print_phase, print_info, print_success, print_error, Color, _c
)
from agent.planner import ActionPlan


class ExecutionResult:
    """Outcome of the EXECUTE phase."""

    def __init__(
        self,
        success: bool,
        action_type: str,
        message: str,
        detail: Optional[str] = None,
    ) -> None:
        self.success     = success
        self.action_type = action_type
        self.message     = message
        self.detail      = detail

    def __repr__(self) -> str:
        return (
            f"ExecutionResult(success={self.success}, "
            f"action_type={self.action_type!r}, message={self.message!r})"
        )


class Executor:
    """
    Applies the remediation described in an ActionPlan.

    Attributes
    ----------
    core_v1:
        Kubernetes CoreV1Api client.
    apps_v1:
        Kubernetes AppsV1Api client.
    namespace:
        Target namespace.
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

    def execute(self, plan: ActionPlan) -> ExecutionResult:
        """
        Dispatch to the appropriate fix method based on plan.action_type.
        """
        time.sleep(1)
        print_phase("EXECUTE", "🔧", f"Applying fix: {plan.description}")

        dispatch = {
            "PATCH_DEPLOYMENT_IMAGE":          self._fix_image_tag,
            "PATCH_DEPLOYMENT_LIVENESS_PROBE": self._fix_liveness_probe,
            "PATCH_DEPLOYMENT_MEMORY":         self._fix_memory_limit,
            "CREATE_CONFIGMAP":                self._fix_create_configmap,
            "PATCH_DEPLOYMENT_CPU":            self._fix_cpu_request,
        }

        handler = dispatch.get(plan.action_type)
        if handler is None:
            msg = f"Unknown action type: {plan.action_type}"
            print_error(msg)
            return ExecutionResult(success=False, action_type=plan.action_type, message=msg)

        try:
            return handler(plan)
        except ApiException as exc:
            msg = f"Kubernetes API error: {exc.reason} (HTTP {exc.status})"
            print_error(msg)
            return ExecutionResult(success=False, action_type=plan.action_type, message=msg)
        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error during execution: {exc}"
            print_error(msg)
            return ExecutionResult(success=False, action_type=plan.action_type, message=msg)

    # ── Fix implementations ────────────────────────────────────────────────────

    def _fix_image_tag(self, plan: ActionPlan) -> ExecutionResult:
        """Patch the deployment to use a known-good image tag."""
        new_image   = plan.params["new_image"]
        container   = plan.context.get("container_name", "")
        deployment  = plan.deployment_name

        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {"name": container, "image": new_image}
                        ]
                    }
                }
            }
        }

        print_info(f"Patching deployment/{deployment}")
        print_info(f"Container: {container}")
        print_info(f"New image: {new_image}")

        self.apps_v1.patch_namespaced_deployment(
            name=deployment,
            namespace=self.namespace,
            body=patch,
        )

        print_success(f"Deployment patched successfully → {new_image}")
        return ExecutionResult(
            success=True,
            action_type=plan.action_type,
            message=f"Patched image to {new_image}",
        )

    def _fix_liveness_probe(self, plan: ActionPlan) -> ExecutionResult:
        """Patch the liveness probe path in the deployment."""
        new_path   = plan.params["new_probe_path"]
        container  = plan.context.get("container_name", "")
        deployment = plan.deployment_name

        # Read the current deployment to preserve probe settings
        current = self.apps_v1.read_namespaced_deployment(
            name=deployment, namespace=self.namespace
        )
        ctr_patch = None
        for ctr in current.spec.template.spec.containers:
            if ctr.name == container:
                if ctr.liveness_probe and ctr.liveness_probe.http_get:
                    ctr.liveness_probe.http_get.path = new_path
                    ctr_patch = ctr
                break

        if ctr_patch is None:
            # Build a minimal patch if we can't find the container
            patch = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "name": container,
                                    "livenessProbe": {
                                        "httpGet": {"path": new_path, "port": 80}
                                    },
                                }
                            ]
                        }
                    }
                }
            }
        else:
            patch = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "name": container,
                                    "livenessProbe": {
                                        "httpGet": {
                                            "path": new_path,
                                            "port": ctr_patch.liveness_probe.http_get.port,
                                        },
                                        "initialDelaySeconds": (
                                            ctr_patch.liveness_probe.initial_delay_seconds or 5
                                        ),
                                        "periodSeconds": (
                                            ctr_patch.liveness_probe.period_seconds or 10
                                        ),
                                        "failureThreshold": (
                                            ctr_patch.liveness_probe.failure_threshold or 3
                                        ),
                                    },
                                }
                            ]
                        }
                    }
                }
            }

        print_info(f"Patching deployment/{deployment}")
        print_info(f"Container:       {container}")
        print_info(f"New probe path:  {new_path}")

        self.apps_v1.patch_namespaced_deployment(
            name=deployment,
            namespace=self.namespace,
            body=patch,
        )

        print_success(f"Liveness probe patched → {new_path}")
        return ExecutionResult(
            success=True,
            action_type=plan.action_type,
            message=f"Patched liveness probe path to {new_path}",
        )

    def _fix_memory_limit(self, plan: ActionPlan) -> ExecutionResult:
        """Increase the memory limit in the deployment."""
        new_limit   = plan.params["new_memory_limit"]
        new_request = plan.params["new_memory_request"]
        container   = plan.context.get("container_name", "")
        deployment  = plan.deployment_name

        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": container,
                                "resources": {
                                    "limits":   {"memory": new_limit},
                                    "requests": {"memory": new_request},
                                },
                            }
                        ]
                    }
                }
            }
        }

        print_info(f"Patching deployment/{deployment}")
        print_info(f"Container:      {container}")
        print_info(f"Memory limit:   {plan.context.get('memory_limit', '?')} → {new_limit}")
        print_info(f"Memory request: → {new_request}")

        self.apps_v1.patch_namespaced_deployment(
            name=deployment,
            namespace=self.namespace,
            body=patch,
        )

        print_success(f"Memory limit increased → {new_limit}")
        return ExecutionResult(
            success=True,
            action_type=plan.action_type,
            message=f"Memory limit increased to {new_limit}",
        )

    def _fix_create_configmap(self, plan: ActionPlan) -> ExecutionResult:
        """Create the missing ConfigMap with default data."""
        cm_name  = plan.params["configmap_name"]
        cm_data  = plan.params.get("default_data", {})

        print_info(f"Creating ConfigMap/{cm_name}")
        for k, v in cm_data.items():
            print_info(f"  {k} = {v}")

        # Check if it already exists (idempotent)
        try:
            self.core_v1.read_namespaced_config_map(
                name=cm_name, namespace=self.namespace
            )
            print_success(f"ConfigMap/{cm_name} already exists — skipping creation")
            return ExecutionResult(
                success=True,
                action_type=plan.action_type,
                message=f"ConfigMap {cm_name} already existed",
            )
        except ApiException as exc:
            if exc.status != 404:
                raise

        body = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(
                name=cm_name,
                namespace=self.namespace,
                labels={
                    "demo":     "k8s-healing-agent",
                    "scenario": "4",
                },
            ),
            data=cm_data,
        )

        self.core_v1.create_namespaced_config_map(
            namespace=self.namespace, body=body
        )

        print_success(f"ConfigMap/{cm_name} created")
        return ExecutionResult(
            success=True,
            action_type=plan.action_type,
            message=f"ConfigMap {cm_name} created",
        )

    def _fix_cpu_request(self, plan: ActionPlan) -> ExecutionResult:
        """Reduce the CPU request to a schedulable value."""
        new_request = plan.params["new_cpu_request"]
        new_limit   = plan.params["new_cpu_limit"]
        container   = plan.context.get("container_name", "")
        deployment  = plan.deployment_name

        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": container,
                                "resources": {
                                    "limits":   {"cpu": new_limit},
                                    "requests": {"cpu": new_request},
                                },
                            }
                        ]
                    }
                }
            }
        }

        print_info(f"Patching deployment/{deployment}")
        print_info(f"Container:   {container}")
        print_info(f"CPU request: {plan.context.get('cpu_request', '?')} → {new_request}")
        print_info(f"CPU limit:   → {new_limit}")

        self.apps_v1.patch_namespaced_deployment(
            name=deployment,
            namespace=self.namespace,
            body=patch,
        )

        print_success(f"CPU request reduced → {new_request}")
        return ExecutionResult(
            success=True,
            action_type=plan.action_type,
            message=f"CPU request reduced to {new_request}",
        )
