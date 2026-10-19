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
    "fx": "손절 환율 근접: 02·03 탭의 손절 환율과 현재 환율 거리 확인 · 체결 입력이 있으면 평균 매수 환율 기준",
}
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
            ev.append(("buy", f"{NAMES[i]} 매수 지표 ON{d}"))
        if cur["stop"][i] and not prev["stop"][i]:
            ev.append(("stop", f"{NAMES[i]} 손절 규칙 미달 진입 (최악 가정 원화 실질 {cur['worst'][i]}% < {cur['sr']}%)"))
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
        open(os.path.join(ROOT, "data", "last_alert.md"), "w", encoding="utf-8").write(f"# {title}\n\n{head}\n\n" + "\n".join(f"- {TIPS[k]}" for k in dict.fromkeys(k for k, _ in ev) if k in TIPS) + f"\n\n{FULL_CHECKLIST}\n")
    except OSError: pass
    msg = (head + " ▶ " + tips)[:240].replace('"', "'").replace("\\", "")
    subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "{title}" sound name "Glass"'], check=False)

def notify_actions(ev):
    repo = os.environ.get("GITHUB_REPOSITORY", "sbhong2008/pf32-dashboard"); owner = repo.split("/")[0]
    body = f"@{owner} PF32 신호가 바뀌었습니다. 앱 01 탭에서 확인하세요. (개인 설정이 공개되지 않도록 어떤 신호인지·가격 등 상세는 이 이슈에 적지 않습니다.)\n\n{FULL_CHECKLIST}"
    return subprocess.run(["gh", "issue", "create", "-R", repo, "--title", "🔔 PF32 알림 — 신호 변경", "--body", body], capture_output=True, text=True)

def weekly_due(prev):
    """로컬: 새 ISO 주가 시작된 뒤 첫 점검에서 주간 점검 알림 1회(첫 실행 제외)"""
    import datetime
    wk = "%d-W%02d" % datetime.date.today().isocalendar()[:2]
    return wk, bool(prev) and prev.get("week") != wk

def test():
    """알림 경로 시험: macOS 알림 + (--github) 테스트 이슈 생성 후 즉시 닫음(@멘션 알림은 생성 시점에 발송됨)"""
    ev = [("buy", "알림 테스트 — 실제 신호가 아닙니다"), ("fill", "알림 테스트")]
    notify_local(ev, "PF32 알림 (테스트)"); print("macOS 알림 전송, 상세: data/last_alert.md")
    if "--github" in sys.argv:
        repo = os.environ.get("GITHUB_REPOSITORY", "sbhong2008/pf32-dashboard"); owner = repo.split("/")[0]
        r = subprocess.run(["gh", "issue", "create", "-R", repo, "--title", "🔔 PF32 알림 테스트", "--body", f"@{owner} 알림 수신 확인용 테스트입니다. 폰에 알림이 왔는지 확인하세요. 바로 닫힙니다."], capture_output=True, text=True)
        url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        print("GitHub 테스트 이슈:", url or r.stderr.strip()[:200])
        if url: subprocess.run(["gh", "issue", "close", url, "-c", "테스트 완료"], capture_output=True, text=True)

def main():
    if "--test" in sys.argv: return test()
    cur = signals()
    prev = None
    try: prev = json.load(open(STATE))
    except (OSError, ValueError): pass
    ev = events(prev, cur) if prev else []
    wk, wdue = weekly_due(prev) if not ACTIONS else (None, False)
    print("신호:", {k: cur[k] for k in ("buy", "stop", "reached", "fxNear")}, "| 이전:", "없음(첫 실행)" if prev is None else "있음", "| 새 이벤트:", [t for _, t in ev] or "없음")
    if wdue: print("주간 점검 알림 대상(새 주)")
    if not DRY:
        if ev: (notify_actions if ACTIONS else notify_local)(ev)
        if wdue: subprocess.run(["osascript", "-e", f'display notification "{WEEKLY}" with title "PF32 주간 점검"'], check=False)
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        st = {k: cur[k] for k in ("buy", "stop", "reached", "fxNear")}
        if wk: st["week"] = wk
        json.dump(st, open(STATE, "w"))

if __name__ == "__main__":
    try: main()
    except Exception as e: print("알림 점검 실패:", e); sys.exit(1)
