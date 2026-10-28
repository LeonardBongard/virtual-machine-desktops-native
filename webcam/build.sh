#!/bin/bash
# Builds the small webcam helper the mod runs on the player's computer, for every system the jar supports:
# macOS (Swift + AVFoundation, needs Xcode), Linux (V4L2) and Windows (Media Foundation), the last two with Zig.
# Output: webcam/build/<os>-<arch>/vmd-webcam[.exe] (copied into the jar by the build).
#
#   webcam/build.sh <zig>
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
ZIG=${1:?usage: webcam/build.sh <path to zig>}
B="$HERE/build"
mkdir -p "$B"/{macos-aarch64,macos-x86_64,linux-aarch64,linux-x86_64,windows-x86_64}
swiftc -O -target arm64-apple-macos11 "$HERE/vmd-webcam-mac.swift" -o "$B/macos-aarch64/vmd-webcam"
swiftc -O -target x86_64-apple-macos11 "$HERE/vmd-webcam-mac.swift" -o "$B/macos-x86_64/vmd-webcam"
for a in aarch64 x86_64; do
	"$ZIG" cc -O2 -s -static -target $a-linux-musl "$HERE/vmd-webcam-linux.c" -o "$B/linux-$a/vmd-webcam"
done
"$ZIG" cc -O2 -s -target x86_64-windows-gnu "$HERE/vmd-webcam-windows.c" -o "$B/windows-x86_64/vmd-webcam.exe" \
	-lmfplat -lmf -lmfreadwrite -lmfuuid -lole32
ls -l "$B"/*/vmd-webcam*
