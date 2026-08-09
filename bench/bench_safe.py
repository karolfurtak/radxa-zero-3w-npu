#!/usr/bin/env python3
"""
bench_safe.py -- rewrite after the 1st run (wyniki_bench.json) was flagged as invalid:
it ran CPU fp32 -> CPU int8 -> NPU -> hybrid back-to-back with no cooldown, hit 85 degC
sustained (throttled 1800 -> 408 MHz, a 4.4x clock drop), and free memory bottomed out
at ~150 MB while vitalis-waga has absolute priority. Numbers from that run mixed variants
measured at different, uncontrolled clock speeds -- not a fair comparison, and the low
free-memory point was a real risk to the always-on service.

Fixes in this version:
  1. Cooldown gate between every variant: wait until temp <= COOLDOWN_TEMP_C and cpu freq
     back at BASE_FREQ_KHZ before starting the next one, so every variant starts from the
     same thermal state (fair) instead of inheriting heat from whatever ran before it.
  2. Per-sample freq + temp capture (cheap local sysfs reads, not SSH polling) -- so a
     mid-run throttle shows up in the data instead of being averaged away.
  3. Memory guard: MemAvailable checked before every variant; abort (not crash) below
     MIN_AVAILABLE_MB, with a clear note in the results instead of risking vitalis-waga.
  4. Self-deprioritization: nice + oom_score_adj raised so the kernel reaches for this
     process, not the always-on services, under memory pressure.
  5. Smaller N per variant (150, not 600) specifically to shorten the thermal exposure
     window -- plus a short separate "cold" burst (first 30 samples right after warmup,
     always closest to full clock) reported distinctly from the full run's distribution.
"""
import gc
import json
import multiprocessing as mp
import os
import threading
import time
from pathlib import Path

import numpy as np
from tokenizers import Tokenizer

BASE = Path(__file__).parent
SEQ_LEN = 64
TOKENIZER_PATH = str(BASE / "tokenizer.json")
ONNX_FP32 = str(BASE / "model.onnx")
ONNX_INT8 = str(BASE / "model_int8.onnx")
RKNN_PATH = str(BASE / "model_int8_rk3566.rknn")
SAMPLE_PATH = BASE / "sample_600.jsonl"
OUT_PATH = BASE / "wyniki_bench_safe.json"

LIB_TOTAL_SENTENCES = 163607
N_PER_VARIANT = 150
N_COLD_BURST = 30

MIN_AVAILABLE_MB = 350
# Prawdziwy stan spoczynkowy tej plytki (potwierdzony telemetria + wymog Karola
# "wszystkie testy startuj na iddle"): ~65-67 stC, takt DOLNY 408 MHz (nie gorny
# 1800 MHz -- to bylby stan obciazenia), obciazenie systemu ponizej 0,5.
IDLE_TEMP_C = 67.0
IDLE_FREQ_KHZ = 408000
IDLE_LOAD1_MAX = 0.5
ACTIVE_FREQ_KHZ = 1800000       # gorny takt pod obciazeniem -- throttling = spadek ponizej tego
COOLDOWN_TIMEOUT_S = 300
HARD_ABORT_TEMP_C = 88.0        # stop a run outright if exceeded mid-loop
TEMP_SAMPLE_INTERVAL_S = 1.0    # rozdzielczosc szeregu czasowego temperatury per-wariant

with open(SAMPLE_PATH, encoding="utf-8") as f:
    ALL_SENTENCES = [json.loads(l)["text"] for l in f]


def self_deprioritize():
    os.nice(15)
    try:
        Path(f"/proc/self/oom_score_adj").write_text("500")
    except Exception:
        pass


def temp_soc_c() -> float:
    return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000.0


def cpu_freq_khz() -> int:
    return int(Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq").read_text())


def mem_available_mb() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 1024.0
    return -1.0


def mem_total_mb() -> float:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) / 1024.0
    return -1.0


MEM_TOTAL_MB = mem_total_mb()


def mem_used_mb() -> float:
    """Karol: 'ilosc zajetego ramu' -- total minus available (available juz
    liczy sie z bufory/cache jako odzyskiwalne, wiec to lepsza miara nacisku
    na pamiec niz surowe 'used' z /proc/meminfo)."""
    return MEM_TOTAL_MB - mem_available_mb()


def vmrss_mb() -> float:
    for linia in Path("/proc/self/status").read_text().splitlines():
        if linia.startswith("VmRSS:"):
            return int(linia.split()[1]) / 1024.0
    return -1.0


def load1() -> float:
    return float(Path("/proc/loadavg").read_text().split()[0])


def wait_for_idle() -> dict:
    """Block until the board is genuinely at rest -- temp <= IDLE_TEMP_C, freq at the
    IDLE floor (408 MHz, not the 1800 MHz active clock), load1 < IDLE_LOAD1_MAX -- or
    timeout. Local sysfs/procfs reads only, no live SSH polling."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < COOLDOWN_TIMEOUT_S:
        t, f, l = temp_soc_c(), cpu_freq_khz(), load1()
        if t <= IDLE_TEMP_C and f == IDLE_FREQ_KHZ and l < IDLE_LOAD1_MAX:
            return {"ok": True, "waited_s": round(time.monotonic() - t0, 1), "temp_c": t, "freq_khz": f, "load1": l}
        time.sleep(3)
    return {"ok": False, "waited_s": round(time.monotonic() - t0, 1), "temp_c": temp_soc_c(),
            "freq_khz": cpu_freq_khz(), "load1": load1(),
            "uwaga": f"timeout oczekiwania na iddle po {COOLDOWN_TIMEOUT_S}s -- pomiar mimo to wykonany, "
                     "stan startowy zapisany ponizej zamiast idealnego iddle"}


class SamplerTemperatury:
    """Watek w tle: probkuje temp_soc_c + freq co TEMP_SAMPLE_INTERVAL_S od momentu start()
    do stop() -- niezalezne od tempa przetwarzania zdan, wiec daje rowna siatke czasowa
    do wykresu temperatura(czas), niezaleznie ile trwa pojedyncza inferencja."""

    def __init__(self):
        self._stop = threading.Event()
        self._dane = []
        self._t0 = None
        self._thread = None

    def _run(self):
        while not self._stop.is_set():
            self._dane.append({
                "elapsed_s": round(time.monotonic() - self._t0, 2),
                "temp_c": temp_soc_c(),
                "freq_khz": cpu_freq_khz(),
                "mem_used_mb": round(mem_used_mb(), 1),
            })
            self._stop.wait(TEMP_SAMPLE_INTERVAL_S)

    def start(self):
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> list:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        return self._dane


def check_memory_guard(nazwa_etapu: str) -> dict:
    avail = mem_available_mb()
    ok = avail >= MIN_AVAILABLE_MB
    return {"etap": nazwa_etapu, "mem_available_mb": round(avail, 1), "ok": ok}


def tokenizuj_jedno(tok: Tokenizer, zdanie: str):
    tok.enable_padding(length=SEQ_LEN, pad_id=0)
    tok.enable_truncation(max_length=SEQ_LEN)
    enc = tok.encode(zdanie)
    input_ids = np.array([enc.ids], dtype=np.int64)
    attention_mask = np.array([enc.attention_mask], dtype=np.int64)
    token_type_ids = np.zeros_like(input_ids)
    return input_ids, attention_mask, token_type_ids


def mean_pool(last_hidden: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    mask = attention_mask[..., None].astype(np.float32)
    summed = (last_hidden * mask).sum(axis=1)
    counts = np.clip(mask.sum(axis=1), 1e-9, None)
    return summed / counts


def stats_z_czasow(czasy):
    a = sorted(czasy)
    n = len(a)
    return {
        "min_s": round(a[0], 4), "p50_s": round(a[n // 2], 4),
        "p90_s": round(a[int(n * 0.9)], 4), "max_s": round(a[-1], 4),
        "srednia_s": round(sum(a) / n, 4),
    }


def run_timed_loop(infer_fn, sentences, tok):
    """Runs infer_fn(ids, mask, typ) per sentence, recording time + freq + temp per sample.
    Splits results into 'cold' (first N_COLD_BURST, closest to full clock) and 'full' (all)."""
    czasy, freqs, temps = [], [], []
    embeddingi = []
    t_start = time.monotonic()
    for i, s in enumerate(sentences):
        ids, mask, typ = tokenizuj_jedno(tok, s)
        f_before = cpu_freq_khz()
        t0 = time.monotonic()
        out = infer_fn(ids, mask, typ)
        dt = time.monotonic() - t0
        czasy.append(dt)
        freqs.append(f_before)
        temps.append(temp_soc_c())
        embeddingi.append(mean_pool(out, mask)[0])
        if temps[-1] >= HARD_ABORT_TEMP_C:
            return {"przerwano_przegrzanie": True, "przy_probce": i + 1, "temp_c": temps[-1]}, embeddingi
    t_total = time.monotonic() - t_start

    cold_czasy = czasy[:N_COLD_BURST]
    cold_freqs = freqs[:N_COLD_BURST]
    return {
        "przerwano_przegrzanie": False,
        "n": len(sentences),
        "czas_calkowity_s": round(t_total, 2),
        "przepustowosc_zdan_na_s": round(len(sentences) / t_total, 3),
        "ekstrapolacja_cala_biblioteka_s": round(LIB_TOTAL_SENTENCES / (len(sentences) / t_total), 1),
        "czas_per_zdanie_caly_bieg": stats_z_czasow(czasy),
        "czas_per_zdanie_zimny_start_pierwsze_n": {
            "n": len(cold_czasy),
            **stats_z_czasow(cold_czasy),
            "freq_khz_min": min(cold_freqs), "freq_khz_max": max(cold_freqs),
            "przy_pelnym_zegarze": min(cold_freqs) == ACTIVE_FREQ_KHZ,
        },
        "freq_khz_min_caly_bieg": min(freqs), "freq_khz_max_caly_bieg": max(freqs),
        "throttling_wystapil": min(freqs) < ACTIVE_FREQ_KHZ,
        "temp_min_c": min(temps), "temp_max_c": max(temps),
    }, embeddingi


def _zapisz_szereg_czasowy(nazwa: str, dane: list, temp_startowa: float, koniec_pomiaru_s: float) -> str:
    """elapsed_s=0 w probkach == start wlasciwego pomiaru (sampler startuje tuz przed
    petla inferencji); koniec_pomiaru_s == moment jej zakonczenia -- oba potrzebne do
    odroznienia na wykresie fazy obliczen od ewentualnego stygniecia po fakcie."""
    p = BASE / f"temp_szereg_{nazwa}.json"
    p.write_text(json.dumps({
        "wariant": nazwa, "temp_startowa_c": temp_startowa,
        "start_pomiaru_s": 0.0, "koniec_pomiaru_s": round(koniec_pomiaru_s, 2),
        "probki": dane,
    }, indent=2, ensure_ascii=False))
    return str(p)


def run_cpu(onnx_path: str, sentences: list, nazwa: str) -> dict:
    import onnxruntime as ort
    tok = Tokenizer.from_file(TOKENIZER_PATH)
    temp_startowa = temp_soc_c()
    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    ids, mask, typ = tokenizuj_jedno(tok, sentences[0])
    sess.run(None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": typ})
    mem_po_zaladowaniu = vmrss_mb()

    def infer(ids, mask, typ):
        (out,) = sess.run(None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": typ})
        return out

    sampler = SamplerTemperatury()
    sampler.start()
    wyniki, emb = run_timed_loop(infer, sentences, tok)
    szereg = sampler.stop()

    koniec_s = wyniki.get("czas_calkowity_s", szereg[-1]["elapsed_s"] if szereg else 0.0)
    wyniki.update({"wariant": nazwa, "temp_startowa_c": temp_startowa,
                   "pamiec_po_zaladowaniu_mb": round(mem_po_zaladowaniu, 1),
                   "pamiec_po_biegu_mb": round(vmrss_mb(), 1),
                   "szereg_czasowy_plik": _zapisz_szereg_czasowy(nazwa, szereg, temp_startowa, koniec_s)})
    return wyniki, emb


def run_npu(sentences: list, rknn_path: str, nazwa: str) -> dict:
    from rknnlite.api import RKNNLite
    tok = Tokenizer.from_file(TOKENIZER_PATH)
    temp_startowa = temp_soc_c()
    rknn = RKNNLite()
    if rknn.load_rknn(rknn_path) != 0:
        return {"wariant": nazwa, "blad": "load_rknn"}, []
    if rknn.init_runtime() != 0:
        return {"wariant": nazwa, "blad": "init_runtime"}, []
    ids, mask, typ = tokenizuj_jedno(tok, sentences[0])
    rknn.inference(inputs=[ids, mask, typ])
    mem_po_zaladowaniu = vmrss_mb()

    def infer(ids, mask, typ):
        return rknn.inference(inputs=[ids, mask, typ])[0]

    sampler = SamplerTemperatury()
    sampler.start()
    wyniki, emb = run_timed_loop(infer, sentences, tok)
    szereg = sampler.stop()

    koniec_s = wyniki.get("czas_calkowity_s", szereg[-1]["elapsed_s"] if szereg else 0.0)
    wyniki.update({"wariant": nazwa, "temp_startowa_c": temp_startowa,
                   "pamiec_po_zaladowaniu_mb": round(mem_po_zaladowaniu, 1),
                   "pamiec_po_biegu_mb": round(vmrss_mb(), 1),
                   "szereg_czasowy_plik": _zapisz_szereg_czasowy(nazwa, szereg, temp_startowa, koniec_s)})
    rknn.release()
    return wyniki, emb


def _worker_cpu(sentences, wynik_path):
    self_deprioritize()
    import onnxruntime as ort
    tok = Tokenizer.from_file(TOKENIZER_PATH)
    sess = ort.InferenceSession(ONNX_INT8, providers=["CPUExecutionProvider"])
    ids, mask, typ = tokenizuj_jedno(tok, sentences[0])
    sess.run(None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": typ})
    t0 = time.monotonic()
    for s in sentences:
        ids, mask, typ = tokenizuj_jedno(tok, s)
        sess.run(None, {"input_ids": ids, "attention_mask": mask, "token_type_ids": typ})
    dt = time.monotonic() - t0
    Path(wynik_path).write_text(json.dumps({"n": len(sentences), "czas_s": dt}))


def _worker_npu(sentences, wynik_path):
    self_deprioritize()
    from rknnlite.api import RKNNLite
    tok = Tokenizer.from_file(TOKENIZER_PATH)
    rknn = RKNNLite()
    rknn.load_rknn(RKNN_PATH)
    rknn.init_runtime()
    ids, mask, typ = tokenizuj_jedno(tok, sentences[0])
    rknn.inference(inputs=[ids, mask, typ])
    t0 = time.monotonic()
    for s in sentences:
        ids, mask, typ = tokenizuj_jedno(tok, s)
        rknn.inference(inputs=[ids, mask, typ])
    dt = time.monotonic() - t0
    rknn.release()
    Path(wynik_path).write_text(json.dumps({"n": len(sentences), "czas_s": dt}))


def run_hybrid(sentences: list) -> dict:
    nieparzyste = sentences[0::2]
    parzyste = sentences[1::2]
    p_npu, p_cpu = BASE / "_hyb_npu.json", BASE / "_hyb_cpu.json"
    for p in (p_npu, p_cpu):
        if p.exists():
            p.unlink()

    temp_startowa = temp_soc_c()
    sampler = SamplerTemperatury()
    sampler.start()
    t_start = time.monotonic()
    proc_npu = mp.Process(target=_worker_npu, args=(nieparzyste, str(p_npu)))
    proc_cpu = mp.Process(target=_worker_cpu, args=(parzyste, str(p_cpu)))
    proc_npu.start(); proc_cpu.start()
    proc_npu.join(); proc_cpu.join()
    t_total = time.monotonic() - t_start
    szereg = sampler.stop()
    temp_po = temp_soc_c()

    wynik_npu = json.loads(p_npu.read_text()) if p_npu.exists() else None
    wynik_cpu = json.loads(p_cpu.read_text()) if p_cpu.exists() else None
    return {
        "wariant": "hybrid_cpu_int8_plus_npu_int8_rownolegle",
        "opis_podzialu": "zdania nieparzyste -> NPU, zdania parzyste -> CPU(int8), 2 procesy rownolegle",
        "n_zdan_probki": len(sentences),
        "temp_startowa_c": temp_startowa,
        "czas_calkowity_rownolegle_s": round(t_total, 2),
        "przepustowosc_zdan_na_s_rownolegle": round(len(sentences) / t_total, 3),
        "ekstrapolacja_cala_biblioteka_s": round(LIB_TOTAL_SENTENCES / (len(sentences) / t_total), 1),
        "npu_polowka_czas_s": wynik_npu["czas_s"] if wynik_npu else None,
        "npu_polowka_n": wynik_npu["n"] if wynik_npu else None,
        "npu_polowka_przepustowosc": round(wynik_npu["n"] / wynik_npu["czas_s"], 3) if wynik_npu else None,
        "cpu_polowka_czas_s": wynik_cpu["czas_s"] if wynik_cpu else None,
        "cpu_polowka_n": wynik_cpu["n"] if wynik_cpu else None,
        "cpu_polowka_przepustowosc": round(wynik_cpu["n"] / wynik_cpu["czas_s"], 3) if wynik_cpu else None,
        "temp_po_c": temp_po, "delta_temp_c": round(temp_po - temp_startowa, 1),
        "szereg_czasowy_plik": _zapisz_szereg_czasowy("hybrid", szereg, temp_startowa, t_total),
    }


def topk_neighbors(mat, i, k):
    sims = mat @ mat[i] / (np.linalg.norm(mat, axis=1) * np.linalg.norm(mat[i]) + 1e-9)
    order = np.argsort(-sims)
    return set([j for j in order if j != i][:k])


def ocena_jakosci(emb_ref: list, emb_test: list, k: int = 3) -> dict:
    n = min(len(emb_ref), len(emb_test))
    ref, test = np.array(emb_ref[:n]), np.array(emb_test[:n])
    trafienia = mozliwe = 0
    for i in range(n):
        trafienia += len(topk_neighbors(ref, i, k) & topk_neighbors(test, i, k))
        mozliwe += k
    return {"recall_at_k": round(trafienia / mozliwe, 3), "k": k, "n_zdan": n}


if __name__ == "__main__":
    self_deprioritize()
    wyniki = {"uwaga_metodologiczna": (
        "Poprzedni bieg (wyniki_bench.json) uniewazniony: cztery warianty bez wychlodzenia "
        "miedzy nimi, SoC throttlowany (1800->408 MHz) przy 85 stC, wolna pamiec spadla do "
        "~150 MB. Ten bieg: KAZDY wariant startuje z potwierdzonego stanu spoczynkowego "
        f"(temp <= {IDLE_TEMP_C} stC, takt = {IDLE_FREQ_KHZ/1000:.0f} MHz -- dolny/iddle, nie gorny "
        f"aktywny -- obciazenie < {IDLE_LOAD1_MAX}), straz pamieci (próg {MIN_AVAILABLE_MB} MB), "
        f"niski priorytet (nice 15, oom_score_adj 500), N={N_PER_VARIANT}, szereg czasowy "
        f"temperatura+takt co {TEMP_SAMPLE_INTERVAL_S:.0f} s zapisany osobno per wariant "
        "(temp_szereg_<wariant>.json) do wykresu temperatura(czas)."
    )}
    sentences = ALL_SENTENCES[:N_PER_VARIANT]

    tok_dummy = Tokenizer.from_file(TOKENIZER_PATH)

    plan = [
        ("cpu_fp32", lambda s: run_cpu(ONNX_FP32, s, "cpu_fp32")),
        ("cpu_int8", lambda s: run_cpu(ONNX_INT8, s, "cpu_int8")),
        ("npu_int8", lambda s: run_npu(s, RKNN_PATH, "npu_int8")),
    ]

    embeddingi_by_wariant = {}
    for nazwa, fn in plan:
        guard = check_memory_guard(nazwa)
        wyniki.setdefault("straz_pamieci", []).append(guard)
        if not guard["ok"]:
            wyniki[nazwa] = {"pominieto": True, "powod": "mem_available ponizej progu", **guard}
            continue

        idle = wait_for_idle()
        wyniki.setdefault("oczekiwanie_na_iddle", []).append({nazwa: idle})

        print(f"== {nazwa} == (start: {idle.get('temp_c')} stC, {idle.get('freq_khz')} kHz)", flush=True)
        wynik, emb = fn(sentences)
        wyniki[nazwa] = wynik
        embeddingi_by_wariant[nazwa] = emb
        gc.collect()

    # hybrid: needs its own memory guard + idle wait, both sub-models loaded at once
    guard = check_memory_guard("hybrid")
    wyniki["straz_pamieci"].append(guard)
    if guard["ok"]:
        idle = wait_for_idle()
        wyniki.setdefault("oczekiwanie_na_iddle", []).append({"hybrid": idle})
        print(f"== hybrid == (start: {idle.get('temp_c')} stC, {idle.get('freq_khz')} kHz)", flush=True)
        wyniki["hybrid"] = run_hybrid(sentences)
    else:
        wyniki["hybrid"] = {"pominieto": True, "powod": "mem_available ponizej progu", **guard}

    if "cpu_fp32" in embeddingi_by_wariant:
        ref = embeddingi_by_wariant["cpu_fp32"]
        for wariant in ("cpu_int8", "npu_int8"):
            if wariant in embeddingi_by_wariant:
                wyniki[f"jakosc_{wariant}_vs_fp32"] = ocena_jakosci(ref, embeddingi_by_wariant[wariant], k=3)

    OUT_PATH.write_text(json.dumps(wyniki, indent=2, ensure_ascii=False))
    print(f"ZAPISANO: {OUT_PATH}")
