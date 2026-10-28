#!/bin/bash
# Puts the files of one GitHub Release of this repository where the mod's build takes them from
# (webcam/build, qemu/build, additions/build), after checking every file against the release's SHA256SUMS.
# The mod's jars then carry exactly the released files.
#
#   ./fetch-release.sh v0.1.1
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
TAG=${1:?usage: fetch-release.sh <tag>}
REPO=LeonardBongard/virtual-machine-desktops-native
T=$(mktemp -d)
curl -fsSL "https://github.com/$REPO/releases/download/$TAG/vmd-native-$TAG.zip" -o "$T/r.zip"
curl -fsSL "https://github.com/$REPO/releases/download/$TAG/SHA256SUMS" -o "$T/SHA256SUMS"
mkdir -p "$T/r" && unzip -q "$T/r.zip" -d "$T/r"
(cd "$T/r" && shasum -a 256 -c "$T/SHA256SUMS")
for d in webcam qemu additions; do
	mkdir -p "$HERE/$d/build" && cp -R "$T/r/$d/." "$HERE/$d/build/"
done
chmod +x "$HERE"/webcam/build/*/vmd-webcam* 
echo "$TAG" > "$HERE/RELEASE-IN-USE"
echo "release $TAG in place"
