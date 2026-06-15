# NAD Address Verification

Fuzzy address verification on top of the **National Address Database (NAD)**.

A user types a freeform address; a C# API searches a PostgreSQL copy of the NAD
for the three closest matches; the user confirms the right one; the API saves it
to a separate submissions database. A statistics page shows address counts per
county and per state for both databases.

```
Browser ─▶ nginx (web container) ──/api/──▶ C# API (api container) ─▶ PostgreSQL
                                                                      ├─ nad      (reference addresses)
                                                                      └─ nad_sub  (confirmed submissions)
```

The reference table can be the full national `nad_addresses` (~96.9M rows) or
the smaller `il_addresses` (~4.86M Illinois rows); the API reads whichever is
named by `NAD_TABLE` (see [Configuration](#configuration)).

## Components

| Piece | Tech | Where |
|---|---|---|
| Database | PostgreSQL 16 + `pg_trgm` | container `address-verification-pg` (port 5433) |
| API | C# / ASP.NET Core (.NET 8) + Npgsql | [`app/api/`](app/api), container `address-verification-api` |
| Web UI | static HTML/JS behind nginx | [`app/web/`](app/web), container `address-verification-web` |
| Infra | Terraform (kreuzwerker/docker) | [`app/terraform/`](app/terraform) |
| Orchestration | Python | [`app/start.py`](app/start.py) |
| Data loaders | Python (`docker exec` + `COPY`) | [`tools/`](tools) |

PostgreSQL is **reused, not recreated** by Terraform — it already holds the
loaded address data, so destroying it would throw that away. Terraform owns only
the API and web containers and their network; the API reaches Postgres via
`host.docker.internal:5433`.

## Quick start

```bash
cd app
python3 start.py          # bring everything up
python3 start.py --open   # ... and open the browser
```

Then visit:

- Web UI — <http://localhost:8088>
- Statistics — <http://localhost:8088/stats.html>
- API health — <http://localhost:8081/api/health>

`start.py` ensures Docker and the Postgres container are up, initializes the
databases and search indexes, runs `terraform init` + `apply` to build the API
and web containers, then waits for health checks and prints the URLs.

```bash
python3 start.py --status   # container status + URLs
python3 start.py --down     # terraform destroy (API + web; keeps PostgreSQL)
```

## API

| Method | Path | Body | Returns |
|---|---|---|---|
| GET  | `/api/health` | — | `{ status, table, cacheHits, cacheMisses }` |
| POST | `/api/verify` | `{ "query": "1916 Lombard Ave, Berwyn IL 60402" }` | top-3 matches, each with a `score` |
| POST | `/api/submit` | a chosen match `{ ...address, query }` | `{ id }` (new `nad_sub` row) |
| GET  | `/api/stats`  | — | `{ nad: {...}, nadSub: {...} }`, each `{ total, byState[], byCounty[] }` |

`/api/verify` returns **422** with a guidance message when a query can't be
narrowed (no ZIP and no recognizable city), and **504** if a search exceeds the
command timeout — instead of a bare 500.

### Configuration

Environment variables on the API container (defaults target a local Postgres):

| Var | Default | Meaning |
|---|---|---|
| `NAD_CONNECTION` | `Host=host.docker.internal;Port=5433;Database=nad;Username=postgres` | reference DB |
| `NADSUB_CONNECTION` | `...;Database=nad_sub;...` | submissions DB |
| `NAD_TABLE` | `il_addresses` | table searched and aggregated |

`NAD_TABLE` is driven by `nad_table` in `app/terraform/terraform.tfvars`. The
bulk loader can flip it for you:
`python3 tools/load_all_addresses.py --switch-only --table nad_addresses`.

## How the search works

The query string is parsed and routed down the cheapest path that can answer it:

1. **ZIP fast path** — a 5-digit ZIP narrows the table through the `zip_code`
   btree to a few thousand rows, which are then ranked by trigram
   `similarity(...)`. (~tens of ms.)
2. **Locality path** — with no ZIP, the API parses a state, house number, and
   candidate city names out of the query and narrows through a composite btree
   on `(city expression, add_number)`, then ranks those rows by similarity. This
   keeps no-ZIP searches off the full-table scan, which on the ~96.9M-row
   national table would blow the command timeout.
3. **Refusal** — a query that can't be narrowed at all (e.g. just a state) is
   refused with a 422 and a message asking for a ZIP or a city and state.

The normalized "full address" expression used for similarity scoring and the
GiST trigram index must stay identical between
[`app/db/01_init_nad.sql`](app/db/01_init_nad.sql) and
[`app/api/AddressRepository.cs`](app/api/AddressRepository.cs). NAD stores the
literal placeholder `'Not stated'` for a missing postal city (with the real
value in `inc_muni`), so the city expression strips it.

Verify results are cached in-process (NAD reference data is read-only within a
deploy), and the stats aggregates are single-flighted behind a short TTL.

## Loading data

NAD source files live under `data/TXT/` (e.g. the ~38 GB, ~74M-row
`NAD_r22.txt`). The loaders stream rows in with native `COPY` via `docker exec`
— no Python packages required.

```bash
# full national load into nad_addresses, then build indexes and point the app at it
python3 tools/load_all_addresses.py

# inspect any loaded table (sizes, columns, indexes, sample CSV)
python3 tools/describe_database.py
```

| Tool | Purpose |
|---|---|
| [`load_all_addresses.py`](tools/load_all_addresses.py) | full national load + indexes, then switch the app to the table |
| [`load_nad_postgres.py`](tools/load_nad_postgres.py) | the underlying NAD `COPY` bulk-load pipeline |
| [`describe_database.py`](tools/describe_database.py) | report table sizes / columns / indexes, export sample CSVs |
| [`start_postgres.py`](tools/start_postgres.py) | build and start the local Postgres container |

## Repository layout

```
app/          C# API, web UI, Terraform infra, start.py orchestration
  api/        ASP.NET Core service (search, submit, stats) + Npgsql
  db/         schema + index SQL, Postgres Dockerfile, start_db.py
  web/        static HTML/JS, nginx config
  terraform/  kreuzwerker/docker resources for the API + web containers
tools/        Python data loaders and database inspection utilities
tests/perf/   Playwright + k6 performance suite
data/         NAD source files (not committed)
```

See [`app/README.md`](app/README.md) for deeper detail on the application stack,
and [`performance_tune.md`](performance_tune.md) / [`implementation_plan.md`](implementation_plan.md)
for the performance findings and the tuning roadmap.

## Troubleshooting

- **Terraform can't reach Docker:** set `DOCKER_HOST`, e.g.
  `export DOCKER_HOST="unix://$HOME/.docker/run/docker.sock"`.
- **First `terraform apply` is slow:** it pulls the .NET SDK image and compiles
  the API; subsequent runs are cached.
- **Ports** (web `8088`, API `8081`, Postgres `5433`) are set in
  `app/terraform/variables.tf` (and `start.py`) — change them if they clash.
