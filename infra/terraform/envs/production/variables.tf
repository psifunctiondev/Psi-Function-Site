variable "digitalocean_token" { type = string sensitive = true }
variable "name_prefix" { type = string }
variable "region" { type = string }
variable "image" { type = string default = "ubuntu-24-04-x64" }
variable "size" { type = string }
variable "ssh_keys" { type = list(string) }
variable "vpc_uuid" { type = string default = null }
variable "ssh_source_addresses" { type = list(string) default = ["0.0.0.0/0", "::/0"] }
variable "deploy_ssh_public_key" { type = string }
variable "enable_reserved_ip" { type = bool default = false }
