# Release process

Releases are generated only from version tags. Before tagging:

1. Run `python -m unittest discover -s tests -v`.
2. Run `WISE_SMOKE_BUILD=1 scripts/container-smoke.sh` with Podman, or build and
   run `/app/container/smoke.sh` with Docker.
3. Confirm the release version and changelog.
4. Confirm the GitHub repository owner and visibility.
5. Confirm GHCR packages should be public before Community Applications use.
6. Test the generated plugin package on a disposable supported Unraid system.

To inspect assets locally:

```bash
scripts/build-release-assets.sh 0.1.0 GITHUB_OWNER wise-route-manager dist
```

Pushing `v0.1.0` runs tests, publishes amd64/arm64 images to GHCR, builds the
versioned `.txz`, generates the `.plg` and Community Applications XML, records
SHA-256 checksums, and creates a GitHub release. Publishing and Unraid/App Store
submission remain deliberate external actions and are not performed by tests.
