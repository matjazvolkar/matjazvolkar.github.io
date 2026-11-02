"""Posnetek aktivnih kampanj za razdelek 0 strani GTM kapacitete 2026/2027 (GitHub Actions, samo branje).

Koraki (vsak je svoj korak workflowa, da stran kaze napredek v odstotkih):
  instantly  kampanje, ki niso koncane, s sestevki leadov in posiljatelji (ime osebe iz nabiralnika)
  heyreach   isto za LinkedIn (leadi, ki cakajo ali so v teku, in sedezi)
  zdruzi     para obeh kanalov po segmentu, trgu in tipu ter zapis aktivne-kampanje.json

Izjema od pravila prehodov SDR (lib/<vendor>.py): ta repo je javen in nima dostopa do zasebnih
prehodov, zato je tu najmanjsi odjemalec samo za branje (2. 11. 2026). V izhod gredo samo sestevki,
trgi, tipi, statusi in imena posiljateljev; nobenega naslova, leada, ID-ja ali kljuca.
Kljuca prideta iz skrivnosti repozitorija (INSTANTLY_API_KEY, HEYREACH_MCP_URL) in se nikjer ne izpiseta.
"""
import datetime as dt
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

KOREN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IZHOD = os.environ.get("IZHOD") or os.path.join(KOREN, "GTM-kapacitete-2026-2027", "aktivne-kampanje.json")
TMP = os.environ.get("RUNNER_TEMP") or "/tmp"
I_DAT, H_DAT = os.path.join(TMP, "kampanje_instantly.json"), os.path.join(TMP, "kampanje_heyreach.json")

# Instantly: 0 osnutek, 1 aktivna, 2 pavza, 3 koncana, 4 podsekvence, -1 racuni z napako, -2 zascita pred odboji, -99 ustavljena
STATUS_I = {0: "osnutek", 1: "tece", 2: "pavza", 4: "tece", -1: "tece", -2: "tece"}
STATUS_H = {"IN_PROGRESS": "tece", "SCHEDULED": "nacrtovana", "DRAFT": "osnutek", "PAUSED": "pavza"}
TRGI = {"slovenia": "Slovenija", "croatia": "Hrvaška", "uae": "UAE", "florida": "Florida", "usa": "ZDA",
        "new york": "New York", "italy": "Italija", "greece": "Grčija", "austria": "Avstrija",
        "netherlands": "Nizozemska", "nordic": "Severna Evropa", "europe-turkey": "Evropa in Turčija"}
IZPUSTI = re.compile(r"za brisanje|\btest\b", re.I)


def zahteva(url, metoda="GET", telo=None, glave=None, odpiralec=None, poskusi=7):
    """HTTP z odmikom pri 429 in 5xx. Napaka nikoli ne izpise poizvedbe (HeyReach ima kljuc v URL-ju)."""
    kje = urllib.parse.urlsplit(url).netloc
    for i in range(poskusi):
        # privzeti User-Agent knjiznice urllib Instantly (Cloudflare) zavrne s 403
        req = urllib.request.Request(url, method=metoda, headers={"User-Agent": "nevron-gtm-kapacitete/1.0", **(glave or {})},
                                     data=None if telo is None else json.dumps(telo).encode("utf-8"))
        try:
            with (odpiralec or urllib.request.build_opener()).open(req, timeout=60) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if (e.code == 429 or e.code >= 500) and i < poskusi - 1:
                time.sleep(min(60, 3 * 2 ** i))
                continue
            raise SystemExit(f"HTTP {e.code} pri {kje}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            if i < poskusi - 1:
                time.sleep(min(60, 3 * 2 ** i))
                continue
            raise SystemExit(f"omrezna napaka pri {kje}: {type(e).__name__}") from None
    raise SystemExit(f"prevec poskusov pri {kje}")


def korak_instantly():
    kljuc = os.environ.get("INSTANTLY_API_KEY", "").strip()
    if not kljuc:
        raise SystemExit("manjka skrivnost INSTANTLY_API_KEY")
    G = {"Authorization": f"Bearer {kljuc}"}

    def vse(pot, p=None):
        out, kurzor = [], None
        while True:
            q = dict(p or {}, limit=100)
            if kurzor:
                q["starting_after"] = kurzor
            d = json.loads(zahteva(f"https://api.instantly.ai/api/v2{pot}?{urllib.parse.urlencode(q)}", glave=G))
            out += d.get("items", [])
            kurzor = d.get("next_starting_after")
            if not kurzor or not d.get("items"):
                return out

    racuni = {(a.get("email") or "").lower(): (a.get("first_name") or "").strip() for a in vse("/accounts")}
    kamp = [c for c in vse("/campaigns") if c.get("status") in STATUS_I]
    an = {}
    for i in range(0, len(kamp), 25):
        ids = [c["id"] for c in kamp[i:i + 25]]
        d = json.loads(zahteva("https://api.instantly.ai/api/v2/campaigns/analytics?" + urllib.parse.urlencode({"ids": ids}, doseq=True), glave=G))
        for r in (d if isinstance(d, list) else d.get("items", [])):
            an[r.get("campaign_id")] = r
    out = []
    for c in kamp:
        a, status = an.get(c["id"], {}), STATUS_I[c["status"]]
        leadov, koncanih = int(a.get("leads_count") or 0), int(a.get("completed_count") or 0)
        out.append({"ime": c.get("name") or "", "status": status, "leadov": leadov,
                    # osnutek: vsi leadi so se pred nami; sicer leadi, ki sekvence se niso koncali
                    "preostalo": leadov if status == "osnutek" else max(0, leadov - koncanih),
                    "posiljatelji": sorted({racuni.get(e.lower()) or "?" for e in (c.get("email_list") or [])})})
    json.dump(out, open(I_DAT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"Instantly: {len(out)} nekoncanih kampanj, " + ", ".join(f"{s} {sum(1 for x in out if x['status'] == s)}" for s in sorted({x['status'] for x in out})))


def korak_heyreach():
    url = os.environ.get("HEYREACH_MCP_URL", "").strip()
    if not url:
        raise SystemExit("manjka skrivnost HEYREACH_MCP_URL")
    od = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))  # AWSALB afiniteta
    G = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    zahteva(url, "POST", {"jsonrpc": "2.0", "method": "initialize", "id": 1,
                          "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "gtm-kapacitete", "version": "1.0"}}}, G, od)
    zahteva(url, "POST", {"jsonrpc": "2.0", "method": "notifications/initialized"}, G, od)
    st = [1]

    def orodje(ime, args):
        for poskus in range(6):
            st[0] += 1
            txt = zahteva(url, "POST", {"jsonrpc": "2.0", "method": "tools/call", "id": st[0], "params": {"name": ime, "arguments": args}}, G, od)
            env = next((json.loads(v[6:]) for v in txt.split("\n") if v.startswith("data: ")), None) or json.loads(txt)
            res = env.get("result") or {}
            besedilo = "".join(c.get("text", "") for c in res.get("content") or [] if isinstance(c, dict))
            if res.get("isError") or "error" in env:
                if re.search(r"429|toomanyrequests|rate limit|status code 50\d", besedilo, re.I) and poskus < 5:
                    time.sleep(3 * 2 ** poskus)
                    continue
                raise SystemExit(f"HeyReach {ime}: napaka orodja")
            return json.loads(besedilo) if besedilo else {}
        raise SystemExit(f"HeyReach {ime}: prevec poskusov")

    def vse(ime):
        out, odmik = [], 0
        while True:
            d = orodje(ime, {"offset": odmik, "limit": 100})
            stran = d.get("items", [])
            out += stran
            if len(stran) < 100:
                return out
            odmik += 100

    sedezi = {a.get("id"): (a.get("firstName") or "").strip() for a in vse("get_all_linked_in_accounts")}
    out = []
    for c in vse("get_all_campaigns"):
        if c.get("status") not in STATUS_H:
            continue
        p = c.get("progressStats") or {}
        out.append({"ime": c.get("name") or "", "status": STATUS_H[c["status"]], "leadov": int(p.get("totalUsers") or 0),
                    "preostalo": int(p.get("totalUsersPending") or 0) + int(p.get("totalUsersInProgress") or 0),
                    "posiljatelji": sorted({sedezi.get(i) or "?" for i in (c.get("campaignAccountIds") or [])})})
    json.dump(out, open(H_DAT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"HeyReach: {len(out)} nekoncanih kampanj, " + ", ".join(f"{s} {sum(1 for x in out if x['status'] == s)}" for s in sorted({x['status'] for x in out})))


def razcleni(ime):
    """'NevronCore | UAE | General Scrape' -> (hoteli, UAE, General Scrape); 'IPTV | Nordic | ...' -> ladje."""
    if IZPUSTI.search(ime):
        return None
    deli = [d.strip() for d in ime.split("|") if d.strip()]
    seg = "hoteli"
    if deli and deli[0].lower() == "iptv":
        seg, deli = "ladje", deli[1:]
    elif deli and deli[0].lower() == "nevroncore":
        deli = deli[1:]
    if not deli:
        return None
    return seg, TRGI.get(deli[0].lower(), deli[0]), " | ".join(deli[1:]) or "kampanja"


def korak_zdruzi():
    vrstice = {}
    for kanal, pot in (("email", I_DAT), ("li", H_DAT)):
        for c in json.load(open(pot, encoding="utf-8")):
            r = razcleni(c["ime"])
            if not r:
                continue
            seg, trg, tip = r
            v = vrstice.setdefault((seg, trg.lower(), tip.lower()), {"seg": seg, "trg": trg, "tip": tip, "email": None, "li": None})
            prej = v[kanal]
            nov = {k: c[k] for k in ("status", "leadov", "preostalo", "posiljatelji")}
            if prej:  # dve kampanji istega imena na istem kanalu: sestej
                nov = {"status": prej["status"] if prej["status"] == "tece" else nov["status"], "leadov": prej["leadov"] + nov["leadov"],
                       "preostalo": prej["preostalo"] + nov["preostalo"], "posiljatelji": sorted(set(prej["posiljatelji"]) | set(nov["posiljatelji"]))}
            v[kanal] = nov
    zeton = os.environ.get("ZETON", "")
    zeton = zeton if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", zeton) else "rocno"
    out = {"kdaj": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(), "zeton": zeton,
           "opomba": "Vse kampanje, ki niso koncane (tece, nacrtovana, osnutek, pavza), brez imen z 'ZA BRISANJE' ali 'TEST'. "
                     "Email preostalo: osnutek vsi leadi, sicer leadi brez koncane sekvence (Instantly analytics). "
                     "LinkedIn preostalo: leadi, ki cakajo ali so v teku (HeyReach progressStats).",
           "vrstice": sorted(vrstice.values(), key=lambda v: (v["seg"], v["trg"], v["tip"]))}
    os.makedirs(os.path.dirname(IZHOD), exist_ok=True)
    with open(IZHOD, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"zapisano: {len(out['vrstice'])} vrstic (segment, trg, tip)")
    for v in out["vrstice"]:
        print(" ", v["seg"], v["trg"], "|", v["tip"], "| email", v["email"] and (v["email"]["status"], v["email"]["preostalo"]), "| li", v["li"] and (v["li"]["status"], v["li"]["preostalo"]))


if __name__ == "__main__":
    {"instantly": korak_instantly, "heyreach": korak_heyreach, "zdruzi": korak_zdruzi}[sys.argv[1]]()
