# Radxa Zero 3W NPU (rknpu2) — Experiment Log

An in-progress log of using the Neural Processing Unit (NPU) on the
**Radxa Zero 3W** (Rockchip RK3566, `rknpu2` runtime, ~0.8 TOPS — Tera
Operations Per Second) for real workloads on a 2 GB, passively-cooled,
single-board computer.

## Why this repository exists

Nobody has written up what it's actually like to put this NPU to work. The
vendor ships a runtime and some sample models; what's missing is the
in-between: which real workloads convert cleanly, which don't and why, how
to benchmark the NPU against the CPU without lying to yourself, and what a
2 GB memory ceiling and passive cooling actually cost you in practice.

Failed attempts are documented as thoroughly as working ones. "This model
doesn't convert because `rknpu2` lacks operator X" is exactly the kind of
sentence that saves the next person the hours it took us to find it — a
lesson learned the same way on a companion project,
[calculix-arm64-debian-build](https://github.com/karolfurtak/calculix-arm64-debian-build),
where the value turned out to be the documented workarounds, not the build
script itself.

## The board and the unit

| Item | Value |
|---|---|
| SoC (System on Chip) | Rockchip RK3566, quad-core Arm Cortex-A55 |
| NPU runtime | `rknpu2` |
| NPU peak throughput (vendor spec) | ~0.8 TOPS |
| RAM | 2 GB |
| Storage | eMMC (embedded MultiMediaCard), 14.6 GB usable |
| Cooling | Passive (no fan) |

Full parameter table, interfaces, and known gotchas:
[`docs/hardware-map.md`](docs/hardware-map.md).

## What we're trying to do, in order

1. **Semantic search** over a small technical-manual corpus, including text
   in Polish — a fixed-shape embedding computation, and the kind of workload
   NPUs are generally good at. First attempt, in progress.
2. **Text-to-speech (TTS) synthesis** as a fallback path on a downstream
   application, used only when that application's primary (faster) synthesis
   path is unavailable. Planned second, specifically *because* TTS models
   have variable-length output per sentence — a shape NPUs tend to handle
   worse than fixed-shape work — so it's a harder test to run second, once
   the first attempt has taught us the toolchain's real limits.

A hybrid mode (NPU + CPU splitting the sentence workload) is planned for
attempt 2 and written up — as a hypothesis, not a result — in
[`docs/hybrid-mode-plan.md`](docs/hybrid-mode-plan.md).

## Status

| Attempt | Status | Details |
|---|---|---|
| NPU present and idle, baseline recorded | Done | [`docs/log.md`](docs/log.md) |
| Semantic search on the NPU | In progress | [`docs/log.md`](docs/log.md) |
| TTS synthesis on the NPU | Not started | [`docs/hybrid-mode-plan.md`](docs/hybrid-mode-plan.md) |

Nothing has been benchmarked on real hardware yet at the time of writing —
see [`docs/log.md`](docs/log.md) for the current entry and
[`docs/methodology.md`](docs/methodology.md) for a measurement mistake we
already made and fixed before collecting a single real number: reading live
CPU load over the same SSH (Secure Shell) session used to drive a test
inflates the result (`sshd` at 21.8 %, the interactive shell at 16.6 % of
CPU at the moment of reading, on this quad-core board). The fix — background
telemetry logging instead of live polling over SSH — is mandatory reading
before trusting any number in this repository.

## Repository layout

```text
docs/
  hardware-map.md      SoC, memory, storage, cooling, I/O, vendor links
  methodology.md        what to measure and how to avoid biasing it
  log.md                 attempt-by-attempt journal (result + numbers + conclusion)
  hybrid-mode-plan.md   NPU+CPU split plan, marked explicitly as unverified
```

## Continuous integration

This repository is documentation-only for now — there is no code to unit
test or compile. CI runs `markdownlint` on every push and pull request as a
lightweight correctness check on the docs themselves (broken lists, heading
structure, stray trailing whitespace); it is not a stand-in for hardware
verification. A CI check exercising actual NPU code will be added once this
repository contains a conversion or benchmark script — until then, adding
one just to have a green badge would be a fake signal, not a real one.

## License

[MIT](LICENSE) — matches the sibling
[calculix-arm64-debian-build](https://github.com/karolfurtak/calculix-arm64-debian-build)
repository, keeping any future scripts or code snippets here maximally
reusable without license friction. Documentation and prose are covered under
the same terms for simplicity, at the minor cost of MIT being an
unconventional choice for pure text.

## Contributing

If you have a Radxa Zero 3W (or another RK3566-class board) and have tried
something similar — including something that failed outright — an issue or
pull request describing what you tried and what happened is welcome. The
goal is a written record the search engines can find, not a polished
product.

---

## Streszczenie (polski)

Repozytorium dokumentuje próby wykorzystania jednostki obliczeniowej sieci
neuronowych (NPU, `rknpu2`, ~0,8 biliona operacji na sekundę) na płytce
Radxa Zero 3W (układ RK3566, 2 GB pamięci, chłodzenie bierne, pamięć
wbudowana eMMC 14,6 GB). Nikt dotąd nie opisał tej jednostki dla tej
płytki — stąd wartość mają też próby nieudane: informacja „ten model się
nie konwertuje, bo brakuje takiej operacji" oszczędza kolejnej osobie
godziny pracy. Plan: wyszukiwanie znaczeniowe jako pierwsza próba (w toku),
synteza mowy jako druga (jeszcze nie rozpoczęta). Po drodze wyłapano i
opisano błąd pomiarowy: odczyt obciążenia procesora przez to samo
połączenie SSH, którym steruje się testem, zawyża wynik (zmierzono: `sshd`
21,8 %, powłoka 16,6 %) — właściwa metoda to zapis telemetrii w tle, nie
odczyt na żywo. Tryb hybrydowy (NPU + procesor) opisany w
`docs/hybrid-mode-plan.md` jest oznaczony wprost jako hipoteza do
zweryfikowania, nie wynik.
