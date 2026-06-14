#!/usr/bin/env bash
# One-shot Azure deploy: build → push to ACR → provision Container App via bicep.
# Prereqs: az CLI logged in (az login), an Azure subscription, an Azure OpenAI resource.
set -euo pipefail

RG="${RG:-alpha-advisor-rg}"
LOC="${LOC:-eastus}"
ACR="${ACR:-alphaadvisoracr$RANDOM}"
IMAGE_TAG="alpha-advisor:$(git rev-parse --short HEAD 2>/dev/null || echo latest)"

: "${AZURE_OPENAI_ENDPOINT:?set AZURE_OPENAI_ENDPOINT}"
: "${AZURE_OPENAI_API_KEY:?set AZURE_OPENAI_API_KEY}"
CHECKPOINT_DB="${ALPHA_CHECKPOINT_DB:-}"   # optional postgres conn string

echo "→ resource group"
az group create -n "$RG" -l "$LOC" -o none

echo "→ container registry"
az acr create -g "$RG" -n "$ACR" --sku Basic --admin-enabled true -o none

echo "→ build & push image (ACR build — no local Docker needed)"
az acr build -r "$ACR" -t "$IMAGE_TAG" .

echo "→ deploy container app"
az deployment group create -g "$RG" -f deploy/main.bicep -o table \
  -p image="$ACR.azurecr.io/$IMAGE_TAG" \
     azureOpenAiEndpoint="$AZURE_OPENAI_ENDPOINT" \
     azureOpenAiKey="$AZURE_OPENAI_API_KEY" \
     checkpointDb="$CHECKPOINT_DB"

echo "✓ done — see the 'url' output above; GET <url>/api/health"
