# Private beta installation

Do not reuse the Unraid host address. Assign the container an unused, reserved
address on `br0`; ports 80 and 443 belong to Caddy on that address, while the
management UI uses port 9080.

## Prerequisites

- Unraid 7.2 or later.
- A reserved LAN address outside the DHCP pool.
- A PEM certificate or full chain covering every managed LAN hostname.
- The matching unencrypted PEM private key.
- Certificate and key files readable by container UID 1000.
- Restricted API credentials for the selected DNS provider and Pangolin.

Mount the certificate read-only at `/config/tls/tls.crt` and the key read-only
at `/config/tls/tls.key`. The container fails closed when either file is absent
or unreadable. Caddy redirects port 80 to HTTPS and uses only the supplied
certificate on port 443; it does not request or renew certificates.

Leave `WISE_ENABLE_PROVIDER_MUTATIONS=0` during onboarding. Connect providers,
run discovery and audits, verify backups, and preview the exact plan first. Set
the variable to `1` only when ready to approve live transactions.

The API token is generated at `/config/api-token`. Treat it as a secret. The
optional Unraid plugin stores only the application URL in
`/boot/config/plugins/wise.route.manager/wise.route.manager.cfg`:

```ini
APP_URL="http://192.168.1.50:9080"
```

Removing the plugin does not remove or stop the container. Removing the
container must not delete its appdata directory unless the operator separately
chooses to erase desired state, encrypted credentials, backups, and audit logs.
