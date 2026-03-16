output "droplet_id" {
  value = module.app.droplet_id
}

output "ipv4_address" {
  value = module.app.ipv4_address
}

output "reserved_ip" {
  value = try(module.reserved_ip[0].ip_address, null)
}
