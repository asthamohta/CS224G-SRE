#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../deploy"

kubectl delete -f kubernetes-manifests/namespaces
kubectl delete -f istio-manifests/allow-egress-googleapis.yaml
