# Application tier: a private network plus the C# API and nginx web containers.
# (PostgreSQL is reused, not managed here — see variables.tf.)

resource "docker_network" "addrnet" {
  name = "addrnet"
}

# ---- Images (built from the local Dockerfiles) ----

resource "docker_image" "api" {
  name = "address-verification-api:latest"
  build {
    context    = "${path.module}/../api"
    dockerfile = "Dockerfile"
    tag        = ["address-verification-api:latest"]
  }
  # Rebuild when any source file under api/ changes.
  triggers = {
    src = sha1(join("", [
      for f in fileset("${path.module}/../api", "**") : filesha1("${path.module}/../api/${f}")
    ]))
  }
}

resource "docker_image" "web" {
  name = "address-verification-web:latest"
  build {
    context    = "${path.module}/../web"
    dockerfile = "Dockerfile"
    tag        = ["address-verification-web:latest"]
  }
  triggers = {
    src = sha1(join("", [
      for f in fileset("${path.module}/../web", "**") : filesha1("${path.module}/../web/${f}")
    ]))
  }
}

# ---- Containers ----

resource "docker_container" "api" {
  name    = "address-verification-api"
  image   = docker_image.api.image_id
  restart = "unless-stopped"

  env = [
    "NAD_CONNECTION=Host=${var.pg_host};Port=${var.pg_port};Database=${var.nad_db};Username=postgres",
    "NADSUB_CONNECTION=Host=${var.pg_host};Port=${var.pg_port};Database=${var.nadsub_db};Username=postgres",
    "NAD_TABLE=${var.nad_table}",
    "ASPNETCORE_URLS=http://+:8080",
  ]

  networks_advanced {
    name    = docker_network.addrnet.name
    aliases = ["api"]
  }

  # Map host.docker.internal to the host gateway so the container can reach the
  # PostgreSQL port published on the host (works on Docker Desktop and Linux).
  host {
    host = "host.docker.internal"
    ip   = "host-gateway"
  }

  ports {
    internal = 8080
    external = var.api_port
  }
}

resource "docker_container" "web" {
  name    = "address-verification-web"
  image   = docker_image.web.image_id
  restart = "unless-stopped"

  networks_advanced {
    name    = docker_network.addrnet.name
    aliases = ["web"]
  }

  ports {
    internal = 80
    external = var.web_port
  }

  depends_on = [docker_container.api]
}
