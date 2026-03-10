#!/usr/bin/env bash
# K8s Healing Agent — Cleanup script
# Removes all demo resources from the cluster.
# Usage: ./cleanup.sh [--namespace <ns>]

NAMESPACE="${NAMESPACE:-default}"

# Allow --namespace flag
while [[ $# -gt 0 ]]; do
    case "$1" in
        --namespace|-n)
            NAMESPACE="$2"; shift 2;;
        *)
            shift;;
    esac
done

echo "🧹 Cleaning up K8s Healing Agent demo resources..."
echo "   Namespace: ${NAMESPACE}"
echo ""

# Delete demo deployments
kubectl delete deployment \
    web-frontend api-server data-processor config-service ml-worker \
    -n "${NAMESPACE}" --ignore-not-found --timeout=60s 2>/dev/null || true

# Delete demo ConfigMaps
kubectl delete configmap app-config \
    -n "${NAMESPACE}" --ignore-not-found 2>/dev/null || true

# Belt-and-suspenders: delete everything with the demo label
kubectl delete all -l demo=k8s-healing-agent \
    -n "${NAMESPACE}" --ignore-not-found --timeout=60s 2>/dev/null || true
kubectl delete configmap -l demo=k8s-healing-agent \
    -n "${NAMESPACE}" --ignore-not-found 2>/dev/null || true

echo ""
echo "✅ Cleanup complete — namespace '${NAMESPACE}' is clean."
