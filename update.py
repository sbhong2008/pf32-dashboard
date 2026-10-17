#!/usr/bin/env python3
"""PF32 데이터 업데이터 — 환율(BRL/KRW)·브라질 국채 CSV를 내려받아 data/data.json 생성.
표준 라이브러리만 사용. 매일 실행해도 안전(ETag/Range 이어받기, 변경 없으면 건너뜀)."""
import csv, glob, json, os, shutil, sys, time, urllib.request, urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

TT_URL = ("https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/"
          "resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv")
FX_URL = "https://api.frankfurter.dev/v1/{start}..?base=BRL&symbols=KRW,USD"
FOCUS_URL = ("https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais"
             "?$top=4000&$filter=Indicador%20eq%20'IPCA'%20and%20baseCalculo%20eq%200%20and%20Data%20ge%20'{start}'"
             "&$orderby=Data%20desc&$format=json&$select=Data,DataReferencia,Mediana")
FX_USD = []  # (date, BRL→USD) — update_fx 가 채움
UA = {"User-Agent": "Mozilla/5.0 pf32-app"}


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def num(s):
    """'R$ 1.234,56' / '12,98%' / '12,98' -> float"""
    s = s.replace("R$", "").replace("%", "").replace("\xa0", "").strip()
    return float(s.replace(".", "").replace(",", ".")) if "," in s else float(s)


def dmy(s):
    return datetime.strptime(s, "%d/%m/%Y").date()


# ---------------------------------------------------------------- FX
def update_fx():
    start = (date.today() - timedelta(days=365 * 10)).isoformat()
    req = urllib.request.Request(FX_URL.format(start=start), headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        j = json.load(r)
    rows = sorted((d, v["KRW"]) for d, v in j["rates"].items())
    FX_USD[:] = sorted((d, v["USD"]) for d, v in j["rates"].items() if "USD" in v)
    with open(DATA / "fx_brlkrw.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "brl_krw"]); w.writerows(rows)
    log(f"FX 저장: {len(rows)}행, 최신 {rows[-1]}")
    return rows


def update_infl():
    """브라질 시장 IPCA 기대치(BCB Focus, 연도별 중앙값). 한국·미국 물가는 키 없이 받을 수 있는 소스가 없어 설정값 사용."""
    start = (date.today() - timedelta(days=400)).isoformat()
    req = urllib.request.Request(FOCUS_URL.format(start=start), headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        v = json.load(r)["value"]
    if not v: raise ValueError("Focus 응답 비어 있음")
    history = {}
    for x in v: history.setdefault(x["Data"], {})[x["DataReferencia"]] = x["Mediana"]
    d0 = max(history)
    by_year = history[d0]
    log(f"IPCA 기대(Focus {d0}):", by_year, f"· 이력 {len(history)}일")
    # history: 날짜별 연도별 중앙값 → 화면이 과거 시점마다 그날의 물가 기대로 실질수익률 곡선을 그림
    return {"asof": d0, "by_year": by_year, "history": dict(sorted(history.items())), "source": "BCB Focus 연도별 중앙값"}


# ---------------------------------------------------------------- Treasury (Tesouro Transparente)
def download_treasury(max_seconds=1500):
    """느린 서버 대응: ETag 확인 → .part 이어받기. 완료되면 PrecoTaxaTesouroDireto.csv 로 확정."""
    final, part, etag_f = CACHE / "PrecoTaxaTesouroDireto.csv", CACHE / "PrecoTaxaTesouroDireto.csv.part", CACHE / "etag.txt"
    head = urllib.request.Request(TT_URL, headers=UA, method="HEAD")
    with urllib.request.urlopen(head, timeout=60) as r:
        etag, total = r.headers.get("ETag", ""), int(r.headers.get("Content-Length", 0))
    old = etag_f.read_text() if etag_f.exists() else ""
    if final.exists() and old == etag:
        log("국채 CSV 변경 없음(ETag 동일) — 캐시 사용"); return final
    if old != etag and part.exists() and not (final.exists() is False and old == ""):
        part.unlink()  # 서버 파일이 바뀌었으면 처음부터
    t0 = time.time()
    while True:
        have = part.stat().st_size if part.exists() else 0
        if total and have >= total: break
        if time.time() - t0 > max_seconds:
            log(f"시간 초과 — {have}/{total} 바이트, 다음 실행에서 이어받기"); return final if final.exists() else None
        req = urllib.request.Request(TT_URL, headers={**UA, "Range": f"bytes={have}-"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(part, "ab" if r.status == 206 else "wb") as f:
                while chunk := r.read(65536):
                    f.write(chunk)
        except urllib.error.HTTPError as e:
            if e.code == 416: break  # 이미 전부 받음 (Content-Length 없는 서버 대응)
            log("재시도:", e); time.sleep(3)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            log("재시도:", e); time.sleep(3)
    shutil.move(part, final); etag_f.write_text(etag)
    log(f"국채 CSV 다운로드 완료 {final.stat().st_size/1e6:.1f}MB")
    return final


def read_treasury(path):
    """최근 history_days 일치만 {key: [(date, taxa_compra, pu_compra, taxa_venda, pu_venda)]}"""
    cutoff = date.today() - timedelta(days=CFG["history_days"])
    out = {}
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        rd = csv.reader(f, delimiter=";"); next(rd)
        for r in rd:
            try:
                d = dmy(r[2])
                if d < cutoff: continue
                out.setdefault(f"{r[0]}|{r[1]}", []).append((d.isoformat(), num(r[3]), num(r[5]), num(r[4]), num(r[6])))
            except (ValueError, IndexError):
                continue
    for v in out.values(): v.sort()
    return out


# ---------------------------------------------------------------- Investir CSV (사용자가 받은 라이브 스냅샷)
def newest_investir():
    files = glob.glob(os.path.expanduser(CFG["downloads_glob"])) + glob.glob(str(DATA / "inbox" / "*.csv"))
    return max(files, key=os.path.getmtime) if files else None


def read_investir(path):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            name = r["Título"].strip()
            tipo = name.rsplit(" ", 1)[0] if name.rsplit(" ", 1)[-1].isdigit() else name
            ry = r["Rendimento anual do título"].strip()
            rate = None if "SELIC" == ry else num(ry.split("+")[-1])
            rows.append({"name": name, "key": f"{tipo}|{r['Vencimento do Título'].strip()}", "yield_text": ry,
                         "rate": rate, "min_invest": num(r["Investimento mínimo"]),
                         "pu": num(r["Preço unitário de investimento"]), "venc": r["Vencimento do Título"].strip()})
    return rows


# ---------------------------------------------------------------- main
def main():
    DATA.mkdir(exist_ok=True); CACHE.mkdir(exist_ok=True); (DATA / "snapshots").mkdir(exist_ok=True)
    status = {}
    try: fx = update_fx(); status["fx"] = "ok"
    except Exception as e:
        log("FX 실패:", e); status["fx"] = f"error: {e}"
        p = DATA / "fx_brlkrw.csv"
        fx = [tuple(r) for r in list(csv.reader(open(p)))[1:]] if p.exists() else []
        fx = [(d, float(v)) for d, v in fx]

    prev = {}
    try: prev = json.loads((DATA / "data.json").read_text(encoding="utf-8"))
    except Exception: pass
    fx_usd = ({"latest": FX_USD[-1], "series": FX_USD[-400:]} if FX_USD else prev.get("fx_usd"))
    if status["fx"] == "ok" and not FX_USD: status["fx_usd"] = "empty"
    try: infl = {"br": update_infl()}; status["infl"] = "ok"
    except Exception as e:
        log("IPCA 기대 실패:", e); status["infl"] = f"error: {e}"; infl = prev.get("infl")

    hist = {}
    try:
        p = download_treasury()
        if p and p.exists(): hist = read_treasury(p); status["treasury_csv"] = "ok"
        else: status["treasury_csv"] = "partial"
    except Exception as e:
        log("국채 CSV 실패:", e); status["treasury_csv"] = f"error: {e}"
        p = CACHE / "PrecoTaxaTesouroDireto.csv"
        if p.exists(): hist = read_treasury(p)

    live, live_info = [], None
    ip = newest_investir()
    if ip:
        live = read_investir(ip)
        ts = datetime.fromtimestamp(os.path.getmtime(ip))
        live_info = {"file": os.path.basename(ip), "mtime": ts.isoformat(timespec="minutes")}
        shutil.copy(ip, DATA / "snapshots" / f"rendimento-investir_{ts:%Y-%m-%d_%H%M}.csv")
        log(f"Investir 스냅샷: {live_info['file']} ({live_info['mtime']})")

    def tk(c): return f"{c['tipo']}|{c['venc']}"
    watch = [CFG["tracked"]] + CFG["peers"]
    series = {c["label"]: hist.get(tk(c), []) for c in watch}
    latest_hist = {k: v[-1] for k, v in hist.items() if v}
    bonds = [{"key": k, "tipo": k.split("|")[0], "venc": k.split("|")[1], "date": v[0], "taxa_compra": v[1],
              "pu_compra": v[2], "taxa_venda": v[3], "pu_venda": v[4]}
             for k, v in latest_hist.items() if v[0] >= (date.today() - timedelta(days=10)).isoformat()]
    # 이어받기 완료 전에도 사용자의 최신 스냅샷은 바로 반영
    out = {"generated": datetime.now().isoformat(timespec="seconds"), "status": status,
           "live": live, "live_info": live_info, "bonds": sorted(bonds, key=lambda b: (b["tipo"], b["venc"][-4:])),
           "series": series,
           "fx": {"latest": fx[-1] if fx else None, "series": fx}, "fx_usd": fx_usd, "infl": infl}
    (DATA / "data.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    log("data.json 생성 완료", status)


if __name__ == "__main__":
    main()
