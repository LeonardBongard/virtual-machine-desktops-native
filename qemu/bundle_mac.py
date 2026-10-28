#!/usr/bin/env python3
"""Packs the official, unchanged QEMU for Apple Silicon Macs into one zip the mod carries in its jar.

Takes Homebrew's QEMU (qemu-system-aarch64, qemu-img) with every non-system library it needs, makes them find each
other next to the binaries (@loader_path), signs them again (changing a binary breaks its signature) with the one
right QEMU needs to use the Mac's virtualization (com.apple.security.hypervisor), and adds the UEFI firmware, the
licences and where the source is. Run on an Apple Silicon Mac with `brew install qemu`:

    python3 qemu/bundle_mac.py            # writes qemu/build/macos-aarch64.zip (not in git)
"""
import json
import pathlib
import shutil
import subprocess
import tempfile
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "build" / "macos-aarch64.zip"
BREW = pathlib.Path("/opt/homebrew")
BINARIES = ["qemu-system-aarch64", "qemu-img"]
FIRMWARE = ["edk2-aarch64-code.fd", "edk2-arm-vars.fd"]
ENTITLEMENTS = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>com.apple.security.hypervisor</key><true/></dict></plist>
"""


def run(*cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def deps(path):
    """The libraries a binary needs that are not part of macOS."""
    out = []
    for line in run("otool", "-L", str(path)).splitlines()[1:]:
        lib = line.strip().split(" ")[0]
        if lib.startswith(str(BREW)) or lib.startswith("@rpath"):
            out.append(lib)
    return out


def resolve(lib, origin):
    if lib.startswith("@rpath/"):  # Homebrew libraries name siblings through @rpath
        return (pathlib.Path(origin).parent / lib.split("/", 1)[1]).resolve()
    return pathlib.Path(lib).resolve()


def main():
    work = pathlib.Path(tempfile.mkdtemp(prefix="qemu-mac-"))
    (work / "bin").mkdir()
    (work / "lib").mkdir()
    (work / "share").mkdir()
    todo, seen, libs = [], {}, {}
    for b in BINARIES:
        src = (BREW / "bin" / b).resolve()
        shutil.copy2(src, work / "bin" / b)
        todo.append((work / "bin" / b, src))
    while todo:  # copy every library the binaries (and the libraries) need, once
        copy, original = todo.pop()
        for lib in deps(copy):
            real = resolve(lib, original)
            name = real.name
            if name not in libs:
                libs[name] = real
                shutil.copy2(real, work / "lib" / name)
                (work / "lib" / name).chmod(0o755)
                todo.append((work / "lib" / name, real))
            seen.setdefault(copy, []).append((lib, name))
    for f, changes in seen.items():  # point every reference at the copy next to it
        prefix = "@loader_path/../lib/" if f.parent.name == "bin" else "@loader_path/"
        for old, name in changes:
            run("install_name_tool", "-change", old, prefix + name, str(f))
    for lib in (work / "lib").iterdir():
        run("install_name_tool", "-id", "@loader_path/" + lib.name, str(lib))
    ent = work / "qemu.entitlements"
    ent.write_text(ENTITLEMENTS)
    for f in list((work / "lib").iterdir()) + [work / "bin" / b for b in BINARIES]:
        sign = ["codesign", "--force", "-s", "-"]
        if f.name == "qemu-system-aarch64":
            sign += ["--entitlements", str(ent)]
        run(*sign, str(f))
    ent.unlink()
    for fw in FIRMWARE:
        shutil.copy2(BREW / "share/qemu" / fw, work / "share" / fw)
    for rom in (BREW / "share/qemu").glob("efi-*.rom"):  # the network cards' boot ROMs, which QEMU loads from -L
        shutil.copy2(rom, work / "share" / rom.name)
    shutil.copytree(BREW / "share/qemu/keymaps", work / "share/keymaps")  # the VNC server needs a keyboard layout file
    cellar = (BREW / "bin/qemu-system-aarch64").resolve().parents[1]
    for lic in ("COPYING", "COPYING.LIB", "LICENSE"):
        if (cellar / lic).exists():
            shutil.copy2(cellar / lic, work / f"QEMU-{lic}")
    version = cellar.name
    versions = {}
    for name, real in sorted(libs.items()):
        parts = real.parts
        if "Cellar" in parts:
            i = parts.index("Cellar")
            versions[parts[i + 1]] = parts[i + 2]
    (work / "SOURCES.md").write_text(
        f"# QEMU {version} for Apple Silicon Macs\n\n"
        "The official, unchanged QEMU, as built by Homebrew (https://formulae.brew.sh/formula/qemu), with the libraries it needs.\n"
        f"QEMU's source: https://download.qemu.org/qemu-{version}.tar.xz (GNU GPL v2, see QEMU-COPYING).\n\n"
        "Libraries (each under its own licence, source from https://formulae.brew.sh/formula/<name>):\n\n"
        + "".join(f"- {n} {v}\n" for n, v in sorted(versions.items())))
    (work / "bundle.json").write_text(json.dumps({"qemu": version, "os": "macos", "arch": "aarch64",
                                                   "system": "bin/qemu-system-aarch64", "img": "bin/qemu-img",
                                                   "firmware": "share/edk2-aarch64-code.fd", "vars": "share/edk2-arm-vars.fd"}, indent=2))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(work.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(work).as_posix())
    print(f"{OUT}: {OUT.stat().st_size / 1e6:.1f} MB, QEMU {version}, {len(libs)} libraries")
    shutil.rmtree(work)


if __name__ == "__main__":
    main()
