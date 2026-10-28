// vmd-webcam for Windows: the player's real webcam (Media Foundation) as raw YUYV frames on stdout, for the mod to
// pass into the PC's Linux.  vmd-webcam <width> <height>  — frames of exactly width*height*2 bytes.
//                            vmd-webcam --list            — the cameras there are.
// Media Foundation converts and scales to YUY2 itself (advanced video processing). Runs only while a Linux program
// inside the PC has the webcam open.
#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <fcntl.h>
#include <io.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static IMFActivate **cameras(UINT32 *count) {
	IMFAttributes *attr = NULL;
	IMFActivate **devs = NULL;
	*count = 0;
	if (FAILED(MFCreateAttributes(&attr, 1))) return NULL;
	IMFAttributes_SetGUID(attr, &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE, &MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_GUID);
	if (FAILED(MFEnumDeviceSources(attr, &devs, count))) *count = 0;
	IMFAttributes_Release(attr);
	return devs;
}

static void name_of(IMFActivate *dev, char *out, int n) {
	WCHAR *w = NULL;
	UINT32 len = 0;
	out[0] = 0;
	if (SUCCEEDED(IMFActivate_GetAllocatedString(dev, &MF_DEVSOURCE_ATTRIBUTE_FRIENDLY_NAME, &w, &len))) {
		WideCharToMultiByte(CP_UTF8, 0, w, -1, out, n, NULL, NULL);
		CoTaskMemFree(w);
	}
}

int main(int argc, char **argv) {
	char name[256];
	if (FAILED(CoInitializeEx(NULL, COINIT_MULTITHREADED)) || FAILED(MFStartup(MF_VERSION, MFSTARTUP_FULL))) return 1;
	UINT32 count = 0;
	IMFActivate **devs = cameras(&count);
	if (argc == 2 && strcmp(argv[1], "--list") == 0) {
		for (UINT32 i = 0; i < count; i++) {
			name_of(devs[i], name, sizeof name);
			printf("%s\n", name);
		}
		return 0;
	}
	if (argc < 3) {
		fprintf(stderr, "usage: vmd-webcam <width> <height> | --list\n");
		return 2;
	}
	int width = atoi(argv[1]), height = atoi(argv[2]);
	if (count == 0) {
		fprintf(stderr, "no camera\n");
		return 1;
	}
	IMFMediaSource *source = NULL;
	name_of(devs[0], name, sizeof name);
	if (FAILED(IMFActivate_ActivateObject(devs[0], &IID_IMFMediaSource, (void **) &source))) {
		fprintf(stderr, "camera %s refused (Windows privacy settings: let desktop apps use the camera)\n", name);
		return 1;
	}
	IMFAttributes *opts = NULL;
	MFCreateAttributes(&opts, 1);
	IMFAttributes_SetUINT32(opts, &MF_SOURCE_READER_ENABLE_ADVANCED_VIDEO_PROCESSING, TRUE);
	IMFSourceReader *reader = NULL;
	if (FAILED(MFCreateSourceReaderFromMediaSource(source, opts, &reader))) return 1;
	IMFMediaType *type = NULL;
	MFCreateMediaType(&type);
	IMFMediaType_SetGUID(type, &MF_MT_MAJOR_TYPE, &MFMediaType_Video);
	IMFMediaType_SetGUID(type, &MF_MT_SUBTYPE, &MFVideoFormat_YUY2);
	IMFMediaType_SetUINT64(type, &MF_MT_FRAME_SIZE, ((UINT64) width << 32) | (UINT32) height);
	if (FAILED(IMFSourceReader_SetCurrentMediaType(reader, (DWORD) MF_SOURCE_READER_FIRST_VIDEO_STREAM, NULL, type))) {
		fprintf(stderr, "camera %s cannot give %dx%d YUY2 pictures\n", name, width, height);
		return 1;
	}
	_setmode(_fileno(stdout), _O_BINARY);
	fprintf(stderr, "camera: %s\n", name);
	size_t frame = (size_t) width * height * 2;
	for (;;) {
		DWORD stream, flags;
		LONGLONG at;
		IMFSample *sample = NULL;
		if (FAILED(IMFSourceReader_ReadSample(reader, (DWORD) MF_SOURCE_READER_FIRST_VIDEO_STREAM, 0, &stream, &flags, &at, &sample))) return 1;
		if (flags & MF_SOURCE_READERF_ENDOFSTREAM) return 0;
		if (!sample) continue;
		IMFMediaBuffer *buf = NULL;
		if (SUCCEEDED(IMFSample_ConvertToContiguousBuffer(sample, &buf))) {
			BYTE *p;
			DWORD len;
			if (SUCCEEDED(IMFMediaBuffer_Lock(buf, &p, NULL, &len))) {
				int ok = len >= frame && fwrite(p, 1, frame, stdout) == frame && fflush(stdout) == 0;
				IMFMediaBuffer_Unlock(buf);
				if (!ok && len >= frame) return 0; // the mod closed the pipe: no longer wanted
			}
			IMFMediaBuffer_Release(buf);
		}
		IMFSample_Release(sample);
	}
}
