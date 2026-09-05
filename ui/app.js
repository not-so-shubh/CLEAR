(() => {
  "use strict";

  const State = Object.freeze({
    IDLE: "IDLE",
    RUNNING: "RUNNING",
    VALID_RESULT: "VALID_RESULT",
    TAMPER_REVEALED: "TAMPER_REVEALED",
    ERROR: "ERROR",
  });

  const transitions = Object.freeze({
    IDLE: [State.RUNNING],
    RUNNING: [State.VALID_RESULT, State.ERROR],
    VALID_RESULT: [State.RUNNING, State.TAMPER_REVEALED],
    TAMPER_REVEALED: [State.RUNNING],
    ERROR: [State.RUNNING],
  });

  let state = State.IDLE;
  let currentResult = null;
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let motionPaused = reducedMotion.matches;

  function updateMotion() {
    const off = motionPaused || reducedMotion.matches;
    document.documentElement.dataset.motion = off ? "off" : "on";
    $(".motion-toggle").setAttribute("aria-pressed", String(off));
    $(".motion-toggle").disabled = reducedMotion.matches;
    setText("[data-motion-label]", reducedMotion.matches ? "Reduced motion" : off ? "Resume motion" : "Pause motion");
    setText("[data-motion-icon]", off ? "▷" : "Ⅱ");
  }

  function closeMenu() {
    $(".menu-toggle").setAttribute("aria-expanded", "false");
    $("#primary-nav").classList.remove("is-open");
  }

  function setupExperience() {
    updateMotion();
    reducedMotion.addEventListener("change", () => {
      motionPaused = reducedMotion.matches;
      updateMotion();
    });
    $(".motion-toggle").addEventListener("click", () => {
      motionPaused = !motionPaused;
      updateMotion();
    });

    // Real text is retained for assistive technology; the animated letters are decorative.
    $$("[data-split]").forEach((line) => {
      const text = line.textContent;
      line.setAttribute("aria-label", text);
      const letters = document.createDocumentFragment();
      Array.from(text).forEach((character, index) => {
        const letter = document.createElement("span");
        letter.className = "split-char";
        letter.setAttribute("aria-hidden", "true");
        letter.style.setProperty("--char-index", String(index));
        letter.textContent = character === " " ? "\u00a0" : character;
        letters.append(letter);
      });
      line.replaceChildren(letters);
    });

    if ("IntersectionObserver" in window) {
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        });
      }, { threshold: 0.06, rootMargin: "0px 0px -20px 0px" });
      $$("[data-reveal]").forEach((element) => observer.observe(element));
      document.documentElement.classList.add("reveal-ready");
    }

    // Native scrolling, with one paint per scroll frame. No scroll interception or idle loop.
    let scrollFrame = null;
    const updateScroll = () => {
      const root = document.documentElement;
      const distance = Math.max(0, root.scrollHeight - window.innerHeight);
      const progress = distance ? Math.min(1, Math.max(0, window.scrollY / distance)) : 0;
      $(".reading-progress").style.transform = `scaleX(${progress})`;
      document.body.classList.toggle("is-scrolled", window.scrollY > 24);
      scrollFrame = null;
    };
    const scheduleScroll = () => {
      if (scrollFrame === null) scrollFrame = window.requestAnimationFrame(updateScroll);
    };
    window.addEventListener("scroll", scheduleScroll, { passive: true });
    window.addEventListener("resize", scheduleScroll, { passive: true });
    $$("details").forEach((detail) => detail.addEventListener("toggle", scheduleScroll));
    updateScroll();

    $(".menu-toggle").addEventListener("click", () => {
      const open = $(".menu-toggle").getAttribute("aria-expanded") !== "true";
      $(".menu-toggle").setAttribute("aria-expanded", String(open));
      $("#primary-nav").classList.toggle("is-open", open);
    });
    $$("#primary-nav a").forEach((link) => link.addEventListener("click", closeMenu));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && $(".menu-toggle").getAttribute("aria-expanded") === "true") {
        closeMenu();
        $(".menu-toggle").focus();
      }
    });
    document.addEventListener("click", (event) => {
      if (!$(".site-header").contains(event.target)) closeMenu();
    });
  }

  function setText(selector, value) {
    const element = $(selector);
    if (element) element.textContent = String(value);
  }

  function formatRupees(paise) {
    const rupees = Math.floor(paise / 100);
    const remainder = String(paise % 100).padStart(2, "0");
    return `₹${rupees.toLocaleString("en-IN")}.${remainder}`;
  }

  function assertPresentation(payload) {
    const required = ["current_run", "intent", "policy", "offers", "allocation", "certificate", "verification", "governor", "valid_provider_branch", "tamper_branch"];
    if (!payload || payload.presentation_version !== "clear-authority-presentation-v1" || required.some((key) => !(key in payload))) throw new Error("Invalid presentation response");
    if (payload.current_run.ai_invoked !== false || payload.current_run.razorpay_contacted !== false) throw new Error("Unsafe runtime claims");
    if (!Array.isArray(payload.offers) || payload.offers.length < 1) throw new Error("Missing offers");
    if (!Array.isArray(payload.allocation.winner_merchant_ids) || payload.allocation.winner_merchant_ids.length < 1) throw new Error("Missing winners");
    if (payload.verification.verified !== true || payload.verification.state !== "VERIFIED") throw new Error("Certificate was not verified");
    if (payload.valid_provider_branch.first_invocation.post_count !== 1 || payload.valid_provider_branch.first_invocation.get_count !== 0) throw new Error("Invalid first provider proof");
    if (payload.valid_provider_branch.cumulative_after_second.post_count !== 1 || payload.valid_provider_branch.cumulative_after_second.get_count !== 1) throw new Error("Invalid cumulative provider proof");
    if (payload.tamper_branch.failure_code !== "CERTIFICATE_NOT_VERIFIED" || payload.tamper_branch.provider_counters.post_count !== 0 || payload.tamper_branch.provider_counters.get_count !== 0) throw new Error("Invalid tamper proof");
    return payload;
  }

  function transition(next, result = null) {
    if (!transitions[state].includes(next)) throw new Error(`Invalid UI transition: ${state} -> ${next}`);
    state = next;
    currentResult = result;
    render();
  }

  function clearRuntimeEvidence() {
    ["requested-quantity", "max-winners", "allocation-requested", "allocation-fulfilled", "winner-count", "allocation-total", "allocation-total-paise", "certificate-id", "provider-order-id"].forEach((field) => setText(`[data-field="${field}"]`, "—"));
    const offerPlaceholder = document.createElement("p");
    offerPlaceholder.className = "muted";
    offerPlaceholder.textContent = "No current-run evidence.";
    $("#offer-list").replaceChildren(offerPlaceholder);
    const winnerPlaceholder = document.createElement("span");
    winnerPlaceholder.className = "muted";
    winnerPlaceholder.textContent = "No current-run evidence.";
    $("#winner-ids").replaceChildren(winnerPlaceholder);
    ["provider-first-resolution", "provider-second-resolution"].forEach((field) => setText(`[data-field="${field}"]`, "—"));
    ["provider-first-post", "provider-first-get", "provider-cumulative-post", "provider-cumulative-get"].forEach((field) => setText(`[data-field="${field}"]`, "—"));
    setText('[data-field="policy-status"]', "AWAITING RUN");
    setText('[data-field="certificate-state"]', "AWAITING RUN");
    setText('[data-field="verification-state"]', "AWAITING RUN");
    setText('[data-field="verification-copy"]', "Awaiting local verification.");
    setText('[data-field="governor-state"]', "AWAITING RUN");
    setText('[data-field="governor-plan"]', "ExecutionPlanV1 / AWAITING RUN");
    setText('[data-field="resolved-chain"]', "AWAITING PROOF  →  MONEY GOVERNOR  →  AWAITING RESERVATION");
    setText('[data-field="provider-cumulative-state"]', "AWAITING RUN");
    ["tamper-failure-code", "tamper-reservation", "tamper-idempotency", "tamper-post", "tamper-get"].forEach((field) => setText(`[data-field="${field}"]`, "—"));
    setText('[data-field="tamper-altered-claim"]', "Awaiting reveal.");
  }

  function renderResult(data) {
    setText('[data-field="requested-quantity"]', data.intent.requested_quantity);
    setText('[data-field="max-winners"]', data.intent.max_winners);
    setText('[data-field="allocation-requested"]', data.allocation.requested_quantity);
    setText('[data-field="allocation-fulfilled"]', data.allocation.fulfilled_quantity);
    setText('[data-field="winner-count"]', data.allocation.winner_count);
    setText('[data-field="allocation-total"]', formatRupees(data.allocation.total_payment_paise));
    setText('[data-field="allocation-total-paise"]', `${data.allocation.total_payment_paise} PAISE`);
    setText('[data-field="certificate-identity"]', data.certificate.identity);
    setText('[data-field="certificate-id"]', data.certificate.certificate_id);
    setText('[data-field="certificate-state"]', data.certificate.state);
    setText('[data-field="policy-status"]', data.policy.status);
    setText('[data-field="verification-state"]', data.verification.state);
    setText('[data-field="verification-copy"]', data.verification.copy);
    setText('[data-field="governor-state"]', data.governor.state);
    setText('[data-field="governor-plan"]', `${data.governor.execution_plan_identity} / ${data.governor.execution_plan_state}`);
    setText('[data-field="resolved-chain"]', "VERIFIED CERTIFICATE  →  MONEY GOVERNOR  →  EXECUTION RESERVED");
    setText('[data-field="provider-order-id"]', data.valid_provider_branch.controlled_order_id);
    setText('[data-field="provider-first-resolution"]', data.valid_provider_branch.first_invocation.resolution);
    setText('[data-field="provider-first-post"]', data.valid_provider_branch.first_invocation.post_count);
    setText('[data-field="provider-first-get"]', data.valid_provider_branch.first_invocation.get_count);
    setText('[data-field="provider-second-resolution"]', data.valid_provider_branch.second_invocation.resolution);
    setText('[data-field="provider-cumulative-post"]', data.valid_provider_branch.cumulative_after_second.post_count);
    setText('[data-field="provider-cumulative-get"]', data.valid_provider_branch.cumulative_after_second.get_count);
    setText('[data-field="provider-cumulative-state"]', "CUMULATIVE AFTER SECOND CALL");
    // Render provider facts as text, never as interpolated HTML.
    $("#offer-list").replaceChildren(...data.offers.map((offer) => {
      const row = document.createElement("div");
      row.className = "offer-row";
      const title = document.createElement("strong");
      title.textContent = "MerchantOfferV2";
      const details = document.createElement("span");
      details.className = "offer-details";
      [`merchant ${offer.merchant_id}`, `offer ${offer.offer_id}`, `capacity ${offer.capacity} / ${offer.unit_price_paise} paise per unit`].forEach((line, index) => {
        if (index) details.append(document.createElement("br"));
        details.append(document.createTextNode(line));
      });
      const status = document.createElement("span");
      status.className = "offer-auth";
      status.textContent = "AUTHENTICATED";
      row.append(title, details, status);
      return row;
    }));
    $("#winner-ids").replaceChildren(...data.allocation.winner_merchant_ids.map((id) => {
      const item = document.createElement("span");
      item.className = "id-item";
      item.textContent = id;
      return item;
    }));
  }

  function renderTamper(data) {
    setText('[data-field="tamper-failure-code"]', data.tamper_branch.failure_code);
    setText('[data-field="tamper-altered-claim"]', data.tamper_branch.altered_claim);
    setText('[data-field="tamper-reservation"]', data.tamper_branch.execution_reservation);
    setText('[data-field="tamper-idempotency"]', data.tamper_branch.idempotency_record);
    setText('[data-field="tamper-post"]', data.tamper_branch.provider_counters.post_count);
    setText('[data-field="tamper-get"]', data.tamper_branch.provider_counters.get_count);
  }

  function render() {
    document.body.dataset.state = state;
    const labels = { IDLE: "READY TO RUN", RUNNING: "RUNNING", VALID_RESULT: "VERIFIED", TAMPER_REVEALED: "TAMPER CHECKED", ERROR: "UNAVAILABLE" };
    setText("[data-state-label]", labels[state]);
    const runButton = $("#run-demo");
    const revealButton = $("#reveal-tamper");
    const tamperFlow = $("#tamper-flow");
    const tamperCounters = $("#tamper-counters");
    runButton.disabled = state === State.RUNNING;
    $$('[data-run-demo]').forEach((button) => { button.disabled = state === State.RUNNING; });
    const complete = state === State.VALID_RESULT || state === State.TAMPER_REVEALED;
    setText("[data-run-label]", state === State.RUNNING ? "Verifying the proof…" : complete ? "Run the demo again" : state === State.ERROR ? "Retry the demo" : "Run the authority demo");
    revealButton.disabled = state !== State.VALID_RESULT;
    revealButton.setAttribute("aria-expanded", String(state === State.TAMPER_REVEALED));
    $(".proof-console").setAttribute("aria-busy", String(state === State.RUNNING));
    $(".results-link").hidden = !complete;
    tamperFlow.hidden = state !== State.TAMPER_REVEALED;
    tamperCounters.hidden = state !== State.TAMPER_REVEALED;
    if (state === State.IDLE) {
      setText("#run-status", "Local. Deterministic. No credentials needed.");
      setText("[data-console-status]", "Waiting for a verified certificate");
      setText("[data-console-icon]", "○");
    }
    if (state === State.RUNNING) {
      setText("#run-status", "Running the allocator, verifier, and Money Governor…");
      setText("[data-console-status]", "Running the local authority demo…");
      setText("[data-console-icon]", "↻");
    }
    if (complete) {
      setText("#run-status", state === State.TAMPER_REVEALED ? "Tampered claim rejected. No provider action." : "Certificate verified. Explore the evidence below.");
      setText("[data-console-status]", `${currentResult.allocation.fulfilled_quantity} units · ${currentResult.allocation.winner_count} winners · ${formatRupees(currentResult.allocation.total_payment_paise)}`);
      setText("[data-console-icon]", "✓");
    }
    if (state === State.ERROR) {
      setText("#run-status", "Demo unavailable. Check that the Python server is running, then retry.");
      setText("[data-console-status]", "No verified result. Money authority stays closed.");
      setText("[data-console-icon]", "×");
    }
    setText("#tamper-note", state === State.TAMPER_REVEALED ? "Evidence from the same run. No additional provider request." : complete ? "Ready to inspect. Reveal the altered claim from this same run." : "Run the demo first. This reveals the tamper evidence from that same run.");
  }

  async function runDemo() {
    if (state === State.RUNNING) return;
    transition(State.RUNNING);
    clearRuntimeEvidence();
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch("/api/authority-demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}", signal: controller.signal });
      if (!response.ok) throw new Error(`Demo request failed: ${response.status}`);
      const data = assertPresentation(await response.json());
      renderResult(data);
      renderTamper(data);
      transition(State.VALID_RESULT, data);
    } catch (error) {
      currentResult = null;
      clearRuntimeEvidence();
      transition(State.ERROR);
    } finally {
      window.clearTimeout(timeout);
    }
  }

  const LiveState = Object.freeze({
    IDLE: "IDLE",
    RUNNING: "RUNNING",
    SUCCESS: "SUCCESS",
    FAILED: "FAILED",
    UNAVAILABLE: "UNAVAILABLE",
  });
  const liveFailureHeadings = Object.freeze({
    LIVE_TEST_MODE_UNAVAILABLE: "TEST MODE UNAVAILABLE",
    LIVE_EVIDENCE_BUSY: "CHECK ALREADY RUNNING",
    PROVIDER_AUTHENTICATION_FAILURE: "PROVIDER AUTHENTICATION FAILED",
    PROVIDER_TIMEOUT_OR_NETWORK_FAILURE: "PROVIDER REQUEST DID NOT COMPLETE",
    INVALID_PROVIDER_RESPONSE: "INVALID PROVIDER RESPONSE",
    AUTHORITY_VERIFICATION_FAILURE: "AUTHORITY NOT VERIFIED",
    MONEY_GOVERNOR_REFUSAL: "MONEY GOVERNOR REFUSED",
    PROVIDER_ORDER_MISMATCH: "PROVIDER ORDER MISMATCH",
    PROVIDER_REQUEST_FAILURE: "PROVIDER REQUEST FAILED",
    LIVE_EVIDENCE_INTERNAL_FAILURE: "CHECK FAILED CLOSED",
  });
  const liveActionLabels = Object.freeze({
    IDLE: "NOT RUN · USER INITIATED",
    RUNNING: "RUNNING · USER INITIATED",
    SUCCESS: "CURRENT RUN · VALIDATED",
    FAILED: "CURRENT RUN · NOT VALIDATED",
    UNAVAILABLE: "CURRENT RUN · NOT VALIDATED",
  });
  let liveState = LiveState.IDLE;

  function clearLiveEvidence() {
    const result = $("#live-evidence-result");
    result.hidden = true;
    result.removeAttribute("data-result");
    $$('[data-live-success]').forEach((element) => { element.hidden = true; });
    setText('[data-live-field="result-heading"]', "CURRENT-RUN RESULT");
    setText('[data-live-field="result-message"]', "");
    setText('[data-live-field="error-code"]', "");
    $('[data-live-field="error-code"]').hidden = true;
    ["authority", "governor", "execution-plan", "first-resolution", "second-resolution", "retrieval", "provider-order-id", "same-order"].forEach((field) => setText(`[data-live-field="${field}"]`, "—"));
  }

  function assertLivePresentation(payload) {
    if (!payload || payload.presentation_version !== "clear-razorpay-test-order-evidence-v1" || payload.mode !== "RAZORPAY TEST MODE" || payload.current_run !== true) throw new Error("Invalid live evidence response");
    if (![LiveState.SUCCESS, LiveState.FAILED, LiveState.UNAVAILABLE].includes(payload.result)) throw new Error("Invalid live evidence state");
    if (payload.result !== LiveState.SUCCESS) {
      if (!(payload.code in liveFailureHeadings) || typeof payload.message !== "string" || !payload.message) throw new Error("Invalid live failure response");
      if (typeof payload.authority_verified !== "boolean" || typeof payload.execution_reserved !== "boolean" || typeof payload.provider_contacted !== "boolean") throw new Error("Invalid live failure facts");
      return payload;
    }
    const first = payload.first_invocation;
    const second = payload.second_identical_invocation;
    const orderPattern = /^order_[A-Za-z0-9]{1,128}$/;
    if (payload.authority_verified !== true || payload.governor_state !== "EXECUTION RESERVED" || payload.execution_reserved !== true || payload.execution_plan !== "ExecutionPlanV1" || payload.provider_contacted !== true) throw new Error("Invalid live authority facts");
    if (!first || first.resolution !== "CREATED" || !orderPattern.test(first.provider_order_id)) throw new Error("Invalid first invocation facts");
    if (!second || second.resolution !== "EXISTING" || second.retrieval !== "PROVIDER-BACKED" || second.provider_order_id !== first.provider_order_id) throw new Error("Invalid second invocation facts");
    if (payload.same_provider_order !== true || payload.provider_observation !== "CURRENT-RUN PROVIDER OBSERVATION") throw new Error("Invalid provider identity proof");
    return payload;
  }

  function renderLiveResult(data) {
    const result = $("#live-evidence-result");
    result.hidden = false;
    result.dataset.result = data.result;
    if (data.result === LiveState.SUCCESS) {
      $$('[data-live-success]').forEach((element) => { element.hidden = false; });
      setText('[data-live-field="result-heading"]', "ORDER PATH VALIDATED");
      setText('[data-live-field="result-message"]', "Validated provider facts from this explicit Test Mode request.");
      setText('[data-live-field="authority"]', "VERIFIED");
      setText('[data-live-field="governor"]', data.governor_state);
      setText('[data-live-field="execution-plan"]', `${data.execution_plan} / PRODUCED`);
      setText('[data-live-field="first-resolution"]', data.first_invocation.resolution);
      setText('[data-live-field="second-resolution"]', data.second_identical_invocation.resolution);
      setText('[data-live-field="retrieval"]', `${data.second_identical_invocation.retrieval} RETRIEVAL`);
      setText('[data-live-field="provider-order-id"]', data.first_invocation.provider_order_id);
      setText('[data-live-field="same-order"]', "SAME ORDER IDENTITY CONFIRMED");
      return;
    }
    setText('[data-live-field="result-heading"]', liveFailureHeadings[data.code]);
    setText('[data-live-field="error-code"]', data.code);
    $('[data-live-field="error-code"]').hidden = false;
    setText('[data-live-field="result-message"]', data.message);
  }

  function renderLiveState() {
    const button = $("#run-live-evidence");
    button.disabled = liveState === LiveState.RUNNING;
    button.setAttribute("aria-busy", String(liveState === LiveState.RUNNING));
    setText(".live-not-run", liveActionLabels[liveState]);
    setText("[data-live-run-label]", liveState === LiveState.RUNNING ? "Checking Razorpay Test Mode order path…" : liveState === LiveState.IDLE ? "Run Razorpay Test Mode order check" : "Run a new Test Mode order check");
    if (liveState === LiveState.IDLE) setText("#live-evidence-status", "No current-run provider claim. Requires server-side Test Mode credentials.");
    if (liveState === LiveState.RUNNING) setText("#live-evidence-status", "Running the verified authority and Test Mode order path. No payment is being processed.");
    if (liveState === LiveState.SUCCESS) setText("#live-evidence-status", "Current-run Test Mode order facts validated. This is not payment or real-money evidence.");
    if (liveState === LiveState.FAILED) setText("#live-evidence-status", "The current check failed closed. No successful live claim is retained.");
    if (liveState === LiveState.UNAVAILABLE) setText("#live-evidence-status", "The optional current-run Test Mode check is unavailable. The deterministic demo is unaffected.");
  }

  async function runLiveEvidence() {
    if (liveState === LiveState.RUNNING) return;
    clearLiveEvidence();
    liveState = LiveState.RUNNING;
    renderLiveState();
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch("/api/razorpay-test-order-evidence", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}", signal: controller.signal });
      const data = assertLivePresentation(await response.json());
      if (data.result === LiveState.SUCCESS && !response.ok) throw new Error("Invalid successful response status");
      liveState = data.result;
      renderLiveResult(data);
    } catch (error) {
      liveState = LiveState.UNAVAILABLE;
      renderLiveResult({
        result: LiveState.UNAVAILABLE,
        code: "LIVE_EVIDENCE_INTERNAL_FAILURE",
        message: "The current-run Test Mode check did not return a valid presentation response.",
      });
    } finally {
      window.clearTimeout(timeout);
      renderLiveState();
    }
  }

  $("#run-demo").addEventListener("click", runDemo);
  $$("[data-run-demo]").forEach((button) => button.addEventListener("click", () => {
    closeMenu();
    $("#demo").scrollIntoView({ behavior: motionPaused || reducedMotion.matches ? "instant" : "smooth", block: "start" });
    runDemo();
  }));
  $("#reveal-tamper").addEventListener("click", () => {
    if (currentResult && state === State.VALID_RESULT) transition(State.TAMPER_REVEALED, currentResult);
  });
  $("#run-live-evidence").addEventListener("click", runLiveEvidence);
  setupExperience();
  render();
  renderLiveState();
})();
