variable "name" {
  type    = string
  default = "retail-bank-a2a"
}
variable "environment" {
  type    = string
  default = "prod"
}
variable "aws_region" {
  type    = string
  default = "ap-south-1"
}
variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}
variable "cluster_version" {
  type    = string
  default = "1.36"
}
variable "github_org" {
  type = string
}
variable "github_repo" {
  type = string
}
variable "db_name" {
  type    = string
  default = "bankagents"
}
variable "db_master_username" {
  type      = string
  default   = "bankadmin"
  sensitive = true
}
variable "aurora_engine_version" {
  type = string
  description = "Approved Aurora PostgreSQL version available in the target region."
  default = "16.6"
}
variable "valkey_engine_version" {
  type    = string
  default = "8.0"
}
