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

  $("#run-demo").addEventListener("click", runDemo);
  $$("[data-run-demo]").forEach((button) => button.addEventListener("click", () => {
    closeMenu();
    $("#demo").scrollIntoView({ behavior: motionPaused || reducedMotion.matches ? "instant" : "smooth", block: "start" });
    runDemo();
  }));
  $("#reveal-tamper").addEventListener("click", () => {
    if (currentResult && state === State.VALID_RESULT) transition(State.TAMPER_REVEALED, currentResult);
  });
  setupExperience();
  render();
})();
