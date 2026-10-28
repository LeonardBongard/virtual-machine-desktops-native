#!/usr/bin/env python3
"""Packs the official, unchanged QEMU for Windows PCs into one zip the mod carries in its jar.

Uses MSYS2's QEMU (mingw-w64-ucrt-x86_64-qemu, built from QEMU's own source). Reads which DLLs
qemu-system-x86_64.exe and qemu-img.exe import, follows them recursively, and fetches only the MSYS2 packages that
hold those DLLs (Windows' own DLLs are skipped). Needs the `zstd` command.

    python3 -I qemu/bundle_windows.py <download dir>   # downloads ucrt64.files and the packages into it, once
"""
import io
import json
import pathlib
import struct
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "build" / "windows-x86_64.zip"
MIRROR = "https://mirror.msys2.org/mingw/ucrt64/"
PREFIX = "ucrt64/"
SHARE = ("bios-256k.bin", "bios.bin", "vgabios-virtio.bin", "vgabios-stdvga.bin", "vgabios.bin", "kvmvapic.bin", "linuxboot_dma.bin",
         "linuxboot.bin", "multiboot_dma.bin", "pvh.bin", "efi-virtio.rom", "efi-e1000e.rom")


def untar_zst(path):
    data = subprocess.run(["zstd", "-dc", str(path)], check=True, capture_output=True).stdout
    return tarfile.open(fileobj=io.BytesIO(data), mode="r:")


def fetch(dl, name):
    local = dl / name
    if not local.exists():
        urllib.request.urlretrieve(MIRROR + name, local)
    return local


def read_files_db(path):
    """package name -> {filename, version, files}; and file path -> package name."""
    pkgs, owner = {}, {}
    with untar_zst(path) as t:
        for m in t.getmembers():
            if not m.isfile():
                continue
            pkgdir, kind = m.name.rsplit("/", 1)
            text = t.extractfile(m).read().decode()
            fields, key = {}, None
            for line in text.splitlines():
                if line.startswith("%") and line.endswith("%"):
                    key = line.strip("%")
                    fields[key] = []
                elif line and key:
                    fields[key].append(line)
            p = pkgs.setdefault(pkgdir, {})
            p.update(fields)
    byname = {}
    for p in pkgs.values():
        if "NAME" in p:
            byname[p["NAME"][0]] = p
            for f in p.get("FILES", []):
                owner[f.lower()] = p["NAME"][0]
    return byname, owner


def imports(data):
    """The DLL names a PE file (exe or dll) imports."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    dirs = opt + (112 if magic == 0x20B else 96)
    imp_rva = struct.unpack_from("<I", data, dirs + 8)[0]
    secs = opt + struct.unpack_from("<H", data, pe + 20)[0]

    def off(rva):
        for i in range(nsec):
            s = secs + i * 40
            va, vsize, raw = struct.unpack_from("<I", data, s + 12)[0], struct.unpack_from("<I", data, s + 8)[0], struct.unpack_from("<I", data, s + 20)[0]
            if va <= rva < va + max(vsize, 1):
                return rva - va + raw
        return None

    names, o = [], off(imp_rva)
    while o is not None:
        name_rva = struct.unpack_from("<I", data, o + 12)[0]
        if name_rva == 0:
            break
        no = off(name_rva)
        names.append(data[no:data.index(b"\0", no)].decode())
        o += 20
    return names


def main():
    dl = pathlib.Path(sys.argv[1])
    dl.mkdir(parents=True, exist_ok=True)
    pkgs, owner = read_files_db(fetch(dl, "ucrt64.files"))
    files, opened, versions = {}, {}, {}

    def package(name):
        if name not in opened:
            p = pkgs[name]
            versions[name] = p["VERSION"][0]
            with untar_zst(fetch(dl, p["FILENAME"][0])) as t:
                opened[name] = {m.name: t.extractfile(m).read() for m in t.getmembers() if m.isfile()}
        return opened[name]

    q = package("mingw-w64-ucrt-x86_64-qemu")
    img_pkg = owner.get(PREFIX + "bin/qemu-img.exe")
    todo = []
    for exe, pkg in (("qemu-system-x86_64.exe", "mingw-w64-ucrt-x86_64-qemu"), ("qemu-img.exe", img_pkg or "mingw-w64-ucrt-x86_64-qemu")):
        data = package(pkg)[PREFIX + "bin/" + exe]
        files["bin/" + exe] = data
        todo.append(data)
    seen = set()
    while todo:  # every DLL the programs (and those DLLs) import that some MSYS2 package holds
        for dll in imports(todo.pop()):
            path = PREFIX + "bin/" + dll.lower()
            if dll.lower() in seen or path not in owner:
                continue  # already taken, or one of Windows' own DLLs
            seen.add(dll.lower())
            content = package(owner[path])
            real = next(k for k in content if k.lower() == path)
            files["bin/" + real.split("/")[-1]] = content[real]
            todo.append(content[real])
    for pkg in list(opened):  # firmware and keymaps from QEMU's share folder
        for k, v in opened[pkg].items():
            if k.startswith(PREFIX + "share/qemu/keymaps/"):
                files["share/keymaps/" + k.split("/")[-1]] = v
            elif k.startswith(PREFIX + "share/qemu/") and k.split("/")[-1] in SHARE:
                files["share/" + k.split("/")[-1]] = v
    for k, v in q.items():
        if k.split("/")[-1] == "COPYING" or "licenses/" in k and k.endswith(("COPYING", "LICENSE")):
            files["QEMU-" + k.split("/")[-1]] = v
    for lic in ("COPYING", "COPYING.LIB"):  # QEMU's licence (the same GPL text for every version); these packages leave it out
        src = pathlib.Path("/opt/homebrew/opt/qemu") / lic  # QEMU_LICENCES
        if src.exists():
            files["QEMU-" + lic] = src.read_bytes()
    ver = versions["mingw-w64-ucrt-x86_64-qemu"].split("-")[0]
    files["bundle.json"] = json.dumps({"qemu": ver, "os": "windows", "arch": "x86_64", "system": "bin/qemu-system-x86_64.exe",
                                       "img": "bin/qemu-img.exe", "share": "share"}, indent=2).encode()
    files["SOURCES.md"] = ("# QEMU for Windows PCs\n\nThe official, unchanged QEMU as built by MSYS2 (https://packages.msys2.org/base/mingw-w64-qemu), "
                           "with the DLLs it needs, each under its own licence.\n"
                           f"QEMU's source: https://download.qemu.org/qemu-{ver}.tar.xz (GNU GPL v2).\n"
                           "Every package's build recipe and source: https://github.com/msys2/MINGW-packages\n\n"
                           + "".join(f"- {n} {v}\n" for n, v in sorted(versions.items()))).encode()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in sorted(files.items()):
            z.writestr(name, data)
    dlbytes = sum(f.stat().st_size for f in dl.iterdir())
    print(f"{OUT}: {OUT.stat().st_size / 1e6:.1f} MB, {len(seen)} DLLs from {len(opened)} packages ({dlbytes / 1e6:.1f} MB downloaded)")


if __name__ == "__main__":
    main()
