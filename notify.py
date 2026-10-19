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

def notify_local(ev):
    msg = " / ".join(t for _, t in ev)[:230].replace('"', "'")
    subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "PF32 알림" sound name "Glass"'], check=False)

def notify_actions(ev):
    repo = os.environ.get("GITHUB_REPOSITORY", "sbhong2008/pf32-dashboard"); owner = repo.split("/")[0]
    body = f"@{owner} PF32 신호가 바뀌었습니다. 앱에서 확인하세요. (개인 설정이 공개되지 않도록 상세 내용은 이 이슈에 적지 않습니다.)"
    subprocess.run(["gh", "issue", "create", "-R", repo, "--title", "🔔 PF32 알림 — 신호 변경", "--body", body], check=False)

def main():
    cur = signals()
    prev = None
    try: prev = json.load(open(STATE))
    except (OSError, ValueError): pass
    ev = events(prev, cur) if prev else []
    print("신호:", {k: cur[k] for k in ("buy", "stop", "reached", "fxNear")}, "| 이전:", "없음(첫 실행)" if prev is None else "있음", "| 새 이벤트:", [t for _, t in ev] or "없음")
    if ev and not DRY: (notify_actions if ACTIONS else notify_local)(ev)
    if not DRY:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        json.dump({k: cur[k] for k in ("buy", "stop", "reached", "fxNear")}, open(STATE, "w"))

if __name__ == "__main__":
    try: main()
    except Exception as e: print("알림 점검 실패:", e); sys.exit(1)
