# Azure Staging Terraform

This directory recreates the Azure side of the SME Back-Office staging
environment. It intentionally does not create Neon, Upstash, Vercel, or any
document data. Terraform owns Azure infrastructure; GitHub Actions owns image
builds and later rollouts.

## What it creates

- resource group, Log Analytics workspace, Container Apps environment
- Azure Container Registry
- private Azure Blob Storage `documents` container
- Azure Document Intelligence (`FormRecognizer`, S0)
- runtime managed identity with Blob access and ACR image pull access
- GitHub Actions user-assigned identity, OIDC federation for `main`, and scoped
  Contributor/ACR writer roles
- optional API, Celery worker, and outbox dispatcher Container Apps

No populated `.tfvars`, Terraform state, database URL, Upstash URL, or API key
is committed.

## Prerequisites

Install Terraform 1.8+ and sign in to the target subscription:

```bash
brew tap hashicorp/tap
brew install hashicorp/tap/terraform
az login
az account set --subscription "Azure subscription 1"
```

Create a local input file:

```bash
cd /Users/quangkimle/Documents/code/SME_Back_Office/sme-backoffice-copilot/infra/terraform
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform fmt -check
terraform validate
```

## Phase 1: Azure foundation

Set a **new** `resource_group_name` in `terraform.tfvars`, keep
`enable_container_apps = false`, then review and apply:

```bash
terraform plan -out foundation.tfplan
terraform apply foundation.tfplan
```

Do not run this against the current manually created staging resources unless
you first import them. Terraform otherwise correctly treats same-named Azure
resources as a conflict.

Capture the outputs:

```bash
terraform output
```

Use `github_actions_client_id` as GitHub Actions `AZURE_CLIENT_ID`. The tenant
and subscription IDs remain the existing repository secrets.

## Phase 2: Bootstrap the application image

The Azure Container Apps need one real backend image before Terraform can
create the runtime. ACR Tasks is disabled on this subscription, so use local
Docker for this one bootstrap push:

```bash
ACR_NAME="$(terraform output -raw acr_login_server | cut -d. -f1)"
ACR_LOGIN_SERVER="$(terraform output -raw acr_login_server)"

az acr login --name "$ACR_NAME"
docker build -t "$ACR_LOGIN_SERVER/sme-backoffice-api:bootstrap" ../../backend
docker push "$ACR_LOGIN_SERVER/sme-backoffice-api:bootstrap"
```

## Phase 3: Create the runtime

Set `enable_container_apps = true` and the five runtime variables in the local
`terraform.tfvars`. Then apply:

```bash
terraform plan -out runtime.tfplan
terraform apply runtime.tfplan
```

The three apps share the same image but start different commands:

- API: Dockerfile default Uvicorn command, public ingress on port 8000
- worker: Celery queues `high`, `medium`, and `low`
- dispatcher: `python -m app.workers.outbox_dispatcher`

The worker and dispatcher stay at one replica because the present design uses
Redis/Celery and a database-polling dispatcher. KEDA/Service Bus is a later
optimization, not silently assumed by this blueprint.

## After recreation

1. Put the new `github_actions_client_id` in GitHub Actions `AZURE_CLIENT_ID`.
2. Update `ACR_LOGIN_SERVER`, `AZURE_RESOURCE_GROUP`, and the three Container
   App names in repository variables or the deployment workflow if names differ.
3. Commit to `main`; the existing deploy workflow builds a SHA-tagged image and
   rolls it out to API, worker, and dispatcher.
4. Run Alembic migrations against the recreated Neon database before sending
   uploads.
5. Verify the API health endpoint using `terraform output -raw api_url`.

## State handling

The runtime configuration contains sensitive values, so a local state file is
appropriate only for a personal staging demo. For team or production use,
migrate the state to a protected Azure Storage backend and grant access through
Azure RBAC. Never commit `terraform.tfvars` or any `.tfstate` file.

## Destroying a demo environment

Review the plan carefully before running this destructive command:

```bash
terraform destroy
```

It removes only resources managed by this Terraform state, including the Blob
Storage account and the private uploaded files stored in it.
