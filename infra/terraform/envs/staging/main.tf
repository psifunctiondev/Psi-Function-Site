locals {
  app_name = "${var.name_prefix}-staging-web-01"
  tags     = [var.name_prefix, "staging", "web"]
}

module "app" {
  source     = "../../modules/droplet_app"
  name       = local.app_name
  region     = var.region
  size       = var.size
  image      = var.image
  ssh_keys   = var.ssh_keys
  backups    = false
  monitoring = true
  vpc_uuid   = var.vpc_uuid
  tags       = local.tags

  user_data = templatefile("${path.module}/../../../cloud-init/dockerless-flask.yaml", {
    deploy_ssh_public_key = var.deploy_ssh_public_key
  })
}

module "firewall" {
  source               = "../../modules/firewall"
  name                 = "${var.name_prefix}-staging-fw"
  droplet_ids          = [tostring(module.app.droplet_id)]
  ssh_source_addresses = var.ssh_source_addresses
}

module "reserved_ip" {
  count      = var.enable_reserved_ip ? 1 : 0
  source     = "../../modules/reserved_ip"
  region     = var.region
  droplet_id = module.app.droplet_id
}
