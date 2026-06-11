using System.Text.Json.Serialization;

namespace AddressVerification;

// Source-generated serializer metadata: no per-request reflection, fewer
// allocations. Runtime options (camelCase web defaults) still apply, so the
// wire format is unchanged. Every type written to or read from an endpoint
// must be listed here.
[JsonSerializable(typeof(List<AddressResult>))]
[JsonSerializable(typeof(StatsResponse))]
[JsonSerializable(typeof(VerifyRequest))]
[JsonSerializable(typeof(SubmitRequest))]
[JsonSerializable(typeof(HealthResponse))]
[JsonSerializable(typeof(ErrorResponse))]
[JsonSerializable(typeof(SubmitResponse))]
internal partial class AppJsonContext : JsonSerializerContext
{
}
