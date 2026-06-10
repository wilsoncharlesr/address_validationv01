# Multi-stage build for the C# address-verification API.
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

# Restore first (cached unless the project file changes), then build.
COPY AddressVerification.csproj ./
RUN dotnet restore

COPY . ./
RUN dotnet publish AddressVerification.csproj -c Release -o /app /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app ./

ENV ASPNETCORE_URLS=http://+:8080
EXPOSE 8080

ENTRYPOINT ["dotnet", "AddressVerification.dll"]
