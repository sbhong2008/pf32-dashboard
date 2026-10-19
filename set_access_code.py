#!/usr/bin/env python3
"""접속 코드 설정/교체 — 코드를 index.html 의 ACCESS(PBKDF2-SHA256 해시)에 반영한다. 코드 자체는 어디에도 저장하지 않는다.
사용: python3 set_access_code.py            # 새 코드를 무작위 생성해 출력
      python3 set_access_code.py MYCODE     # 지정한 코드 사용(영문·숫자 8자 이상 권장 — 공개 저장소에 해시가 보이므로 길고 무작위일수록 안전)
정적 사이트(GitHub Pages)라 브라우저 안에서만 확인하는 '가벼운 잠금'이다. 로컬 서버(127.0.0.1)는 면제."""
import hashlib, os, re, secrets, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
ALPHA = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # 헷갈리는 0/O/1/I/L 제외
ITER = 310000

def norm(c): return re.sub(r"[^A-Z0-9]", "", c.upper())

def main():
    code = sys.argv[1] if len(sys.argv) > 1 else "".join(secrets.choice(ALPHA) for _ in range(10))
    n = norm(code)
    if len(n) < 8: sys.exit("코드는 영문·숫자 8자 이상이어야 합니다.")
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", n.encode(), salt, ITER, 32).hex()
    p = os.path.join(ROOT, "index.html"); s = open(p, encoding="utf-8").read()
    new = f'const ACCESS = {{salt: "{salt.hex()}", iter: {ITER}, hash: "{h}"}};'
    s2, k = re.subn(r'const ACCESS = \{[^}]*\};', new, s, count=1)
    if k != 1: sys.exit("index.html 에서 ACCESS 정의를 찾지 못했습니다.")
    open(p, "w", encoding="utf-8").write(s2)
    shown = "-".join(n[i:i + 5] for i in range(0, len(n), 5))
    print(f"접속 코드: {shown}   (대소문자·하이픈 무시)\n※ 이 코드는 화면에만 출력됩니다. 안전한 곳에 보관하세요. index.html 에는 해시만 저장됩니다.")

if __name__ == "__main__":
    main()
