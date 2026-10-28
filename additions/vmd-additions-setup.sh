#!/bin/sh
# Runs once, as root, in the background after VMD Additions is installed: brings the camera driver (v4l2loopback,
# from RPM Fusion, which Fedora itself does not carry) and loads it with the two cameras' names.
set -e
DONE=/var/lib/vmd-additions/setup-done
[ -e "$DONE" ] && exit 0
mkdir -p /var/lib/vmd-additions
# GNOME Software may still hold the package lock from installing us: wait for it
for i in $(seq 120); do dnf -q repolist >/dev/null 2>&1 && break; sleep 5; done
if ! rpm -q rpmfusion-free-release >/dev/null 2>&1; then
	dnf -y install "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm"
fi
dnf -y install akmod-v4l2loopback "kernel-devel-$(uname -r)"
# The driver's build tools pull in the newest kernel's headers and core only. Make every installed kernel whole (its
# modules hold the sound and video drivers), or the next boot starts a kernel without sound and without the cameras.
for v in $(rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-core); do
	rpm -q "kernel-modules-$v" >/dev/null 2>&1 || dnf -y install "kernel-$v" "kernel-modules-$v" "kernel-modules-extra-$v"
	akmods --kernels "$v" || :
done
akmods --force --kernels "$(uname -r)"
modprobe v4l2loopback
touch "$DONE"
