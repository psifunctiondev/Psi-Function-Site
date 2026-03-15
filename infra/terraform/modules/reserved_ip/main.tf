resource "digitalocean_reserved_ip" "this" {
  region = var.region
}

resource "digitalocean_reserved_ip_assignment" "this" {
  ip_address = digitalocean_reserved_ip.this.ip_address
  droplet_id = var.droplet_id
}
