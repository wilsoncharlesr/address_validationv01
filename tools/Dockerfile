# PostgreSQL image for local address-verification development.
# Trust auth: no password required for any connection — local dev only.
FROM postgres:16

ENV POSTGRES_HOST_AUTH_METHOD=trust
ENV POSTGRES_DB=nad

EXPOSE 5432
