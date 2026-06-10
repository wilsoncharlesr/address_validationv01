terraform {
  required_version = ">= 1.3"
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

# Uses the local Docker daemon (Docker Desktop on macOS). If the socket is not
# at the default location, set DOCKER_HOST, e.g.
#   export DOCKER_HOST="unix://$HOME/.docker/run/docker.sock"
provider "docker" {}
