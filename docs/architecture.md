# Architecture

## Components

### Route Manager container

The container owns the desired route definitions, provider adapters, audit log,
and browser UI. It also runs Caddy for LAN reverse proxying. Caddy configuration
is generated exclusively from validated desired state.

The container is intended to receive a dedicated `br0` address on Unraid. This
allows Caddy to bind ports 80 and 443 without competing with Unraid's webGUI.
The operator must confirm that address availability and port ownership before
deployment.

### Unraid plugin

The plugin adds a Tools page that displays container health and opens Route
Manager. It does not hold provider credentials or mutate DNS/proxy resources.
Its removal must not affect existing routes.

### Providers

Provider integrations implement four operations: inspect, plan, apply, and
rollback. The first release supports HTTP/HTTPS routes only.

- Technitium: an A/AAAA record for LAN modes.
- Caddy: an HTTPS virtual host and reverse-proxy handler for LAN modes.
- Pangolin: a public resource and target for remote modes.

## Route model

Each route has a stable UUID and these principal fields:

- `name` and `hostname`
- `mode`: `lan`, `remote`, or `lan_remote`
- upstream `scheme`, `host`, and `port`
- LAN proxy address
- Pangolin site and domain identifiers
- authentication and health-check policy
- ownership metadata and last applied revision

Provider-specific IDs are state, not user input. Imports record existing IDs
without claiming ownership until the user approves adoption.

## Transaction model

1. Validate the desired route and reject unsafe or ambiguous values.
2. Inspect all providers without mutating them.
3. Produce a deterministic plan with before/after summaries.
4. Store the plan briefly and return a one-time confirmation token.
5. Apply in dependency order: DNS, local proxy, public route.
6. If a step fails, roll back successful steps in reverse order.
7. Persist the new desired state only after all steps succeed.
8. Append the complete result to the audit log.

Pangolin adoption is deliberately conservative. A duplicate hostname or an
existing resource/target response that omits fields needed for an exact restore
blocks mutation. Route Manager never deletes unrelated targets or policies.

Deletion is staged: disable, verify, then remove after a separate approval.

## Network boundaries

- Application API: container port 9080, authenticated.
- Caddy listeners: ports 80/443 on the container's dedicated LAN address.
- Caddy admin: Unix socket inside the container only.
- Provider APIs: outbound HTTPS to configured private endpoints.
- No Docker socket, host networking, privileged mode, or host root mount.

The Pangolin VPS Traefik instance remains untouched. Caddy handles LAN traffic
only; remote traffic continues through Pangolin, Gerbil/Newt, and Traefik.

## Persistent data

All persistent files live below `/config`:

```text
config.json             non-secret application settings
routes.json             desired route state
secrets.json            encrypted provider tokens (0600)
audit.jsonl             append-only audit events
backups/                timestamped pre-apply snapshots
caddy/                   generated and last-known-good configuration
```

The master-key path is selected with `WISE_MASTER_KEY_FILE`. The default CA
template keeps it under `/config` for recoverability, but higher-security
installations should mount that path from a separately backed-up secret file.
The key and encrypted store are both mode 0600. Environment-variable credential
values are not supported and secrets are never rendered back into the UI.

## Release gates

- Provider adapters have fixture-backed unit tests.
- Apply requires a valid, unexpired, single-use plan token.
- Caddy config passes `caddy validate` before reload.
- Rollback is tested for failure at every transaction step.
- Secret fields are redacted in responses and logs.
- Container runs as a non-root UID after binding through the dedicated address
  strategy is validated.
- CA template requires no privileged access or Docker socket.
- Installation and removal are tested on supported Unraid releases.

## Guided bundle roadmap

The normal application remains independently installable. A later setup wizard
will offer optional greenfield bundles without combining unrelated services into
one container:

- Local-only: Route Manager/Caddy plus one selected DNS provider.
- Homelab: local-only bundle plus a Newt connector paired to Pangolin.
- Existing infrastructure: discover and adopt services without reinstalling.

The wizard must inventory addresses and ports, preview all resources, pin image
versions, generate credentials, preserve existing services, and record ownership
in an installation manifest. Failure rolls back only resources created by the
current installation.

### Optional VPS deployment

For users without Pangolin, the wizard may prepare a remote control-plane install.
The recommended method is a signed, short-lived copy-and-run bootstrap command;
the application does not retain SSH credentials. Advanced alternatives are an
exported Compose package and a guided SSH deployment with host-key pinning,
temporary restricted credentials, explicit mutation approval, backups, port and
firewall previews, and post-install credential revocation.

The VPS bundle may include Pangolin, Gerbil, Pangolin's Traefik configuration,
and its database. It must never silently replace an existing installation or
change a cloud firewall. Newt remains on the private Unraid network.
