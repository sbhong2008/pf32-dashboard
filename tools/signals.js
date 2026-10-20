#!/usr/bin/env node
// 매수 지표·손절 규칙·체결 조건 신호 판정 — index.html 의 계산 코드를 그대로 가상 DOM 에서 실행(중복 구현 없음). 개인 값은 읽지 않는다:
// 임계값은 환경변수 BUY_REAL("10.4,5,7")·STOP_REAL("4.5") 또는 로컬 실행 시 config.local.json(buy_real, stop_real, stages)만 사용. 결과(JSON)는 stdout.
const fs = require("fs"), path = require("path"), ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const src = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(x => x[1]).join("\n");
const stub = () => new Proxy(function () {}, {get: (t, k) => k === Symbol.toPrimitive ? () => "" : k === "classList" ? {add() {}, remove() {}, toggle() {}} : stub(), set: () => true, apply: () => stub()});
const store = {};
const env = {localStorage: {getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; }, removeItem() {}}, sessionStorage: {getItem: () => null, setItem() {}, removeItem() {}}, document: stub(),
  location: {protocol: "http:", hostname: "127.0.0.1", search: "", hash: ""}, navigator: {}, fetch: () => Promise.reject(new Error("stub")), scrollX: 0, scrollY: 0, scrollTo() {}, setInterval() {}, alert() {}, addEventListener() {}, innerWidth: 900, crypto: {subtle: {}}};
const names = Object.keys(env);
const mod = new Function(...names, src + "\nreturn {set(d, c) { D = d; C = c; }, model, buySignals, stopStatus, stopFx, consistentBuy};")(...names.map(n => env[n]));
const rd = f => { try { return JSON.parse(fs.readFileSync(path.join(ROOT, f), "utf8")); } catch (e) { return null; } };
const D = rd("data/data.json"); if (!D) { console.error("data/data.json 없음"); process.exit(2); }
const C = {...rd("config.json"), ...(process.env.GITHUB_ACTIONS ? {} : rd("config.local.json") || {})};
delete C.stop_price; delete C.stop_fx;
if (process.env.BUY_REAL) C.buy_real = process.env.BUY_REAL.split(",").map(Number);
if (process.env.STOP_REAL) C.stop_real = +process.env.STOP_REAL;
if (process.env.TARGET_REAL) C.target_real = +process.env.TARGET_REAL;
mod.set(D, C);
const m = mod.model(), sg = mod.buySignals(m), ss = mod.stopStatus(m), cb = mod.consistentBuy(m), r = x => Math.round(x * 100) / 100;
// 일정 알림용 시장 스냅샷(공개 시세만) · 로컬 설정(C.cal_zone, C.cal_watch)이 있으면 판정·점검판도 계산
const usd = D.fx_usd && D.fx_usd.latest ? D.fx_usd.latest[1] : null, ust = D.ust && D.ust.series && D.ust.series.at(-1), us = (D.infl && D.infl.us) || {};
const ip32 = (D.live || []).find(b => b.key === "Tesouro IPCA+|15/08/2032");
const snap = {ytm: m.ytm, price: m.price, fx: r(m.fx), usdkrw: usd ? r(m.fx / usd) : null, ust10: ust ? ust[4] : null, ust5: ust ? ust[2] : null, bei: us.bei ? us.bei.v : null, ipca32: ip32 ? ip32.rate : null, asof: D.generated};
let zone = null; const Z = C.cal_zone;   // {cuts:[a,b,c], names:[4개]} — 결선 후 체크리스트 구간(개인 계획, 로컬 전용)
if (Z && Z.cuts && Z.names) { let k = 0; while (k < Z.cuts.length && m.ytm >= Z.cuts[k]) k++; zone = Z.names[k]; }
let watch = null; const W = C.cal_watch;   // 점검판 경계(개인 계획, 로컬 전용)
if (W) watch = [["원/달러", snap.usdkrw, W.usdkrw_low != null && snap.usdkrw != null && snap.usdkrw < W.usdkrw_low, `< ${W.usdkrw_low}`], ["PF32 금리", m.ytm, (W.pf32_lo != null && m.ytm <= W.pf32_lo) || (W.pf32_hi != null && m.ytm >= W.pf32_hi), `≤${W.pf32_lo} / ≥${W.pf32_hi}`],
  ["헤알/원", snap.fx, W.brl_low != null && snap.fx < W.brl_low, `< ${W.brl_low}`], ["미 10년물", snap.ust10, W.ust10_hi != null && snap.ust10 != null && snap.ust10 >= W.ust10_hi, `≥ ${W.ust10_hi}`],
  ["미 기대인플레(손익분기)", snap.bei, W.bei_hi != null && snap.bei != null && snap.bei >= W.bei_hi, `≥ ${W.bei_hi}`]].map(([n, v, f, rule]) => ({n, v, flag: !!f, rule}));
console.log(JSON.stringify({
  asof: D.generated, price: m.price, ytm: m.ytm, fx: m.fx,
  buy: [sg.p1.on, sg.p2.on, sg.p3.on], line: [r(sg.p1.line), r(sg.p2.line)], cur: [r(sg.p1.cur), r(sg.p2.cur)],
  stop: ss.breach, worst: ss.worst.map(r), sr: ss.sr, reached: ss.reached, fxNear: ss.fxNear, target: sg.target.reached, targetLine: r(sg.target.line), align: cb.req.map(r), snap, zone, watch,
}));
