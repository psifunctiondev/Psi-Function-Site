variable "name" { type = string }
variable "region" { type = string }
variable "size" { type = string }
variable "image" { type = string }
variable "ssh_keys" { type = list(string) }
variable "backups" { type = bool default = false }
variable "monitoring" { type = bool default = true }
variable "vpc_uuid" { type = string default = null }
variable "tags" { type = list(string) default = [] }
variable "user_data" { type = string default = null }
