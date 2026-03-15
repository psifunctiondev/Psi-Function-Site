resource "digitalocean_droplet" "this" {
  name       = var.name
  region     = var.region
  size       = var.size
  image      = var.image
  ssh_keys   = var.ssh_keys
  backups    = var.backups
  monitoring = var.monitoring
  vpc_uuid   = var.vpc_uuid
  tags       = var.tags
  user_data  = var.user_data
}
