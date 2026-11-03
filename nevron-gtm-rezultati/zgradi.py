"""Zgradi stran Nevron GTM rezultati (index.html) iz podatki.json in vrednosti.json.

Samo standardna knjiznica: tece na PC-ju in na Hetznerju (/opt/nevron-gtm-rezultati/run.sh, vsako noc).
  podatki.json    zgradba: naslov, sezona, opomba, kanali, KPI-ji (ureja clovek)
  vrednosti.json  stevilke, obdobje in cas osvezitve (pise nocni proces SDR/scripts/pipelines/gtm_rezultati.py)

  python zgradi.py
  python zgradi.py --test 88888 --izhod C:/pot/test.html   # vse celice z isto vrednostjo (prileganje)

Vrednost, ki je ni, se izpise kot "00". Preverba prileganja: Projects/nevron-gtm-rezultati/shot.py.
"""
import argparse
import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

TU = Path(__file__).resolve().parent
PRAZNO = "00"

# Nevron logo brez slogana, bel (nevron-brand-agent/assets/logos/nevron-logo-no-tagline-white.svg, samo poti).
LOGO_SVG = '<svg viewBox="0 0 960 276.9" role="img" aria-label="Nevron" fill="#FFFFFF"><path d="M244.3,93.9h30.5V2.1H183v30.5h61.3V93.9z M30.5,185.1H0v91.8h91.8v-30.5H30.5V185.1z M274.8,185.1h-30.5V233 L30.5,2.1H0v91.8h30.5V45.7l213.7,231.1h30.5L274.8,185.1z"/><path d="M467.4,0c-15.3,0-25.3,7.5-29.8,16.7V2.1h-25.4v91.8h25.4v-53c0-13.5,8.2-20.2,19.1-20.2 c11.2,0,16.1,6,16.1,18.4v54.7h25.4V35.4C498.3,10.9,485.5,0,467.4,0z M557.3,0c-26.7,0-47.2,18.8-47.2,47.7v1.4 c0,29.3,20.2,46.7,47.9,46.7c25.1,0,40.9-11.1,43.9-30.9h-24c-1.6,7.7-7.4,12.8-19.1,12.8c-13.9,0-22.1-8.8-22.8-24h66.2v-7 C602.1,13.9,581,0,557.3,0z M536.3,38.1c1.9-13,9.7-20.5,21.1-20.5c12.1,0,19.1,6.7,20,20.5H536.3z M813.3,0 c-27.5,0-48.4,18.8-48.4,47.6V49c0,28.6,20.9,46.8,48.3,46.8c27.5,0,48.4-18.4,48.4-47.4V47C861.5,18.4,840.8,0,813.3,0z M835.7,48.6c0,17.4-8.2,27.9-22.5,27.9c-14.4,0-22.5-10.5-22.5-28.1V47c0-17.5,8.4-27.7,22.5-27.7c14.2,0,22.5,10.5,22.5,28.1 V48.6z M929.1,0c-15.3,0-25.3,7.5-29.8,16.7V2.1h-25.4v91.8h25.4v-53c0-13.5,8.2-20.2,19.1-20.2c11.2,0,16.1,6,16.1,18.4v54.7H960 V35.4C960,10.9,947.2,0,929.1,0z M730.6,19.7V2.1h-25.4v91.8h25.4v-46c0-17.5,10.9-23.7,29.7-23.5V0.7 C745.4,0.9,736.4,7.4,730.6,19.7z M650.9,67.7L629,2.1h-27.2l33.5,91.8h28.6l33.3-91.8h-24.6L650.9,67.7z"/></svg>'


def stevilka(v) -> tuple[str, bool]:
    """Slovenski zapis tisočic (3.900). Vrne (besedilo, je_prazno)."""
    if v is None:
        return PRAZNO, True
    if isinstance(v, float) and not v.is_integer():
        return f"{v:,.1f}".replace(",", " ").replace(".", ",").replace(" ", "."), False
    return f"{int(v):,}".replace(",", "."), False


def _lokalno(t: datetime) -> datetime:
    """UTC -> Ljubljana (CET/CEST) brez tzdata: poletni cas od zadnje nedelje marca do zadnje nedelje oktobra, 01:00 UTC."""
    if t.tzinfo is None:
        return t
    t = t.astimezone(timezone.utc)

    def zadnja_nedelja(mesec):
        d = datetime(t.year, mesec, 31, 1, tzinfo=timezone.utc)
        return d - timedelta(days=(d.weekday() + 1) % 7)

    poletni = zadnja_nedelja(3) <= t < zadnja_nedelja(10)
    return (t + timedelta(hours=2 if poletni else 1)).replace(tzinfo=None)


def _datum(t: datetime) -> str:
    return f"{t.day}. {t.month}. {t.year}"


def obdobje_besedilo(od, osv) -> str:
    """Od prve pomladne kampanje do dneva nocnega teka (zastal proces = star datum na TV)."""
    if not od:
        return "Številke še niso povezane z viri"
    do = _lokalno(datetime.fromisoformat(osv)) if osv else datetime.now()
    return f"Od {_datum(datetime.fromisoformat(od))} do {_datum(do)}"


def zgradi(pod: dict, vred: dict, test=None) -> str:
    """Tabela v skupinah: vsaka skupina ima svojo naslovno vrstico KPI-jev (klici: Called ...; ostali: Opens ...)."""
    e = html.escape
    stevilke = (vred or {}).get("vrednosti") or {}
    skupine = pod["skupine"]
    stolpcev = len(skupine[0]["kpiji"])
    if any(len(s["kpiji"]) != stolpcev for s in skupine):
        raise SystemExit("vse skupine morajo imeti enako stevilo KPI stolpcev")
    vrste, visine = [], []
    for i, skupina in enumerate(skupine):
        kpiji = skupina["kpiji"]
        nova = " nova" if i else ""
        vrste.append('    <div class="row" role="row">')
        vrste.append(f'      <div class="head blank{nova}" aria-hidden="true"></div>')
        for k in kpiji:
            vrste.append(f'      <div class="head col{nova}" role="columnheader">{e(k["ime"])}</div>')
        vrste.append("    </div>")
        visine.append("auto")
        for kanal in skupina["kanali"]:
            vrste.append('    <div class="row" role="row">')
            vrste.append(f'      <div class="label" role="rowheader">{e(kanal["ime"])}</div>')
            for k in kpiji:
                v = test if test is not None else (stevilke.get(kanal["id"]) or {}).get(k["id"])
                besedilo, prazno = stevilka(v)
                razred = "figure prazno" if prazno else "figure"
                vrste.append(
                    f'      <div class="cell" role="cell"><span class="{razred}" data-kanal="{e(kanal["id"])}" '
                    f'data-kpi="{e(k["id"])}">{besedilo}</span></div>'
                )
            vrste.append("    </div>")
            visine.append("minmax(0, 1fr)")
    stran = PREDLOGA
    zamenjave = {
        "@@NASLOV@@": e(pod["naslov"]),
        "@@SEZONA@@": e(pod["sezona"]),
        "@@OSVEZENO@@": e(obdobje_besedilo((vred or {}).get("od"), (vred or {}).get("osvezeno"))),
        "@@OPOMBA@@": e(pod.get("opomba") or ""),
        "@@LOGO@@": LOGO_SVG,
        "@@STOLPCEV@@": str(stolpcev),
        "@@VRSTICE@@": " ".join(visine),
        "@@TABELA@@": "\n".join(vrste),
    }
    for k, v in zamenjave.items():
        stran = stran.replace(k, v)
    return stran


PREDLOGA = """<!doctype html>
<html lang="sl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta http-equiv="refresh" content="900">
<title>@@NASLOV@@</title>
<meta name="description" content="GTM rezultati po kanalih: opens, reads, clicks, demos booked, AE follow-up in wins od prve pomladne kampanje 2026.">
<meta name="color-scheme" content="dark">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 2000 2000'><rect width='2000' height='2000' rx='340' fill='%23000126'/><path fill='%231B92FF' d='M1681.3,693.4h197.8V98.8h-594.7v197.8h396.9V693.4z M296.7,1284.3H98.9V1879h594.7v-197.8H296.7V1284.3z'/><path fill='%231B92FF' d='M1879.1,1284.3h-197.8v310.2L296.7,98.8H98.9v594.7h197.8V381.6L1681.3,1879h197.8L1879.1,1284.3z'/></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">
<style>
  /* Nevron brand: M1 navy temna tema, barve iz nevron-tokens.css (kot hospitality-abundance-linkedin) */
  :root {
    --navy: #000126;
    --near-black: #080C13;
    --panel: rgba(255, 255, 255, 0.04);
    --rule: rgba(115, 199, 255, 0.22);
    --rule-strong: rgba(115, 199, 255, 0.45);
    --text: #FFFFFF;
    --text-dim: #B4B6B9;
    --text-soft: #E0E1E2;
    --blue: #1B92FF;
    --blue-mid: #73C7FF;
    color-scheme: dark;
    /* ena enota za vse mere: 1 % visine 16:9 zaslona, zato se vse prilega v okno (HD TV, prenosnik) */
    --u: min(1vh, 0.5625vw);
  }
  * { box-sizing: border-box; }
  html { background: var(--navy); }
  body {
    margin: 0;
    background: linear-gradient(180deg, var(--navy) 0%, #000A33 45%, var(--near-black) 100%);
    background-attachment: fixed;
    color: var(--text);
    font-family: "Neue Haas Unica", "Inter", "Helvetica Neue", Arial, sans-serif;
    line-height: 1.3;
    -webkit-font-smoothing: antialiased;
  }
  .page {
    height: 100vh; height: 100svh;
    display: grid;
    grid-template-rows: auto minmax(0, 1fr) auto;
    gap: calc(var(--u) * 2.6);
    padding: calc(var(--u) * 3.2) calc(var(--u) * 4.6);
    max-width: calc(var(--u) * 177.8);
    margin: 0 auto;
  }

  .brand { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: calc(var(--u) * 3.6); }
  .logo { width: calc(var(--u) * 15); }
  .logo svg { width: 100%; height: auto; display: block; }
  h1 { margin: 0; font-size: calc(var(--u) * 4.2); line-height: 1.1; font-weight: 700; letter-spacing: -0.015em; }
  .stamp { text-align: right; font-size: calc(var(--u) * 1.5); font-weight: 600; letter-spacing: 0.16em; text-transform: uppercase; color: var(--blue-mid); }
  .stamp span { display: block; margin-top: calc(var(--u) * 0.5); font-size: calc(var(--u) * 1.6); font-weight: 500; letter-spacing: 0.02em; text-transform: none; color: var(--text-dim); }

  .scroll { min-height: 0; display: grid; }
  .board {
    display: grid;
    grid-template-columns: minmax(0, 1.9fr) repeat(@@STOLPCEV@@, minmax(0, 1fr));
    grid-template-rows: @@VRSTICE@@;
    column-gap: 0;
    min-height: 0;
    border-top: 1px solid var(--rule-strong);
    background: var(--panel);
    padding-inline: calc(var(--u) * 2.8);
    border-radius: 0 0 4px 4px;
  }
  .row { display: contents; }
  .row > div { border-bottom: 1px solid var(--rule); min-width: 0; display: flex; align-items: center; }
  .row:last-child > div { border-bottom: 0; }
  .head { padding-block: calc(var(--u) * 1.7); border-bottom-color: var(--rule-strong) !important; }
  /* naslovna vrstica druge skupine: zrak nad njo, da se skupini locita */
  .head.nova { padding-top: calc(var(--u) * 3); }
  .head.col {
    justify-content: flex-end; text-align: right;
    font-size: calc(var(--u) * 1.55); font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: var(--text-dim);
    white-space: nowrap;
  }
  /* imena kanalov: ista velikost, brand Body utez 400 in S5 siva, da v ospredju ostanejo stevilke */
  .label { font-size: calc(var(--u) * 2.5); font-weight: 400; line-height: 1.2; color: var(--text-soft); padding-block: calc(var(--u) * 0.6); }
  /* razmik med stolpci je v celicah, da so crte vrstic neprekinjene */
  .head.col, .cell { padding-left: calc(var(--u) * 2.6); }
  .cell { justify-content: flex-end; }
  .figure {
    font-weight: 700; font-variant-numeric: tabular-nums lining-nums;
    font-size: calc(var(--u) * 4.9); line-height: 1; letter-spacing: -0.015em;
    color: var(--text); white-space: nowrap;
  }
  .opomba { margin: calc(var(--u) * -0.8) 0 0; font-size: calc(var(--u) * 1.45); line-height: 1.4; color: var(--text-dim); }

  /* telefon in ozko okno: brez prileganja v en zaslon, tabela se drsi vodoravno */
  @media (max-width: 760px), (max-aspect-ratio: 1/1) {
    :root { --u: 7px; }
    .page { height: auto; min-height: 100svh; padding: 20px 16px; gap: 18px; }
    .brand { grid-template-columns: auto 1fr; gap: 12px 16px; }
    .stamp { grid-column: 1 / -1; text-align: left; }
    .opomba { margin: 0; font-size: 0.8125rem; }
    h1 { font-size: 1.375rem; }
    .scroll { overflow-x: auto; margin-inline: -16px; padding-inline: 16px; }
    .board { min-width: 1000px; grid-template-rows: none; }
    .row > div { padding-block: 12px; }
    .label { font-size: 0.9375rem; }
    .head.col { font-size: 0.6875rem; }
    .figure { font-size: 1.75rem; }
  }
</style>
</head>
<body>
<div class="page">
  <header class="brand">
    <div class="logo">@@LOGO@@</div>
    <h1>@@NASLOV@@</h1>
    <div class="stamp">@@SEZONA@@<span>@@OSVEZENO@@</span></div>
  </header>

  <div class="scroll">
  <section class="board" role="table" aria-label="Rezultati po kanalih">
@@TABELA@@
  </section>
  </div>
  <p class="opomba">@@OPOMBA@@</p>
</div>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--podatki", default=str(TU / "podatki.json"))
    ap.add_argument("--vrednosti", default=str(TU / "vrednosti.json"))
    ap.add_argument("--izhod", default=str(TU / "index.html"))
    ap.add_argument("--test", type=float, default=None, help="vse celice s to vrednostjo")
    a = ap.parse_args()
    pod = json.loads(Path(a.podatki).read_text(encoding="utf-8"))
    vp = Path(a.vrednosti)
    vred = json.loads(vp.read_text(encoding="utf-8")) if vp.exists() else {}
    test = None if a.test is None else (int(a.test) if a.test.is_integer() else a.test)
    Path(a.izhod).write_text(zgradi(pod, vred, test), encoding="utf-8", newline="\n")
    print("zapisano:", a.izhod)


if __name__ == "__main__":
    main()
