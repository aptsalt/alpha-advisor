/** Records a ~95s captioned walkthrough of ALPHA Advisor against the static demo
 *  (localhost:8215) — deterministic, no model latency. Output → ./video/*.webm,
 *  converted to alpha-advisor-demo.mp4 by the runner. */
import { chromium } from "playwright";
import { mkdirSync } from "fs";

const URL = "http://localhost:8215/index.html";
mkdirSync("./video", { recursive: true });

const browser = await chromium.launch({ channel: "chrome", headless: true });
const ctx = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  recordVideo: { dir: "./video", size: { width: 1280, height: 800 } },
});
const page = await ctx.newPage();

await page.addInitScript(() => {
  const ready = () => {
    if (document.getElementById("__cap")) return;
    const cap = document.createElement("div");
    cap.id = "__cap";
    Object.assign(cap.style, {
      position: "fixed", left: "50%", bottom: "84px", transform: "translateX(-50%)",
      maxWidth: "960px", padding: "13px 24px", background: "#062c22", color: "#eafffb",
      font: "600 17px/1.45 -apple-system,'Segoe UI',sans-serif", borderRadius: "13px",
      zIndex: 2147483647, boxShadow: "0 8px 30px rgba(0,0,0,.4)", opacity: "0",
      transition: "opacity .35s", pointerEvents: "none", textAlign: "center",
    });
    document.body.appendChild(cap);
    window.__cap = (t) => { cap.textContent = t; cap.style.opacity = t ? "1" : "0"; };
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready); else ready();
});
const cap = (t) => page.evaluate((x) => window.__cap?.(x), t).catch(() => {});
const sleep = (ms) => page.waitForTimeout(ms);

await page.goto(URL, { waitUntil: "networkidle" });
await sleep(700);

// 1 · intro
await cap("ALPHA Advisor — a multi-agent wealth-advisory copilot built on LangGraph.");
await sleep(3200);
await cap("An advisor asks for a portfolio review. Watch the agent work, live.");
await page.locator("#suggest button").first().click();
await sleep(800);

// 2 · streaming trace
await cap("Plan → guardrails → agentic RAG → tools → compliance → rebalance → draft, streamed live.");
await page.getByText("compliance", { exact: false }).first().waitFor({ timeout: 20000 }).catch(() => {});
await sleep(3500);

// 3 · compliance + rebalance
await page.locator(".rebal").waitFor({ timeout: 20000 });
await page.locator(".comp").scrollIntoViewIfNeeded();
await cap("Compliance catches a restricted holding and 78% issuer concentration — a multi-hop graph query.");
await sleep(4200);
await page.locator(".rebal").scrollIntoViewIfNeeded();
await cap("It then proposes specific, computed trades to bring the book back within policy.");
await sleep(4200);

// 4 · cited briefing
await page.getByText("approval required").waitFor({ timeout: 25000 });
await page.locator(".answer").first().scrollIntoViewIfNeeded();
await cap("A fully cited client briefing — every claim grounded in a source.");
await sleep(4000);

// 5 · eval + graph
const tbtns = page.locator(".tbtn");
await tbtns.filter({ hasText: "Evaluate" }).click();
await sleep(300);
await tbtns.filter({ hasText: "graph" }).click();
await sleep(700);
await page.locator(".eval").scrollIntoViewIfNeeded();
await cap("LLM-as-judge evaluation scores groundedness, suitability and citation coverage.");
await sleep(4200);
await page.locator("svg.kg").scrollIntoViewIfNeeded();
await cap("The client's knowledge graph: client → holding → issuer → sector. Restricted in red, over-limit in amber.");
await sleep(4600);

// 6 · approval (human-in-the-loop)
await page.locator(".gate").scrollIntoViewIfNeeded();
await cap("Nothing reaches the client until a human approves — a real LangGraph interrupt / resume.");
await sleep(1800);
await page.locator(".allow").click();
await page.locator(".decided").waitFor({ timeout: 10000 });
await sleep(800);
await cap("Approved — and the run's tamper-evident audit chain is verified.");
await sleep(3200);

// 7 · portfolio dashboard
await page.locator("#tab-portfolio").click();
await sleep(900);
await cap("A book-wide compliance scan — the flagged-for-review queue. Click any client to run a full review.");
await sleep(4600);

// 8 · end card
await cap("github.com/aptsalt/alpha-advisor  ·  LangGraph · Graph RAG · governance · HITL · audit");
await sleep(4200);
await cap("");
await sleep(500);

const vp = await page.video().path();
await ctx.close();
await browser.close();
console.log("VIDEO:" + vp);
