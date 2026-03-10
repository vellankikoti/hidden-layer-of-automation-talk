# hidden-layer-of-automation-talk

**"The Hidden Layer of Automation"** — AI DevCon India 2026

This repository contains the live demo system for the conference talk.

## 🤖 K8s Healing Agent

The main demo project is located in [`k8s-healing-agent/`](./k8s-healing-agent/).

It is a production-grade, autonomous Kubernetes healing agent that detects
real-world pod failures and fixes them in seconds — with zero human intervention.

See the **[k8s-healing-agent README](./k8s-healing-agent/README.md)** for full
documentation, quick-start instructions, and a description of all 5 demo scenarios.

```bash
cd k8s-healing-agent
pip install kubernetes
python3 demo.py
```