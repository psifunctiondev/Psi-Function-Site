terraform {
  required_providers {
    digitalocean = {
      source = "digitalocean/digitalocean"
    }
    time = {
      source = "hashicorp/time"
    }
  }
}

resource "time_sleep" "wait_for_droplet" {
  create_duration = "30s"
}

resource "digitalocean_reserved_ip" "this" {
  region = var.region
}

resource "digitalocean_reserved_ip_assignment" "this" {
  depends_on = [time_sleep.wait_for_droplet]

  ip_address = digitalocean_reserved_ip.this.ip_address
  droplet_id = var.droplet_id
}
