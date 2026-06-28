// OTP autofill — runs on every page, but only acts when THIS page is actually
// showing a verification-code field AND the tab is focused/visible. That local
// presence is the core defense: a remote attacker's login challenge renders on
// THEIR browser, not yours, so this never arms for them.

(() => {
  "use strict";

  const SIGNAL = /(^|[^a-z])(otp|2fa|mfa|one[\s_-]?time|verif|passcode|sign[\s_-]?in\s*code|login\s*code|security\s*code|auth(?:entication)?\s*code|\bcode\b|\btoken\b|\bpin\b)([^a-z]|$)/i;
  const NEGATIVE = /(coupon|promo|discount|gift|voucher|search|query|zip|postal|postcode|address|phone|tel|card|cvv|cvc|expir|amount|quantity|username|email|user)/i;

  const POLL_MS = 3000;
  const MAX_MS = 90000;       // give up (and TB time to sync) after 90s
  const SUBMIT_RE = /verify|submit|continue|confirm|log\s?in|sign\s?in|next|proceed/i;

  let armTs = 0;              // ms; set when an OTP target is first seen
  let polling = false;
  let stopped = false;
  const filled = new Set();   // codes already used on this page

  // ---- visibility / focus gate ---------------------------------------------
  const userPresent = () =>
    document.visibilityState === "visible" && document.hasFocus();

  // ---- target detection -----------------------------------------------------
  function visible(el) {
    if (!el || el.disabled || el.readOnly || el.type === "hidden") return false;
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    const s = getComputedStyle(el);
    return s.visibility !== "hidden" && s.display !== "none";
  }

  function attrs(el) {
    return [el.name, el.id, el.placeholder, el.getAttribute("aria-label"),
            el.getAttribute("autocomplete")].filter(Boolean).join(" ");
  }

  function isOtpSingle(el) {
    if (el.tagName !== "INPUT") return false;
    const t = (el.type || "text").toLowerCase();
    if (!["text", "tel", "number", ""].includes(t)) return false;
    const a = attrs(el);
    if (NEGATIVE.test(a)) return false;
    if (el.getAttribute("autocomplete") === "one-time-code") return true;
    return SIGNAL.test(a);
  }

  // A row of >=4 single-char boxes = a split OTP widget.
  function findSplit() {
    const ones = [...document.querySelectorAll("input")].filter(
      (el) => visible(el) &&
        (el.maxLength === 1 ||
         (el.getAttribute("inputmode") === "numeric" && el.maxLength === 1)) &&
        !NEGATIVE.test(attrs(el)));
    if (ones.length >= 4 && ones.length <= 8) return ones;
    return null;
  }

  function findTarget() {
    const split = findSplit();
    if (split) return { kind: "split", els: split };
    const el = [...document.querySelectorAll("input")].find(
      (e) => visible(e) && isOtpSingle(e));
    if (el) return { kind: "single", el };
    return null;
  }

  // ---- fill helpers (React-safe) -------------------------------------------
  function setValue(el, val) {
    const proto = el instanceof window.HTMLTextAreaElement
      ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    setter.call(el, val);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function fillSingle(el, code) {
    el.focus();
    setValue(el, code);
  }

  function fillSplit(els, code) {
    const chars = code.split("");
    els.forEach((el, i) => {
      el.focus();
      setValue(el, chars[i] || "");
      el.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, key: chars[i] || "" }));
    });
    (els[els.length - 1] || els[0]).focus();
  }

  // ---- submit ---------------------------------------------------------------
  function submit(anchor) {
    const form = anchor.closest("form");
    const scope = form || document;
    const btns = [...scope.querySelectorAll(
      "button, input[type=submit], [role=button]")].filter((b) => {
        if (b.disabled) return false;
        const txt = (b.innerText || b.value || b.getAttribute("aria-label") || "");
        return SUBMIT_RE.test(txt);
      });
    if (btns.length) { btns[0].click(); return true; }
    if (form) {
      if (form.requestSubmit) form.requestSubmit();
      else form.submit();
      return true;
    }
    return false;
  }

  // ---- main loop ------------------------------------------------------------
  async function tick() {
    if (stopped) return;
    const target = findTarget();
    if (!target) return;
    if (!userPresent()) return;            // focus/visibility gate
    if (!armTs) armTs = Date.now();        // record when the OTP page appeared

    let resp;
    try {
      resp = await browser.runtime.sendMessage({ type: "queryCode", armTs });
    } catch (e) {
      return;
    }
    if (!resp || !resp.code || filled.has(resp.code)) return;
    if (!userPresent()) return;            // re-check right before acting

    filled.add(resp.code);
    if (target.kind === "split") fillSplit(target.els, resp.code);
    else fillSingle(target.el, resp.code);
    setTimeout(() => { if (userPresent()) submit(target.kind === "split" ? target.els[0] : target.el); }, 250);
    stopped = true;                         // one fill per page load
  }

  function startPolling() {
    if (polling) return;
    polling = true;
    const t0 = Date.now();
    const iv = setInterval(() => {
      if (stopped || Date.now() - t0 > MAX_MS) { clearInterval(iv); return; }
      tick();
    }, POLL_MS);
    tick(); // immediate first try
  }

  // Kick off once an OTP field shows up (SPA-friendly via MutationObserver).
  function maybeStart() {
    if (!stopped && findTarget()) startPolling();
  }
  maybeStart();
  const mo = new MutationObserver(() => maybeStart());
  mo.observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener("visibilitychange", maybeStart);
  window.addEventListener("focus", maybeStart);
})();
