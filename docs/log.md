# Attempt log

One entry per attempt. Each entry follows the same four fields:

- **Attempt** — what we tried
- **Result** — worked / partially worked / did not work
- **Numbers** — whatever was actually measured (see
  [`methodology.md`](methodology.md) for what "measured properly" means)
- **Conclusion** — what this tells us, and what it doesn't

Failed and inconclusive attempts are kept, not deleted — a documented dead
end saves the next person the hours we already spent finding it.

---

## 2026-08-09 — Baseline: confirming the NPU is present and idle

**Attempt.** Before running anything, confirmed the `rknpu2` service exists
on this board and checked its resting footprint. Decided the order of the
two planned attempts: semantic search (embedding computation) first,
text-to-speech (TTS) synthesis second — reasoning below.

**Result.** `rknpu2` is present and running, idle. No model has been
converted or run on it yet — this entry is a starting point, not a
benchmark.

**Numbers.**

- NPU (Neural Processing Unit) vendor spec: ~0.8 TOPS (Tera Operations Per
  Second)
- Idle footprint: ~2 % CPU, ~1 MB RAM
- Measurement-methodology defect found before any real benchmark was run:
  reading live CPU load over the SSH (Secure Shell) session used to drive
  the test showed `sshd` at 21.8 % and the interactive shell at 16.6 % —
  see [`methodology.md`](methodology.md) for the fix (background telemetry
  logging, not live polling over SSH).

**Conclusion.** Two things settled before any conversion work starts:

1. **Attempt order.** Embedding computation (semantic search) is a
   fixed-shape workload — the kind NPUs handle well — so it goes first.
   TTS synthesis has variable-length output per sentence, which NPUs
   generally handle less gracefully; it goes second, informed by whatever
   the first attempt teaches us about this toolchain's limits.
2. **Measurement discipline comes before results.** The SSH-overhead finding
   above means every number from here on needs to come from background
   telemetry, not a live shell — otherwise "NPU vs. CPU" numbers would
   actually be measuring "NPU/CPU vs. our own SSH session."

Next entry lands when the semantic-search attempt produces a result —
success, partial success, or a documented reason it doesn't run on this
NPU at all.

---

## 2026-08-10 -- Semantic search: three-way benchmark, a quantization failure, and a non-additive hybrid

**Attempt.** Converted `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
(118M parameters, 384-dim sentence embeddings, Apache-2.0, Polish + English support --
see [`model-attribution.md`](../model-attribution.md)) from its
[Xenova ONNX export](https://huggingface.co/Xenova/paraphrase-multilingual-MiniLM-L12-v2)
to RKNN (target `rk3566`, int8, calibrated on 200 real sentences from the OpenStax
corpus this project searches). Benchmarked three configurations against that corpus
(163,607 sentences extracted from 355 Markdown chapter files, 43 MB): CPU alone, NPU
alone, and CPU+NPU running in parallel on a sentence split (odd/even).

**A measurement mistake found and fixed before trusting any number.** The first full
run (four configurations back-to-back, no cooldown) hit 85 °C sustained, throttled
1800 -> 408 MHz (a 4.4x clock drop), and free memory bottomed out around 150 MB on a
board where `vitalis-waga` (an unrelated always-on service on this device) has absolute
priority. Those numbers are discarded. The fix, now the standing methodology for every
result below:

- every configuration starts from a **confirmed idle baseline** (temp <= 67 °C, clock
  at the idle floor of 408 MHz -- not the 1800 MHz active clock -- system load < 0.5),
  polled locally on-device (not over the SSH session driving the test);
- a **memory guard** skips a configuration outright, with a note instead of a crash, if
  available memory drops under 350 MB before it starts;
- the process **deprioritizes itself** (`nice 15`, raised `oom_score_adj`) so the kernel
  reaches for it, not the always-on services, under pressure;
- temperature, clock, and memory-in-use are sampled on a **fixed 1 Hz timer**,
  independent of how long each sentence takes to process -- this is what the three
  time-series charts below are built from.

Two of the four idle-waits still hit a 300 s timeout without ever catching an instant at
exactly the idle clock floor (governor noise -- the clock briefly spikes even at rest);
those two runs proceeded anyway, starting 1-2 °C above the ideal baseline, disclosed in
the raw results rather than hidden.

**Numbers** (150 sentences per configuration; N=150 chosen specifically to shorten
thermal exposure vs. the original N=600 run):

| | CPU only (fp32) | CPU+NPU (hybrid) | NPU only (int8) |
|---|---|---|---|
| Start temp | 71.1 °C | 67.5 °C | 72.2 °C |
| Per-sentence, median | 297 ms | -- (see below) | 53.6 ms |
| Per-sentence, cold-start (first 30) | 266 ms | -- | 53.8 ms |
| Throughput | 3.25 sentences/s | 5.73 sentences/s | 17.52 sentences/s |
| Whole-library extrapolation (163,607 sentences) | ~14.0 hours | ~7.9 hours | ~2.6 hours |
| Peak temp | 85.0 °C (hit the throttle ceiling) | 84.4 °C | 74.4 °C |
| Clock throttled? | Yes -- 1800 -> 1104 MHz within ~10 s | Yes -- 1800 -> ~1420 MHz around t=14s | No -- flat 1800 MHz the entire run |
| Memory in use | ~1,290-1,299 MB | ~950-1,830 MB (both models loading concurrently) | ~1,161 MB (flat) |

Time-series charts (temperature / clock / memory-in-use, one figure per configuration,
85 °C threshold and throttle-onset markers included):
[`charts/temp_wykres_cpu_fp32.png`](../charts/temp_wykres_cpu_fp32.png),
[`charts/temp_wykres_hybrid.png`](../charts/temp_wykres_hybrid.png),
[`charts/temp_wykres_npu_int8.png`](../charts/temp_wykres_npu_int8.png)
(generator: [`charts/gen_temp_wykresy.py`](../charts/gen_temp_wykresy.py)).

**A smaller CPU model, tried as requested.** A dynamically int8-quantized ONNX export
(same source weights, Xenova's `model_int8.onnx`) cut CPU memory from ~840 MB (Karol's
earlier fp32 reference figure) to ~750 MB after load, and was consistently ~2.9x faster
than fp32 on this board (106 ms/sentence median vs. 297 ms). Search-quality check
(recall@3 against the fp32 reference, over the same 150 sentences -- does the
CPU-int8 model return the same top-3 nearest neighbors as fp32 for a given query):
**0.871** -- quality essentially intact.

**The NPU's own int8 quantization is a different story -- and this is the important
finding.** The RKNN int8 model is fast (17.5 sentences/s, no thermal throttling at all)
but recall@3 against the same fp32 reference came back at **0.062** -- statistically
close to random (a random baseline over 150 candidates would land near 0.02). A
follow-up diagnostic isolated the cause: a second RKNN export with quantization turned
off entirely (fp16, same conversion path, same masking/padding code) scored **0.994**
recall@3 -- essentially perfect. Same toolchain, same model, same input handling; only
the int8 calibration differs. **Conclusion: this is a quantization-calibration failure,
not a conversion or masking bug.** The RKNN model as currently calibrated (200 generic
sentences, default `rknn-toolkit2` w8a8 scheme) is not usable for semantic search --
**do not use `model_int8_rk3566.rknn` for retrieval as published; use the fp16 RKNN
export, or invest in a larger/better calibration set and per-channel quantization
before trusting int8 again.** This is exactly the kind of documented failure this
repository exists to record.

**Does CPU+NPU work in parallel actually add up?** No, and not by a small margin. Naive
best case if both halves ran independently at their solo speed: `max(75/9.08, 75/17.52)`
= 8.3 s. Actual wall-clock time for the hybrid run: **26.2 s** -- roughly 3x worse than
that best case, and the combined throughput (5.73 sentences/s) is *below* CPU-int8 alone
(9.08 sentences/s), let alone anywhere near the naive sum of both (26.6 sentences/s).
The memory time-series explains most of it: both child processes load their models
*concurrently*, on a passively-cooled quad-core Cortex-A55 already carrying background
services -- memory-in-use climbs to ~1,830 MB during that overlapping load phase (see
chart), well above either model's solo footprint, and that contention-heavy startup
dominates the measured wall time far more than the actual per-sentence inference does.
**The two-process, cold-start-each-time design tested here does not deliver additive
throughput on this board.** A persistent worker pool (both models loaded once, kept
warm, fed a work queue) would very likely change this conclusion -- untested here, flagged
as the next thing to try before writing off the hybrid approach entirely.

**Conclusion.**

1. NPU-alone is the clear winner on raw throughput (5.4x faster than CPU-fp32, 1.9x
   faster than CPU-int8) *and* the only configuration that never throttled -- but its
   default int8 quantization is currently unusable for this task's actual purpose
   (semantic search). Use fp16 on the NPU, not int8, until the calibration is fixed.
2. CPU-int8 is a solid, unglamorous fallback: 2.9x faster than fp32, quality intact,
   no NPU toolchain risk.
3. The hybrid split as implemented here is not worth using -- it is slower than
   CPU-int8 alone. Don't ship it without first testing a warm-worker-pool redesign.
4. Whole-board thermal ceiling is real: any CPU-involving configuration reaches 85 °C
   and throttles within seconds under sustained load on this passively-cooled board.
   NPU-only load barely warms the board at all (72 -> 74 °C over the full run) --
   the NPU itself is the thermally cheap option here, independent of its quantization
   problem.

Reproduction: [`bench/bench_safe.py`](../bench/bench_safe.py) (three-way benchmark, idle-gating, memory guard, time-series capture) and [`bench/quality_diag.py`](../bench/quality_diag.py) (the int8-vs-fp16 recall diagnostic). Raw `wyniki_bench_safe.json` is generated fresh per run, not committed -- see [`methodology.md`](methodology.md).

---

## 2026-08-10 (addendum) — The missing comparison: NPU fp16, the only quality-usable NPU configuration

**Why this entry exists.** The 2026-08-10 entry above benchmarked NPU-only using the
int8 RKNN export -- the fast one, and the one later shown (same entry) to have
recall@3 = 0.062, near-random. That is not a configuration anyone should ship. Comparing
its speed against CPU-fp32 and calling it a win was comparing a fast, broken
configuration against a slow, correct one -- not a fair test of "does the NPU actually
help." The missing number was **NPU running fp16** (quantization off, recall@3 = 0.994,
the only NPU configuration confirmed to preserve quality) benchmarked with the exact
same rigor as everything else: idle-gated start, memory guard, 1 Hz temperature/clock/
memory time series. That run is below, and the table from the earlier entry is repeated
here in a form that actually answers the question the whole exercise was for.

**Numbers** (150 sentences, same corpus sample as the earlier entry; NPU fp16 started
from 70.6 °C after a 3 s idle wait):

| | CPU fp32 (quality reference) | CPU int8 (recall@3 = 0.871) | NPU fp16 (recall@3 = 0.994) | NPU int8 -- NOT USABLE (recall@3 = 0.062) |
|---|---|---|---|---|
| Per-sentence, median | 297 ms | 106 ms | 77.2 ms | 53.6 ms |
| Whole-library extrapolation (163,607 sentences) | ~14.0 h | ~5.0 h | ~3.7 h | ~2.6 h |
| Throughput | 3.25 sentences/s | 9.08 sentences/s | 12.17 sentences/s | 17.52 sentences/s |
| Start -> peak temp | 71.1 -> 85.0 °C | 72.2 -> 83.9 °C | 70.6 -> 73.9 °C | 72.2 -> 74.4 °C |
| Clock behavior | Throttled 1800 -> 1104 MHz within ~10 s | Throttled 1800 -> 1416 MHz | Flat 1800 MHz on the 1 Hz chart; a single sub-second dip to 816 MHz was caught only by the finer per-sentence sampling -- not sustained throttling, no thermal cause (peak temp stayed 11 °C below the 85 °C ceiling) | Flat 1800 MHz, zero throttling, entire run |
| Memory in use | ~1,290-1,299 MB | ~750 MB after load | ~1,077 MB after load | ~1,161 MB (flat) |

Chart: [`charts/temp_wykres_npu_fp16.png`](../charts/temp_wykres_npu_fp16.png).

**The answer to "does the unit still win once quality is comparable": yes, but by less
than the int8 number suggested.** NPU-fp16 is **3.85x faster than CPU-fp32** (the
correct baseline-to-baseline comparison: both preserve quality) and still **1.34x
faster than CPU-int8** despite carrying twice the per-weight precision of int8. It also
runs 11 °C cooler at peak than CPU-fp32 and never comes close to the 85 °C throttle
ceiling. The int8 NPU number in the entry above (17.5 sentences/s) was real, but it was
never a usable result -- it was a measurement of how fast this board can compute
something close to noise.

**Conclusion, restated with the fair comparison:**

1. **Use NPU-fp16 for semantic search on this board.** It is the fastest
   *quality-preserving* configuration measured, and the only NPU configuration that is
   both fast and correct.
2. **CPU-int8 remains a reasonable fallback** where the NPU toolchain is unavailable or
   unwanted -- 2.9x faster than CPU-fp32, quality intact, no RKNN dependency.
3. **Never quote the NPU-int8 throughput figure as a capability of this board without
   the recall@3 = 0.062 figure next to it.** See
   [`docs/quantization-warning.md`](quantization-warning.md) for why, and for the
   diagnosis, in one place, so nobody has to reconstruct it from two log entries.

Reproduction: same scripts as the entry above
([`bench/bench_safe.py`](../bench/bench_safe.py) -- run
`python bench_safe.py npu_fp16` to reproduce only this configuration without re-running
the full sweep).
