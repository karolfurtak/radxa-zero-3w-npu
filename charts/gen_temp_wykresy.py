#!/usr/bin/env python3
"""
gen_temp_wykresy.py -- temperatura SoC (System on Chip), takt rdzeni i zajetosc RAM w
funkcji czasu, dla trzech przypadkow: sam procesor (CPU), procesor + jednostka rownolegle
(CPU+NPU, hybrid), sama jednostka (NPU -- Neural Processing Unit). Dane z bench_safe.py
(temp_szereg_*.json, probkowanie co 1 s, niezalezne od tempa przetwarzania zdan).

Uklad: TRZY PANELE JEDEN POD DRUGIM ze wspolna osia czasu (nie trzy osie Y na jednym
rysunku) -- trzy wielkosci o niewspolmiernych jednostkach (st C, MHz, MB) na jednej osi
pionowej wymagalyby trzech roznie skalowanych osi Y na tym samym polu wykresu, co przy
stylu czarno-bialym (bez koloru odrozniajacego serie) staje sie nieczytelne; panele
stackowane zachowuja czytelnosc KAZDEJ wielkosci osobno, a wspolna os X wciaz pozwala
odczytac wprost, ze wzrost temperatury (panel 1) pokrywa sie w czasie ze spadkiem taktu
(panel 2) i ze wzrostem zajetosci pamieci (panel 3).

Uzywa fundamentu rysunek_techniczny.py (skill wykresy-techniczne): czern na bieli,
FL Pismo Techniczne, przecinek dziesietny, anty-tofu. Kazdy test w tym repo startuje
z potwierdzonego stanu spoczynkowego (temp <= 67 stC, takt 408 MHz, obciazenie < 0,5)
-- temperatura startowa kazdego wykresu jest wiec porownywalna miedzy wariantami.

Uruchomienie:
    python gen_temp_wykresy.py <katalog_z_danymi> <katalog_wyjsciowy>
"""
import json
import sys
from pathlib import Path

FUNDAMENT_SCIEZKA = r"C:\Users\karol\Documents\Jarwis\Jarwis\.claude\skills\wykresy-techniczne\scripts"
sys.path.insert(0, FUNDAMENT_SCIEZKA)
from rysunek_techniczny import plt, kategoria_obrazu, legenda, zapisz  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

# fundament szuka czcionki pod sciezka linuksowa -- na Windows jest zarejestrowana
# systemowo pod ta sama nazwa, wiec wystarczy nadpisac font.family jawnie
plt.rcParams['font.family'] = 'FL Pismo Techniczne'

PROG_THROTTLE_C = 85.0
TAKT_PELNY_KHZ = 1800000
TAKT_PELNY_MHZ = TAKT_PELNY_KHZ / 1000.0

WARIANTY = [
    ("cpu_fp32", "Sam procesor (CPU, fp32)"),
    ("hybrid", "Procesor + jednostka rownolegle (CPU int8 + NPU int8)"),
    ("npu_int8", "Sama jednostka (NPU, int8) - NIENADAJACA SIE DO UZYTKU, recall@3=0,06"),
    ("npu_fp16", "Sama jednostka (NPU, fp16) - jedyny wariant jednostki o zachowanej jakosci"),
]


def przecinek(wartosc, miejsca=1):
    return ("%.*f" % (miejsca, wartosc)).replace(".", ",")


def fmt(miejsca=0):
    return FuncFormatter(lambda v, pos: przecinek(v, miejsca))


def wczytaj_szereg(katalog: Path, klucz: str):
    p = katalog / f"temp_szereg_{klucz}.json"
    if not p.exists():
        return None
    dane = json.loads(p.read_text(encoding="utf-8"))
    probki = dane["probki"]
    return {
        "temp_startowa_c": dane.get("temp_startowa_c"),
        "start_pomiaru_s": dane.get("start_pomiaru_s", 0.0),
        "koniec_pomiaru_s": dane.get("koniec_pomiaru_s"),
        "t": [pr["elapsed_s"] for pr in probki],
        "temp": [pr["temp_c"] for pr in probki],
        "freq_mhz": [pr["freq_khz"] / 1000.0 for pr in probki],
        "mem_mb": [pr.get("mem_used_mb") for pr in probki],
    }


def throttle_markery(t, freq_mhz):
    """Pierwsza probka kazdej ciaglej serii ponizej pelnego taktu -- moment,
    w ktorym uklad zaczyna sie bronic (Karol)."""
    tx, fx = [], []
    byl = False
    for ti, fi in zip(t, freq_mhz):
        ponizej = fi < TAKT_PELNY_MHZ
        if ponizej and not byl:
            tx.append(ti); fx.append(fi)
        byl = ponizej
    return tx, fx


def rysuj_wariant(katalog: Path, katalog_wy: Path, klucz: str, tytul: str):
    dane = wczytaj_szereg(katalog, klucz)
    if dane is None:
        print(f"POMINIETO ({klucz}): brak pliku temp_szereg_{klucz}.json")
        return
    if not dane["t"] or dane["mem_mb"][0] is None:
        print(f"POMINIETO ({klucz}): szereg bez danych pamieci (uruchom bench_safe.py "
              f"po dopisaniu mem_used_mb do SamplerTemperatury)")
        return

    t = dane["t"]
    koniec = dane["koniec_pomiaru_s"] if dane["koniec_pomiaru_s"] is not None else t[-1]

    kategoria_obrazu('rysunek')
    fig, (ax_t, ax_f, ax_m) = plt.subplots(
        3, 1, figsize=(9, 9.5), sharex=True,
        gridspec_kw={'hspace': 0.12})

    # --- panel 1: temperatura ---
    ax_t.plot(t, dane["temp"], color='black', lw=1.6,
              marker='o', mfc='white', mec='black', ms=3, mew=0.8)
    ax_t.axhline(PROG_THROTTLE_C, color='black', lw=1.0, linestyle='--')
    ax_t.text(t[-1] * 0.99, PROG_THROTTLE_C + 0.5,
              f'prog throttlingu {przecinek(PROG_THROTTLE_C, 0)} $^\\circ$C',
              ha='right', va='bottom', fontsize=8.5,
              bbox=dict(facecolor='white', edgecolor='none', pad=1))
    ax_t.set_ylabel('temperatura\n[$^\\circ$C]')
    ax_t.yaxis.set_major_formatter(fmt(0))
    ax_t.grid(True, linewidth=0.4, color='0.75')
    ax_t.set_axisbelow(True)

    # --- panel 2: takt rdzeni ---
    tx, fx = throttle_markery(t, dane["freq_mhz"])
    ax_f.plot(t, dane["freq_mhz"], color='black', lw=1.6,
              marker='s', mfc='white', mec='black', ms=3, mew=0.8)
    if tx:
        ax_f.scatter(tx, fx, marker='v', s=70, facecolor='black', edgecolor='black',
                     zorder=5, label='poczatek ograniczania taktu')
        legenda(ax_f, fontsize=8.5)
    ax_f.set_ylabel('takt rdzeni\n[MHz]')
    ax_f.yaxis.set_major_formatter(fmt(0))
    ax_f.grid(True, linewidth=0.4, color='0.75')
    ax_f.set_axisbelow(True)

    # --- panel 3: zajetosc RAM ---
    ax_m.plot(t, dane["mem_mb"], color='black', lw=1.6,
              marker='^', mfc='white', mec='black', ms=3, mew=0.8)
    ax_m.set_ylabel('zajeta pamiec\n[MB]')
    ax_m.set_xlabel('czas od startu pomiaru [s]')
    rozpietosc_mb = max(dane["mem_mb"]) - min(dane["mem_mb"])
    ax_m.yaxis.set_major_formatter(fmt(1 if rozpietosc_mb < 5 else 0))
    ax_m.xaxis.set_major_formatter(fmt(0))
    ax_m.grid(True, linewidth=0.4, color='0.75')
    ax_m.set_axisbelow(True)

    # start/koniec wlasciwego pomiaru -- na wszystkich trzech panelach, zeby
    # odroznic fazę obliczen od ewentualnego stygniecia po jej zakonczeniu
    for ax in (ax_t, ax_f, ax_m):
        ax.axvline(0.0, color='black', lw=0.8, linestyle=':')
        ax.axvline(koniec, color='black', lw=0.8, linestyle=':')
    ax_t.text(0.0, ax_t.get_ylim()[1], ' start pomiaru', fontsize=7.5,
              ha='left', va='top', rotation=90,
              bbox=dict(facecolor='white', edgecolor='none', pad=0.5))
    ax_t.text(koniec, ax_t.get_ylim()[1], ' koniec pomiaru ', fontsize=7.5,
              ha='right', va='top', rotation=90,
              bbox=dict(facecolor='white', edgecolor='none', pad=0.5))

    temp_startowa = dane["temp_startowa_c"]
    ax_t.text(0.02, 0.04,
              f'temperatura startowa: {przecinek(temp_startowa, 1)} $^\\circ$C (stan spoczynkowy)',
              transform=ax_t.transAxes, fontsize=8.5, ha='left', va='bottom',
              bbox=dict(facecolor='white', edgecolor='black', linewidth=0.6, pad=3))

    fig.suptitle(tytul, fontsize=12, fontweight='bold', y=0.995)

    out = katalog_wy / f"temp_wykres_{klucz}.png"
    zapisz(fig, str(out))


if __name__ == "__main__":
    katalog = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    katalog_wy = Path(sys.argv[2]) if len(sys.argv) > 2 else katalog
    katalog_wy.mkdir(parents=True, exist_ok=True)
    for klucz, tytul in WARIANTY:
        rysuj_wariant(katalog, katalog_wy, klucz, tytul)
