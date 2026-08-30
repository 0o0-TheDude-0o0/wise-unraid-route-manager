# Wise Route Manager

Wise Route Manager provides one place to define a service route and safely
coordinate the infrastructure needed to reach it:

- Technitium split-horizon DNS for direct LAN access.
- Caddy reverse proxying for LAN clients.
- Pangolin resources and targets for remote access.
- A thin Unraid plugin that links the application into the Unraid webGUI.

The route engine is distributed as a container. The Unraid plugin is optional;
routing continues if the plugin is removed or the Unraid webGUI is unavailable.

## Route Manager Lite

The same tested engine also ships with a focused route-only interface. Set
`WISE_EDITION=lite` or use `templates/wise-route-manager-lite.xml`. Lite keeps
only route health, reviewed correction, quick creation, Technitium, Pangolin,
and LAN proxy setup. Its read-only Unraid inspection detects Caddy, Nginx Proxy
Manager, SWAG, and Traefik before suggesting bundled Caddy. Existing proxies are
preserved; non-Caddy proxies are reported as requiring their own connection
adapter rather than being modified through an unsafe generic configuration.
The Lite inventory keeps Pangolin resources, Technitium zone records, and
reverse-proxy routes in separate lists, reports hostname resolution, and lets
an operator copy a discovered item into the reviewed adoption/update form. Its
port manager lists Unraid containers with published services, IP/binding data,
host and container ports, and quick upstream selection.

Lite assumes the normal deployment topology: Pangolin and the reverse proxy it
installs live together on a VPS, while Newt, Technitium, and an optional LAN
reverse proxy live on the Unraid side. The Pangolin-owned VPS proxy is treated as part of one edge
stack and is inspected through the Pangolin API; it is never rewritten as an
independent proxy. Proxy discovery on Unraid applies only to the LAN path.
Nginx Proxy Manager can be connected with a bearer token for read-only proxy
host inventory using its official `/api/nginx/proxy-hosts` endpoint. Write
support remains disabled until certificate selection, access-list preservation,
advanced configuration, and rollback behavior are represented in reviewed plans.

For LAN TLS, operators can choose independent DNS-01 issuance or a reviewed,
pull-only synchronization from a private certificate endpoint reached through
Newt. Synchronization validates the PEM, matching private key, expected SAN or
wildcard, validity window, and fingerprint in memory. Installation uses a
short-lived one-time approval, atomic mode-0600 writes, Caddy validation and
reload, and restoration of both previous files if validation or reload fails.
The private endpoint itself is a separate VPS deployment component and is not
created automatically by Route Manager.

## Safety model

- Planning is read-only and is always performed before an apply.
- Apply requests must include the current plan's one-time confirmation token.
- Secrets are accepted only by the backend and are never returned by its API.
- Saved integration credentials use authenticated encryption with an independent
  mode-0600 master key; API responses contain redacted metadata only.
- Provider credentials should be limited API tokens, not administrator passwords.
- The Caddy admin endpoint is private to the container.
- Every mutation is written to an append-only audit log.
- Read-only audits classify routes as healthy, drifted, broken, incomplete,
  unmanaged, or conflicting and produce provider-specific correction previews.
- The previous desired state and Caddy configuration are retained for rollback.
- The container does not require the Docker socket, privileged mode, or Unraid
  filesystem mounts other than its dedicated `/config` volume.

## Repository layout

```text
app/                 Python route engine and web application
container/           Container entry point and Caddy configuration
unraid-plugin/       Thin native Unraid webGUI integration
templates/           Community Applications template
tests/               Unit and API tests
docs/                Architecture and operator documentation
packaging/           Versioned Unraid plugin release template
scripts/             Reproducible packaging and container smoke tests
```

Planned guided bundles cover new local-only installations, Newt pairing, and an
optional Pangolin VPS bootstrap. See `docs/architecture.md`; these deployment
features are roadmap items and are not enabled in the development build.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m app --config-dir /tmp/wise-route-manager --listen 127.0.0.1:9080
```

Open `http://127.0.0.1:9080`. Development mode generates an initial API token
in the configuration directory and prints only its file location.

Provider mutations are guarded by `WISE_ENABLE_PROVIDER_MUTATIONS=1` and remain
off by default. When enabled, a reviewed plan reconciles its exact Technitium,
AdGuard Home, or Pi-hole answer, reloads validated Caddy configuration, and
reconciles the Pangolin public resource and target as one compensating
transaction. Only the providers required by the selected route mode are used.
Desired state is saved only after every step succeeds.

Production LAN routing requires a user-supplied PEM certificate and matching
private key mounted read-only. See `docs/installation.md`. Release construction
and publication are documented in `docs/releasing.md`.

## Status

This repository is under active development. Discovery and auditing are
functional; guarded transactional mutation support is implemented but disabled
by default. The generated artifacts are suitable for isolated private-beta
validation, not unattended production deployment. Complete the release checklist
in `docs/architecture.md` before a public stable release.
