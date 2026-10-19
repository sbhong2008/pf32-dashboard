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
mod.set(D, C);
const m = mod.model(), sg = mod.buySignals(m), ss = mod.stopStatus(m), cb = mod.consistentBuy(m), r = x => Math.round(x * 100) / 100;
console.log(JSON.stringify({
  asof: D.generated, price: m.price, ytm: m.ytm, fx: m.fx,
  buy: [sg.p1.on, sg.p2.on, sg.p3.on], line: [r(sg.p1.line), r(sg.p2.line)], cur: [r(sg.p1.cur), r(sg.p2.cur)],
  stop: ss.breach, worst: ss.worst.map(r), sr: ss.sr, reached: ss.reached, fxNear: ss.fxNear, align: cb.req.map(r),
}));
