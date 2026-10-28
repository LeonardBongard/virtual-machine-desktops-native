# Virtual Machine Desktops — native files

Everything that is not Java inside the [Virtual Machine Desktops](https://modrinth.com/mod/virtual-machine-desktops) jar, with its source
and the build that makes it. The Java mod itself is not here; these are the programs it starts and the CD it offers.

[`.github/workflows/build.yml`](.github/workflows/build.yml) builds every file below from this repository on GitHub's runners.
A tag `v*` publishes them as a GitHub Release with `SHA256SUMS`; the mod's jars carry exactly the files of a release.

| In the jar | What it is | Whose | Made by |
|---|---|---|---|
| `webcam/macos-aarch64/vmd-webcam`, `webcam/macos-x86_64/vmd-webcam` | reads the player's real webcam (AVFoundation) and writes raw frames to stdout | ours, [`webcam/vmd-webcam-mac.swift`](webcam/vmd-webcam-mac.swift) | `swiftc`, job `webcam-mac` |
| `webcam/linux-aarch64/vmd-webcam`, `webcam/linux-x86_64/vmd-webcam` | the same with V4L2 | ours, [`webcam/vmd-webcam-linux.c`](webcam/vmd-webcam-linux.c) | `zig cc`, static musl, job `webcam-zig` |
| `webcam/windows-x86_64/vmd-webcam.exe` | the same with Media Foundation | ours, [`webcam/vmd-webcam-windows.c`](webcam/vmd-webcam-windows.c) | `zig cc`, job `webcam-zig` |
| `additions/vmd-additions.iso` | a CD the player may insert into the virtual PC; holds one RPM (a Python agent, systemd units, a udev rule) and a README | ours, [`additions/`](additions/) | `rpmbuild` + `xorriso` in `fedora:44`, job `additions` |
| `qemu/macos-aarch64.zip` | QEMU and its libraries for Apple Silicon Macs | QEMU and Homebrew | [`qemu/bundle_mac.py`](qemu/bundle_mac.py), job `qemu-mac` |
| `qemu/windows-x86_64.zip` | QEMU and its DLLs for Windows | QEMU and MSYS2 | [`qemu/bundle_windows.py`](qemu/bundle_windows.py), job `qemu-windows` |
| `qemu/linux-x86_64.zip` | QEMU and its libraries for x86 Linux | QEMU and Alpine Linux | [`qemu/bundle_linux.py`](qemu/bundle_linux.py), job `qemu-linux` |

## The QEMU bundles are third-party

We compile no QEMU. Each bundle script downloads the official packages of a known distribution and zips the files QEMU needs:

- **Windows** — MSYS2's `mingw-w64-ucrt-x86_64-qemu` and the packages holding the DLLs it imports, from `mirror.msys2.org`. Files unchanged.
- **Linux** — Alpine Linux v3.23's `qemu-system-x86_64` and its dependencies (musl included, so it runs on any distribution), from `dl-cdn.alpinelinux.org`. Files unchanged.
- **macOS** — Homebrew's `qemu` bottle and its non-system libraries. **Changed in two ways only:** the library paths are rewritten to `@loader_path` (`install_name_tool`) so the bundle finds its own libraries, and every binary is signed again ad hoc, with the `com.apple.security.hypervisor` entitlement QEMU needs for Apple's virtualization.

Every bundle carries a `SOURCES.md` naming QEMU's version, its source tarball on `download.qemu.org`, and the exact version of every
package inside. The lists of the bundles in 0.1.0 are in [`qemu/sources/`](qemu/sources/). QEMU is GNU GPL v2; each library keeps its own licence.

## What the Additions do inside the virtual PC

Installing the RPM (the player double-clicks it and types their own password) adds a user service, `vmd-agent`, that talks to the mod
over a virtio serial port. The mod sends it microphone sound and camera pictures, which it turns into a PipeWire microphone and two
v4l2loopback cameras; it sends back only its version, byte counters, which cameras a program has open, and how the screens are arranged
(the message list is at the top of `vmd-agent.py`). A one-time system service installs the `v4l2loopback` camera driver from [RPM Fusion](https://rpmfusion.org) (needs the
internet once). See [`additions/vmd-additions.spec`](additions/vmd-additions.spec) and [`additions/vmd-agent.py`](additions/vmd-agent.py).

## Version 0.1.0

0.1.0 was built on a developer Mac before this repository existed; [`SHIPPED-0.1.0.sha256`](SHIPPED-0.1.0.sha256) lists its files.
From the next version on, the jars carry the files of a release of this repository, and their hashes match its `SHA256SUMS`.

## Licence

Our own code here (webcam helpers, Additions, bundle scripts) is MIT, see [LICENSE](LICENSE). QEMU and the packages in the bundles
keep their own licences.
