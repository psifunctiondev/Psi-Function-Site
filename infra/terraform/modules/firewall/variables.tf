variable "name" {
  type = string
}

variable "droplet_ids" {
  type = list(string)
}

variable "ssh_source_addresses" {
  type    = list(string)
  default = ["0.0.0.0/0", "::/0"]
}
