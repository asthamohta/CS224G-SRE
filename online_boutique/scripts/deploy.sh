#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../deploy"

kubectl apply -f kubernetes-manifests/namespaces
kubectl apply -f kubernetes-manifests/deployments
kubectl apply -f kubernetes-manifests/services
kubectl apply -f istio-manifests/allow-egress-googleapis.yaml

for ns in ad cart checkout currency email frontend loadgenerator \
    payment product-catalog recommendation shipping; do
        kubectl label namespace "$ns" istio-injection=enabled --overwrite
done

for ns in ad cart checkout currency email frontend loadgenerator \
    payment product-catalog recommendation shipping; do
        kubectl rollout restart deployment -n "$ns"
done

for ns in ad cart checkout currency email frontend loadgenerator \
    payment product-catalog recommendation shipping; do
        kubectl rollout restart deployment -n ${ns}
done