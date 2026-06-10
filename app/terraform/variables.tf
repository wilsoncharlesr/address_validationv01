# PostgreSQL is the existing `address-verification-pg` container, managed
# outside Terraform (by tools/start_postgres.py) so its ~4.86M-row data volume
# is never recreated. The API container reaches it over the host gateway.
variable "pg_host" {
  description = "Hostname the API container uses to reach PostgreSQL"
  type        = string
  default     = "host.docker.internal"
}

variable "pg_port" {
  description = "Host port PostgreSQL is published on"
  type        = number
  default     = 5433
}

variable "nad_db" {
  description = "Reference (NAD) database name"
  type        = string
  default     = "nad"
}

variable "nadsub_db" {
  description = "Submissions database name"
  type        = string
  default     = "nad_sub"
}

variable "nad_table" {
  description = "Table in the nad database to search and aggregate"
  type        = string
  default     = "il_addresses"
}

variable "api_port" {
  description = "Host port for direct access to the API"
  type        = number
  default     = 8081
}

variable "web_port" {
  description = "Host port for the web UI"
  type        = number
  default     = 8088
}
