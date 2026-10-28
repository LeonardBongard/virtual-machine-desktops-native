// vmd-webcam for Linux: the player's real webcam (V4L2, YUYV) as raw YUYV frames on stdout, for the mod to pass
// into the PC's Linux.  vmd-webcam <width> <height> [device]  — frames of exactly width*height*2 bytes.
//                       vmd-webcam --list                      — the cameras there are.
// Built static (musl) so it runs on any Linux. Runs only while a Linux program inside the PC has the webcam open.
#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

static int xioctl(int fd, unsigned long req, void *arg) {
	int r;
	do r = ioctl(fd, req, arg); while (r == -1 && errno == EINTR);
	return r;
}

static int is_capture(int fd, char *name, size_t n) {
	struct v4l2_capability cap;
	if (xioctl(fd, VIDIOC_QUERYCAP, &cap) < 0) return 0;
	unsigned caps = cap.capabilities & V4L2_CAP_DEVICE_CAPS ? cap.device_caps : cap.capabilities;
	snprintf(name, n, "%s", (char *) cap.card);
	return (caps & V4L2_CAP_VIDEO_CAPTURE) && (caps & V4L2_CAP_STREAMING);
}

static int write_all(const unsigned char *p, size_t n) {
	while (n > 0) {
		ssize_t w = write(1, p, n);
		if (w <= 0) return 0;
		p += w;
		n -= (size_t) w;
	}
	return 1;
}

int main(int argc, char **argv) {
	char name[64];
	signal(SIGPIPE, SIG_IGN);
	if (argc == 2 && strcmp(argv[1], "--list") == 0) {
		for (int i = 0; i < 64; i++) {
			char dev[32];
			snprintf(dev, sizeof dev, "/dev/video%d", i);
			int fd = open(dev, O_RDWR);
			if (fd < 0) continue;
			if (is_capture(fd, name, sizeof name)) printf("%s %s\n", dev, name);
			close(fd);
		}
		return 0;
	}
	if (argc < 3) {
		fprintf(stderr, "usage: vmd-webcam <width> <height> [device] | --list\n");
		return 2;
	}
	int width = atoi(argv[1]), height = atoi(argv[2]), fd = -1;
	if (argc > 3) {
		fd = open(argv[3], O_RDWR);
		if (fd >= 0 && !is_capture(fd, name, sizeof name)) { close(fd); fd = -1; }
	} else {
		for (int i = 0; i < 64 && fd < 0; i++) { // the first real capture camera
			char dev[32];
			snprintf(dev, sizeof dev, "/dev/video%d", i);
			fd = open(dev, O_RDWR);
			if (fd >= 0 && !is_capture(fd, name, sizeof name)) { close(fd); fd = -1; }
		}
	}
	if (fd < 0) {
		fprintf(stderr, "no camera\n");
		return 1;
	}
	struct v4l2_format fmt = {0};
	fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	fmt.fmt.pix.width = 1280;
	fmt.fmt.pix.height = 720;
	fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_YUYV;
	fmt.fmt.pix.field = V4L2_FIELD_ANY;
	if (xioctl(fd, VIDIOC_S_FMT, &fmt) < 0 || fmt.fmt.pix.pixelformat != V4L2_PIX_FMT_YUYV) {
		fprintf(stderr, "camera %s gives no YUYV pictures\n", name);
		return 1;
	}
	int w = (int) fmt.fmt.pix.width, h = (int) fmt.fmt.pix.height, row = (int) fmt.fmt.pix.bytesperline;
	if (row < w * 2) row = w * 2;
	struct v4l2_requestbuffers req = {.count = 4, .type = V4L2_BUF_TYPE_VIDEO_CAPTURE, .memory = V4L2_MEMORY_MMAP};
	if (xioctl(fd, VIDIOC_REQBUFS, &req) < 0 || req.count < 2) {
		fprintf(stderr, "camera %s: no buffers\n", name);
		return 1;
	}
	void *mem[8];
	size_t len[8];
	for (unsigned i = 0; i < req.count && i < 8; i++) {
		struct v4l2_buffer b = {.type = V4L2_BUF_TYPE_VIDEO_CAPTURE, .memory = V4L2_MEMORY_MMAP, .index = i};
		if (xioctl(fd, VIDIOC_QUERYBUF, &b) < 0) return 1;
		len[i] = b.length;
		mem[i] = mmap(NULL, b.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, b.m.offset);
		if (mem[i] == MAP_FAILED || xioctl(fd, VIDIOC_QBUF, &b) < 0) return 1;
	}
	enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	if (xioctl(fd, VIDIOC_STREAMON, &type) < 0) {
		fprintf(stderr, "camera %s would not start\n", name);
		return 1;
	}
	fprintf(stderr, "camera: %s (%dx%d)\n", name, w, h);
	unsigned char *out = malloc((size_t) width * height * 2);
	// the camera's picture scaled (nearest) to the size asked for, centre-cropped to keep its shape; pixels in pairs
	double scale = (double) width / w > (double) height / h ? (double) width / w : (double) height / h;
	double x0 = (w - width / scale) / 2, y0 = (h - height / scale) / 2;
	for (;;) {
		struct v4l2_buffer b = {.type = V4L2_BUF_TYPE_VIDEO_CAPTURE, .memory = V4L2_MEMORY_MMAP};
		if (xioctl(fd, VIDIOC_DQBUF, &b) < 0) return 1;
		const unsigned char *src = mem[b.index];
		for (int y = 0; y < height; y++) {
			int sy = (int) (y0 + y / scale);
			if (sy > h - 1) sy = h - 1;
			for (int x = 0; x < width; x += 2) {
				int sx = (int) (x0 + x / scale);
				if (sx > w - 2) sx = w - 2;
				sx &= ~1;
				memcpy(out + (y * width + x) * 2, src + sy * row + sx * 2, 4);
			}
		}
		if (xioctl(fd, VIDIOC_QBUF, &b) < 0) return 1;
		if (!write_all(out, (size_t) width * height * 2)) return 0; // the mod closed the pipe: no longer wanted
	}
	(void) len;
}
