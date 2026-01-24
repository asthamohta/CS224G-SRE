# Online Boutique Deployment

This directory contains the Kubernetes and Istio manifests and scripts used to deploy the Online Boutique sample application.

## Prerequisites
- A running Kubernetes cluster
- `kubectl` configured to point to the cluster
- Istio / Service Mesh installed on the cluster (if you want sidecar injection and Istio resources) 

## Directory layout
- `deploy/`
  - `kubernetes-manifests/`: namespaces, deployments, services
  - `istio-manifests/`: Istio resources 
  - `frontend-external.yaml`
- `scripts/`: one-command deploy and cleanup

## Deploy
From the repo root:

```bash
chmod +x online_boutique/scripts/*.sh
./online_boutique/scripts/deploy.sh
