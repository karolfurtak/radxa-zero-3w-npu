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

> **If you're converting an embedding model to int8 on this NPU: read
> [`docs/quantization-warning.md`](docs/quantization-warning.md) first.**
> The default calibration workflow produced a model that ran without a
> single error or warning while returning retrieval results close to
> random (recall@3 = 0.062 vs. 0.994 for the same model at fp16) — the kind
> of failure that is invisible until a human checks the actual search
> results.

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
   NPUs are generally good at. First attempt, benchmarked — partially
   worked (see [Status](#status)).
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
| Semantic search on the NPU | Done — fp16 is fast (3.85x CPU-fp32) and correct; int8 is faster but unusable (recall@3 = 0.062) | [`docs/log.md`](docs/log.md), [`docs/quantization-warning.md`](docs/quantization-warning.md) |
| CPU fp32 vs. CPU int8 vs. NPU fp16 vs. NPU int8 vs. hybrid, benchmarked | Done — hybrid does **not** deliver additive throughput as implemented | [`docs/log.md`](docs/log.md) |
| TTS synthesis on the NPU | Not started | [`docs/hybrid-mode-plan.md`](docs/hybrid-mode-plan.md) |

The first real benchmark run on hardware also caught a second measurement
mistake, beyond the SSH-polling one below: running four configurations
back-to-back with no cooldown between them let heat and clock state leak
from one measurement into the next, and free memory dropped to a level that
was a real risk to an unrelated always-on service on the same board. Both
are now fixed as standing methodology (idle-gating before every
configuration, a memory guard, fixed-rate time-series sampling) — see the
2026-08-10 entry in [`docs/log.md`](docs/log.md) for the fix and the
corrected numbers, and the temperature/clock/memory time-series charts (one
per configuration) in [`charts/`](charts/).

[`docs/methodology.md`](docs/methodology.md) documents a third measurement
mistake, caught earliest of the three, before collecting a single real
number: reading live CPU load over the same SSH (Secure Shell) session used
to drive a test inflates the result (`sshd` at 21.8 %, the interactive shell
at 16.6 % of CPU at the moment of reading, on this quad-core board). The fix
— background telemetry logging instead of live polling over SSH — is
mandatory reading before trusting any number in this repository.

## Repository layout

```text
docs/
  hardware-map.md            SoC, memory, storage, cooling, I/O, vendor links
  methodology.md              what to measure and how to avoid biasing it
  log.md                       attempt-by-attempt journal (result + numbers + conclusion)
  hybrid-mode-plan.md         NPU+CPU split plan, marked explicitly as unverified
  quantization-warning.md    int8 on this NPU can silently wreck retrieval quality -- read before you ship int8
conversion/
  convert_to_rknn.py                     ONNX -> RKNN int8, reproduces the semantic-search model
  convert_to_rknn_fp16_diagnostic.py     same, quantization OFF -- the diagnostic that isolated the int8 quality bug
bench/
  bench_safe.py         CPU fp32 / CPU int8 / NPU fp16 / NPU int8 / hybrid benchmark: idle-gating, memory guard, time-series capture
  quality_diag.py        int8-vs-fp16 recall@k diagnostic (isolates quantization vs. conversion bugs)
charts/
  gen_temp_wykresy.py    generates the time-series charts below from bench_safe.py output
  temp_wykres_*.png      temperature / clock / memory-in-use vs. time, one per configuration (4 configurations)
model-attribution.md    source model, license, and what this repo adds (see below)
```

## Model used for semantic search

`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (118M
parameters, Apache-2.0, Polish + English among 50+ supported languages) —
source, license, and exactly what this repo changed:
[`model-attribution.md`](model-attribution.md). The converted `.rknn` file
itself (~120 MB) is not committed here — over plain git's 100 MB per-file
limit — but [`conversion/convert_to_rknn.py`](conversion/convert_to_rknn.py)
reproduces it from the public source weights in a few minutes.

## Continuous integration

This repository is documentation-only for now — there is no code to unit
test or compile. CI runs `markdownlint` on every push and pull request as a
lightweight correctness check on the docs themselves (broken lists, heading
structure, stray trailing whitespace); it is not a stand-in for hardware
verification. A CI check exercising actual NPU code will be added once this
repository contains a conversion or benchmark script — until then, adding
one just to have a green badge would be a fake signal, not a real one.

## License

Copyright (c) 2026 Karol Furtak. **All rights reserved.** Commercial use, copying, distribution and modification only with the author's written permission — see [LICENSE](LICENSE). Viewing the code on GitHub does not grant a licence.

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
płytki — stąd wartość mają też próby nieudane.

**Wyszukiwanie znaczeniowe (model `paraphrase-multilingual-MiniLM-L12-v2`,
118 mln parametrów, licencja Apache-2.0, polski i angielski) — zmierzone
cztery warianty:** procesor pełną precyzją (fp32, punkt odniesienia jakości),
procesor int8, jednostka fp16, jednostka int8, plus procesor i jednostka
równolegle (podział zdań nieparzyste/parzyste). **Pierwszy pomiar porównał
prędkość jednostki w wariancie int8 z procesorem fp32 — porównanie
nieuczciwe, bo int8 na jednostce okazał się bezużyteczny jakościowo**
(recall@3 = 0,062 względem pełnej precyzji — poziom bliski losowemu),
podczas gdy ten sam model bez kwantyzacji (fp16) na tej samej jednostce
daje recall@3 = 0,994. **Wniosek diagnostyczny: to wina kalibracji
kwantyzacji (`rknn-toolkit2`, schemat w8a8), nie błąd konwersji** — pełne
uzasadnienie i ostrzeżenie dla innych: `docs/quantization-warning.md`.

**Uczciwe porównanie (warianty o zachowanej jakości):** jednostka fp16 —
77,2 ms/zdanie, 12,17 zdania/s — jest **3,85× szybsza niż procesor fp32**
i wciąż **1,34× szybsza niż procesor int8** (recall@3 = 0,871), mimo
dwukrotnie większej precyzji per liczba niż int8. Szczyt temperatury dla
jednostki fp16: 73,9°C (procesor fp32 dochodzi do progu throttlingu 85°C).
**Jednostka nadal wygrywa — ale mniej efektownie, niż sugerował pierwszy,
nieuczciwy pomiar.**

Praca równoległa (procesor + jednostka) **nie sumuje się** — złożone
obciążenie wyszło wolniejsze niż sam procesor int8 osobno, prawdopodobnie
przez rywalizację obu procesów o zasoby przy jednoczesnym ładowaniu modeli
na słabym, czterordzeniowym układzie. Pełne liczby, cztery wykresy
temperatura/takt/pamięć w funkcji czasu i uzasadnienie: `docs/log.md`,
wpisy 2026-08-10 (główny i uzupełnienie).

Po drodze wyłapano i opisano dwa błędy pomiarowe: (1) odczyt obciążenia
procesora przez to samo połączenie SSH, którym steruje się testem, zawyża
wynik (zmierzono: `sshd` 21,8 %, powłoka 16,6 %) — właściwa metoda to zapis
telemetrii w tle, nie odczyt na żywo; (2) pomiar czterech wariantów jeden po
drugim bez wychłodzenia między nimi zawyżał temperaturę startową kolejnych
wariantów i ryzykował pamięć współdzieloną z inną, stale działającą usługą
na tej samej płytce — poprawka: każdy wariant startuje z potwierdzonego
stanu spoczynkowego, ze strażą pamięci i próbkowaniem temperatury/taktu/
pamięci co 1 s.

Synteza mowy — druga próba, jeszcze nie rozpoczęta. Tryb hybrydowy dla niej
opisany w `docs/hybrid-mode-plan.md` pozostaje hipotezą — wynik z
wyszukiwania znaczeniowego (praca równoległa się nie sumuje) jest istotnym
ostrzeżeniem przed założeniem, że ten sam wzorzec zadziała dla mowy bez
osobnego sprawdzenia.
