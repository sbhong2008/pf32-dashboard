#!/usr/bin/env python3
"""PF32 데이터 업데이터 — 환율(BRL/KRW)·브라질 국채 CSV를 내려받아 data/data.json 생성.
표준 라이브러리만 사용. 매일 실행해도 안전(ETag/Range 이어받기, 변경 없으면 건너뜀)."""
import csv, glob, json, os, shutil, subprocess, sys, time, urllib.request, urllib.error
from datetime import date, datetime, timedelta, timezone
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
    for i in range(4):  # 일시 오류 대비 재시도(5·15·45초 대기)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                j = json.load(r)
            break
        except Exception as e:
            if i == 3: raise
            log(f"FX 재시도 {i + 1}: {e}"); time.sleep(5 * 3 ** i)
    rows = sorted((d, v["KRW"]) for d, v in j["rates"].items())
    FX_USD[:] = sorted((d, v["USD"]) for d, v in j["rates"].items() if "USD" in v)
    with open(DATA / "fx_brlkrw.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "brl_krw"]); w.writerows(rows)
    log(f"FX 저장: {len(rows)}행, 최신 {rows[-1]}")
    return rows


# 집권 기간(진영별 환율 비교용). 데이터 시작이 2016-10이라 그 이후 기간만 사용
TERMS = [("브라질", "테메르(중도우파)", "2016-10-20", "2018-12-31"), ("브라질", "보우소나루(우파)", "2019-01-01", "2022-12-30"), ("브라질", "룰라(좌파)", "2023-01-02", None),
         ("미국", "트럼프 1기(공화)", "2017-01-20", "2021-01-20"), ("미국", "바이든(민주)", "2021-01-20", "2025-01-20"), ("미국", "트럼프 2기(공화)", "2025-01-20", None)]


def fx_terms(sers):
    out = []
    for c, who, a, b in TERMS:
        row = {"c": c, "who": who, "from": a, "to": b or sers["brl"][-1][0]}
        for key, ser in sers.items():
            x0 = next(x for x in ser if x[0] >= a) if ser[0][0] < a else ser[0]
            x1 = [x for x in ser if x[0] <= row["to"]][-1]
            yrs = (date.fromisoformat(x1[0]) - date.fromisoformat(x0[0])).days / 365.25
            row[key] = {"chg": round((x1[1] / x0[1] - 1) * 100, 1), "cagr": round(((x1[1] / x0[1]) ** (1 / yrs) - 1) * 100, 1)}
        out.append(row)
    return out


def fx_stats(brl_krw, brl_usd, years=5):
    """최근 N년 환율 통계(원화 기준 BRL/KRW·USD/KRW): 연평균 변화율(CAGR), 롤링 1년 변화율의 강세·약세 구간 평균."""
    usd = dict(brl_usd)
    sers = {"brl": [(d, v) for d, v in brl_krw],
            "usd": [(d, k / usd[d]) for d, k in brl_krw if usd.get(d)]}
    out = {"yrs": years}
    for key, ser in sers.items():
        if len(ser) < 400: return None
        ds = [date.fromisoformat(d) for d, _ in ser]; vs = [v for _, v in ser]
        end = ds[-1]; start = end.replace(year=end.year - years)
        roll = []; j = 0
        for i, d in enumerate(ds):
            if d < start: continue
            tgt = d - timedelta(days=365)
            while j + 1 < i and ds[j + 1] <= tgt: j += 1
            if ds[j] <= tgt: roll.append((vs[i] / vs[j] - 1) * 100)
        i0 = max(i for i, d in enumerate(ds) if d <= start)
        up = [x for x in roll if x > 0]; dn = [x for x in roll if x < 0]
        out[key] = {"cagr": round(((vs[-1] / vs[i0]) ** (1 / years) - 1) * 100, 2),
                    "up": round(sum(up) / len(up), 2) if up else 0, "down": round(sum(dn) / len(dn), 2) if dn else 0}
    out["terms"] = fx_terms(sers)
    # 롤링 1년 변화율 쌍(헤알, 달러, 구간 종료일) — 약 주 1회 표본. 환율 가정이 과거에 얼마나 자주 있었는지 계산용
    bs, us = sers["brl"], sers["usd"]; ud = dict(us); roll = []; j = 0
    ds = [date.fromisoformat(d) for d, _ in bs]
    for i in range(0, len(bs), 5):
        tgt = ds[i] - timedelta(days=365)
        if tgt < ds[0]: continue
        while j + 1 < i and ds[j + 1] <= tgt: j += 1
        d1, d0 = bs[i][0], bs[j][0]
        if d1 in ud and d0 in ud: roll.append([round((bs[i][1] / bs[j][1] - 1) * 100, 1), round((ud[d1] / ud[d0] - 1) * 100, 1), d1])
    out["roll"] = roll
    out["asof"] = ds[-1].isoformat()
    return out


OECD_CPI = "https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0/{c}.M.N.CPI.PA._T.N.GY?lastNObservations=13&dimensionAtObservation=AllDimensions"


ECOS_URL = "https://ecos.bok.or.kr/api/StatisticSearch/sample/json/kr/1/10/511Y003/M/{a}/{b}/{c}"   # 공개 sample 키(최대 10건) — 개인 키 아님


def ecos_expect():
    """한국은행 소비자동향조사 기대인플레이션율(향후 1·3·5년, 최신월). 월별이라 최근 6개월 범위에서 마지막 값."""
    t = date.today(); a = (t.replace(day=1) - timedelta(days=160)).strftime("%Y%m"); b = t.strftime("%Y%m")
    out = {}
    for key, code in (("y1", "FMB"), ("y3", "FMC"), ("y5", "FMD")):
        req = urllib.request.Request(ECOS_URL.format(a=a, b=b, c=code), headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r: j = json.load(r)
        rows = j.get("StatisticSearch", {}).get("row")
        if not rows: raise ValueError(f"ECOS {code}: {j.get('RESULT', {}).get('MESSAGE', '데이터 없음')}")
        last = max(rows, key=lambda x: x["TIME"])
        out[key] = {"v": float(last["DATA_VALUE"]), "period": f"{last['TIME'][:4]}-{last['TIME'][4:]}"}
    log("ECOS 기대인플레이션율:", out)
    return out


UST_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all?type={t}&field_tdr_date_value={y}&page&_format=csv"


def _ust(t, y):
    req = urllib.request.Request(UST_URL.format(t=t, y=y), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return {x["Date"]: {k.upper(): v for k, v in x.items()} for x in csv.DictReader(r.read().decode("utf-8-sig").splitlines())}   # 열 이름 대소문자가 파일마다 다름(5 Yr / 5 YR)


def us_breakeven():
    """미 재무부 일별 명목·실질(TIPS) 국채금리(키 불필요)로 5·7년 손익분기 인플레이션 = 명목 − 실질. 최신 공통일, 5·7년 단순 평균."""
    y = date.today().year
    for yy in (y, y - 1):   # 연초에는 올해 행이 없을 수 있음
        nom, real = _ust("daily_treasury_yield_curve", yy), _ust("daily_treasury_real_yield_curve", yy)
        days = sorted((d for d in nom if d in real and nom[d].get("5 YR") and real[d].get("5 YR") and nom[d].get("7 YR") and real[d].get("7 YR")),
                      key=lambda d: datetime.strptime(d, "%m/%d/%Y"))
        if days: break
    else: raise ValueError("재무부 금리 데이터 없음")
    d = days[-1]; b5 = float(nom[d]["5 YR"]) - float(real[d]["5 YR"]); b7 = float(nom[d]["7 YR"]) - float(real[d]["7 YR"])
    out = {"v": round((b5 + b7) / 2, 3), "y5": round(b5, 3), "y7": round(b7, 3), "period": datetime.strptime(d, "%m/%d/%Y").strftime("%Y-%m-%d")}
    log("미 국채 손익분기 인플레이션:", out)
    return out


REACH_THR = [25, 50, 75, 100, 125, 150, 175, 200, 250, 300]   # 금리 상승폭(bp)
REACH_HOR = [21, 63, 126, 252]                                  # 영업일(약 1·3·6·12개월)


def update_yield_reach(path=None):
    """잔존 4~6.5년 Prefixado(≈PF32)의 과거 금리 상승 도달 빈도: 시작일로부터 N영업일 안에 금리가 한 번이라도 +X bp 이상 오른 시작일 비율(2016-10 이후, 3일 간격 표본).
    매수 사다리에서 '이 가격(=금리 +X bp)에 과거 얼마나 자주 닿았나'를 보여 주는 용도. 국채 CSV 캐시가 없으면 예외."""
    path = path or CACHE / "PrecoTaxaTesouroDireto.csv"
    if not Path(path).exists(): raise FileNotFoundError("국채 CSV 캐시 없음")
    B = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.reader(f, delimiter=";"):
            if not r or r[0] != "Tesouro Prefixado": continue
            try: d = datetime.strptime(r[2], "%d/%m/%Y").date(); mv = datetime.strptime(r[1], "%d/%m/%Y").date(); y = float(r[3].replace(",", "."))
            except (ValueError, IndexError): continue
            if d >= date(2016, 10, 21): B.setdefault(mv, []).append((d, y))
    for v in B.values(): v.sort()
    idx = {mv: {x[0]: i for i, x in enumerate(v)} for mv, v in B.items()}
    dates = sorted({x[0] for v in B.values() for x in v})
    hit = {h: [0] * len(REACH_THR) for h in REACH_HOR}; tot = {h: 0 for h in REACH_HOR}
    for dd in dates[::3]:
        best = None
        for mv in B:
            if dd in idx[mv]:
                t = (mv - dd).days / 365.25
                if 4.0 <= t <= 6.5 and (best is None or abs(t - 5.2) < abs(best[0] - 5.2)): best = (t, mv)
        if not best: continue
        v = B[best[1]]; i = idx[best[1]][dd]
        for h in REACH_HOR:
            seg = v[i:i + h + 1]
            if len(seg) < h + 1: continue
            tot[h] += 1; rise = max(y for _, y in seg[1:]) - seg[0][1]
            for k, thr in enumerate(REACH_THR):
                if rise >= thr / 100: hit[h][k] += 1
    out = {"thr": REACH_THR, "hor": REACH_HOR, "p": [[round(hit[h][k] / tot[h] * 100) if tot[h] else None for k in range(len(REACH_THR))] for h in REACH_HOR], "n": [tot[h] for h in REACH_HOR]}
    log("금리 상승 도달 빈도:", out["p"][:2], "표본", out["n"])
    return out


def update_yield_dist(path=None):
    """잔존 4~6.5년 Prefixado(≈PF32) 12개월(252영업일) 금리 변동의 과거 분포(평균 제거, bp 분위 0~100%)와 최근 변동성 비율.
    앱 민감도 표의 '진입 후 금리 변동 발생 확률'을 매일 다시 계산하는 데 쓴다: 분포 모양=과거 표본, 중심=시나리오 가정, 폭=과거 대비 최근 60영업일 일간 변동성 비율(0.7~1.5로 제한)."""
    path = path or CACHE / "PrecoTaxaTesouroDireto.csv"
    if not Path(path).exists(): raise FileNotFoundError("국채 CSV 캐시 없음")
    B = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.reader(f, delimiter=";"):
            if not r or r[0] != "Tesouro Prefixado": continue
            try: d = datetime.strptime(r[2], "%d/%m/%Y").date(); mv = datetime.strptime(r[1], "%d/%m/%Y").date(); y = float(r[3].replace(",", "."))
            except (ValueError, IndexError): continue
            if d >= date(2016, 10, 21): B.setdefault(mv, []).append((d, y))
    for v in B.values(): v.sort()
    idx = {mv: {x[0]: i for i, x in enumerate(v)} for mv, v in B.items()}
    dates = sorted({x[0] for v in B.values() for x in v})
    H = 252; ch = []; daily = []
    for n, dd in enumerate(dates):
        best = None
        for mv in B:
            if dd in idx[mv]:
                t = (mv - dd).days / 365.25
                if 4.0 <= t <= 6.5 and (best is None or abs(t - 5.2) < abs(best[0] - 5.2)): best = (t, mv)
        if not best: continue
        v = B[best[1]]; i = idx[best[1]][dd]
        if i > 0 and (dd - v[i - 1][0]).days <= 5: daily.append((dd, (v[i][1] - v[i - 1][1]) * 100))
        if n % 3 == 0 and i + H < len(v): ch.append((v[i + H][1] - v[i][1]) * 100)
    if len(ch) < 200 or len(daily) < 200: raise ValueError("표본 부족")
    mean = sum(ch) / len(ch); dm = sorted(c - mean for c in ch)
    q = [round(dm[min(len(dm) - 1, int(k / 100 * (len(dm) - 1) + 0.5))]) for k in range(101)]
    sd = lambda a: (sum(x * x for x in a) / len(a)) ** 0.5
    d_all = sd([x for _, x in daily]); d_rec = sd([x for _, x in daily[-60:]])
    vr = max(0.7, min(1.5, d_rec / d_all)) if d_all else 1.0
    out = {"q": q, "n": len(ch), "mean": round(mean), "sd": round(sd(dm)), "vol_ratio": round(vr, 2), "d_all": round(d_all, 1), "d_rec": round(d_rec, 1), "asof": str(daily[-1][0])}
    log("금리 12개월 변동 분포:", {k: out[k] for k in ("n", "mean", "sd", "vol_ratio", "asof")})
    return out


def update_ust():
    """미 재무부 일별 명목 국채금리 3·5·7·10년(키 불필요) 최근 약 150영업일 — 달러표시 브라질 채권의 입력 시세 이후 금리 변동 추정용."""
    y = date.today().year; rows = {}
    for yy in (y - 1, y):
        try: cur = _ust("daily_treasury_yield_curve", yy)
        except Exception as e:
            if yy == y: raise
            log("미 국채 전년도 이력 생략:", e); continue
        for d, r in cur.items():
            try: rows[datetime.strptime(d, "%m/%d/%Y").strftime("%Y-%m-%d")] = [float(r[k]) for k in ("3 YR", "5 YR", "7 YR", "10 YR")]
            except (KeyError, ValueError): continue
    ser = [[d] + v for d, v in sorted(rows.items())][-150:]
    if not ser: raise ValueError("미 국채 금리 데이터 없음")
    log(f"미 국채 금리 이력 {len(ser)}일, 최신 {ser[-1]}")
    return {"cols": [3, 5, 7, 10], "series": ser}


def update_mkt():
    """브렌트유(Yahoo BZ=F)·프랑스-독일 10년물 금리 차(TradingView 스캐너, 비공식·키 불필요). 점검판 자동 입력용. 한쪽만 실패해도 나머지는 저장."""
    out = {}; ua = {"User-Agent": "Mozilla/5.0"}
    try:
        req = urllib.request.Request("https://query1.finance.yahoo.com/v8/finance/chart/BZ=F?interval=1d&range=5d", headers=ua)
        with urllib.request.urlopen(req, timeout=30) as r: m = json.load(r)["chart"]["result"][0]["meta"]
        out["brent"] = {"v": round(float(m["regularMarketPrice"]), 2), "t": datetime.fromtimestamp(m["regularMarketTime"], timezone.utc).strftime("%Y-%m-%d %H:%MZ"), "src": "Yahoo BZ=F"}
    except Exception as e: log("브렌트유 자동 수집 실패:", e)
    try:
        body = json.dumps({"symbols": {"tickers": ["TVC:FR10Y", "TVC:DE10Y"]}, "columns": ["close"]}).encode()
        req = urllib.request.Request("https://scanner.tradingview.com/global/scan", data=body, headers=dict(ua, **{"Content-Type": "application/json", "Origin": "https://www.tradingview.com"}))
        with urllib.request.urlopen(req, timeout=30) as r: d = {x["s"]: x["d"][0] for x in json.load(r)["data"]}
        fr, de = float(d["TVC:FR10Y"]), float(d["TVC:DE10Y"])
        out["frde"] = {"v": round((fr - de) * 100, 1), "fr": round(fr, 3), "de": round(de, 3), "t": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ"), "src": "TradingView TVC:FR10Y−DE10Y"}
    except Exception as e: log("프·독 금리 차 자동 수집 실패:", e)
    if not out: raise ValueError("시장 지표 자동 수집 모두 실패")
    log("점검판 자동 지표:", out)
    return out


def update_infl_kus():
    """한국·미국 소비자물가 전년동월비(OECD SDMX, 키 불필요). 최신월 값 + 최근 13개월 이력. 한 나라가 실패하면 예외."""
    out = {}
    for key, c in (("kr", "KOR"), ("us", "USA")):
        req = urllib.request.Request(OECD_CPI.format(c=c), headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv"})
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = list(csv.DictReader(r.read().decode("utf-8-sig").splitlines()))
        ser = sorted((x["TIME_PERIOD"], round(float(x["OBS_VALUE"]), 3)) for x in rows if x["OBS_VALUE"])
        if not ser: raise ValueError(f"OECD CPI {c} 데이터 없음")
        a12 = round(sum(v for _, v in ser[-12:]) / len(ser[-12:]), 3)   # 12개월 평균 = 1순위 소스 실패 시 대체값
        out[key] = {"v": a12, "period": ser[-1][0], "series": ser, "src": "OECD CPI 12개월 평균", "label": "OECD 12개월 평균 " + ser[-1][0],
                    "cpi": {"v": ser[-1][1], "period": ser[-1][0]}}
        log(f"{c} 물가 전년동월비 {ser[-1][0]}: {ser[-1][1]}% · 12개월 평균 {a12}%")
    try:   # 한국은 향후 기대 물가(3년 후)를 기본값으로, 최근 CPI 는 참고(cpi)
        e = ecos_expect()
        out["kr"].update(exp=e, v=e["y3"]["v"], period=e["y3"]["period"], src="ECOS 3년후 기대인플레이션율", label="ECOS 3년후 기대 " + e["y3"]["period"])
    except Exception as ex:
        log("ECOS 기대인플레이션 실패(OECD 12개월 평균으로 대체):", ex)
    try:   # 미국은 시장 기대(손익분기 인플레이션 = 명목 − TIPS 실질금리, 5·7년 평균 ≈ PF32 잔존 기간)
        b = us_breakeven()
        out["us"].update(bei=b, v=b["v"], period=b["period"], src="미 국채 손익분기 인플레이션(5·7년 평균)", label="미 국채 BEI(5·7년) " + b["period"])
    except Exception as ex:
        log("미 국채 BEI 실패(OECD 12개월 평균으로 대체):", ex)
    return out


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
INVESTIR_URL = "https://www.tesourodireto.com.br/documents/d/guest/rendimento-investir-csv?download=true"


def fetch_investir():
    """Tesouro Direto '투자하기' 가격표 CSV 를 직접 받아 data/inbox 에 저장(검증 통과 시에만 교체). 실패해도 기존 파일로 계속."""
    inbox = DATA / "inbox"; inbox.mkdir(exist_ok=True)
    tmp, dst = inbox / "rendimento-investir.csv.part", inbox / "rendimento-investir.csv"
    try:
        err = None
        for i in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(INVESTIR_URL, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
                    tmp.write_bytes(r.read())
                break
            except Exception as e:
                err = e; time.sleep(5 * 3 ** i)
        else:
            raise err
        rows = read_investir(tmp)   # 형식이 다르면 예외
        if not any("Prefixado" in x["name"] for x in rows): raise ValueError("Prefixado 행 없음")
        os.replace(tmp, dst)
        log(f"Investir CSV 자동 다운로드: {len(rows)}종목")
    except Exception as e:
        log("Investir CSV 다운로드 실패(기존 파일 사용):", e)
        tmp.unlink(missing_ok=True)


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
    try: fxs = fx_stats(fx, FX_USD) if status["fx"] == "ok" and FX_USD else None
    except Exception as e: log("환율 통계 실패:", e); fxs = None
    fxs = fxs or prev.get("fx_stats")
    fx_usd = ({"latest": FX_USD[-1], "series": FX_USD[-400:]} if FX_USD else prev.get("fx_usd"))
    if status["fx"] == "ok" and not FX_USD: status["fx_usd"] = "empty"
    try: infl = {"br": update_infl()}; status["infl"] = "ok"
    except Exception as e:
        log("IPCA 기대 실패:", e); status["infl"] = f"error: {e}"; infl = prev.get("infl")
    try: ust = update_ust(); status["ust"] = "ok"
    except Exception as e:
        log("미 국채 금리 이력 실패(이전 값 유지):", e); status["ust"] = f"error: {e}"; ust = prev.get("ust")
    try: mkt = update_mkt(); status["mkt"] = "ok"
    except Exception as e:
        log("점검판 자동 지표 실패(이전 값 유지):", e); status["mkt"] = f"error: {e}"; mkt = prev.get("mkt")
    try: reach = update_yield_reach(); status["reach"] = "ok"
    except Exception as e:
        log("금리 도달 빈도 계산 실패(이전 값 유지):", e); status["reach"] = f"error: {e}"; reach = prev.get("yield_reach")
    try: ydist = update_yield_dist(); status["ydist"] = "ok"
    except Exception as e:
        log("금리 변동 분포 계산 실패(이전 값 유지):", e); status["ydist"] = f"error: {e}"; ydist = prev.get("yield_dist")
    prev_infl = prev.get("infl") or {}
    try: infl = dict(infl or {}, **update_infl_kus())
    except Exception as e:
        log("한국·미국 물가 실패(이전 값 유지):", e); status["infl_kus"] = f"error: {e}"
        infl = dict(infl or {}, **{k: prev_infl[k] for k in ("kr", "us") if k in prev_infl})

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
    fetch_investir()
    ip = newest_investir()
    if ip:
        live = read_investir(ip)
        ts = datetime.fromtimestamp(os.path.getmtime(ip))
        live_info = {"file": os.path.basename(ip), "mtime": ts.isoformat(timespec="minutes"),   # 파일 수정 시각(이 기기 로컬)
                     "picked": datetime.now().astimezone().isoformat(timespec="seconds")}   # 자동 갱신이 이 파일을 집어간 시각
        snaps = sorted((DATA / "snapshots").glob("rendimento-investir_*.csv"))
        if not snaps or snaps[-1].read_bytes() != Path(ip).read_bytes():   # 내용이 같으면 스냅샷 중복 저장 안 함
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
    out = {"generated": datetime.now().astimezone().isoformat(timespec="seconds"), "status": status,
           "live": live, "live_info": live_info, "bonds": sorted(bonds, key=lambda b: (b["tipo"], b["venc"][-4:])),
           "series": series,
           "fx": {"latest": fx[-1] if fx else None, "series": fx}, "fx_usd": fx_usd, "fx_stats": fxs, "infl": infl, "ust": ust, "mkt": mkt, "yield_reach": reach, "yield_dist": ydist}
    (DATA / "data.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    log("data.json 생성 완료", status)
    if not os.environ.get("GITHUB_ACTIONS") and not os.environ.get("PF32_NO_NOTIFY"):   # 로컬 실행: 새로 켜진 신호를 macOS 알림으로 (Actions 는 워크플로가 따로 처리)
        try:
            r = subprocess.run([sys.executable, "-I", str(ROOT / "notify.py"), "--local"], capture_output=True, text=True, timeout=90)
            log("알림 점검:", (r.stdout or r.stderr).strip().splitlines()[-1][:200] if (r.stdout or r.stderr).strip() else "출력 없음")
        except Exception as e: log("알림 점검 실패:", e)


if __name__ == "__main__":
    main()
