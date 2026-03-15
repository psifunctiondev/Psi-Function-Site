# Terraform Notes

This structure uses separate environment roots instead of relying on CLI workspaces
as the primary production/staging separation model.

## Environments

- `envs/production`
- `envs/staging`

Each environment should have separate state.

## Modules

- `droplet_app`: app droplet
- `firewall`: DigitalOcean cloud firewall
- `reserved_ip`: reserved IPv4 and assignment

## Backend

Add your preferred remote backend to `providers.tf` or a separate `backend.tf`.
Examples include HCP Terraform or an S3-compatible backend.
