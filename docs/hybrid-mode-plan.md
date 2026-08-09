# Hybrid mode plan (NPU + CPU)

> **Status: hypothesis, not a result.** Nothing in this document has been
> benchmarked on hardware yet. Numbers below are a back-of-envelope estimate
> meant to decide whether building this is worth the effort — treat them as
> a target to verify, not a finding to cite.

## Motivation

A downstream application performs text-to-speech (TTS) synthesis of a
short, multi-sentence report. Its normal synthesis path runs on a separate,
more capable machine at roughly 5× real-time playback speed. This repository
is about a **fallback path**: when that machine is unavailable, this board
falls back to synthesizing the report itself, CPU-only.

Measured on this board, CPU-only synthesis runs at roughly **half the speed
of playback** — audibly gappy speech, observed as 14 gaps across one sample
recording. That single-sample figure is a low-confidence observation (one
run, not a distribution — see [`methodology.md`](methodology.md)), but
consistent enough with the rest of this project's context to justify
exploring whether the NPU can close the gap.

## Two ways to split the work

### A. Split inside the model

TTS synthesis typically runs in two stages of different computational
character: text → an intermediate acoustic/prosody representation, then
that representation → the audio waveform. In principle only the stage that
suits fixed-shape NPU inference would move to the NPU, with the other
staying on CPU.

Effective if it works, but it requires cutting the model's computation graph
at an internal seam and re-stitching the two halves' outputs back together
— more invasive, more that can go wrong, and it commits to a specific model
architecture.

### B. Split by sentence — recommended variant

A report is a handful of sentences. Assign odd-numbered sentences to the
NPU and even-numbered sentences to the CPU, run both in parallel, concatenate
the resulting audio in order.

**The estimate:** CPU-only synthesis today produces about **0.52 s of audio
per second of compute** (i.e., slower than real time — this is the "half the
speed of playback" figure above, expressed as a rate). If the NPU path could
reach a throughput in the same range as real-time synthesis, running the two
in parallel on alternating sentences could plausibly combine to roughly
**1.5 s of audio produced per second of wall-clock compute** — comfortably
above the 1.0 threshold below which speech starts to break up into audible
gaps.

Advantages over option A:

- Does not require cutting the model apart — each half runs the model (or a
  variant of it) as-is, just on different sentences.
- Graceful degradation: if the NPU path fails or turns out unsupported, the
  application falls back to the current CPU-only behavior with no loss
  compared to today.

## Shared risk

TTS models have variable-length output — a sentence can take anywhere from
about one to five seconds to synthesize — while NPUs (this one included)
generally perform best on fixed-shape workloads. Some of the operations a
TTS model needs may simply not be supported by the `rknpu2` toolchain. This
is the reason TTS synthesis is attempt #2 in this project, not attempt #1:
semantic search (fixed-shape embedding computation) is the better first test
of what this NPU can actually run.

## What would turn this from hypothesis into a result

1. A working NPU-side inference path for at least one TTS stage or model
   variant (see [`log.md`](log.md) for whether that has happened yet).
2. A same-session, back-to-back benchmark of CPU-only vs. hybrid, following
   the checklist in [`methodology.md`](methodology.md).
3. The measured combined throughput, with its distribution — not just
   whether it crossed 1.0 s of audio per second of compute.
