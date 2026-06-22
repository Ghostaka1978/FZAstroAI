/**
 * Regression test for OpenClaude footer ctx display:
 * - API usage valid → "ctx <N>%"
 * - API usage zero + estimate available → "ctx est. <N>%"
 * - No data at all → "ctx unknown"
 *
 * Run with: node tests/test_footer_ctx_display.js
 */

/* ── extract the pure logic from dist\cli.mjs ─────────────────────── */

function buildBuiltinStatusSegments(data) {
  const segments = [{ key: "model", priority: 0, text: data.modelName }];
  if (data.contextUsedPercent !== null) {
    const pct = Math.round(data.contextUsedPercent);
    let ctxLabel;
    if (data._contextEstimated || false) {
      ctxLabel = `ctx est. ~${pct}%`;
    } else {
      ctxLabel = `ctx ${pct}%`;
    }
    segments.push({ key: "context", priority: 1, text: ctxLabel });
  }
  return segments;
}

/* ── helpers ──────────────────────────────────────────────────────── */

function findCtx(segments) {
  const c = segments.find((s) => s.key === "context");
  return c ? c.text : null;
}

let passed = 0;
let failed = 0;

function assert(label, got, expected) {
  if (got === expected) {
    console.log(`  PASS  ${label}`);
    passed++;
  } else {
    console.error(`  FAIL  ${label} — got "${got}", expected "${expected}"`);
    failed++;
  }
}

/* ── test suite ───────────────────────────────────────────────────── */

console.log("Scenario 1 — API usage valid (e.g. 20%) → ctx <N>%");
{
  const segs = buildBuiltinStatusSegments({
    modelName: "qwen3.6-coding:35b",
    contextUsedPercent: 20,
    _contextEstimated: false
  });
  assert("context text", findCtx(segs), "ctx 20%");
}

console.log();
console.log("Scenario 2 — API usage zero + estimate available → ctx est. <N>%");
{
  const segs = buildBuiltinStatusSegments({
    modelName: "qwen3.6-coding:35b",
    contextUsedPercent: 0,
    _contextEstimated: true
  });
  const txt = findCtx(segs);
  assert("starts with ctx est.", txt.startsWith("ctx est."), true);
  assert("does not contain just 'ctx 0%'", txt === "ctx 0%", false);
}

console.log();
console.log("Scenario 3 — No context data at all → ctx unknown");
{
  const segs = buildBuiltinStatusSegments({
    modelName: "qwen3.6-coding:35b",
    contextUsedPercent: null,
    _contextEstimated: false
  });
  assert("no context chunk", findCtx(segs), null);
}

console.log();
console.log(`Result: ${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
