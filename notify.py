#!/usr/bin/env python3
"""신호 변화 알림 — tools/signals.js 로 매수 지표·손절 규칙·체결 조건을 판정하고, 이전 상태 대비 '새로 켜진' 신호만 알린다.
  --local    : 이 Mac 로컬 실행(launchd/update.py 후). macOS 알림센터에 상세 내용 표시. 상태 data/signal_state.json(git 제외)
  --actions  : GitHub Actions. 개인 값이 공개되지 않도록 일반 문구 이슈(@멘션)만 생성. 임계값은 저장소 변수 BUY_REAL·STOP_REAL. 상태 data/cache(캐시)
  --dry-run  : 알림을 보내지 않고 출력만
첫 실행(이전 상태 없음)은 현재 상태만 저장하고 알리지 않는다."""
import glob, json, os, shutil, subprocess, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
ACTIONS = "--actions" in sys.argv or bool(os.environ.get("GITHUB_ACTIONS"))
DRY = "--dry-run" in sys.argv
STATE = os.path.join(ROOT, "data", "cache" if ACTIONS else "", "signal_state.json")
NAMES = ["① 헤알채", "② 달러채", "③ 5:5"]

# 상황별 점검표(개인 값 없음). 로컬 알림은 상황에 맞는 항목만, 공개 이슈는 어떤 신호인지 드러나지 않도록 전체 점검표를 고정 문구로 붙인다.
TIPS = {
    "buy": "매수 직전: 앱 PU는 '매수 쪽 가격'(매도가는 약 0.6% 낮음) → 증권사 호가 확인 · 가격은 하루 두 번 갱신이라 시점 차이 있음 · ②는 달러채 시세가 수동 입력값(갱신 필요)",
    "fill": "체결 조건 충족: 호가 확인 후 매수 · 체결하면 설정 탭에 체결가·날짜·체결 체크 입력 → 폰에 '설정 복사→붙여넣기'",
    "stop": "손절 규칙 점검: 01 탭 손절 지표(최악 가정 원화 실질·한계 환율)와 02 탭 손절 카드 확인 · 기준 4.5%는 환율 가정 최악 기준",
    "watch": "중단·보류 기준 도달: 01 탭 '다가오는 일정' 주간 점검판에서 해당 지표 확인 · 브렌트유·프랑스-독일 금리 차는 직접 입력한 값 기준(입력일 확인)",
    "target": "수익 소진 TARGET 도달: 매도 검토 — 매도가는 약 0.6% 낮음 · 세금·환율·보유 시 남은 실질 수익률과 비교 후 판단 · 02 탭 TARGET 카드에서 기준 확인",
    "fx": "손절 환율 근접: 02·03 탭의 손절 환율과 현재 환율 거리 확인 · 체결 입력이 있으면 평균 매수 환율 기준",
}

def checklist_md(kind):
    """calendar.json 의 점검표(kind: fiscal|buy)를 마크다운 체크박스로(공개 문구만, 개인 값 없음)"""
    try: cal = json.load(open(os.path.join(ROOT, "calendar.json"), encoding="utf-8"))
    except (OSError, ValueError): return ""
    gs = cal.get(kind + "_checklist")
    if not gs: return ""
    out = [f"### {cal.get(kind + '_title', '점검표')}"]
    for g in gs: out += [f"**{g['g']}**"] + [f"- [ ] {t}" for t in g["items"]]
    if cal.get(kind + "_note"): out.append(f"\n{cal[kind + '_note']}")
    return "\n".join(out)

def fiscal_md(): return checklist_md("fiscal")
def all_md(): return "\n\n".join(x for x in (checklist_md("fiscal"), checklist_md("buy")) if x)

WEEKLY = "주 1회 점검: 달러채 시세 갱신(수동) · 매수 기준·손절 기준·TARGET 재검토 · 큰 이벤트(결선 10/25 등) 전후 04-1 시나리오 확률 확인"
FULL_CHECKLIST = """### 아침 3분 점검표
1. 알림 확인 (GitHub 앱, Mac 알림센터)
2. 앱 01 탭: 갱신 시각이 오늘인지, '자동 갱신 멈춤'·환율 지연 경고가 없는지
3. 매수 지표 박스: ON 여부와 🔔 개수
4. 손절 지표 박스: 상태 변화 여부
5. 02 탭: '체결 조건 충족' 표시 여부

### 매수 직전에 꼭 할 것
- 앱의 PU는 매수 쪽 가격이고 매도가는 약 0.6% 낮습니다. 실제 주문은 증권사 호가로 확인하세요.
- 신호가 켜진 시점과 지금 사이에 가격이 움직였을 수 있습니다(하루 두 번 갱신).
- 달러채는 시세가 수동 입력값이라 갱신이 필요합니다.

### 체결 후 할 일
- 설정 탭에 체결가·날짜·체결 체크를 입력하고, 폰에도 '설정 복사 → 붙여넣기'를 하세요.

### 주 1회 점검
- 달러채 시세 갱신 · 매수/손절 기준·TARGET 재검토 · 큰 이벤트 전후 04-1 시나리오 확률 확인"""

def find_node():
    for c in [shutil.which("node"), "/opt/homebrew/bin/node", "/usr/local/bin/node", *sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/node")))]:
        if c and os.path.exists(c): return c
    raise RuntimeError("node 를 찾을 수 없습니다")

def signals():
    r = subprocess.run([find_node(), os.path.join(ROOT, "tools", "signals.js")], capture_output=True, text=True, timeout=60, env=os.environ)
    if r.returncode: raise RuntimeError(r.stderr.strip()[:300])
    return json.loads(r.stdout)

def events(prev, cur):
    ev = []
    for i in range(3):
        if cur["buy"][i] and not prev["buy"][i]:
            d = f" (가격 {cur['cur'][i]} ≤ 선 {cur['line'][i]})" if i < 2 else ""
            if not ACTIONS and cur.get("zoneWait", [False] * 3)[i]: d += " — 단, 이벤트 구간 기준으로는 대기"
            ev.append(("buy", f"{NAMES[i]} 매수 지표 ON{d}"))
        if cur["stop"][i] and not prev["stop"][i]:
            ev.append(("stop", f"{NAMES[i]} 손절 규칙 미달 진입 (최악 가정 원화 실질 {cur['worst'][i]}% < {cur['sr']}%)"))
    if cur.get("target") and prev.get("target") is False: ev.append(("target", f"수익 소진 TARGET(헤알 실질 기준) 도달 (PU ≥ {cur.get('targetLine')})"))
    for w in cur.get("wflag", []):   # 중단·보류 기준(점검판): 경계는 로컬 config.local.json 또는 저장소 변수 WATCH_CFG
        if w not in prev.get("wflag", []): ev.append(("watch", f"{w} 중단·보류 기준 도달"))
    if not ACTIONS:   # 체결 조건·손절 환율은 개인 설정(체결가·날짜) 기반이라 로컬에서만 판정
        if cur["reached"] and not prev.get("reached"): ev.append(("fill", f"분할매수 지정가 체결 조건 충족 (현재 {cur['price']})"))
        if cur["fxNear"] and not prev.get("fxNear"): ev.append(("fx", f"BRL/KRW {cur['fx']} 손절 환율에 근접"))
    return ev

def local_message(ev):
    """상황별 한 줄 + 해당 점검 팁(중복 제거). macOS 알림 길이 한도 때문에 요약, 전체는 data/last_alert.md 에 저장."""
    kinds = []
    for k, _ in ev:
        if k not in kinds: kinds.append(k)
    head = " / ".join(t for _, t in ev)
    tips = " ▶ ".join(TIPS[k].split(": ", 1)[1] if ": " in TIPS[k] else TIPS[k] for k in kinds if k in TIPS)
    return head, tips

def notify_local(ev, title="PF32 알림"):
    head, tips = local_message(ev)
    try:
        os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
        open(os.path.join(ROOT, "data", "last_alert.md"), "w", encoding="utf-8").write(f"# {title}\n\n{head}\n\n" + "\n".join(f"- {TIPS[k]}" for k in dict.fromkeys(k for k, _ in ev) if k in TIPS) + f"\n\n{FULL_CHECKLIST}\n\n{all_md()}\n")
    except OSError: pass
    msg = (head + " ▶ " + tips)[:240].replace('"', "'").replace("\\", "")
    subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "{title}" sound name "Glass"'], check=False)

def assign_owner(url, repo):
    """알림 이슈를 저장소 소유자에게 할당 — '직접 멘션'과 '할당됨' 중 하나만 켜져 있어도 알림이 가도록. 실패해도 무시(이슈는 이미 생성됨)."""
    owner = repo.split("/")[0]
    if url: subprocess.run(["gh", "issue", "edit", url, "--add-assignee", owner], capture_output=True, text=True)

def issue_body(owner, sample=False):
    tag = "[샘플 — 실제 신호가 아닙니다] " if sample else ""
    return f"@{owner} {tag}PF32 신호가 바뀌었습니다. 앱 01 탭에서 확인하세요. (개인 설정이 공개되지 않도록 어떤 신호인지·가격 등 상세는 이 이슈에 적지 않습니다.)\n\n{FULL_CHECKLIST}\n\n{all_md()}"

def notify_actions(ev):
    repo = os.environ.get("GITHUB_REPOSITORY", "sbhong2008/pf32-dashboard"); owner = repo.split("/")[0]
    body = issue_body(owner)
    r = subprocess.run(["gh", "issue", "create", "-R", repo, "--title", "🔔 PF32 알림 — 신호 변경", "--body", body], capture_output=True, text=True)
    url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    assign_owner(url, repo); return r

def weekly_due(prev):
    """로컬: 새 ISO 주가 시작된 뒤 첫 점검에서 주간 점검 알림 1회(첫 실행 제외)"""
    import datetime
    wk = "%d-W%02d" % datetime.date.today().isocalendar()[:2]
    return wk, bool(prev) and prev.get("week") != wk

def test():
    """알림 경로 시험: macOS 알림 + (--github) 테스트 이슈 생성 후 즉시 닫음(@멘션 알림은 생성 시점에 발송됨)"""
    ev = [("buy", "[샘플] ① 헤알채 매수 지표 ON (가격 495.1 ≤ 선 495.4)"), ("fill", "[샘플] 분할매수 지정가 체결 조건 충족 (현재 495.1)")]
    if not ACTIONS and sys.platform == "darwin": notify_local(ev, "PF32 알림 (테스트)"); print("macOS 알림 전송, 상세: data/last_alert.md")
    if "--github" in sys.argv:
        repo = os.environ.get("GITHUB_REPOSITORY", "sbhong2008/pf32-dashboard"); owner = repo.split("/")[0]
        r = subprocess.run(["gh", "issue", "create", "-R", repo, "--title", "🔔 PF32 알림 — 신호 변경 (샘플)", "--body", issue_body(owner, sample=True) + ("" if ACTIONS else "\n\n※ 본인 계정으로 만든 이슈는 GitHub가 본인에게 알림을 보내지 않습니다. 폰 알림 확인은 alert-test 워크플로(봇)로 하세요.")], capture_output=True, text=True)
        url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        print("GitHub 테스트 이슈:", url or r.stderr.strip()[:200])
        if url:
            assign_owner(url, repo)
            subprocess.run(["gh", "issue", "close", url, "-c", "테스트 완료"], capture_output=True, text=True)

# ---------- 일정 알림: calendar.json(공개 일정) 의 알림 시점이 오면 시장 스냅샷과 함께 발송 ----------
import datetime
KST = datetime.timezone(datetime.timedelta(hours=9))
def today_kst():
    for a in sys.argv:
        if a.startswith("--today="): return datetime.date.fromisoformat(a.split("=", 1)[1])
    return datetime.datetime.now(KST).date()

def due_calendar(cal, today, sent):
    """오늘(KST)이 알림일이거나 하루 지난 미발송 알림(catch-up 1일) → [(event, alert, key)]. 주간 항목은 해당 요일에 주 1회."""
    out = []
    for e in cal.get("events", []):
        if e.get("weekly"):
            key = "%s:%d-W%02d" % ((e["id"],) + tuple(today.isocalendar()[:2]))
            if today.weekday() == e["weekday"] and key not in sent: out.append((e, {"label": "금요일 점검"}, key))
            continue
        for a in e.get("alerts", []):
            d = datetime.date.fromisoformat(a["date"]) if "date" in a else datetime.date.fromisoformat(e["date"]) + datetime.timedelta(days=a["offset"])
            key = f"{e['id']}:{a.get('date', a.get('offset'))}"
            if d <= today <= d + datetime.timedelta(days=1) and key not in sent: out.append((e, a, key))
    return out

def snap_line(sn):
    f = lambda v, d=2: "—" if v is None else f"{v:.{d}f}"
    return f"PF32 YTM {f(sn['ytm'])}% (PU {f(sn['price'])}) · 헤알/원 {f(sn['fx'])} · 원/달러 {f(sn['usdkrw'], 1)} · 미 10년물 {f(sn['ust10'])}% · 미 손익분기 인플레 {f(sn['bei'])}%"

def weekly_status(cur):
    """주간 점검 결과 한 줄(공개 이슈용): 지표 이름만, 경계값·현재값은 적지 않는다. 경계 미설정이면 판정 불가로 표시."""
    w = cur.get("watch")
    if not w: return "ℹ️ 경계 기준이 설정되지 않아 이상 여부를 판정하지 못했습니다(저장소 변수 WATCH_CFG).", "판정 불가"
    bad = [x["n"] for x in w if x["flag"] and not x.get("zoneOnly")]
    miss = [x["n"] for x in w if x["v"] is None]
    tail = f" (값 없음: {', '.join(miss)})" if miss else ""
    if bad: return f"⚠️ **이상 징후 {len(bad)}건** — {', '.join(bad)} 경계 도달. 앱 01 탭 점검판에서 확인하세요.{tail}", f"⚠ 이상 징후 {len(bad)}건"
    return f"✅ **정상** — 점검판 {len(w)}개 지표 모두 경계 이내입니다.{tail}", "✅ 정상"

def calendar_issue(e, a, sn, owner, cur=None):
    when = e.get("when", ""); chk = "\n".join(f"- {c}" for c in e.get("check", []))
    unc = "" if e.get("confirmed", True) else "\n\n※ 일정이 확정되지 않았거나 단일 출처입니다. 공식 일정으로 재확인하세요."
    note = f"\n\n참고: {e['note']}" if e.get("note") else ""
    fis = "".join(f"\n\n{checklist_md(k)}" for k in ("fiscal", "buy") if e.get(k))
    st, tag = weekly_status(cur) if e.get("weekly") and cur else ("", "")
    return (f"📅 PF32 일정 — {e['title']} ({a['label']})" + (f" · {tag}" if tag else ""),
            f"@{owner} **{e['title']}** · {when}\n\n" + (f"**점검 결과**\n{st}\n\n" if st else "") + f"**확인할 것**\n{chk}\n\n**시장 스냅샷**(갱신 {sn.get('asof', '')[:16].replace('T', ' ')} UTC)\n{snap_line(sn)}{unc}{note}{fis}\n\n개인 계획·판정은 공개 이슈에 적지 않습니다. 앱 01 탭의 '다가오는 일정'에서 확인하세요.")

def calendar_main():
    path = os.path.join(ROOT, "calendar.json")
    if not os.path.exists(path): return
    cal = json.load(open(path, encoding="utf-8")); today = today_kst()
    sp = os.path.join(ROOT, "data", "cache" if ACTIONS else "", "calendar_state.json")
    try: sent = set(json.load(open(sp)).get("sent", []))
    except (OSError, ValueError): sent = set()
    due = due_calendar(cal, today, sent)
    print(f"일정 알림: 오늘(KST) {today} · 대상 {len(due)}건", [f"{e['id']}/{a['label']}" for e, a, _ in due] or "")
    if not due: return
    cur = signals(); sn = cur["snap"]; local = {}
    if not ACTIONS:
        try: local = json.load(open(os.path.join(ROOT, "config.local.json")))
        except (OSError, ValueError): pass
    owner = os.environ.get("GITHUB_REPOSITORY", "sbhong2008/pf32-dashboard").split("/")[0]; repo = os.environ.get("GITHUB_REPOSITORY", "sbhong2008/pf32-dashboard")
    for e, a, key in due:
        if ACTIONS:
            title, body = calendar_issue(e, a, sn, owner, cur)
            if DRY: print("  [이슈]", title, "\n   ", body.replace("\n", "\n    ")[:600]); 
            else:
                r = subprocess.run(["gh", "issue", "create", "-R", repo, "--title", title, "--body", body], capture_output=True, text=True)
                url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""; assign_owner(url, repo); print("  이슈:", url or r.stderr.strip()[:150])
        else:
            plan = (local.get("cal_plan") or {}).get(e["id"], ""); zone = cur.get("zone") if e["id"] == "br-post-close" else None
            wl = [f"{w['n']} {'미입력' if w['v'] is None else w['v']}{' ⚠' if w['flag'] else ''}" for w in (cur.get("watch") or [])] if e.get("weekly") else []
            msg = f"{e['title']} ({a['label']}) · {e.get('when', '')}" + (f" ▶ {plan}" if plan else "") + (f" ▶ 현재 구간: {zone}" if zone else "") + (" ▶ " + " · ".join(wl) if wl else f" ▶ {snap_line(sn)}")
            if not DRY:
                try: open(os.path.join(ROOT, "data", "last_calendar.md"), "a", encoding="utf-8").write(f"- {today} {msg}\n")
                except OSError: pass
            if DRY: print("  [Mac 알림]", msg[:400])
            else: subprocess.run(["osascript", "-e", 'display notification "' + msg[:240].replace('"', "'").replace("\\", "") + '" with title "PF32 일정" sound name "Glass"'], check=False)
        sent.add(key)
    if not DRY:
        os.makedirs(os.path.dirname(sp), exist_ok=True); json.dump({"sent": sorted(sent)}, open(sp, "w"))

def main():
    if "--test" in sys.argv: return test()
    if "--calendar-only" in sys.argv: return calendar_main()
    cur = signals()
    prev = None
    try: prev = json.load(open(STATE))
    except (OSError, ValueError): pass
    ev = events(prev, cur) if prev else []
    wk, wdue = weekly_due(prev) if not ACTIONS else (None, False)
    print("신호:", {k: cur[k] for k in ("buy", "stop", "reached", "fxNear", "target")}, "| 이전:", "없음(첫 실행)" if prev is None else "있음", "| 새 이벤트:", [t for _, t in ev] or "없음")
    if wdue: print("주간 점검 알림 대상(새 주)")
    if not DRY:
        if ev: (notify_actions if ACTIONS else notify_local)(ev)
        if wdue: subprocess.run(["osascript", "-e", f'display notification "{WEEKLY}" with title "PF32 주간 점검"'], check=False)
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        st = {k: cur[k] for k in ("buy", "stop", "reached", "fxNear", "target", "wflag")}
        if wk: st["week"] = wk
        json.dump(st, open(STATE, "w"))

if __name__ == "__main__":
    rc = 0
    try: main()
    except Exception as e: print("알림 점검 실패:", e); rc = 1
    if "--test" not in sys.argv and "--calendar-only" not in sys.argv:
        try: calendar_main()
        except Exception as e: print("일정 알림 실패:", e); rc = 1
    sys.exit(rc)
