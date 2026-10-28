#!/bin/bash
# Builds the VMD Additions CD from the files in this folder: the RPM with rpmbuild, the CD image with xorriso.
# Runs inside Fedora (the GitHub Actions job uses the fedora:44 container): dnf install rpm-build xorriso
# SOURCE_DATE_EPOCH (the commit's time) fixes every timestamp, so the same commit gives the same files.
# Output: additions/build/vmd-additions.iso
#
#   additions/build.sh
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
B="$HERE/build"
rm -rf "$B" && mkdir -p "$B/rpmbuild/SOURCES" "$B/rpmbuild/SPECS" "$B/cd"
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(git -C "$HERE" log -1 --format=%ct)}
cp "$HERE"/vmd-agent.py "$HERE"/vmd-agent.service "$HERE"/vmd-additions-setup.sh "$HERE"/vmd-additions-setup.service \
	"$HERE"/60-vmd-additions.rules "$HERE"/vmd-v4l2loopback.conf "$HERE"/vmd-modules-load.conf "$B/rpmbuild/SOURCES/"
cp "$HERE"/vmd-additions.spec "$B/rpmbuild/SPECS/"
rpmbuild -bb --quiet --define "_topdir $B/rpmbuild" \
	--define "use_source_date_epoch_as_buildtime 1" --define "clamp_mtime_to_source_date_epoch 1" \
	"$B/rpmbuild/SPECS/vmd-additions.spec"
REL=$(awk '/^Version:/{v=$2} /^Release:/{r=$2} END{print v "-" r}' "$HERE/vmd-additions.spec")
cp "$B/rpmbuild/RPMS/noarch/vmd-additions-$REL.noarch.rpm" "$B/cd/Install VMD Additions.rpm"
cat > "$B/cd/README.txt" <<'TXT'
VMD Additions — microphone and cameras from Minecraft

Double-click "Install VMD Additions.rpm", click Install, and type your password.
Then wait a few minutes: the camera driver is set up in the background (it needs the internet once).
TXT
touch -d "@$SOURCE_DATE_EPOCH" "$B/cd"/*
xorriso -as mkisofs -quiet -o "$B/vmd-additions.iso" -V VMD_ADDITIONS -J -joliet-long -r "$B/cd"
ls -la "$B/vmd-additions.iso"
