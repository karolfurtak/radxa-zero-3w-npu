# Measurement methodology

How to compare the NPU (Neural Processing Unit) against CPU-only execution
on this board fairly — and a measurement mistake we made ourselves that is
worth avoiding.

## What to measure

For every attempt, record all three — one number alone is not a comparison:

1. **Processing time** — wall-clock latency for the task (e.g. one embedding
   computed, one sentence synthesized). Report both a single-run figure and
   a distribution (min/median/max over several runs); a single sample tells
   you a number, not a trend.
2. **Memory usage** — peak resident memory of the process under test, on a
   board with only 2 GB total. Memory pressure here can cause swapping or
   OOM (Out Of Memory) kills well before it would on a desktop-class machine,
   so it is not optional to record.
3. **Temperature rise (ΔT)** — board temperature at the end of the run minus
   the idle baseline measured immediately before the run started. On a
   passively-cooled board (see [`hardware-map.md`](hardware-map.md)),
   sustained NPU or CPU load can throttle performance, which will silently
   distort any timing number collected later in a long run.

## The pitfall: measuring over the connection you're using to measure

While setting up the first benchmark on this board, we watched CPU load
during an SSH (Secure Shell) session and found:

| Process | CPU load at time of reading |
|---|---|
| `sshd` (SSH daemon) | 21.8 % |
| Interactive shell | 16.6 % |

That is close to 40 percentage points of a small quad-core board's capacity
consumed by the tooling used to *observe* the benchmark, not by the
benchmark itself. On a machine this size, that is large enough to swamp the
signal you're trying to measure — a workload that looks NPU-bound or
CPU-bound over SSH may simply be sharing the core with your own remote
session.

**Consequence:** don't read live metrics (`top`, `htop`, ad-hoc `ps` polling,
etc.) over the same SSH session that is driving the test.

**Correct approach:** run a lightweight telemetry logger *on the device*, in
the background, writing to a local file (CPU%, memory, temperature, at a
fixed sampling interval) for the duration of the test. Start the logger,
run the test headless or via a command that returns immediately, let the
logger finish, then disconnect or read the log file after the fact — not
during. If you must observe live, expect an SSH-session tax on every number
you read and say so in the write-up.

## Fair-comparison checklist

- [ ] Same board, same thermal starting point (idle baseline, not warm from
      a previous run)
- [ ] Same input (same text, same sentence count, same model precision)
- [ ] Telemetry logged in the background, not read live over SSH
- [ ] Multiple runs reported as a distribution, not a single number
- [ ] ΔT reported alongside latency, not omitted because it "looked fine"
- [ ] NPU and CPU-only paths benchmarked in the same session, back to back,
      to cancel out day-to-day ambient temperature drift
