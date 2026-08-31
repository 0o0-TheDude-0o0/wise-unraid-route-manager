#!/bin/sh
set -eu

version=${1:?usage: build-release-assets.sh VERSION OWNER [REPOSITORY] [OUTPUT_DIR]}
owner=${2:?GitHub owner is required}
repository=${3:-wise-route-manager}
output=${4:-dist}

case "$version" in *[!0-9A-Za-z._-]*|'') echo "invalid version" >&2; exit 1;; esac
case "$owner/$repository" in *[!0-9A-Za-z._/-]*|/*|*/|*//* ) echo "invalid GitHub owner or repository" >&2; exit 1;; esac

mkdir -p "$output"
package_version=$(printf '%s\n' "$version" | tr '-' '_')
package="$output/wise.route.manager-$package_version-noarch-1.txz"
tar --xz --create --file "$package" --owner=0 --group=0 --numeric-owner -C unraid-plugin .
md5=$(md5sum "$package" | awk '{print $1}')

sed -e "s|@VERSION@|$version|g" -e "s|@PACKAGE_VERSION@|$package_version|g" -e "s|@OWNER@|$owner|g" -e "s|@REPOSITORY@|$repository|g" -e "s|@MD5@|$md5|g" \
  packaging/wise.route.manager.plg.in > "$output/wise.route.manager.plg"
sed -e "s|OWNER|$owner|g" templates/wise-route-manager.xml > "$output/wise-route-manager.xml"
sed -e "s|OWNER|$owner|g" templates/wise-route-manager-lite.xml > "$output/wise-route-manager-lite.xml"

sha256sum "$package" "$output/wise.route.manager.plg" "$output/wise-route-manager.xml" "$output/wise-route-manager-lite.xml" > "$output/SHA256SUMS"
echo "Release assets written to $output"
