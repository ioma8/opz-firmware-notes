/*
 * audiosink.c - play raw interleaved 16-bit stereo PCM from stdin at 48 kHz.
 *
 * Python cannot open a low-latency audio device without a third-party package, and the OP-Z harness is
 * dependency-free by design. This tiny helper closes that gap: it owns a CoreAudio AudioQueue, and every
 * buffer it needs is refilled by reading from stdin. The Python side renders blocks with the translated
 * engine (microseconds each) and writes PCM into this process, so playback is realtime with a latency set
 * by the queue depth below - about 3 x 512 frames, i.e. ~30 ms.
 *
 * Build: cc -O2 -o audiosink audiosink.c -framework AudioToolbox -framework CoreAudio
 * Usage: <pcm producer> | audiosink [rate] [frames_per_buffer]
 */
#include <AudioToolbox/AudioToolbox.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define CHANNELS 2
#define BUFFERS 4

static AudioQueueRef queue;
static AudioQueueBufferRef buffers[BUFFERS];
static UInt32 frames_per_buffer = 512;
static int finished = 0;

static int fill(AudioQueueBufferRef buf) {
    size_t want = frames_per_buffer * CHANNELS * sizeof(int16_t);
    size_t got = fread(buf->mAudioData, 1, want, stdin);
    if (got == 0) { return 0; }
    if (got < want) { memset((char *)buf->mAudioData + got, 0, want - got); }
    buf->mAudioDataByteSize = (UInt32)want;
    return 1;
}

static void callback(void *user, AudioQueueRef q, AudioQueueBufferRef buf) {
    (void)user;
    if (finished) { return; }
    if (fill(buf)) {
        AudioQueueEnqueueBuffer(q, buf, 0, NULL);
    } else {
        finished = 1;
        AudioQueueStop(q, false);
    }
}

int main(int argc, char **argv) {
    double rate = (argc > 1) ? atof(argv[1]) : 48000.0;
    if (argc > 2) { frames_per_buffer = (UInt32)atoi(argv[2]); }

    AudioStreamBasicDescription fmt;
    memset(&fmt, 0, sizeof fmt);
    fmt.mSampleRate = rate;
    fmt.mFormatID = kAudioFormatLinearPCM;
    fmt.mFormatFlags = kLinearPCMFormatFlagIsSignedInteger | kLinearPCMFormatFlagIsPacked;
    fmt.mBytesPerPacket = CHANNELS * sizeof(int16_t);
    fmt.mFramesPerPacket = 1;
    fmt.mBytesPerFrame = CHANNELS * sizeof(int16_t);
    fmt.mChannelsPerFrame = CHANNELS;
    fmt.mBitsPerChannel = 16;

    if (AudioQueueNewOutput(&fmt, callback, NULL, NULL, NULL, 0, &queue) != noErr) {
        fprintf(stderr, "audiosink: AudioQueueNewOutput failed\n");
        return 1;
    }
    UInt32 bytes = frames_per_buffer * CHANNELS * sizeof(int16_t);
    for (int i = 0; i < BUFFERS; i++) {
        if (AudioQueueAllocateBuffer(queue, bytes, &buffers[i]) != noErr) {
            fprintf(stderr, "audiosink: AudioQueueAllocateBuffer failed\n");
            return 1;
        }
        if (!fill(buffers[i])) { return 0; }         /* stdin already closed: nothing to play */
        AudioQueueEnqueueBuffer(queue, buffers[i], 0, NULL);
    }
    if (AudioQueueStart(queue, NULL) != noErr) {
        fprintf(stderr, "audiosink: AudioQueueStart failed\n");
        return 1;
    }
    /* The callback drives refills, so this loop only waits for completion or a closed stdin. */
    while (!finished) { usleep(20000); }
    AudioQueueStop(queue, true);
    AudioQueueDispose(queue, true);
    return 0;
}
