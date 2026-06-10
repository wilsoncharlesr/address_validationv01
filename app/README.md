# Address Verification Stack

Fuzzy address verification on top of the National Address Database (NAD).

A user types an address; a **C#** API searches the `nad` PostgreSQL database for
the three closest matches (PostgreSQL `pg_trgm` trigram similarity); the user
confirms one; the API saves it to a separate `nad_sub` database. A statistics
page shows address counts per county and per state for **both** databases.

```
Browser ──▶ nginx (web container) ──/api/──▶ C# API (api container) ──▶ PostgreSQL
                                                                         ├─ nad      (il_addresses, ~4.86M IL rows)
                                                                         └─ nad_sub  (submissions)
```

## Components

| Piece | Tech | Where |
|---|---|---|
| Database | PostgreSQL 16 + `pg_trgm` | container `address-verification-pg` (port 5433) |
| API | C# / ASP.NET Core (.NET 8) + Npgsql | `api/`, container `address-verification-api` |
| Web UI | static HTML/JS behind nginx | `web/`, container `address-verification-web` |
| Infra | Terraform (kreuzwerker/docker) | `terraform/` |
| Orchestration | Python | `start.py` |

PostgreSQL is **reused, not recreated** by Terraform: the existing container
already holds ~4.86M Illinois addresses in `nad.il_addresses`, so destroying it
would throw that data away. It is managed by `../tools/start_postgres.py`, and
the API reaches it via `host.docker.internal:5433`. Terraform owns only the API
and web containers and their network.

## Run it

```bash
python3 start.py          # bring everything up
python3 start.py --open   # ... and open the browser
```

Then visit:

- Web UI: <http://localhost:8088>
- Statistics: <http://localhost:8088/stats.html>
- API health: <http://localhost:8081/api/health>

`start.py` will:

1. ensure Docker and the PostgreSQL container are running;
2. initialize the databases — `pg_trgm` and the **trigram search index** on
   `nad` (the first build on ~5M rows takes a few minutes; it is cached in the
   Postgres volume afterward), and create `nad_sub` + its `submissions` table;
3. `terraform init` + `terraform apply` to build and start the API and web
   containers;
4. wait for health checks and print the URLs.

### Other commands

```bash
python3 start.py --status       # container status + URLs
python3 start.py --skip-index   # skip the slow one-time index build
python3 start.py --down         # terraform destroy (API + web; keeps PostgreSQL)
```

## API

| Method | Path | Body | Returns |
|---|---|---|---|
| GET  | `/api/health` | — | `{ status, table }` |
| POST | `/api/verify` | `{ "query": "1916 Lombard Ave, Berwyn IL 60402" }` | top-3 matches with a `score` |
| POST | `/api/submit` | a chosen match `{ ...address, query }` | `{ id }` (new `nad_sub` row) |
| GET  | `/api/stats`  | — | `{ nad: {...}, nadSub: {...} }`, each `{ total, byState[], byCounty[] }` |

### Configuration (env vars on the API container)

| Var | Default | Meaning |
|---|---|---|
| `NAD_CONNECTION` | `Host=host.docker.internal;Port=5433;Database=nad;Username=postgres` | reference DB |
| `NADSUB_CONNECTION` | `...;Database=nad_sub;...` | submissions DB |
| `NAD_TABLE` | `il_addresses` | table searched and aggregated |

To point at the full national `nad_addresses` table once it is loaded, set
`nad_table` in `terraform/variables.tf` (and add a trigram index on it).

## How the search works

Both the index (`db/01_init_nad.sql`) and the query
(`api/AddressRepository.cs`) use the same normalized expression:

```
lower(addno_full || ' ' || stnam_full || ' ' || post_city || ' ' || state || ' ' || zip_code)
```

A GIN `gin_trgm_ops` index lets the `%` operator find candidates quickly; they
are then ranked by `similarity(...)` and the top 3 are returned.

## Notes / troubleshooting

- **Terraform can't reach Docker:** set `DOCKER_HOST`, e.g.
  `export DOCKER_HOST="unix://$HOME/.docker/run/docker.sock"`.
- **First `terraform apply` is slow:** it pulls the .NET SDK image and compiles
  the API. Subsequent runs are cached.
- **Ports:** web `8088`, API `8081`, PostgreSQL `5433` — change them in
  `terraform/variables.tf` (and `start.py`) if they clash.
