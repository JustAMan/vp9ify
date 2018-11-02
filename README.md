# vp9ify
Tooling to automate compressing video archive into WebM (VP9 for video, Vorbis for audio) to save space compared to h264 without losing quality.
You as user bear full responsibility to make sure that you're allowed to compress and store the media you're planning to (i.e. contry laws allow that, media license allows that, etc.). I am not to be held liable for any legal consequencies of using this tool.

If you want to read the rationale behind this tool - continue to [idea section](#idea).

**NOTE**: this tool is implemented as a POSIX-only (when run on Windows it is run in stubbed testing mode, for development only).
I have no use for it on Windows, but if there would be demand I might consider making it cross-platform (which is not so hard, thanks for Python nature).

# Usage
Would be filled later when all code is here.

# Rationale

## Idea
Using VP9 over (industry default) h264 has some advantages as it is a roalty-free codec that is widely supported in browsers which should yield around 50% savings over h264 without losing quality. It has also good enough decoding support in hardware (I'm interested in h/w support in Smart TVs, and it was supported at least in Tizen 2.4+ and WebOS 2.0+ last time I checked; it is also supported in recent ARM SoCs, thus recent Android TV boxes also should have hardware decoding).

So encoding media archive in VP9 should allow saving some space.

## Problem
VP9 has some tuning parameters which are not obvious to use or discover. For example, compared to h264, where you have a "set-and-forget" `-crf` parameter, in VP9 this `-crf` is video-dimension-dependant (see https://developers.google.com/media/vp9/settings/vod/). It's also not obvious how to control the "worst" quality codec would give when it wants to lower the bitrate (see good ranting on that here: https://github.com/deterenkelt/Nadeshiko/wiki/Pitfalls-in-VP9).

It also is insanely slow - in the settings which I eventually set up second pass of encoding takes around 4 hours for 1 hour of video (and around 1.5 hours for first pass, not speaking about audio transcoding).

Besides, when you have some media plus you use same device to watch for other sources (like YouTube) you may face the need to keep adjusting the volume as you switch from one media to another, as they do not have the same level of "perceived loudness". I found a great repository having a tool to fix that - https://github.com/slhck/ffmpeg-normalize.

## More on speed
During my experiments I noted that the only step that was decently parallelized was that second pass (albeit in my 6-core-constrained LXC container it used only 3.5 cores while I thought it should be using all 6). First pass uses around 1.2 cores, and audio normalization and encoding are single-threaded by design (and they also take around 10-15 minutes per 1 hour of 1 audio track). So if one has a library which has lots of videos, transcoding them one by one would be too slow to begin with (1 hour of 3-tracked media would be encoded in 6 hours).

So I decided to add more top-level parallelization, and the state I ended in should be so that for a media source with enough videos (around 4+ for a "typical" 8-core desktop) the whole process should take time almost equal to that of running second pass for all videos (all other stuff needed to completely transcode the library should be run in parallel to encoding the video part).
