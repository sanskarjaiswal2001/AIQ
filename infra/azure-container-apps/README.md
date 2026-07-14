# AIQ on Azure Container Apps

Minimal Terraform for one AIQ mothership on Azure Container Apps.

What it creates:
- Resource group
- Log Analytics workspace
- Azure Container Registry (ACR)
- Azure Storage Account + Azure Files share mounted at `/data`
- Azure Container Apps environment
- One Container App with HTTPS ingress and `max_replicas = 1`

Why `max_replicas = 1`: current AIQ uses SQLite at `/data/aiq.db`. Azure Files makes it persistent, but SQLite is not a multi-writer enterprise DB. Move to Azure Postgres before scaling replicas.

## Deploy

```bash
az login
az account set --subscription "<subscription>"

cd infra/azure-container-apps
terraform init
terraform apply
```

Terraform first boots the app with a public placeholder image so the ACR can exist before the AIQ image is built.

Build AIQ into the created ACR and switch the app to it:

```bash
ACR=$(terraform output -raw acr_name)
RG=$(terraform output -raw resource_group_name)
APP=$(terraform output -raw container_app_name)
IMAGE=$(terraform output -raw aiq_image)

cd ../..
az acr build -r "$ACR" -t aiq:latest .
az containerapp update -g "$RG" -n "$APP" --image "$IMAGE"
```

Get the URL and admin key:

```bash
URL=$(terraform -chdir=infra/azure-container-apps output -raw container_app_url)
ADMIN_KEY=$(terraform -chdir=infra/azure-container-apps output -raw aiq_admin_key)

echo "$URL"
curl "$URL/api/health"
```

Create an invite:

```bash
python scripts/aiq-mothership.py create-invite \
  --server-url "$URL" \
  --admin-key "$ADMIN_KEY" \
  --team Engineering
```

Or use lobby onboarding:

```bash
# employee
aiq register --server-url "$URL" --lobby --name "Jane Doe" --team Engineering

# admin
python scripts/aiq-mothership.py lobby --server-url "$URL" --admin-key "$ADMIN_KEY"
```

## Destroy

```bash
terraform -chdir=infra/azure-container-apps destroy
```

This deletes the Azure Files share and the SQLite database. Back it up first if needed.
