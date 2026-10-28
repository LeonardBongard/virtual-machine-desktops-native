#!/usr/bin/env python3
"""A static check of the Windows and Linux QEMU bundles, for when no such computer is at hand: every program and
library in a bundle must find every library it loads, either in the bundle or in the operating system itself, and
bundle.json must point at files that exist. It cannot prove QEMU runs there; it proves nothing is missing.

    python3 -I qemu/check_bundles.py
"""
import io
import json
import pathlib
import struct
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from bundle_windows import imports  # noqa: E402  (the same import-table reader the bundler uses)

# DLLs every Windows 10/11 has (the C runtime UCRT ships with Windows 10 and later).
WINDOWS = {"kernel32.dll", "user32.dll", "gdi32.dll", "advapi32.dll", "shell32.dll", "ole32.dll", "oleaut32.dll", "ws2_32.dll",
           "winmm.dll", "iphlpapi.dll", "bcrypt.dll", "crypt32.dll", "dwmapi.dll", "imm32.dll", "setupapi.dll", "shlwapi.dll",
           "usp10.dll", "version.dll", "comctl32.dll", "comdlg32.dll", "msimg32.dll", "dnsapi.dll", "secur32.dll", "userenv.dll",
           "ncrypt.dll", "winspool.drv", "hid.dll", "opengl32.dll", "d3d9.dll", "dxgi.dll", "d3d11.dll", "dwrite.dll", "uxtheme.dll",
           "wldap32.dll", "normaliz.dll", "cfgmgr32.dll", "netapi32.dll", "ntdll.dll", "mpr.dll", "rpcrt4.dll", "msvcrt.dll",
           "ucrtbase.dll", "winhttp.dll", "wintrust.dll", "psapi.dll", "dbghelp.dll", "powrprof.dll", "propsys.dll", "mfplat.dll",
           "mfreadwrite.dll", "mf.dll", "avrt.dll", "ksuser.dll", "xinput1_4.dll", "dinput8.dll", "d3dcompiler_47.dll", "hhctrl.ocx",
           "rstrtmgr.dll", "virtdisk.dll", "winhvplatform.dll", "winhvemulation.dll", "authz.dll", "credui.dll", "dcomp.dll",
           "d2d1.dll", "mfuuid.dll", "mswsock.dll", "sspicli.dll", "wtsapi32.dll", "gdiplus.dll", "msi.dll", "ntdsapi.dll"}


def check_windows(z):
    names = {pathlib.PurePosixPath(n).name.lower() for n in z.namelist()}
    missing = {}
    for n in z.namelist():
        if n.lower().endswith((".exe", ".dll")):
            for dll in imports(z.read(n)):
                d = dll.lower()
                if d not in names and d not in WINDOWS and not d.startswith(("api-ms-win-", "ext-ms-")):
                    missing.setdefault(d, []).append(pathlib.PurePosixPath(n).name)
    return missing


def elf_needed(data):
    """DT_NEEDED names of a 64-bit little-endian ELF file."""
    if data[:4] != b"\x7fELF":
        return []
    shoff, shentsize, shnum = struct.unpack_from("<Q", data, 0x28)[0], struct.unpack_from("<H", data, 0x3A)[0], struct.unpack_from("<H", data, 0x3C)[0]
    secs = [struct.unpack_from("<IIQQQQIIQQ", data, shoff + i * shentsize) for i in range(shnum)]
    out = []
    for s in secs:
        if s[1] == 6:  # SHT_DYNAMIC
            strtab = secs[s[6]]
            for i in range(0, s[5], 16):
                tag, val = struct.unpack_from("<qQ", data, s[4] + i)
                if tag == 0:
                    break
                if tag == 1:
                    o = strtab[4] + val
                    out.append(data[o:data.index(b"\0", o)].decode())
    return out


def check_linux(z):
    names = {pathlib.PurePosixPath(n).name for n in z.namelist()}
    missing = {}
    for n in z.namelist():
        if n.startswith(("bin/", "lib/")) and not n.endswith("/"):
            for lib in elf_needed(z.read(n)):
                if lib not in names and lib != "libc.musl-x86_64.so.1":  # musl's libc is its loader, ld-musl
                    missing.setdefault(lib, []).append(pathlib.PurePosixPath(n).name)
    if "lib/ld-musl-x86_64.so.1" not in z.namelist():
        missing["ld-musl-x86_64.so.1"] = ["(the loader)"]
    return missing


def main():
    ok = True
    for name, check in (("windows-x86_64", check_windows), ("linux-x86_64", check_linux), ("macos-aarch64", None)):
        path = HERE / "build" / f"{name}.zip"
        if not path.exists():
            print(f"{name}: not built")
            ok = False
            continue
        with zipfile.ZipFile(path) as z:
            b = json.loads(z.read("bundle.json"))
            refs = [b[k] for k in ("system", "img", "firmware", "vars") if k in b] + [x for x in b.get("loader", []) if not x.startswith("-")]
            absent = [r for r in refs if r not in z.namelist() and not any(n.startswith(r + "/") for n in z.namelist())]  # a file or a folder
            missing = check(z) if check else {}
            print(f"{name}: QEMU {b['qemu']}, {len(z.namelist())} files; bundle.json paths {'all present' if not absent else 'MISSING ' + str(absent)}; "
                  + ("every library found" if not missing else f"{len(missing)} libraries missing: {dict(list(missing.items())[:8])}"))
            ok &= not absent and not missing
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
