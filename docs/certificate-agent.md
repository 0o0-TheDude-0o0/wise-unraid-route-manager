# VPS certificate agent

The optional certificate agent is a narrowly scoped, read-only companion for
self-hosted Pangolin. It exposes one authenticated HTTPS operation to Route
Manager through the private Newt path.

## Security boundary

- Mount Traefik's `acme.json` read-only.
- Bind port 9443 only to a private address reachable from the Newt site.
- Never publish port 9443 through the VPS firewall or Pangolin public resources.
- Store a random token of at least 32 characters in a mode-0600 file.
- Mount an internal TLS certificate and key read-only.
- Add each permitted wildcard with a separate `--allowed-name` argument.
- Run rootless, read-only, with all Linux capabilities dropped.

The only certificate response is `GET /v1/certificate?name=*.example.com` with
the scoped bearer token. Names must exactly match the allowlist. The service
rate-limits requests, emits a secret-free success audit event, and contains no
write operation for Pangolin, Traefik, or ACME storage.

Route Manager checks for renewal every six hours by default. Automatic
installation remains inactive until an operator has completed the first
preview-and-approve synchronization, enabled automatic renewal, and enabled
provider mutations. A candidate must have a different fingerprint and a later
expiration date. Validation and rollback are identical to the first install.
Set `WISE_CERT_RENEWAL_INTERVAL_SECONDS` to change the interval; values below
300 seconds are clamped to 300.

Build with `Containerfile.cert-agent`. Review and replace every placeholder in
`container/cert-agent.compose.yml`, especially `OWNER`, the wildcard name, and
`PRIVATE_NEWT_IP`, before deployment.
