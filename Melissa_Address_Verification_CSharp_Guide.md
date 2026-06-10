# Melissa Address Verification

## A Complete C# / .NET Implementation Guide

*Asynchronous, Concurrent Batch Verification in a Containerized Environment*  
*Provisioned with Terraform on Azure Container Apps*

**Engineering Reference & Development Guide**  
Version 1.0 · June 2026  
.NET 9 · ASP.NET Core · Docker · Terraform (azurerm)

---

## Table of Contents

- [1. Executive Summary](#1-executive-summary)
- [2. Introduction](#2-introduction)
  - [2.1 Purpose and Scope](#21-purpose-and-scope)
  - [2.2 Intended Audience](#22-intended-audience)
  - [2.3 Solution Overview](#23-solution-overview)
  - [2.4 Assumptions and Prerequisites](#24-assumptions-and-prerequisites)
- [3. Melissa Address Verification Overview](#3-melissa-address-verification-overview)
  - [3.1 Service Capabilities](#31-service-capabilities)
  - [3.2 The Global Address Cloud API](#32-the-global-address-cloud-api)
  - [3.3 Request Structure](#33-request-structure)
  - [3.4 Response Structure](#34-response-structure)
  - [3.5 Result Codes](#35-result-codes)
  - [3.6 Licensing, Credits, and Limits](#36-licensing-credits-and-limits)
- [4. Solution Architecture](#4-solution-architecture)
  - [4.1 High-Level Architecture](#41-high-level-architecture)
  - [4.2 Component Responsibilities](#42-component-responsibilities)
  - [4.3 Concurrency and Threading Model](#43-concurrency-and-threading-model)
  - [4.4 Resilience and Rate-Limiting Strategy](#44-resilience-and-rate-limiting-strategy)
  - [4.5 Security Considerations](#45-security-considerations)
- [5. Development Guide](#5-development-guide)
  - [5.1 Project Layout](#51-project-layout)
  - [5.2 Project File (csproj)](#52-project-file-csproj)
  - [5.3 Configuration Model](#53-configuration-model)
  - [5.4 Domain Model](#54-domain-model)
  - [5.5 The Melissa API Client](#55-the-melissa-api-client)
  - [5.6 The Multi-Threaded Batch Processor](#56-the-multi-threaded-batch-processor)
  - [5.7 Resilience Pipeline](#57-resilience-pipeline)
  - [5.8 Result Interpretation](#58-result-interpretation)
  - [5.9 Application Host and Health Endpoints](#59-application-host-and-health-endpoints)
  - [5.10 Running a Batch](#510-running-a-batch)
  - [5.11 Testing](#511-testing)
- [6. Containerization](#6-containerization)
  - [6.1 Multi-Stage Dockerfile](#61-multi-stage-dockerfile)
  - [6.2 .NET Runtime Tuning for Containers](#62-net-runtime-tuning-for-containers)
  - [6.3 Build, Tag, and Push](#63-build-tag-and-push)
- [7. Infrastructure as Code with Terraform](#7-infrastructure-as-code-with-terraform)
  - [7.1 Target Platform and File Layout](#71-target-platform-and-file-layout)
  - [7.2 Providers and Remote State](#72-providers-and-remote-state)
  - [7.3 Input Variables](#73-input-variables)
  - [7.4 Core Resources](#74-core-resources)
  - [7.5 Secrets and the Job Queue](#75-secrets-and-the-job-queue)
  - [7.6 Container Apps Environment and the App](#76-container-apps-environment-and-the-app)
  - [7.7 Outputs](#77-outputs)
  - [7.8 Deployment Workflow](#78-deployment-workflow)
- [8. Operations and Observability](#8-operations-and-observability)
  - [8.1 Logging and Metrics](#81-logging-and-metrics)
  - [8.2 Scaling Behavior](#82-scaling-behavior)
  - [8.3 Cost Considerations](#83-cost-considerations)
- [9. Reference Guide](#9-reference-guide)
  - [9.1 Melissa Result Code Quick Reference](#91-melissa-result-code-quick-reference)
  - [9.2 Key Request and Response Fields](#92-key-request-and-response-fields)
  - [9.3 Configuration (Environment Variables)](#93-configuration-environment-variables)
  - [9.4 Terraform Resource Summary](#94-terraform-resource-summary)
  - [9.5 Command Reference](#95-command-reference)
  - [9.6 Tuning Cheat Sheet](#96-tuning-cheat-sheet)
  - [9.7 Troubleshooting](#97-troubleshooting)
  - [9.8 External References](#98-external-references)

# 1. Executive Summary

This guide is a complete, end-to-end blueprint for building, packaging, and deploying a production-grade address verification service in C# on .NET. The service calls the Melissa Global Address Verification cloud API to cleanse, standardize, and geocode postal addresses for the United States and 240+ other countries and territories, and it is engineered to process large volumes of addresses concurrently.

Three engineering concerns drive the design. **First, throughput**: address verification is an I/O-bound workload dominated by network round-trips, so the application is asynchronous and concurrent using .NET's async/await model, request batching, and a bounded-concurrency gate that keeps the service within the limits of the Melissa contract. **Second, resilience**: every outbound call flows through a Polly resilience pipeline — retry, rate-limiting, circuit-breaker, and timeout — so transient failures do not cascade. **Third, portability and operability**: the application is delivered as a single container image and the entire runtime environment is provisioned declaratively with Terraform.

The container platform in this guide is **Azure Container Apps**, chosen because it provides serverless, KEDA-driven horizontal scaling, managed identity for secretless access to the registry and Key Vault, and integrated logging — with no Kubernetes cluster to operate. The .NET, Docker, and resilience layers are deliberately cloud-agnostic: the same image runs unchanged on Kubernetes (AKS/GKE), Cloud Run, or ECS, so only the Terraform layer changes if the target platform changes.

The result is a service that scales on two independent axes simultaneously: vertically, through many concurrent asynchronous requests inside a single replica; and horizontally, as the container platform adds replicas in response to queue depth. Readers can follow the guide front to back to produce a working deployment, or use the Reference Guide in Section 9 as a standalone lookup for result codes, configuration keys, commands, and tuning parameters.

| Concern | Approach in This Guide |
| --- | --- |
| Verification engine | Melissa Global Address Cloud REST API (doGlobalAddress), batch records per request |
| Language / runtime | .NET 9 (C# 13), IHttpClientFactory + HttpClient, System.Text.Json |
| Concurrency | async/await + bounded SemaphoreSlim + request batching |
| Resilience | Polly v8 pipeline: retry (exponential backoff), rate limiter, circuit breaker, timeout |
| Packaging | Multi-stage Dockerfile, ASP.NET runtime image, non-root user |
| Infrastructure | Terraform (azurerm) — Azure Container Apps, ACR, Key Vault, Log Analytics |
| Scaling | In-process concurrency per replica + KEDA queue-depth horizontal scaling |

# 2. Introduction

## 2.1 Purpose and Scope

This document describes how to implement an address verification capability against the Melissa Global Address service using C# on .NET, how to make that implementation concurrent and fault-tolerant, how to package it as a container, and how to provision the surrounding cloud environment with Terraform. It covers the verification client, the multi-threaded batch processor, containerization, and infrastructure-as-code, plus an operational reference.

Out of scope: Melissa account procurement and contract limits (consult your Melissa representative), the upstream system that supplies addresses, and downstream persistence of verified results beyond illustrative examples.

## 2.2 Intended Audience

The guide assumes a senior software or platform engineer comfortable with C#/.NET, the dotnet CLI, Docker, and Terraform, and with basic familiarity with cloud identity and secret management. No prior experience with the Melissa API is assumed.

## 2.3 Solution Overview

At runtime, a fleet of identical container replicas pulls address-batch jobs from a queue. Each replica reads a job, partitions the addresses into request-sized batches, and dispatches those batches concurrently to the Melissa Global Address API. Responses are parsed, each record is classified by its result codes (verified, corrected, ambiguous, or error), and the cleansed records are written to the output sink. The container platform scales the number of replicas up and down based on queue depth, while each replica maximizes throughput internally through asynchronous concurrency.

## 2.4 Assumptions and Prerequisites

| Prerequisite | Version / Notes |
| --- | --- |
| .NET SDK | .NET 9 SDK (async I/O concurrency model; C# 13 language features used throughout) |
| Build tool | dotnet CLI (bundled with the SDK) |
| Container tooling | Docker 24+ (or Azure CLI for az acr build) |
| Terraform | 1.6.0+ with the hashicorp/azurerm provider (~> 4.0) |
| Azure CLI | 2.60+, authenticated to a subscription with Contributor + RBAC admin rights |
| Melissa | Active Global Address license key with available credits |

# 3. Melissa Address Verification Overview

## 3.1 Service Capabilities

Melissa Global Address Verification validates, corrects, and standardizes postal addresses against authoritative postal data, including CASS-certified USPS data for the United States and SERP-certified data for Canada, with coverage for 240+ countries and territories. Beyond a pass/fail decision, the service returns a fully parsed and standardized address, fills in missing components such as postal codes, transliterates non-Latin scripts, and can append rooftop-level latitude and longitude for geocoding.

- Standardization to each country's official postal format.
- Correction of misspellings, wrong premise numbers, and malformed postal codes.
- Enrichment: postal code completion, geocoding (lat/long), and delivery indicators.
- Per-record result codes that explain exactly what was verified, corrected, or rejected.

## 3.2 The Global Address Cloud API

The service is exposed as a REST/JSON web service. The endpoint used throughout this guide is:

```
POST https://address.melissadata.net/v3/WEB/GlobalAddress/doGlobalAddress
```

Authentication is by license key. The key may be supplied as the `id` query-string parameter or, as in this guide, inside the JSON request body. A single request can carry many address records (commonly up to 100), which is the foundation of the batching strategy: one HTTP round-trip verifies an entire batch, and many batches run concurrently.

## 3.3 Request Structure

The request body is a JSON object containing the license key, optional transmission metadata, an `Options` string, and a `Records` array. Each record carries a caller-assigned `RecordID` plus the raw address fields to verify.

*Listing 3-1. Minimal doGlobalAddress JSON request.*

```json
{
  "CustomerID": "YOUR_MELISSA_LICENSE_KEY",
  "TransmissionReference": "batch-2026-06-08-0001",
  "Options": "",
  "Records": [
    {
      "RecordID": "1",
      "Organization": "",
      "AddressLine1": "22382 Avenida Empresa",
      "AddressLine2": "",
      "Locality": "Rancho Santa Margarita",
      "AdministrativeArea": "CA",
      "PostalCode": "92688",
      "Country": "US"
    }
  ]
}
```

## 3.4 Response Structure

The response echoes transmission metadata and returns a `Records` array aligned to the request by `RecordID`. Each response record contains the standardized address, optional geocoding, and a comma-delimited `Results` string of result codes that is the authoritative signal for downstream logic.

*Listing 3-2. Representative doGlobalAddress JSON response.*

```json
{
  "Version": "...",
  "TransmissionReference": "batch-2026-06-08-0001",
  "TransmissionResults": "",
  "TotalRecords": "1",
  "Records": [
    {
      "RecordID": "1",
      "Results": "AV25,GS05",
      "FormattedAddress": "22382 Avenida Empresa;Rancho Santa Margarita CA 92688-2112",
      "AddressLine1": "22382 Avenida Empresa",
      "Locality": "Rancho Santa Margarita",
      "AdministrativeArea": "CA",
      "PostalCode": "92688-2112",
      "CountryName": "United States",
      "Latitude": "33.624...",
      "Longitude": "-117.585..."
    }
  ]
}
```

## 3.5 Result Codes

Result codes are grouped into families by prefix. The **AV** (Address Verification) family is the primary deliverability signal: codes beginning `AV2` indicate full verification, with the final digit denoting how granular the match is (locality through delivery point), while `AV1` codes indicate partial verification only. The **AC** family reports which components were changed, **AE** reports errors, and **GS / GE** report geocoding status. A summarized quick-reference appears in Section 9.1; the authoritative, current list is published by Melissa (Section 9.8).

## 3.6 Licensing, Credits, and Limits

Each verified record consumes account credits, and the contract defines acceptable request rates and concurrency. These limits, not raw machine capacity, are the binding constraint on throughput — which is precisely why the application bounds its own concurrency and rate-limits itself rather than dispatching every batch at once. Confirm your specific limits with Melissa and set the configuration values in Section 5.3 accordingly.

# 4. Solution Architecture

## 4.1 High-Level Architecture

The system is composed of an ingestion queue, a horizontally scaled pool of verifier replicas, the external Melissa API, and an output sink, all observed by the platform's logging stack. The diagram below shows the request path through one replica and the two scaling axes.

```text
                    +------------------------+
  address jobs ---> |   Job Queue (Storage)  |
                    +-----------+------------+
                                | (KEDA queue-depth scaling)
             +------------------+------------------+
             v                  v                  v
      +-------------+    +-------------+    +-------------+
      |  Replica 1  |    |  Replica 2  |    |  Replica N  |   <- horizontal axis
      |             |    |             |    |             |
      |  Batch      |    |  partition  |    |  partition  |
      |  partition  |    |             |    |             |
      |   |  |  |   |    |   |  |  |   |    |   |  |  |   |   <- vertical axis
      | async tasks |    | async tasks |    | async tasks |     (async I/O, bounded
      +------+------+    +------+------+    +------+------+       by a SemaphoreSlim)
             \                 |                 /
              \                v                /
               +----> Melissa Global Address API <----+
                       (rate-limited, retried)
```

Within a replica, an input job is partitioned into batches; each batch is one HTTP request; batches are awaited concurrently up to a bounded limit. Across replicas, the container platform scales the replica count based on queue depth.

## 4.2 Component Responsibilities

| Component | Responsibility |
| --- | --- |
| MelissaConfig | Loads and validates all tunables from environment variables. |
| MelissaAddressClient | Serializes a batch, performs one HTTP call through the resilient typed client, maps the JSON response, classifies HTTP status as transient vs. terminal. |
| ResiliencePolicies | Builds the Polly pipeline (retry, circuit breaker, rate limiter, timeout) attached to the typed HttpClient. |
| BatchAddressVerifier | Partitions input, dispatches batches concurrently, bounds in-flight requests, aggregates and orders results. |
| ResultInterpreter | Parses the Results string into a single business verdict. |
| Program | Builds the host, registers the resilient client and health endpoints. |
| VerificationWorker | Hosted service that runs the batch (or worker loop) and writes output. |

## 4.3 Concurrency and Threading Model

Address verification spends almost all of its wall-clock time waiting on the network, so the bottleneck is concurrency, not CPU. The model has three layers:

- **Batching.** Records are grouped into batches (default 100) so each HTTP round-trip amortizes its latency across many addresses.
- **Asynchronous I/O.** Each batch call is an awaited async operation. While a request is in flight, .NET returns the pooled thread to the thread pool (I/O completion ports do the waiting), so thousands of concurrent HTTP calls cost a handful of threads instead of one OS thread each — the same effect Java gets from virtual threads, achieved here by the async/await state machine.
- **A bounded SemaphoreSlim.** Because awaited tasks are nearly free, the limiting factor must be made explicit: a SemaphoreSlim caps the number of requests actually in flight to the Melissa contract's concurrency limit, providing back-pressure regardless of how many batches are queued.

This separation is deliberate. The task scheduler decides *how work is scheduled*; the semaphore and rate limiter decide *how fast it is allowed to leave the process*. Swapping the semaphore loop for `Parallel.ForEachAsync` (shown in Section 5.6) changes the ergonomics without changing the concurrency contract.

## 4.4 Resilience and Rate-Limiting Strategy

A Polly v8 resilience pipeline composes around every batch call, applied outermost-to-innermost as retry → circuit breaker → rate limiter → timeout, and is attached transparently to the typed HttpClient as a delegating handler:

- `Retry` — retries only transient outcomes (HTTP 5xx, 429, and connection/timeout exceptions) with exponential backoff and jitter; 4xx responses are treated as terminal and never retried.
- `CircuitBreaker` — opens after a sustained failure ratio so the service stops hammering a degraded endpoint and fails fast while it recovers.
- `RateLimiter` — caps requests per second to stay within contract, smoothing bursts across all concurrent callers in the replica.
- `Timeout` — an innermost per-attempt timeout bounds each individual try, so a single slow call cannot stall a worker.

Failed batches do not abort the run: after the pipeline is exhausted the records are emitted with an error sentinel code so downstream processing can route them for manual review.

## 4.5 Security Considerations

- The Melissa license key is never baked into source or the image; it is stored in Key Vault and injected as a secret-backed environment variable via the container app's managed identity.
- The image runs as a non-root user with a read-only-friendly layout.
- The registry is pulled using a user-assigned managed identity with the minimal AcrPull role; no admin credentials are enabled.
- No secret is ever placed in a URL query string in production; the body-based authentication shown in Section 5 keeps the key out of request lines and logs.

# 5. Development Guide

## 5.1 Project Layout

A standard .NET solution layout keeps the verification engine framework-light: the engine classes depend only on HttpClient, System.Text.Json, and logging abstractions, while the host project wires in dependency injection, the resilient HttpClient, and health endpoints. The only NuGet package required is Microsoft.Extensions.Http.Resilience, which brings in Polly v8.

```text
melissa-address-verifier/
  MelissaAddressVerifier.sln
  Dockerfile
  src/MelissaAddressVerifier/
    MelissaAddressVerifier.csproj
    Program.cs
    MelissaConfig.cs
    MelissaAddressClient.cs
    BatchAddressVerifier.cs
    ResiliencePolicies.cs
    ResultInterpreter.cs
    TransientApiException.cs
    VerificationWorker.cs
    Models/
      GlobalAddressRequest.cs
      RequestRecord.cs
      GlobalAddressResponse.cs
      ResponseRecord.cs
  tests/MelissaAddressVerifier.Tests/
    MelissaAddressVerifier.Tests.csproj
    ResultInterpreterTests.cs
  infra/                # Terraform (Section 7)
```

## 5.2 Project File (csproj)

The project targets .NET 9 and builds a framework-dependent deployment via dotnet publish. A single package reference adds the Polly-based resilience handler; System.Text.Json and the hosting, DI, and ASP.NET Core stacks ship with the SDK. Using the Web SDK provides the framework reference needed for the minimal-API health endpoints.

*Listing 5-1. MelissaAddressVerifier.csproj*

```xml
<Project Sdk="Microsoft.NET.Sdk.Web">

  <PropertyGroup>
    <TargetFramework>net9.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <InvariantGlobalization>true</InvariantGlobalization>
    <RootNamespace>MelissaAddressVerifier</RootNamespace>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Microsoft.Extensions.Http.Resilience" Version="9.0.0" />
  </ItemGroup>

</Project>
```

## 5.3 Configuration Model

All tunables come from environment variables so the same image behaves correctly in every environment. The configuration type loads and validates them at startup, failing fast if the required license key is absent.

*Listing 5-2. MelissaConfig.cs*

```csharp
namespace MelissaAddressVerifier;

/// <summary>Strongly-typed configuration, loaded and validated from the environment.</summary>
public sealed class MelissaConfig
{
    public required string LicenseKey { get; init; }
    public string BaseUrl { get; init; } =
        "https://address.melissadata.net/v3/WEB/GlobalAddress/doGlobalAddress";
    public int BatchSize { get; init; } = 100;
    public int MaxConcurrency { get; init; } = 8;
    public double RequestsPerSecond { get; init; } = 10;
    public int MaxRetries { get; init; } = 4;
    public TimeSpan RequestTimeout { get; init; } = TimeSpan.FromMilliseconds(15_000);

    public static MelissaConfig FromEnvironment()
    {
        var key = Environment.GetEnvironmentVariable("MELISSA_LICENSE_KEY");
        if (string.IsNullOrWhiteSpace(key))
            throw new InvalidOperationException(
                "Missing required env var: MELISSA_LICENSE_KEY");

        return new MelissaConfig
        {
            LicenseKey        = key,
            BaseUrl           = Env("MELISSA_BASE_URL",
                "https://address.melissadata.net/v3/WEB/GlobalAddress/doGlobalAddress"),
            BatchSize         = EnvInt("MELISSA_BATCH_SIZE", 100),
            MaxConcurrency    = EnvInt("MELISSA_MAX_CONCURRENCY", 8),
            RequestsPerSecond = EnvDouble("MELISSA_RPS", 10),
            MaxRetries        = EnvInt("MELISSA_MAX_RETRIES", 4),
            RequestTimeout    =
                TimeSpan.FromMilliseconds(EnvInt("MELISSA_REQUEST_TIMEOUT_MS", 15_000)),
        };
    }

    private static string Env(string key, string fallback) =>
        Environment.GetEnvironmentVariable(key) is { Length: > 0 } v ? v : fallback;
    private static int EnvInt(string key, int fallback) =>
        int.TryParse(Environment.GetEnvironmentVariable(key), out var v) ? v : fallback;
    private static double EnvDouble(string key, double fallback) =>
        double.TryParse(Environment.GetEnvironmentVariable(key), out var v) ? v : fallback;
}
```

## 5.4 Domain Model

System.Text.Json-annotated DTOs map directly to the Melissa JSON contract. Request DTOs omit null fields on serialization; response DTOs ignore unknown fields by default, so Melissa can add columns without breaking the client.

*Listing 5-3. Models/GlobalAddressRequest.cs*

```csharp
using System.Text.Json.Serialization;

namespace MelissaAddressVerifier.Models;

public sealed class GlobalAddressRequest
{
    [JsonPropertyName("CustomerID")]            public string CustomerId { get; set; } = "";
    [JsonPropertyName("TransmissionReference")] public string? TransmissionReference { get; set; }
    [JsonPropertyName("Options")]               public string Options { get; set; } = "";
    [JsonPropertyName("Records")]               public List<RequestRecord> Records { get; set; } = [];
}
```

*Listing 5-4. Models/RequestRecord.cs*

```csharp
using System.Text.Json.Serialization;

namespace MelissaAddressVerifier.Models;

public sealed class RequestRecord
{
    [JsonPropertyName("RecordID")]           public string RecordId { get; set; } = "";
    [JsonPropertyName("Organization")]       public string? Organization { get; set; }
    [JsonPropertyName("AddressLine1")]       public string? AddressLine1 { get; set; }
    [JsonPropertyName("AddressLine2")]       public string? AddressLine2 { get; set; }
    [JsonPropertyName("Locality")]           public string? Locality { get; set; }            // city
    [JsonPropertyName("AdministrativeArea")] public string? AdministrativeArea { get; set; }  // state/region
    [JsonPropertyName("PostalCode")]         public string? PostalCode { get; set; }
    [JsonPropertyName("Country")]            public string? Country { get; set; }             // ISO-2, e.g. US
}
```

*Listing 5-5. Models/GlobalAddressResponse.cs*

```csharp
using System.Text.Json.Serialization;

namespace MelissaAddressVerifier.Models;

public sealed class GlobalAddressResponse
{
    [JsonPropertyName("Version")]               public string? Version { get; set; }
    [JsonPropertyName("TransmissionReference")] public string? TransmissionReference { get; set; }
    [JsonPropertyName("TransmissionResults")]   public string? TransmissionResults { get; set; }
    [JsonPropertyName("TotalRecords")]          public string? TotalRecords { get; set; }
    [JsonPropertyName("Records")]               public List<ResponseRecord> Records { get; set; } = [];
}
```

*Listing 5-6. Models/ResponseRecord.cs*

```csharp
using System.Text.Json.Serialization;

namespace MelissaAddressVerifier.Models;

public sealed class ResponseRecord
{
    [JsonPropertyName("RecordID")]           public string RecordId { get; set; } = "";
    [JsonPropertyName("Results")]            public string? Results { get; set; }   // e.g. "AV25,GS05"
    [JsonPropertyName("FormattedAddress")]   public string? FormattedAddress { get; set; }
    [JsonPropertyName("AddressLine1")]       public string? AddressLine1 { get; set; }
    [JsonPropertyName("Locality")]           public string? Locality { get; set; }
    [JsonPropertyName("AdministrativeArea")] public string? AdministrativeArea { get; set; }
    [JsonPropertyName("PostalCode")]         public string? PostalCode { get; set; }
    [JsonPropertyName("CountryName")]        public string? CountryName { get; set; }
    [JsonPropertyName("Latitude")]           public string? Latitude { get; set; }
    [JsonPropertyName("Longitude")]          public string? Longitude { get; set; }
}
```

## 5.5 The Melissa API Client

The client is a typed `HttpClient` (created and pooled by IHttpClientFactory, with the resilience pipeline attached as a handler) and performs exactly one batch call per invocation. Critically, it translates the HTTP status into the right exception type so a transient failure surfaced after the pipeline is distinguishable from a terminal one.

*Listing 5-7. MelissaAddressClient.cs*

```csharp
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using MelissaAddressVerifier.Models;

namespace MelissaAddressVerifier;

public sealed class MelissaAddressClient(HttpClient http, MelissaConfig config)
{
    private static readonly JsonSerializerOptions JsonOpts = new(JsonSerializerDefaults.Web)
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };

    public async Task<GlobalAddressResponse> VerifyBatchAsync(
        IReadOnlyList<RequestRecord> batch, CancellationToken ct)
    {
        var payload = new GlobalAddressRequest
        {
            CustomerId = config.LicenseKey,
            TransmissionReference = $"batch-{DateTime.UtcNow:yyyyMMddHHmmss}-{Guid.NewGuid():N}",
            Options = "",
            Records = [.. batch]
        };

        using var response = await http.PostAsJsonAsync(config.BaseUrl, payload, JsonOpts, ct);
        var status = (int)response.StatusCode;

        if (status == 429 || status >= 500)
            throw new TransientApiException($"Retryable Melissa status {status}");
        if (status >= 400)
            throw new InvalidOperationException(
                $"Terminal Melissa status {status}: {await response.Content.ReadAsStringAsync(ct)}");

        return await response.Content.ReadFromJsonAsync<GlobalAddressResponse>(JsonOpts, ct)
               ?? throw new InvalidOperationException("Melissa returned an empty response body.");
    }
}
```

*Listing 5-8. TransientApiException.cs*

```csharp
namespace MelissaAddressVerifier;

/// <summary>Marks failures that are safe to retry (timeouts, 429, 5xx).</summary>
public sealed class TransientApiException(string message) : Exception(message);
```

## 5.6 The Multi-Threaded Batch Processor

This is the heart of the implementation. It partitions input into batches, awaits each batch concurrently, gates real concurrency with a SemaphoreSlim, and reassembles results in the original order. A failed batch is caught and replaced with error sentinels so one bad batch never aborts the run.

*Listing 5-9. BatchAddressVerifier.cs*

```csharp
using MelissaAddressVerifier.Models;
using Microsoft.Extensions.Logging;

namespace MelissaAddressVerifier;

public sealed class BatchAddressVerifier(
    MelissaAddressClient client,
    MelissaConfig config,
    ILogger<BatchAddressVerifier> logger)
{
    /// <summary>
    /// Verifies all records concurrently, preserving input order in the returned list.
    /// </summary>
    public async Task<IReadOnlyList<ResponseRecord>> VerifyAllAsync(
        IReadOnlyList<RequestRecord> records, CancellationToken ct = default)
    {
        var batches = records.Chunk(config.BatchSize).ToList();   // List<RequestRecord[]>
        logger.LogInformation(
            "Verifying {Count} addresses in {Batches} batches (batchSize={Size}, maxConcurrency={Max})",
            records.Count, batches.Count, config.BatchSize, config.MaxConcurrency);

        var results = new ResponseRecord[batches.Count][];
        using var gate = new SemaphoreSlim(config.MaxConcurrency);

        var tasks = batches.Select(async (batch, index) =>
        {
            await gate.WaitAsync(ct);                  // back-pressure gate
            try
            {
                var response = await client.VerifyBatchAsync(batch, ct);
                results[index] = AlignToRequest(batch, response);
            }
            catch (Exception ex)
            {
                logger.LogError(ex,
                    "Batch {Index} failed after retries; emitting error sentinels.", index);
                results[index] = [.. batch.Select(r => ErrorRecord(r.RecordId))];
            }
            finally
            {
                gate.Release();
            }
        });

        await Task.WhenAll(tasks);
        return [.. results.SelectMany(r => r)];        // flatten in submission order
    }

    // Re-align the response to the request by RecordID so output order is deterministic.
    private static ResponseRecord[] AlignToRequest(
        RequestRecord[] batch, GlobalAddressResponse response)
    {
        var byId = response.Records.ToDictionary(r => r.RecordId);
        return [.. batch.Select(req =>
            byId.TryGetValue(req.RecordId, out var match) ? match : ErrorRecord(req.RecordId))];
    }

    private static ResponseRecord ErrorRecord(string recordId) =>
        new() { RecordId = recordId, Results = "SE01" };   // service-error sentinel
}
```

**Parallel.ForEachAsync alternative.** If you prefer to bound concurrency without an explicit semaphore, `Parallel.ForEachAsync` caps the degree of parallelism in one call (ordering is preserved via the index):

```csharp
var options = new ParallelOptions { MaxDegreeOfParallelism = config.MaxConcurrency };
await Parallel.ForEachAsync(batches.Index(), options, async (item, token) =>
{
    var response = await client.VerifyBatchAsync(item.Item, token);
    results[item.Index] = AlignToRequest(item.Item, response);
});
```

## 5.7 Resilience Pipeline

The Polly v8 pipeline is configured once and attached to the typed client in `Program.cs` (Section 5.9). Strategies execute in the order added: retry (outermost) wraps the circuit breaker, which wraps the rate limiter, which wraps a per-attempt timeout (innermost).

*Listing 5-10. ResiliencePolicies.cs*

```csharp
using System.Threading.RateLimiting;
using Polly;
using Polly.CircuitBreaker;
using Polly.RateLimiting;
using Polly.Retry;
using Polly.Timeout;

namespace MelissaAddressVerifier;

public static class ResiliencePolicies
{
    public static void Configure(
        ResiliencePipelineBuilder<HttpResponseMessage> builder, MelissaConfig config)
    {
        // Retry: only transient outcomes, exponential backoff with jitter.
        builder.AddRetry(new RetryStrategyOptions<HttpResponseMessage>
        {
            ShouldHandle = new PredicateBuilder<HttpResponseMessage>()
                .HandleResult(r => (int)r.StatusCode == 429 || (int)r.StatusCode >= 500)
                .Handle<HttpRequestException>()
                .Handle<TimeoutRejectedException>(),
            MaxRetryAttempts = config.MaxRetries,
            BackoffType = DelayBackoffType.Exponential,
            UseJitter = true,
            Delay = TimeSpan.FromMilliseconds(500)
        });

        // Circuit breaker: trip on a sustained failure ratio, then fail fast.
        builder.AddCircuitBreaker(new CircuitBreakerStrategyOptions<HttpResponseMessage>
        {
            ShouldHandle = new PredicateBuilder<HttpResponseMessage>()
                .HandleResult(r => (int)r.StatusCode == 429 || (int)r.StatusCode >= 500)
                .Handle<HttpRequestException>(),
            FailureRatio = 0.6,
            MinimumThroughput = 20,
            SamplingDuration = TimeSpan.FromSeconds(30),
            BreakDuration = TimeSpan.FromSeconds(15)
        });

        // Rate limiter: cap requests/sec to honor the Melissa contract.
        builder.AddRateLimiter(new SlidingWindowRateLimiter(new SlidingWindowRateLimiterOptions
        {
            PermitLimit = Math.Max(1, (int)Math.Ceiling(config.RequestsPerSecond)),
            Window = TimeSpan.FromSeconds(1),
            SegmentsPerWindow = 4,
            QueueProcessingOrder = QueueProcessingOrder.OldestFirst,
            QueueLimit = int.MaxValue
        }));

        // Innermost: per-attempt timeout.
        builder.AddTimeout(config.RequestTimeout);
    }
}
```

## 5.8 Result Interpretation

Downstream systems should branch on a single verdict, not on raw codes scattered through the pipeline. The interpreter parses the comma-delimited Results string once and collapses it to an enum.

*Listing 5-11. ResultInterpreter.cs*

```csharp
namespace MelissaAddressVerifier;

public enum Verdict { Verified, Corrected, Ambiguous, Unverified, Error }

public static class ResultInterpreter
{
    public static Verdict Classify(string? resultCodes)
    {
        if (string.IsNullOrWhiteSpace(resultCodes)) return Verdict.Unverified;

        var codes = resultCodes
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        if (codes.Any(c => c.StartsWith("SE", StringComparison.OrdinalIgnoreCase)
                        || c.StartsWith("GE", StringComparison.OrdinalIgnoreCase)))
            return Verdict.Error;
        if (codes.Contains("AE05")) return Verdict.Ambiguous;   // multiple matches

        var full      = codes.Any(c => c.StartsWith("AV2", StringComparison.OrdinalIgnoreCase));
        var corrected = codes.Any(c => c.StartsWith("AC",  StringComparison.OrdinalIgnoreCase));
        var partial   = codes.Any(c => c.StartsWith("AV1", StringComparison.OrdinalIgnoreCase));

        if (full && corrected) return Verdict.Corrected;
        if (full)              return Verdict.Verified;
        if (partial)           return Verdict.Unverified;
        return Verdict.Unverified;
    }

    public static bool IsDeliverable(string? resultCodes) =>
        Classify(resultCodes) is Verdict.Verified or Verdict.Corrected;
}
```

## 5.9 Application Host and Health Endpoints

The host wires configuration, the resilient typed client, the verifier, and the worker, then maps lightweight liveness and readiness endpoints the container platform can probe. Disabling the ambient HttpClient timeout lets Polly's per-attempt timeout govern each try instead of cancelling the whole retry chain.

*Listing 5-12. Program.cs*

```csharp
using MelissaAddressVerifier;

var builder = WebApplication.CreateBuilder(args);
var config = MelissaConfig.FromEnvironment();

builder.Services.AddSingleton(config);
builder.Services.AddTransient<BatchAddressVerifier>();
builder.Services.AddHostedService<VerificationWorker>();

builder.Services
    .AddHttpClient<MelissaAddressClient>(c =>
    {
        // Per-attempt timeout is enforced by the resilience pipeline.
        c.Timeout = Timeout.InfiniteTimeSpan;
        c.DefaultRequestHeaders.Add("Accept", "application/json");
    })
    .AddResilienceHandler("melissa", b => ResiliencePolicies.Configure(b, config));

builder.Services.AddHealthChecks();

var app = builder.Build();
app.MapHealthChecks("/health");   // liveness
app.MapHealthChecks("/ready");    // readiness (extend with checks as needed)
app.MapGet("/", () => "melissa-address-verifier");

app.Run();
```

## 5.10 Running a Batch

A hosted background service is the entry point. It reads a batch of addresses (file mode shown; swap the source for a queue consumer in production), verifies them concurrently, writes the output, and signals shutdown so the container exits cleanly when the run completes. Because the verifier is transient, the worker resolves it from a fresh DI scope.

*Listing 5-13. VerificationWorker.cs*

```csharp
using System.Diagnostics;
using System.Text.Json;
using MelissaAddressVerifier.Models;

namespace MelissaAddressVerifier;

public sealed class VerificationWorker(
    IServiceScopeFactory scopeFactory,
    IHostApplicationLifetime lifetime,
    ILogger<VerificationWorker> logger) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var inputPath  = Environment.GetEnvironmentVariable("INPUT_FILE")  ?? "addresses.json";
        var outputPath = Environment.GetEnvironmentVariable("OUTPUT_FILE") ?? "verified.json";

        await using var input = File.OpenRead(inputPath);
        var records = await JsonSerializer.DeserializeAsync<List<RequestRecord>>(
                          input, cancellationToken: stoppingToken) ?? [];

        using var scope = scopeFactory.CreateScope();
        var verifier = scope.ServiceProvider.GetRequiredService<BatchAddressVerifier>();

        var sw = Stopwatch.StartNew();
        var results = await verifier.VerifyAllAsync(records, stoppingToken);
        var deliverable = results.Count(r => ResultInterpreter.IsDeliverable(r.Results));

        await using var output = File.Create(outputPath);
        await JsonSerializer.SerializeAsync(
            output, results, new JsonSerializerOptions { WriteIndented = true }, stoppingToken);

        logger.LogInformation(
            "Verified {Total} records ({Deliverable} deliverable) in {Seconds:F2}s -> {Path}",
            results.Count, deliverable, sw.Elapsed.TotalSeconds, outputPath);

        lifetime.StopApplication();   // batch mode: exit after the run completes
    }
}
```

## 5.11 Testing

The interpreter is pure logic and is unit-tested directly with xUnit. A theory drives every verdict branch without calling the live API or consuming credits; the verifier can be tested similarly against a stubbed client.

*Listing 5-14. ResultInterpreterTests.cs*

```csharp
using Xunit;
using MelissaAddressVerifier;

public class ResultInterpreterTests
{
    [Theory]
    [InlineData("AV25,GS05", Verdict.Verified)]
    [InlineData("AV24",      Verdict.Verified)]
    [InlineData("AV22,AC01", Verdict.Corrected)]
    [InlineData("AE05",      Verdict.Ambiguous)]
    [InlineData("AV12",      Verdict.Unverified)]
    [InlineData("SE01",      Verdict.Error)]
    [InlineData("",          Verdict.Unverified)]
    public void Classify_MapsCodesToVerdict(string codes, Verdict expected) =>
        Assert.Equal(expected, ResultInterpreter.Classify(codes));

    [Theory]
    [InlineData("AV25", true)]
    [InlineData("AV22,AC01", true)]
    [InlineData("AV12", false)]
    [InlineData("SE01", false)]
    public void IsDeliverable_OnlyVerifiedOrCorrected(string codes, bool expected) =>
        Assert.Equal(expected, ResultInterpreter.IsDeliverable(codes));
}
```

# 6. Containerization

## 6.1 Multi-Stage Dockerfile

A build stage restores and publishes with the full SDK; a slim runtime stage carries only the ASP.NET Core runtime and the published output, runs as the non-root user that ships in the .NET base images, and binds the health endpoints to the probe port.

*Listing 6-1. Dockerfile*

```dockerfile
# ---------- build stage ----------
FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src
COPY src/MelissaAddressVerifier/MelissaAddressVerifier.csproj ./MelissaAddressVerifier/
RUN dotnet restore ./MelissaAddressVerifier/MelissaAddressVerifier.csproj
COPY src/MelissaAddressVerifier/ ./MelissaAddressVerifier/
RUN dotnet publish ./MelissaAddressVerifier/MelissaAddressVerifier.csproj \
    -c Release -o /app /p:UseAppHost=false

# ---------- runtime stage ----------
FROM mcr.microsoft.com/dotnet/aspnet:9.0 AS runtime
WORKDIR /app
COPY --from=build /app ./
# The .NET base images ship a non-root user; $APP_UID is its UID.
USER $APP_UID
ENV ASPNETCORE_URLS=http://+:8080 \
    DOTNET_gcServer=1 \
    DOTNET_TieredPGO=1
EXPOSE 8080
ENTRYPOINT ["dotnet", "MelissaAddressVerifier.dll"]
```

## 6.2 .NET Runtime Tuning for Containers

The .NET runtime is container-aware: it reads cgroup CPU and memory limits automatically and sizes the GC heap and thread pool accordingly, so there is usually nothing to hard-code. Set the container memory limit in Terraform (Section 7) and let the runtime honor it. If you need an explicit ceiling, prefer `DOTNET_GCHeapHardLimitPercent` (a fraction of the cgroup limit) over a fixed byte limit, so the cap tracks the size you provision.

| Variable | Purpose |
| --- | --- |
| `DOTNET_gcServer=1` | Server GC: parallel, throughput-oriented collection — the right default for a multi-core, I/O-bound replica. |
| `DOTNET_GCHeapHardLimitPercent` | Optional hard cap on the managed heap as a percentage of the container memory limit. |
| `DOTNET_TieredPGO=1` | Profile-guided optimization for better steady-state throughput on long-running workloads. |
| `ASPNETCORE_URLS=http://+:8080` | Binds the host (and health endpoints) to the container's probe port. |

## 6.3 Build, Tag, and Push

Build locally then push to Azure Container Registry, or let ACR build server-side (no local Docker daemon needed):

```bash
# Option A: local build + push
az acr login --name acrmelissaav
docker build -t acrmelissaav.azurecr.io/melissa-address-verifier:1.0.0 .
docker push acrmelissaav.azurecr.io/melissa-address-verifier:1.0.0

# Option B: server-side build in ACR
az acr build --registry acrmelissaav \
  --image melissa-address-verifier:1.0.0 .
```

# 7. Infrastructure as Code with Terraform

## 7.1 Target Platform and File Layout

The Terraform configuration provisions an Azure Container Apps environment and every supporting resource: a Log Analytics workspace for logs, an Azure Container Registry for the image, a user-assigned managed identity for secretless access, a Key Vault holding the Melissa license key, and a Storage queue that drives autoscaling. The configuration is language-neutral — it is identical whether the image contains the C#/.NET or any other implementation. All files live under `infra/`.

```text
infra/
  providers.tf      # terraform + provider + remote state backend
  variables.tf      # inputs (image, region, scaling, license key)
  main.tf           # all resources
  outputs.tf        # registry server, app FQDN, queue name
  terraform.tfvars  # non-secret values (license key via TF_VAR_*)
```

## 7.2 Providers and Remote State

*Listing 7-1. infra/providers.tf*

```hcl
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }

  backend "azurerm" {
    # Provide via:  terraform init -backend-config=backend.hcl
    # resource_group_name  = "rg-tfstate"
    # storage_account_name = "sttfstateexample"
    # container_name       = "tfstate"
    # key                  = "melissa-verifier.tfstate"
  }
}

provider "azurerm" {
  features {}
}
```

## 7.3 Input Variables

*Listing 7-2. infra/variables.tf*

```hcl
variable "location"        { type = string  default = "centralus" }
variable "name_prefix"     { type = string  default = "melissaav" }

variable "container_image" {
  description = "Fully qualified image reference, registry/repo:tag."
  type        = string
}

variable "melissa_license_key" {
  description = "Supplied via TF_VAR_melissa_license_key; never committed."
  type        = string
  sensitive   = true
}

variable "min_replicas"    { type = number  default = 0 }
variable "max_replicas"    { type = number  default = 10 }
variable "cpu"             { type = number  default = 1.0 }
variable "memory"          { type = string  default = "2Gi" }

variable "max_concurrency" {
  description = "In-process concurrent Melissa requests per replica."
  type        = number
  default     = 8
}
```

## 7.4 Core Resources

The resource group, observability workspace, registry, and the managed identity that ties them together. The identity is granted only AcrPull on the registry.

*Listing 7-3. infra/main.tf (resource group, logging, registry, identity)*

```hcl
data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "this" {
  name     = "rg-${var.name_prefix}"
  location = var.location
}

resource "azurerm_log_analytics_workspace" "this" {
  name                = "log-${var.name_prefix}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_container_registry" "this" {
  name                = "acr${var.name_prefix}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "Standard"
  admin_enabled       = false
}

resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${var.name_prefix}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}
```

## 7.5 Secrets and the Job Queue

Key Vault stores the license key under RBAC. The deploying principal gets Secrets Officer to write it; the app identity gets the read-only Secrets User role. A Storage queue receives address-batch jobs and is the autoscaling signal.

*Listing 7-4. infra/main.tf (Key Vault + queue)*

```hcl
resource "azurerm_key_vault" "this" {
  name                      = "kv-${var.name_prefix}"
  location                  = azurerm_resource_group.this.location
  resource_group_name       = azurerm_resource_group.this.name
  tenant_id                 = data.azurerm_client_config.current.tenant_id
  sku_name                  = "standard"
  enable_rbac_authorization = true
}

resource "azurerm_role_assignment" "kv_deployer" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "kv_app_reader" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_key_vault_secret" "license" {
  name         = "melissa-license-key"
  value        = var.melissa_license_key
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [azurerm_role_assignment.kv_deployer]
}

resource "azurerm_storage_account" "queue" {
  name                     = "st${var.name_prefix}"
  resource_group_name      = azurerm_resource_group.this.name
  location                 = azurerm_resource_group.this.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

resource "azurerm_storage_queue" "jobs" {
  name                 = "address-jobs"
  storage_account_name = azurerm_storage_account.queue.name
}
```

## 7.6 Container Apps Environment and the App

The environment links to Log Analytics. The container app uses the managed identity to pull the image and resolve the Key Vault-backed secret, injects configuration as environment variables, declares liveness/readiness probes, and defines a KEDA queue-depth scale rule.

*Listing 7-5. infra/main.tf (Container Apps environment + app)*

```hcl
resource "azurerm_container_app_environment" "this" {
  name                       = "cae-${var.name_prefix}"
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
}

resource "azurerm_container_app" "verifier" {
  name                         = "ca-${var.name_prefix}"
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = azurerm_resource_group.this.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.this.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  secret {
    name                = "melissa-license-key"
    key_vault_secret_id = azurerm_key_vault_secret.license.id
    identity            = azurerm_user_assigned_identity.app.id
  }

  secret {
    name  = "queue-connection"
    value = azurerm_storage_account.queue.primary_connection_string
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    container {
      name   = "verifier"
      image  = var.container_image
      cpu    = var.cpu
      memory = var.memory

      env { name = "MELISSA_LICENSE_KEY"   secret_name = "melissa-license-key" }
      env { name = "MELISSA_BATCH_SIZE"    value       = "100" }
      env { name = "MELISSA_MAX_CONCURRENCY" value     = tostring(var.max_concurrency) }

      liveness_probe  { transport = "HTTP"  path = "/health"  port = 8080 }
      readiness_probe { transport = "HTTP"  path = "/ready"   port = 8080 }
    }

    custom_scale_rule {
      name             = "queue-depth"
      custom_rule_type = "azure-queue"
      metadata = {
        queueName   = azurerm_storage_queue.jobs.name
        queueLength = "50"   # ~1 replica per 50 queued jobs
      }
      authentication {
        secret_name       = "queue-connection"
        trigger_parameter = "connection"
      }
    }
  }

  depends_on = [azurerm_role_assignment.acr_pull]
}
```

## 7.7 Outputs

*Listing 7-6. infra/outputs.tf*

```hcl
output "resource_group"        { value = azurerm_resource_group.this.name }
output "registry_login_server" { value = azurerm_container_registry.this.login_server }
output "container_app_fqdn"    { value = azurerm_container_app.verifier.latest_revision_fqdn }
output "jobs_queue_name"       { value = azurerm_storage_queue.jobs.name }
```

## 7.8 Deployment Workflow

There is a deliberate ordering constraint: the container app references an image that must already exist in the registry, but the registry is created by this same configuration. Resolve it by applying in two passes — create the registry, push the image, then apply the rest.

1. Authenticate and select the subscription: `az login` then `az account set -s <sub-id>`.
2. Provision the registry first: `terraform apply -target=azurerm_container_registry.this`.
3. Build and push the image to that registry (Section 6.3).
4. Export the secret: `export TF_VAR_melissa_license_key="<key>"`.
5. Full apply: `terraform init`, `terraform plan`, `terraform apply`.
6. Seed the queue with address-batch jobs; KEDA scales replicas to drain it.
7. Tear down when finished: `terraform destroy`.

# 8. Operations and Observability

## 8.1 Logging and Metrics

Container stdout/stderr flows to the linked Log Analytics workspace; query application logs with the ContainerAppConsoleLogs_CL table in Log Analytics. Polly v8 publishes resilience telemetry through System.Diagnostics.Metrics (the "Polly" meter) and event sources, which can be exported via OpenTelemetry to surface retry counts, rate-limiter rejections, and circuit-breaker state.

## 8.2 Scaling Behavior

Two axes operate together. **Inside a replica**, throughput is governed by `MELISSA_MAX_CONCURRENCY` and the rate limiter. **Across replicas**, KEDA adds or removes instances based on queue length, scaling to zero when the queue is empty (set `min_replicas = 0`). The product of per-replica concurrency and replica count must still respect the Melissa contract — size them together, not independently.

## 8.3 Cost Considerations

- Scale-to-zero means you pay for compute only while jobs are queued.
- Each verified record consumes Melissa credits; batching reduces HTTP overhead but not credit consumption — deduplicate addresses before verifying where possible.
- Log Analytics ingestion is billed per GB; tune log verbosity in production.

# 9. Reference Guide

## 9.1 Melissa Result Code Quick Reference

Summary of the commonly encountered families. Codes are returned comma-delimited in the `Results` field. This is a working summary; consult Melissa's official Result Code reference (Section 9.8) for the complete, authoritative list.

| Code / Family | Meaning (summary) |
| --- | --- |
| `AV25` | Full verification to the delivery-point level — highest confidence. |
| `AV24` | Full verification to the sub-premise (e.g., apartment/suite). |
| `AV23` | Full verification to the premise (building). |
| `AV22` | Full verification to the thoroughfare (street). |
| `AV21` | Full verification to the locality (city). |
| `AV11–AV14` | Partial verification only at the corresponding level; treat as not deliverable. |
| `AC01..AC03..` | Address Change — a component (postal code, locality, admin area, etc.) was corrected. |
| `AE01..AE17..` | Address Error — a component is invalid or could not be confirmed. |
| `AE05` | Multiple addresses matched the input (ambiguous). |
| `GS01–GS06` | Geocode Status — from rooftop (best) down to postal-code centroid. |
| `GE / SE` | Geocode/Service error families — treat as failures for routing. |

## 9.2 Key Request and Response Fields

| Field | Direction | Notes |
| --- | --- | --- |
| `CustomerID` | Request | Melissa license key (body) or id query param. |
| `Records[].RecordID` | Both | Caller-assigned key used to align responses. |
| `AddressLine1 / 2` | Both | Street address lines. |
| `Locality` | Both | City. |
| `AdministrativeArea` | Both | State / province / region. |
| `PostalCode` | Both | ZIP / postal code (corrected on output). |
| `Country` | Request | ISO-3166-1 alpha-2 (e.g., US). |
| `Results` | Response | Comma-delimited result codes — the primary signal. |
| `FormattedAddress` | Response | Single standardized, postally formatted string. |
| `Latitude / Longitude` | Response | Geocode when available (see GS codes). |

## 9.3 Configuration (Environment Variables)

| Variable | Default | Purpose |
| --- | --- | --- |
| `MELISSA_LICENSE_KEY` | `(required)` | Account license key; injected from Key Vault. |
| `MELISSA_BASE_URL` | `doGlobalAddress` | Endpoint URL override. |
| `MELISSA_BATCH_SIZE` | `100` | Records per HTTP request. |
| `MELISSA_MAX_CONCURRENCY` | `8` | Concurrent in-flight requests per replica. |
| `MELISSA_RPS` | `10` | Requests-per-second rate-limit ceiling. |
| `MELISSA_MAX_RETRIES` | `4` | Retry attempts for transient failures. |
| `MELISSA_REQUEST_TIMEOUT_MS` | `15000` | Per-attempt request timeout. |
| `INPUT_FILE / OUTPUT_FILE` | `addresses.json` | Batch I/O paths (file mode). |

## 9.4 Terraform Resource Summary

| Resource | Role |
| --- | --- |
| `azurerm_resource_group` | Container for all resources. |
| `azurerm_log_analytics_workspace` | Centralized logs/metrics. |
| `azurerm_container_registry` | Stores the application image. |
| `azurerm_user_assigned_identity` | Secretless pull + Key Vault access. |
| `azurerm_key_vault(_secret)` | Holds the Melissa license key. |
| `azurerm_storage_queue` | Job intake and autoscale signal. |
| `azurerm_container_app_environment` | Container Apps runtime + log link. |
| `azurerm_container_app` | The verifier workload + scale rules. |

## 9.5 Command Reference

```bash
# Build & test (.NET CLI)
dotnet build -c Release            # compile the solution
dotnet test                        # run unit tests
dotnet publish -c Release -o out   # framework-dependent publish

# Container (Docker / ACR)
docker build -t <registry>/melissa-address-verifier:1.0.0 .
az acr build --registry <acr> --image melissa-address-verifier:1.0.0 .

# Infrastructure (Terraform)
terraform init -backend-config=backend.hcl
terraform apply -target=azurerm_container_registry.this   # pass 1
terraform plan
terraform apply                                           # pass 2
terraform destroy

# Operations (Azure CLI)
az containerapp logs show -n ca-melissaav -g rg-melissaav --follow
az containerapp revision list -n ca-melissaav -g rg-melissaav -o table
```

## 9.6 Tuning Cheat Sheet

| Symptom | Likely lever |
| --- | --- |
| Throughput too low | Raise MELISSA_MAX_CONCURRENCY and MELISSA_RPS (within contract); raise max_replicas. |
| HTTP 429 / rate errors | Lower MELISSA_RPS and/or MELISSA_MAX_CONCURRENCY; confirm contract limits. |
| OutOfMemory in container | Increase memory; set DOTNET_GCHeapHardLimitPercent; reduce batch size if responses are large. |
| Circuit breaker keeps opening | Endpoint degraded; check Melissa status, raise BreakDuration briefly. |
| Replicas not scaling | Check queue-depth rule, queueLength threshold, and the queue-connection secret. |

## 9.7 Troubleshooting

| Issue | Resolution |
| --- | --- |
| Startup fails: missing env var | MELISSA_LICENSE_KEY not resolved — verify Key Vault secret + identity role assignment. |
| All records return error sentinel | Network egress blocked or wrong base URL; test connectivity to address.melissadata.net. |
| Image pull fails | AcrPull role missing on the user-assigned identity, or registry server mismatch. |
| Terraform apply ordering error | Run the two-pass workflow (Section 7.8); registry must exist before the app references the image. |
| Readiness probe never passes | Health endpoints not mapped or ASPNETCORE_URLS not bound to 8080; confirm /ready responds. |

## 9.8 External References

- Melissa — Global Address Verification product and developer portal: `https://www.melissa.com`
- Melissa — Result Code reference (authoritative code list): the Result Codes pages on `wiki.melissadata.com`
- Microsoft — Azure Container Apps documentation: `https://learn.microsoft.com/azure/container-apps`
- HashiCorp — azurerm provider (Container Apps resources): `https://registry.terraform.io/providers/hashicorp/azurerm`
- Microsoft — IHttpClientFactory and typed clients: `https://learn.microsoft.com/dotnet/core/extensions/httpclient-factory`
- Microsoft — Building resilient HTTP apps (Microsoft.Extensions.Http.Resilience): `https://learn.microsoft.com/dotnet/core/resilience/http-resilience`
- Polly — v8 resilience strategies (retry, circuit breaker, rate limiter, timeout): `https://www.pollydocs.org`

*— End of Guide —*

