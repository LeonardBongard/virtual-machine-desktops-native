#!/usr/bin/python3
"""VMD Additions agent: runs in the player's Linux session and talks to the Minecraft mod over the PC's own
virtual serial port (org.vmdesktops.0). It turns what the mod sends into a microphone and two cameras:

  - "Minecraft microphone": a PipeWire source fed with 48 kHz mono sound (the player's voice mixed with the game)
  - "Minecraft Camera" and "Webcam": v4l2loopback cameras fed with YUYV frames (installed by vmd-additions-setup)

Messages both ways: 1 byte type, 4 bytes big-endian length, payload.
  1 HELLO   agent -> mod   JSON: version, what works
  2 MIC     mod -> agent   PCM s16le mono 48000 Hz
  3 CAM     mod -> agent   1 byte camera (0 webcam, 1 Minecraft), 2+2 bytes width, height, then YUYV pixels
  4 ASK     mod -> agent   empty: answer with STATS
  5 STATS   agent -> mod   JSON: bytes and frames passed on so far
  6 USE     agent -> mod   JSON: which cameras a Linux program has open now, e.g. {"0": true, "1": false}
                           (the mod films, and turns the real webcam on, only while one is used)
  7 LAYOUT  agent -> mod   JSON: where Linux shows each screen, [{"screen": 0, "x": 0, "y": 0, "w": 1280, "h": 720}, ...]
                           (the mod aims the mouse across all screens with it)
"""
import fcntl
import json
import os
import struct
import subprocess
import sys
import threading
import time

PORT = "/dev/virtio-ports/org.vmdesktops.0"
VERSION = 1
HELLO, MIC, CAM, ASK, STATS, USE, LAYOUT = 1, 2, 3, 4, 5, 6, 7
CAMERA_NAMES = {0: "Webcam", 1: "Minecraft Camera"}
stats = {"mic_bytes": 0, "frames": {"0": 0, "1": 0}, "mic": False, "cameras": []}


def log(*a):
    print("vmd-agent:", *a, file=sys.stderr, flush=True)


class Mic:
    """A PipeWire source reading a pipe; pw-cli keeps the module loaded while it runs. A writer thread feeds the pipe
    in order, whole samples only; when nobody records, PipeWire stops reading and anything over a second is dropped."""
    MAX_BACKLOG = 48000 * 2  # one second of 48 kHz 16-bit mono

    def __init__(self):
        self.fifo = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "vmd-mic")
        if not os.path.exists(self.fifo):
            os.mkfifo(self.fifo)
        args = ("{ tunnel.mode = source pipe.filename = \"%s\" audio.format = S16LE audio.rate = 48000 audio.channels = 1 "
                "audio.position = [ MONO ] node.name = vmd-mic node.description = \"Minecraft microphone\" }" % self.fifo)
        self.proc = subprocess.Popen(["pw-cli", "-m", "load-module", "libpipewire-module-pipe-tunnel", args],
                                     stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
        self.out = os.open(self.fifo, os.O_WRONLY)
        self.pending = bytearray()
        self.lock = threading.Condition()
        threading.Thread(target=self.writer, daemon=True).start()
        stats["mic"] = True
        log("microphone ready")

    def write(self, pcm):
        with self.lock:
            self.pending += pcm
            cut = len(self.pending) - self.MAX_BACKLOG
            if cut > 0:
                del self.pending[:cut + (cut & 1)]  # keep the newest second; an even cut keeps whole 16-bit samples
            self.lock.notify()
        stats["mic_bytes"] += len(pcm)

    def writer(self):
        while True:
            with self.lock:
                while not self.pending:
                    self.lock.wait()
                chunk = bytes(self.pending[:4096])
                del self.pending[:4096]
            view = memoryview(chunk)
            while view:
                view = view[os.write(self.out, view):]  # a pipe may take part of a write: send the rest, in order


class Camera:
    """One v4l2loopback device: set its format once, then every write() is one frame."""
    VIDIOC_S_FMT = 0xC0D05605  # _IOWR('V', 5, struct v4l2_format), 208 bytes
    YUYV = 0x56595559

    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR)
        self.size = None

    def frame(self, w, h, pixels):
        if self.size != (w, h):
            fmt = bytearray(208)
            struct.pack_into("I", fmt, 0, 2)  # V4L2_BUF_TYPE_VIDEO_OUTPUT
            struct.pack_into("IIIIII", fmt, 8, w, h, self.YUYV, 1, w * 2, w * h * 2)  # width height format field(none) bpl size
            fcntl.ioctl(self.fd, self.VIDIOC_S_FMT, fmt)
            self.size = (w, h)
        os.write(self.fd, pixels)


def find_cameras():
    """The loopback devices named by vmd-additions-setup, by camera number."""
    found = {}
    for dev in sorted(os.listdir("/sys/class/video4linux")) if os.path.isdir("/sys/class/video4linux") else []:
        try:
            name = open(f"/sys/class/video4linux/{dev}/name").read().strip()
        except OSError:
            continue
        for num, label in CAMERA_NAMES.items():
            if name == label and num not in found:
                found[num] = "/dev/" + dev
    return found


SEND_LOCK = threading.Lock()


def send(port, kind, payload):
    with SEND_LOCK:
        os.write(port, struct.pack(">BI", kind, len(payload)) + payload)


def cameras_in_use(paths):
    """Which of the camera devices some other program has open, read from /proc (same user: browsers, Discord)."""
    real = {num: os.path.realpath(p) for num, p in paths.items()}
    used = {num: False for num in paths}
    me = str(os.getpid())
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or pid == me:
            continue
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                target = os.readlink(f"/proc/{pid}/fd/{fd}")
                for num, path in real.items():
                    if target == path:
                        used[num] = True
        except OSError:
            continue  # gone, or another user's
    return used


def screen_layout():
    """The screens as GNOME arranges them, from Mutter's display settings; None where that cannot be read."""
    try:
        from gi.repository import Gio
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        serial, monitors, logical, props = bus.call_sync(
            "org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig", "org.gnome.Mutter.DisplayConfig",
            "GetCurrentState", None, None, 0, 2000, None).unpack()
    except Exception:
        return None
    size = {}
    for (connector, *_), modes, _ in monitors:
        for m in modes:
            if m[6].get("is-current"):
                size[connector] = (m[1], m[2])
    physical = props.get("layout-mode") == 2  # else logical: sizes are divided by the scale
    out = []
    for x, y, scale, transform, primary, members, _ in logical:
        for connector, *_ in members:
            if connector.startswith("Virtual-") and connector in size:
                w, h = size[connector]
                if transform % 2:  # turned by 90 or 270 degrees
                    w, h = h, w
                k = 1 if physical else scale
                out.append({"screen": int(connector.split("-")[1]) - 1, "x": x, "y": y, "w": round(w / k), "h": round(h / k)})
    return sorted(out, key=lambda o: o["screen"])


def watch_use(port, paths):
    """Tells the mod whenever a program starts or stops using a camera, or the screens are rearranged; once a second."""
    last, last_layout = None, None
    while True:
        used = cameras_in_use(paths())
        if used != last:
            send(port, USE, json.dumps({str(k): v for k, v in used.items()}).encode())
            last = used
        layout = screen_layout()
        if layout and layout != last_layout:
            send(port, LAYOUT, json.dumps(layout).encode())
            last_layout = layout
        time.sleep(1)


def read_exact(port, n):
    buf = b""
    while len(buf) < n:
        chunk = os.read(port, n - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return buf


def main():
    while not os.path.exists(PORT):
        time.sleep(2)  # this Linux is not running in Virtual Machine Desktops, or the port is not there yet
    port = os.open(PORT, os.O_RDWR)
    cams = {n: Camera(p) for n, p in find_cameras().items()}
    stats["cameras"] = sorted(CAMERA_NAMES[n] for n in cams)
    send(port, HELLO, json.dumps({"version": VERSION, "cameras": stats["cameras"]}).encode())
    log("connected; cameras:", stats["cameras"] or "none (the camera driver is still being set up, or failed)")
    mic, last_scan = None, time.time()
    threading.Thread(target=watch_use, args=(port, find_cameras), daemon=True).start()
    while True:
        kind, length = struct.unpack(">BI", read_exact(port, 5))
        payload = read_exact(port, length)
        if kind == MIC:
            if mic is None:
                mic = Mic()
            mic.write(payload)
        elif kind == CAM:
            num, w, h = struct.unpack(">BHH", payload[:5])
            if num not in cams and time.time() - last_scan > 5:  # the driver may have arrived since (setup runs after install)
                last_scan = time.time()
                cams.update({n: Camera(p) for n, p in find_cameras().items() if n not in cams})
                stats["cameras"] = sorted(CAMERA_NAMES[n] for n in cams)
            if num in cams:
                cams[num].frame(w, h, payload[5:])
                stats["frames"][str(num)] += 1
        elif kind == ASK:
            send(port, STATS, json.dumps(stats).encode())


if __name__ == "__main__":
    while True:
        try:
            main()
        except (EOFError, OSError) as e:
            log("connection lost:", e)
            time.sleep(2)
