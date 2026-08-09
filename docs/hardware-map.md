# Hardware map — Radxa Zero 3W

Reference data for anyone benchmarking or programming the NPU (Neural
Processing Unit) on this board. Vendor documentation is the authority for
anything not listed here — see the links at the bottom.

## SoC (System on Chip)

| Item | Value |
|---|---|
| SoC | Rockchip RK3566 |
| CPU | Quad-core Arm Cortex-A55 |
| NPU (Neural Processing Unit) | Integrated, exposed to userspace via the `rknpu2` runtime/driver stack |
| NPU peak throughput (vendor spec) | ~0.8 TOPS (Tera Operations Per Second, 0.8 × 10¹² operations/s) |

## Memory and storage

| Item | Value | Why it matters |
|---|---|---|
| RAM | 2 GB | Hard ceiling on model size + working set. Rules out most stock embedding/TTS (Text-to-Speech) models without quantization or a smaller variant. |
| Onboard storage | eMMC (embedded MultiMediaCard), 14.6 GB usable | Fixed, non-removable on this SKU (Stock Keeping Unit) — plan model/toolchain footprint against this number, not the nominal chip size. |

## Thermal

The board ships without active cooling (no fan). Any benchmark that runs the
NPU or CPU under sustained load should treat temperature rise (ΔT, measured
against an idle baseline) as a first-class metric, not an afterthought — see
[`methodology.md`](methodology.md). Passive-only cooling means throttling is
a real possibility on long runs, and a benchmark that ignores it will look
better than the board actually performs once warm.

## Software baseline observed

| Item | Value |
|---|---|
| OS | Debian 12 ("bookworm") |
| Kernel | Vendor kernel, `6.1.84-10-rk2410-nocsf` |
| NPU service | `rknpu2`, running idle at ~2 % CPU and ~1 MB RAM at rest |

Kernel and OS versions drift with vendor image releases — treat the above as
"what this log was produced against," not a permanent fact about the board.

## I/O

The board breaks out a general-purpose I/O (GPIO) header alongside USB and
the usual peripheral interfaces (see vendor schematic for the full pinout).
One point worth flagging for anyone wiring a physical button or switch to
this header: **the GPIO pins have no hardware debounce circuit** — a
mechanical switch will produce multiple rapid transitions per press, so
software debouncing is required on any pin read as a discrete input. This
does not affect the NPU work in this repository directly, but it is the
kind of undocumented gotcha this repo exists to record.

## Vendor documentation

| What | Where |
|---|---|
| Product documentation | <https://radxa.com/products/zeros/zero3w#documentation> |
| Downloads (system images, schematics) | <https://radxa.com/products/zeros/zero3w#downloads> |

The schematic under "Downloads" is the only authoritative source for GPIO
pin-to-function mapping — don't trust third-party pinout diagrams without
cross-checking it.
