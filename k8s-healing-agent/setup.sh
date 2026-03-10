#!/usr/bin/env bash
# K8s Healing Agent — One-command setup script
# Usage: ./setup.sh [--namespace <ns>]
set -euo pipefail

NAMESPACE="${NAMESPACE:-default}"

echo "🔧 K8s Healing Agent — Setup"
echo "================================"
echo ""

# ── Check Python version ───────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "❌ python3 not found. Please install Python 3.9+."
    exit 1
fi

PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYMAJ=$(python3 -c "import sys; print(sys.version_info.major)")
PYMIN=$(python3 -c "import sys; print(sys.version_info.minor)")

echo "✅ Python ${PYVER} detected"

if [ "${PYMAJ}" -lt 3 ] || { [ "${PYMAJ}" -eq 3 ] && [ "${PYMIN}" -lt 9 ]; }; then
    echo "❌ Python 3.9+ required (found ${PYVER})"
    exit 1
fi

# ── Install Python dependencies ────────────────────────────────────────────────
echo ""
echo "📦 Installing Python dependencies..."
pip3 install -r requirements.txt --quiet
echo "✅ Dependencies installed"

# ── Check kubectl ──────────────────────────────────────────────────────────────
echo ""
if ! command -v kubectl &>/dev/null; then
    echo "❌ kubectl not found. Install kubectl and connect it to a cluster."
    exit 1
fi

echo "✅ kubectl found: $(kubectl version --client --short 2>/dev/null || echo 'version unknown')"

# ── Check cluster connectivity ─────────────────────────────────────────────────
echo ""
echo "🔗 Checking cluster connectivity..."
if ! kubectl cluster-info &>/dev/null; then
    echo "❌ kubectl is not connected to a cluster."
    echo "   Run 'kubectl cluster-info' to diagnose."
    exit 1
fi

CONTEXT=$(kubectl config current-context 2>/dev/null || echo "unknown")
NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l | tr -d ' ')

echo "✅ Cluster connected"
echo "   Context: ${CONTEXT}"
echo "   Nodes:   ${NODE_COUNT}"

# ── Print next steps ───────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅ Setup complete!                                          ║"
echo "║                                                              ║"
echo "║  Run the demo:  python3 demo.py                             ║"
echo "║  Pre-flight:    python3 demo.py --preflight                 ║"
echo "║  Cleanup:       ./cleanup.sh                                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
