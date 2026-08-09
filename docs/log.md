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
