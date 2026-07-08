# Graph Report - .  (2026-06-12)

## Corpus Check
- Corpus is ~41,507 words - fits in a single context window. You may not need a graph.

## Summary
- 404 nodes · 660 edges · 30 communities (23 shown, 7 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 19 edges (avg confidence: 0.86)
- Token cost: 102,503 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Load Generator Client|Load Generator Client]]
- [[_COMMUNITY_Address Verification Stack|Address Verification Stack]]
- [[_COMMUNITY_Playwright Perf Config|Playwright Perf Config]]
- [[_COMMUNITY_Address Repository (C)|Address Repository (C#)]]
- [[_COMMUNITY_NAD Data Loader|NAD Data Loader]]
- [[_COMMUNITY_Database Inspection Tool|Database Inspection Tool]]
- [[_COMMUNITY_DB Container Bootstrap|DB Container Bootstrap]]
- [[_COMMUNITY_Verify Page Frontend JS|Verify Page Frontend JS]]
- [[_COMMUNITY_Postgres Container Bootstrap|Postgres Container Bootstrap]]
- [[_COMMUNITY_Node Package Manifest|Node Package Manifest]]
- [[_COMMUNITY_App Startup Orchestration|App Startup Orchestration]]
- [[_COMMUNITY_Harvest Record Loader|Harvest Record Loader]]
- [[_COMMUNITY_API Cache Layer|API Cache Layer]]
- [[_COMMUNITY_TypeScript Config|TypeScript Config]]
- [[_COMMUNITY_Full Address Loader|Full Address Loader]]
- [[_COMMUNITY_Stats Page Frontend JS|Stats Page Frontend JS]]
- [[_COMMUNITY_API App Settings|API App Settings]]
- [[_COMMUNITY_Docker Data Relocation|Docker Data Relocation]]
- [[_COMMUNITY_Stats Performance Work|Stats Performance Work]]
- [[_COMMUNITY_API Project Manifest|API Project Manifest]]
- [[_COMMUNITY_k6 10K Verify Test|k6 10K Verify Test]]
- [[_COMMUNITY_JSON Source Generation|JSON Source Generation]]
- [[_COMMUNITY_API Models & Errors|API Models & Errors]]
- [[_COMMUNITY_Playwright Last Run|Playwright Last Run]]
- [[_COMMUNITY_Micro-Optimization Phase|Micro-Optimization Phase]]
- [[_COMMUNITY_DB Bootstrap Script|DB Bootstrap Script]]
- [[_COMMUNITY_Graphify Workflow Doc|Graphify Workflow Doc]]
- [[_COMMUNITY_Health Baseline Spec|Health Baseline Spec]]

## God Nodes (most connected - your core abstractions)
1. `config` - 24 edges
2. `AddressRepository` - 18 edges
3. `$()` - 17 edges
4. `main()` - 12 edges
5. `run()` - 11 edges
6. `psql()` - 11 edges
7. `open_http_csv()` - 10 edges
8. `run()` - 10 edges
9. `start()` - 9 edges
10. `run()` - 9 edges

## Surprising Connections (you probably didn't know these)
- `Melissa Global Address Cloud API (doGlobalAddress)` --semantically_similar_to--> `Address Verification Stack (NAD)`  [INFERRED] [semantically similar]
  Melissa_Address_Verification_CSharp_Guide.md → app/README.md
- `ResultInterpreter` --semantically_similar_to--> `pg_trgm Trigram Similarity Search`  [INFERRED] [semantically similar]
  Melissa_Address_Verification_CSharp_Guide.md → app/README.md
- `Terraform Azure Container Apps Infrastructure` --semantically_similar_to--> `Terraform (kreuzwerker/docker) Infrastructure`  [INFERRED] [semantically similar]
  Melissa_Address_Verification_CSharp_Guide.md → app/README.md
- `KEDA Queue-Depth Scaling` --semantically_similar_to--> `Phase 7 - Scale-Out (conditional)`  [INFERRED] [semantically similar]
  Melissa_Address_Verification_CSharp_Guide.md → implementation_plan.md
- `Capacity Math Note (perf README)` --semantically_similar_to--> `10K req/s Capacity Math`  [INFERRED] [semantically similar]
  tests/perf/README.md → performance_tune.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Melissa C# Batch Verification Pipeline Components** — melissa_address_verification_csharp_guide_melissaconfig, melissa_address_verification_csharp_guide_melissaaddressclient, melissa_address_verification_csharp_guide_batchaddressverifier, melissa_address_verification_csharp_guide_resiliencepolicies, melissa_address_verification_csharp_guide_resultinterpreter, melissa_address_verification_csharp_guide_verificationworker [EXTRACTED 1.00]
- **10K req/s Performance Fix Phase Sequence** — implementation_plan_phase0_baseline, implementation_plan_phase1_pool_tuning, implementation_plan_phase2_stats_cache, implementation_plan_phase3_cancellation, implementation_plan_phase4_nginx_keepalive, implementation_plan_phase5_verify_cache, implementation_plan_phase6_json_sourcegen, implementation_plan_phase7_scaleout [EXTRACTED 1.00]
- **Performance Test Suite Specs 01-06** — perf_readme_spec01_health, perf_readme_spec02_verify_latency, perf_readme_spec03_throughput_ramp, perf_readme_spec04_submit_perf, perf_readme_spec05_stats_interference, perf_readme_spec06_mixed_soak [EXTRACTED 1.00]

## Communities (30 total, 7 thin omitted)

### Community 0 - "Load Generator Client"
Cohesion: 0.08
Nodes (49): envFloat(), envInt(), envIntList(), fireHealth(), fireStats(), fireSubmit(), fireVerify(), mulberry32() (+41 more)

### Community 1 - "Address Verification Stack"
Cohesion: 0.05
Nodes (48): AddressRepository.SearchAsync, Address Verification Stack (NAD), C# API Endpoints (/api/health, /api/verify, /api/submit, /api/stats), nad PostgreSQL Database (il_addresses), nad_sub Submissions Database, nginx Web Container, start.py Orchestration, Terraform (kreuzwerker/docker) Infrastructure (+40 more)

### Community 2 - "Playwright Perf Config"
Cohesion: 0.05
Nodes (36): config, configFile, forbidOnly, fullyParallel, globalSetup, globalTeardown, globalTimeout, grep (+28 more)

### Community 3 - "Address Repository (C#)"
Cohesion: 0.11
Nodes (20): AddressResult, AddressRepository, GeneratedRegex, Regex, string, Bucket, CancellationToken, Cities (+12 more)

### Community 4 - "NAD Data Loader"
Cohesion: 0.15
Nodes (27): build_indexes(), connect(), create_schema(), _data_offset(), download_archive(), existing_columns(), fetch_range(), _fmt_bytes() (+19 more)

### Community 5 - "Database Inspection Tool"
Cohesion: 0.17
Nodes (24): export_sample(), heading(), list_tables(), main(), psql_pretty(), Run a statement via psql and return its aligned, human-readable output., show_database_details(), show_table_details() (+16 more)

### Community 6 - "DB Container Bootstrap"
Cohesion: 0.32
Nodes (16): build_image(), container_state(), data_disk_free_gb(), destroy(), docker_available(), image_exists(), main(), Free space (GB) on the filesystem backing the data volume. (+8 more)

### Community 7 - "Verify Page Frontend JS"
Cohesion: 0.20
Nodes (15): $(), cityLine(), clearMessage(), escapeHtml(), message, queryInput, renderResults(), resultList (+7 more)

### Community 8 - "Postgres Container Bootstrap"
Cohesion: 0.33
Nodes (15): build_image(), container_state(), data_disk_free_gb(), destroy(), docker_available(), main(), Free space (GB) on the filesystem backing the data volume., Replace the data volume with a fresh one and verify it has room     for the full (+7 more)

### Community 9 - "Node Package Manifest"
Cohesion: 0.13
Nodes (14): description, devDependencies, @playwright/test, @types/node, typescript, name, private, scripts (+6 more)

### Community 10 - "App Startup Orchestration"
Cohesion: 0.37
Nodes (13): container_state(), docker_available(), ensure_postgres(), http_ok(), init_databases(), main(), print_status(), psql_capture() (+5 more)

### Community 11 - "Harvest Record Loader"
Cohesion: 0.26
Nodes (11): create_database(), create_table(), fetch_data(), flatten(), load_records(), main(), Download and parse the JSON payload from the source URL., Flatten nested dicts into a single level; JSON-encode lists/leftovers. (+3 more)

### Community 12 - "API Cache Layer"
Cohesion: 0.20
Nodes (6): CacheKeys, CacheMetrics, GeneratedRegex, Regex, string, long

### Community 13 - "TypeScript Config"
Cohesion: 0.18
Nodes (10): compilerOptions, esModuleInterop, module, moduleResolution, noEmit, skipLibCheck, strict, target (+2 more)

### Community 14 - "Full Address Loader"
Cohesion: 0.31
Nodes (10): build_all_indexes(), container_running(), free_gb_on_data_volume(), main(), Point the running app at <table>: guards, tfvars, terraform apply,     then wait, Persist nad_table in terraform.tfvars so every future     `terraform apply` / st, switch_app(), table_exists() (+2 more)

### Community 15 - "Stats Page Frontend JS"
Cohesion: 0.52
Nodes (7): $(), escapeHtml(), fmt(), load(), message, renderBuckets(), setTotal()

### Community 16 - "API App Settings"
Cohesion: 0.33
Nodes (5): AllowedHosts, Logging, LogLevel, Default, Microsoft.AspNetCore

### Community 17 - "Docker Data Relocation"
Cohesion: 0.70
Nodes (4): die(), say(), warn(), relocate-docker-to-data.sh script

### Community 18 - "Stats Performance Work"
Cohesion: 0.83
Nodes (4): AddressRepository.StatsAsync, Phase 2 - Stats Cache + Parallelize, Spec 05 - Stats Cost & Interference, Finding 4 - /api/stats Is a Denial-of-Service Button

### Community 19 - "API Project Manifest"
Cohesion: 0.50
Nodes (3): net8.0, Npgsql (8.0.3), Microsoft.NET.Sdk.Web

### Community 20 - "k6 10K Verify Test"
Cohesion: 0.50
Nodes (3): options, QUERIES, RATE

## Knowledge Gaps
- **130 isolated node(s):** `string`, `State`, `HouseNumber`, `Cities`, `NpgsqlCommand` (+125 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What connects `string`, `State`, `HouseNumber` to the rest of the system?**
  _155 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Load Generator Client` be split into smaller, more focused modules?**
  _Cohesion score 0.0771478667445938 - nodes in this community are weakly interconnected._
- **Should `Address Verification Stack` be split into smaller, more focused modules?**
  _Cohesion score 0.051418439716312055 - nodes in this community are weakly interconnected._
- **Should `Playwright Perf Config` be split into smaller, more focused modules?**
  _Cohesion score 0.05405405405405406 - nodes in this community are weakly interconnected._
- **Should `Address Repository (C#)` be split into smaller, more focused modules?**
  _Cohesion score 0.10756302521008404 - nodes in this community are weakly interconnected._
- **Should `Node Package Manifest` be split into smaller, more focused modules?**
  _Cohesion score 0.13333333333333333 - nodes in this community are weakly interconnected._