#!/bin/sh
# Stamp a new version on the page's files so every open board picks up the update.
# Run before `firebase deploy --only hosting`.
cd "$(dirname "$0")"
V=$(date +%Y-%m-%d.%H%M%S)
sed -i.bak -E "s/data-version=\"[^\"]+\"/data-version=\"$V\"/; s/\?v=[0-9.-]+/?v=$V/g" index.html && rm -f index.html.bak
printf '{ "v": "%s" }\n' "$V" > version.json
echo "Version $V"
