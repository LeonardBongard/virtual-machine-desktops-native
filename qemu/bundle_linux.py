#!/usr/bin/env python3
"""Packs the official, unchanged QEMU for x86 Linux PCs into one zip the mod carries in its jar.

Uses Alpine Linux's QEMU packages: built against musl, so the bundle carries its own C library and loader
(ld-musl) and runs on any Linux, whatever glibc it has. The mod starts QEMU through that loader:
`lib/ld-musl-x86_64.so.1 --library-path lib bin/qemu-system-x86_64 ...`.

    python3 -I qemu/bundle_linux.py <download dir>   # needs <dir>/index/{main,community}/APKINDEX (Alpine v3.23)

Downloads each needed .apk from dl-cdn.alpinelinux.org into <download dir>/apk (once), writes qemu/build/linux-x86_64.zip.
"""
import gzip
import io
import json
import pathlib
import sys
import tarfile
import urllib.request
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "build" / "linux-x86_64.zip"
MIRROR = "https://dl-cdn.alpinelinux.org/alpine/v3.23/{repo}/x86_64/{file}"
START = ["qemu-system-x86_64", "qemu-img", "musl", "qemu", "seabios-bin", "seavgabios-bin",
         "qemu-hw-display-virtio-gpu", "qemu-hw-display-virtio-gpu-pci", "qemu-hw-display-virtio-vga"]
NAMED = {"qemu-hw-display-virtio-gpu"}  # named (not so:) dependencies worth following: the display modules' base
SHARE = ("bios-256k.bin", "bios.bin", "vgabios-virtio.bin", "vgabios-stdvga.bin", "vgabios.bin", "kvmvapic.bin", "linuxboot_dma.bin",
         "linuxboot.bin", "multiboot_dma.bin", "pvh.bin", "efi-virtio.rom", "efi-e1000e.rom")


def read_index(root):
    pkgs, provides = {}, {}
    for repo in ("main", "community"):
        for block in (root / repo / "APKINDEX").read_text().split("\n\n"):
            f = {}
            for line in block.splitlines():
                if len(line) > 2 and line[1] == ":":
                    f[line[0]] = line[2:]
            if "P" not in f:
                continue
            f["repo"] = repo
            pkgs[f["P"]] = f
            for p in f.get("p", "").split():
                provides.setdefault(p.split("=")[0], f["P"])
    return pkgs, provides


def closure(pkgs, provides):
    """Only what QEMU needs to run: its libraries (so:...), never shells or commands."""
    need, todo = set(), list(START)
    while todo:
        name = todo.pop()
        if name in need or name not in pkgs:
            continue
        need.add(name)
        for d in pkgs[name].get("D", "").split():
            d = d.split("=")[0].split(">")[0].split("<")[0]
            if d.startswith("so:"):
                todo.append(provides.get(d, ""))
            elif d in NAMED:
                todo.append(d)
    return need


def members(apk):
    """An .apk is gzip streams (signature, control, data) holding tar parts; read them all as one tar."""
    data = gzip.decompress(apk.read_bytes())
    return tarfile.open(fileobj=io.BytesIO(data), mode="r:", ignore_zeros=True)


def main():
    dl = pathlib.Path(sys.argv[1])
    pkgs, provides = read_index(dl / "index")
    need = closure(pkgs, provides)
    (dl / "apk").mkdir(exist_ok=True)
    total = 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT.with_suffix(".tmp"), "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        versions, written = {}, set()
        for name in sorted(need):
            p = pkgs[name]
            file = f"{name}-{p['V']}.apk"
            local = dl / "apk" / file
            if not local.exists():
                urllib.request.urlretrieve(MIRROR.format(repo=p["repo"], file=file), local)
            total += local.stat().st_size
            versions[name] = p["V"]
            with members(local) as t:
                for m in t.getmembers():
                    n = m.name
                    target = None
                    if n in ("usr/bin/qemu-system-x86_64", "usr/bin/qemu-img"):
                        target = "bin/" + n.split("/")[-1]
                    elif n.startswith("usr/lib/qemu/") and n.endswith(".so"):  # QEMU's plug-in modules (the virtio display)
                        target = "lib/qemu/" + n.split("/")[-1]
                    elif n.startswith("usr/share/seabios/") and n.split("/")[-1] in SHARE:
                        target = "share/" + n.split("/")[-1]
                    elif (n.startswith("usr/lib/") or n.startswith("lib/")) and ".so" in n and n.count("/") <= 2:
                        target = "lib/" + n.split("/")[-1]
                    elif n.startswith("usr/share/qemu/keymaps/"):
                        target = "share/keymaps/" + n.split("/")[-1]
                    elif n.startswith("usr/share/qemu/") and n.split("/")[-1] in SHARE:
                        target = "share/" + n.split("/")[-1]
                    if target is None or target in written:
                        continue
                    if m.issym():  # libfoo.so.1 -> libfoo.so.1.2.3: store a copy under the link's name
                        real = t.getmember(str(pathlib.PurePosixPath(n).parent / m.linkname)) if not m.linkname.startswith("/") else None
                        src = t.extractfile(real) if real is not None and real.isfile() else None
                    else:
                        src = t.extractfile(m) if m.isfile() else None
                    if src is not None:
                        z.writestr(target, src.read())
                        written.add(target)
        for lic in ("COPYING", "COPYING.LIB"):  # QEMU's licence (the same GPL text for every version); Alpine's packages leave it out
            src = pathlib.Path("/opt/homebrew/opt/qemu") / lic  # QEMU_LICENCES
            if src.exists():
                z.writestr("QEMU-" + lic, src.read_bytes())
        z.writestr("bundle.json", json.dumps({"qemu": versions.get("qemu-system-x86_64"), "os": "linux", "arch": "x86_64",
                                              "system": "bin/qemu-system-x86_64", "img": "bin/qemu-img", "share": "share",
                                              "loader": ["lib/ld-musl-x86_64.so.1", "--library-path", "lib"],
                                              "env": {"QEMU_MODULE_DIR": "lib/qemu"}}, indent=2))
        z.writestr("SOURCES.md", "# QEMU for x86 Linux PCs\n\nThe official, unchanged QEMU as built by Alpine Linux v3.23 "
                   "(https://pkgs.alpinelinux.org), with the musl C library and the libraries it needs, each under its own licence.\n"
                   f"QEMU's source: https://download.qemu.org/qemu-{versions.get('qemu-system-x86_64', '?').split('-r')[0]}.tar.xz (GNU GPL v2).\n"
                   "Every package's source: https://gitlab.alpinelinux.org/alpine/aports (its APKBUILD names the upstream source).\n\n"
                   + "".join(f"- {n} {v}\n" for n, v in sorted(versions.items())))
    OUT.with_suffix(".tmp").replace(OUT)
    print(f"{OUT}: {OUT.stat().st_size / 1e6:.1f} MB from {len(need)} packages ({total / 1e6:.1f} MB downloaded)")


if __name__ == "__main__":
    main()
