(() => {
  "use strict";

  const viewButtons = [...document.querySelectorAll("[data-view-target]")];
  const viewPanels = [...document.querySelectorAll("[data-app-view]")];
  const evidenceNav = document.querySelector("[data-evidence-nav]");
  const menuToggle = document.querySelector(".menu-toggle");
  const skipLink = document.querySelector(".skip-link");
  const wordmark = document.querySelector(".wordmark");
  const form = document.querySelector("#buyer-draft-form");

  if (!(form instanceof HTMLFormElement)) return;

  const merchantList = document.querySelector("#buyer-merchant-list");
  const buyerText = document.querySelector("#buyer-text");
  const deadline = document.querySelector("#buyer-deadline");
  const interpretButton = document.querySelector("#interpret-request");
  const interpretLabel = document.querySelector("[data-interpret-label]");
  const newDraftButton = document.querySelector("#new-buyer-draft");
  const actionStatus = document.querySelector("#buyer-action-status");
  const interpretationPanel = document.querySelector("#buyer-interpretation");
  const successPanel = document.querySelector("[data-buyer-interpretation-success]");
  const freezeButton = document.querySelector("#freeze-buyer-policy");
  const frozenPanel = document.querySelector("#buyer-frozen");
  const errorCode = document.querySelector('[data-buyer-field="error-code"]');
  const message = document.querySelector('[data-buyer-field="message"]');
  const validationState = document.querySelector('[data-buyer-field="validation-state"]');
  const diagnosticCode = document.querySelector('[data-buyer-field="diagnostic-code"]');
  const candidateDiagnostic = document.querySelector('[data-buyer-field="candidate-diagnostic"]');
  const merchantSelect = document.querySelector("#merchant-select");
  const merchantProfile = document.querySelector("#merchant-profile");
  const merchantAttributeList = document.querySelector("#merchant-attribute-list");
  const merchantMarketList = document.querySelector("#merchant-market-list");
  const merchantMarketReview = document.querySelector("#merchant-market-review");
  const requestMerchantProposal = document.querySelector("#request-merchant-proposal");
  const submitMerchantProposal = document.querySelector("#submit-merchant-proposal");
  const merchantActionStatus = document.querySelector("#merchant-action-status");
  const clearingMarketList = document.querySelector("#clearing-market-list");
  const refreshClearingMarkets = document.querySelector("#refresh-clearing-markets");
  const clearingSnapshot = document.querySelector("#clearing-snapshot");
  const clearingOfferList = document.querySelector("#clearing-offer-list");
  const clearingClosePanel = document.querySelector("#clearing-close-panel");
  const closeClearingMarket = document.querySelector("#close-clearing-market");
  const clearingResult = document.querySelector("#clearing-result");
  const clearingWinnerList = document.querySelector("#clearing-winner-list");
  const clearingActionStatus = document.querySelector("#clearing-action-status");
  const runtimeAuthoritySequence = document.querySelector("#runtime-authority-sequence");
  const runtimeCertificateLines = document.querySelector("#runtime-proof-lines");
  const runtimeTransferLines = document.querySelector("#runtime-transfer-lines");
  const runtimeTamperButton = document.querySelector("#test-runtime-tamper");
  const runtimeTamperResult = document.querySelector("#runtime-tamper-result");
  const runtimeAuthorizeButton = document.querySelector("#authorize-runtime-execution");
  const runtimeAuthorityStatus = document.querySelector("#runtime-authority-status");
  const runtimeExecutionPlan = document.querySelector("#runtime-execution-plan");
  const runtimeRazorpayButton = document.querySelector("#create-runtime-razorpay-order");
  const runtimeRazorpayStatus = document.querySelector("#runtime-razorpay-status");
  const runtimeRazorpayResult = document.querySelector("#runtime-razorpay-result");

  let currentMarketId = null;
  let running = false;
  let currentMerchantId = null;
  let currentMerchantMarketId = null;
  let currentMerchantInbox = null;
  let merchantRunning = false;
  let merchantInboxRequest = 0;
  let currentClearingMarketId = null;
  let currentClearingState = null;
  let clearingRunning = false;
  let clearingSnapshotRequest = 0;
  let authorityRunning = false;
  let authoritySnapshotRequest = 0;
  let tamperRequestGeneration = 0;
  let authorizeRequestGeneration = 0;
  let razorpayRequestGeneration = 0;
  let razorpayRunning = false;
  let currentRuntimeExecutionId = null;
  let currentRuntimeOrderAmount = null;
  let reconcileActiveWorkspace = () => {};

  const setText = (selector, value) => {
    const target = document.querySelector(selector);
    if (target) target.textContent = String(value);
  };

  const formatInrFromPaise = (paise) => {
    if (!Number.isSafeInteger(paise)) return "—";
    const absolutePaise = Math.abs(paise);
    const rupees = Math.floor(absolutePaise / 100).toLocaleString("en-IN");
    const remainder = String(absolutePaise % 100).padStart(2, "0");
    return `${paise < 0 ? "-" : ""}₹${rupees}.${remainder}`;
  };

  const viewFromHash = () => {
    if (["#buyer", "#buyer-workspace"].includes(window.location.hash)) return "buyer";
    if (["#merchant", "#merchant-workspace"].includes(window.location.hash)) return "merchant";
    if (["#clearing", "#market-clearing"].includes(window.location.hash)) return "clearing";
    if (
      [
        "#evidence",
        "#top",
        "#current-runtime-proof",
        "#historical-evidence",
        "#controlled-demonstrations",
        "#demo",
        "#authority-demo-result",
        "#limitations",
      ].includes(window.location.hash)
    ) {
      return "evidence";
    }
    return null;
  };

  const setView = (view, { hashMode = "replace", preserveHash = false } = {}) => {
    const selected = ["buyer", "merchant", "clearing", "evidence"].includes(view)
      ? view
      : "buyer";
    document.body.dataset.view = selected;
    viewPanels.forEach((panel) => {
      panel.hidden = panel.dataset.appView !== selected;
    });
    viewButtons.forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.viewTarget === selected));
    });
    if (evidenceNav) evidenceNav.hidden = true;
    if (menuToggle) menuToggle.hidden = true;
    if (skipLink instanceof HTMLAnchorElement) {
      skipLink.href =
        selected === "evidence"
          ? "#evidence"
          : selected === "merchant"
            ? "#merchant-workspace"
            : selected === "clearing"
              ? "#clearing-workspace"
              : "#buyer-workspace";
      skipLink.textContent = selected === "evidence" ? "Skip to dossier" : "Skip to workspace";
    }
    if (["buyer", "merchant", "clearing"].includes(selected)) {
      try {
        window.localStorage.setItem("clear-product-view", selected);
      } catch (_error) {
        // View selection remains functional when storage is unavailable.
      }
    }
    const selectedHash = `#${selected}`;
    if (!preserveHash && window.location.hash !== selectedHash) {
      window.history[hashMode === "push" ? "pushState" : "replaceState"](
        null,
        "",
        selectedHash,
      );
    }
  };

  const primaryWorkspaceViews = new Set(["buyer", "merchant", "clearing"]);
  const primaryWorkspaceScrollPositions = new Map();

  const rememberCurrentPrimaryScroll = () => {
    const currentView = document.body.dataset.view;
    if (primaryWorkspaceViews.has(currentView)) {
      primaryWorkspaceScrollPositions.set(currentView, window.scrollY);
    }
  };

  const restorePrimaryWorkspaceScroll = (view, { forceTop = false } = {}) => {
    if (!primaryWorkspaceViews.has(view)) return;
    const rememberedPosition = forceTop
      ? 0
      : (primaryWorkspaceScrollPositions.get(view) ?? 0);
    if (forceTop) primaryWorkspaceScrollPositions.set(view, 0);
    window.requestAnimationFrame(() => {
      window.scrollTo({ top: rememberedPosition, left: 0, behavior: "auto" });
    });
  };

  const selectPrimaryWorkspace = (view, { forceTop = false } = {}) => {
    if (!primaryWorkspaceViews.has(view)) return;
    rememberCurrentPrimaryScroll();
    setView(view, { hashMode: "push" });
    restorePrimaryWorkspaceScroll(view, { forceTop });
    reconcileActiveWorkspace(view);
  };

  viewButtons.forEach((button) => {
    button.addEventListener("click", () => {
      selectPrimaryWorkspace(button.dataset.viewTarget);
    });
  });

  if (wordmark instanceof HTMLAnchorElement) {
    wordmark.addEventListener("click", (event) => {
      event.preventDefault();
      selectPrimaryWorkspace("buyer", { forceTop: true });
    });
  }

  const restoredWorkspaceView = () => {
    try {
      const storedView = window.localStorage.getItem("clear-product-view");
      return ["merchant", "clearing"].includes(storedView) ? storedView : "buyer";
    } catch (_error) {
      return "buyer";
    }
  };
  const initialHashView = viewFromHash();
  const initialSelectedView = initialHashView || restoredWorkspaceView();
  setView(initialSelectedView, {
    preserveHash: initialHashView !== null,
  });
  if (initialSelectedView !== "evidence") {
    restorePrimaryWorkspaceScroll(initialSelectedView);
  }

  const routeFromHash = () => {
    const hashView = viewFromHash();
    const selected = hashView || restoredWorkspaceView();
    const currentView = document.body.dataset.view;
    if (currentView !== selected) rememberCurrentPrimaryScroll();
    setView(selected, { preserveHash: hashView !== null });
    if (currentView !== selected && selected !== "evidence") {
      restorePrimaryWorkspaceScroll(selected);
    }
    reconcileActiveWorkspace(selected);
  };
  window.addEventListener("hashchange", routeFromHash);
  window.addEventListener("popstate", routeFromHash);

  const requestJSON = async (url, options = {}) => {
    const response = await window.fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    let payload;
    try {
      payload = await response.json();
    } catch (_error) {
      throw new Error("The server returned an unreadable response.");
    }
    return { ok: response.ok, status: response.status, payload };
  };

  const setStage = (active) => {
    document.querySelectorAll("[data-buyer-stage]").forEach((stage) => {
      stage.dataset.stageState = stage.dataset.buyerStage === active ? "active" : "idle";
    });
  };

  const setRunning = (value, label) => {
    running = value;
    if (interpretButton instanceof HTMLButtonElement) {
      interpretButton.disabled = value || currentMarketId !== null;
    }
    if (freezeButton instanceof HTMLButtonElement) freezeButton.disabled = value;
    if (newDraftButton instanceof HTMLButtonElement) newDraftButton.disabled = value;
    form.querySelectorAll("textarea, input").forEach((field) => {
      field.disabled = value || currentMarketId !== null;
    });
    if (interpretLabel) interpretLabel.textContent = label;
  };

  const canonicalDeadline = (value) => {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) throw new Error("Choose a valid future offer deadline.");
    return parsed.toISOString().replace(/\.(\d{3})Z$/, ".$1000Z");
  };

  const checkedMerchantIds = () =>
    [...form.querySelectorAll('input[name="eligible_merchant_ids"]:checked')].map(
      (input) => input.value,
    );

  const renderMerchants = (merchants) => {
    if (!merchantList) return;
    merchantList.replaceChildren();
    if (!Array.isArray(merchants) || merchants.length === 0) {
      const empty = document.createElement("p");
      empty.className = "buyer-inline-error";
      empty.textContent = "No runtime merchants are available. Create merchants through the product API first.";
      merchantList.append(empty);
      if (interpretButton instanceof HTMLButtonElement) interpretButton.disabled = true;
      return;
    }
    merchants.forEach((merchant) => {
      const label = document.createElement("label");
      label.className = "merchant-choice";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = "eligible_merchant_ids";
      input.value = String(merchant.merchant_id);
      input.checked = true;
      input.disabled = currentMarketId !== null;
      const copy = document.createElement("span");
      const name = document.createElement("strong");
      name.textContent = String(merchant.display_name);
      const detail = document.createElement("small");
      detail.textContent = `${String(merchant.product_display_name)} · ${String(merchant.merchant_sku)} · ${String(merchant.inventory_quantity)} AVAILABLE`;
      copy.append(name, detail);
      label.append(input, copy);
      merchantList.append(label);
    });
  };

  const renderMerchantOptions = (merchants) => {
    if (!(merchantSelect instanceof HTMLSelectElement)) return;
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Select a merchant";
    const options = [placeholder];
    if (Array.isArray(merchants)) {
      merchants.forEach((merchant) => {
        const option = document.createElement("option");
        option.value = String(merchant.merchant_id);
        option.textContent = `${String(merchant.display_name)} · ${String(merchant.merchant_sku)}`;
        options.push(option);
      });
    }
    merchantSelect.replaceChildren(...options);
    let rememberedMerchantId = null;
    try {
      rememberedMerchantId = window.localStorage.getItem("clear-product-merchant-id");
    } catch (_error) {
      // The server-backed workspace remains available without browser storage.
    }
    if (
      rememberedMerchantId &&
      Array.isArray(merchants) &&
      merchants.some((merchant) => String(merchant.merchant_id) === rememberedMerchantId)
    ) {
      merchantSelect.value = rememberedMerchantId;
      loadMerchantInbox(rememberedMerchantId);
    }
  };

  const loadMerchants = async () => {
    try {
      const response = await requestJSON("/api/product-v1/merchants", { headers: {} });
      if (!response.ok || !Array.isArray(response.payload.merchants)) {
        throw new Error("Runtime merchant discovery failed closed.");
      }
      renderMerchants(response.payload.merchants);
      renderMerchantOptions(response.payload.merchants);
    } catch (error) {
      renderMerchants([]);
      renderMerchantOptions([]);
      if (actionStatus) actionStatus.textContent = error.message;
      if (merchantActionStatus) merchantActionStatus.textContent = error.message;
    }
  };

  const clearInterpretation = () => {
    if (interpretationPanel) interpretationPanel.hidden = true;
    if (frozenPanel) frozenPanel.hidden = true;
    if (errorCode) errorCode.hidden = true;
    if (diagnosticCode) diagnosticCode.hidden = true;
    if (candidateDiagnostic) {
      candidateDiagnostic.hidden = true;
      candidateDiagnostic.replaceChildren();
    }
    if (successPanel) successPanel.hidden = false;
  };

  const renderCandidateDiagnostic = (diagnostic) => {
    if (!candidateDiagnostic) return;
    candidateDiagnostic.replaceChildren();
    if (!diagnostic || typeof diagnostic !== "object") {
      candidateDiagnostic.hidden = true;
      return;
    }
    const allowedFields = new Set([
      "schema_version",
      "buyer_intent_candidate_version",
      "requested_quantity",
      "minimum_acceptable_quantity",
      "max_winners",
      "max_total_payment_paise",
      "hard_constraints",
      "soft_preferences",
    ]);
    const allowedTypes = new Set([
      "string",
      "integer",
      "boolean",
      "array",
      "object",
      "null",
      "number_other",
    ]);
    const safeNames = (value) =>
      Array.isArray(value)
        ? value
            .filter((entry) => typeof entry === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(entry))
            .join(", ") || "none"
        : "none";
    const addLine = (label, value) => {
      const line = document.createElement("div");
      const name = document.createElement("strong");
      const detail = document.createElement("span");
      name.textContent = label;
      detail.textContent = String(value);
      line.append(name, detail);
      candidateDiagnostic.append(line);
    };
    const heading = document.createElement("strong");
    heading.textContent = "CANDIDATE SHAPE";
    candidateDiagnostic.append(heading);
    addLine("MISSING ·", safeNames(diagnostic.missing_fields));
    addLine(
      "EXTRA FIELD COUNT ·",
      Number.isInteger(diagnostic.extra_field_count) ? diagnostic.extra_field_count : 0,
    );
    if (diagnostic.field_types && typeof diagnostic.field_types === "object") {
      Object.entries(diagnostic.field_types).forEach(([field, type]) => {
        if (allowedFields.has(field) && allowedTypes.has(type)) addLine(`${field} ·`, type);
      });
    }
    [
      ["SCHEMA VERSION VALID ·", diagnostic.schema_version_valid],
      ["CANDIDATE VERSION VALID ·", diagnostic.candidate_version_valid],
      ["REQUESTED QUANTITY POSITIVE INTEGER ·", diagnostic.requested_quantity_positive_integer],
      [
        "MINIMUM ACCEPTABLE QUANTITY POSITIVE INTEGER ·",
        diagnostic.minimum_acceptable_quantity_positive_integer,
      ],
      ["MAX WINNERS POSITIVE INTEGER ·", diagnostic.max_winners_positive_integer],
      [
        "MAX PAYMENT NONNEGATIVE INTEGER ·",
        diagnostic.max_total_payment_paise_nonnegative_integer,
      ],
      ["MINIMUM ≤ REQUESTED ·", diagnostic.minimum_lte_requested],
      ["MAX WINNERS ≤ REQUESTED ·", diagnostic.max_winners_lte_requested],
    ].forEach(([label, value]) => {
      if (typeof value === "boolean") addLine(label, value ? "true" : "false");
    });
    ["hard_constraints", "soft_preferences"].forEach((field) => {
      const shape = diagnostic[field];
      if (!shape || typeof shape !== "object") return;
      addLine(
        `${field} ·`,
        `${shape.is_array === true ? "array" : "not-array"} · ${Number.isInteger(shape.item_count) ? shape.item_count : 0} items`,
      );
      addLine(`${field} missing ·`, safeNames(shape.missing_rule_fields));
      addLine(
        `${field} extra field count ·`,
        Number.isInteger(shape.extra_rule_field_count) ? shape.extra_rule_field_count : 0,
      );
      [
        "non_object_item_count",
        "invalid_rule_schema_version_count",
        "invalid_rule_candidate_version_count",
        "invalid_rule_id_format_count",
        "invalid_operator_count",
        "invalid_value_type_count",
        "invalid_allowed_provenance_shape_count",
      ].forEach((key) => {
        if (Number.isInteger(shape[key])) addLine(`${field} ${key} ·`, shape[key]);
      });
    });
    candidateDiagnostic.hidden = false;
  };

  const renderRuleList = (selector, rules) => {
    const list = document.querySelector(selector);
    if (!list) return;
    list.replaceChildren();
    if (!Array.isArray(rules) || rules.length === 0) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "None interpreted.";
      list.append(empty);
      return;
    }
    rules.forEach((rule) => {
      const item = document.createElement("div");
      item.className = "buyer-rule";
      const title = document.createElement("strong");
      title.textContent = String(rule.attribute_key);
      const expression = document.createElement("span");
      expression.textContent = `${String(rule.operator)} · ${String(rule.value_type)} · ${String(rule.value)}`;
      const provenance = document.createElement("small");
      const labels = Array.isArray(rule.allowed_provenance) ? rule.allowed_provenance : [];
      provenance.textContent = `PROVENANCE · ${labels.map(String).join(" / ")}`;
      item.append(title, expression, provenance);
      list.append(item);
    });
  };

  const setMerchantText = (field, value) => {
    const target = document.querySelector(`[data-merchant-field="${field}"]`);
    if (target) target.textContent = String(value);
  };

  const setMerchantMarketText = (field, value) => {
    const target = document.querySelector(`[data-merchant-market-field="${field}"]`);
    if (target) target.textContent = String(value);
  };

  const setMerchantProposalText = (field, value) => {
    const target = document.querySelector(`[data-merchant-proposal-field="${field}"]`);
    if (target) target.textContent = String(value);
  };

  const renderMerchantAttributes = (attributes) => {
    if (!merchantAttributeList) return;
    merchantAttributeList.replaceChildren();
    if (!Array.isArray(attributes) || attributes.length === 0) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "No catalog attributes are persisted for this SKU.";
      merchantAttributeList.append(empty);
      return;
    }
    attributes.forEach((attribute) => {
      const item = document.createElement("div");
      const key = document.createElement("strong");
      const value = document.createElement("span");
      const provenance = document.createElement("small");
      key.textContent = String(attribute.attribute_key);
      value.textContent = `${String(attribute.value_type)} · ${String(attribute.value)}`;
      provenance.textContent = String(attribute.provenance);
      item.append(key, value, provenance);
      merchantAttributeList.append(item);
    });
  };

  const renderMerchantProfile = (merchant) => {
    if (!merchant || typeof merchant !== "object") {
      if (merchantProfile) merchantProfile.hidden = true;
      return;
    }
    setMerchantText("display-name", merchant.display_name);
    setMerchantText("product-name", merchant.product_display_name);
    setMerchantText("merchant-sku", merchant.merchant_sku);
    setMerchantText("inventory", merchant.inventory_quantity);
    setMerchantText(
      "minimum-price",
      formatInrFromPaise(merchant.minimum_allowed_unit_price_paise),
    );
    setMerchantText("maximum-quantity", merchant.max_quantity_per_offer);
    renderMerchantAttributes(merchant.attributes);
    if (merchantProfile) merchantProfile.hidden = false;
  };

  const setMerchantRunning = (value) => {
    merchantRunning = value;
    if (merchantSelect instanceof HTMLSelectElement) merchantSelect.disabled = value;
    if (requestMerchantProposal instanceof HTMLButtonElement) {
      requestMerchantProposal.disabled = value;
    }
    if (submitMerchantProposal instanceof HTMLButtonElement) {
      submitMerchantProposal.disabled = value;
    }
  };

  const clearMerchantSelection = () => {
    currentMerchantMarketId = null;
    if (merchantMarketReview) merchantMarketReview.hidden = true;
    merchantMarketList?.querySelectorAll("button").forEach((button) => {
      button.setAttribute("aria-pressed", "false");
    });
  };

  const renderMerchantProposalLines = (lines, labels) => {
    const target = document.querySelector('[data-merchant-proposal-field="lines"]');
    if (!target) return;
    target.replaceChildren();
    if (!Array.isArray(lines)) return;
    lines.forEach((line) => {
      const item = document.createElement("dl");
      labels.forEach(([label, field]) => {
        if (!(field in line)) return;
        const fact = document.createElement("div");
        const term = document.createElement("dt");
        const detail = document.createElement("dd");
        term.textContent = label;
        detail.textContent =
          field === "proposed_unit_price_paise"
            ? formatInrFromPaise(line[field])
            : String(line[field]);
        fact.append(term, detail);
        item.append(fact);
      });
      target.append(item);
    });
  };

  const renderMerchantProposal = (proposal) => {
    const provider = document.querySelector('[data-merchant-proposal-field="provider"]');
    const safeProposal = proposal && typeof proposal === "object" ? proposal : {};
    const state = String(safeProposal.state || "NO_PROPOSAL");
    if (provider) provider.hidden = true;
    renderMerchantProposalLines([], []);
    if (requestMerchantProposal instanceof HTMLButtonElement) requestMerchantProposal.hidden = true;
    if (submitMerchantProposal instanceof HTMLButtonElement) submitMerchantProposal.hidden = true;

    if (state === "NO_PROPOSAL") {
      setMerchantProposalText("title", "No proposal");
      setMerchantProposalText("state", "READY");
      setMerchantProposalText(
        "message",
        "AI is invoked only when the merchant explicitly requests a proposal.",
      );
      if (requestMerchantProposal instanceof HTMLButtonElement) {
        requestMerchantProposal.hidden = false;
      }
      return;
    }

    const providerInvoked = safeProposal.provider_invoked === true;
    if (provider) {
      provider.hidden = !providerInvoked;
    }
    if (providerInvoked) {
      setMerchantProposalText("provider-name", safeProposal.provider_name || "UNAVAILABLE");
      setMerchantProposalText("model", safeProposal.model || "UNAVAILABLE");
    }
    if (state === "PROPOSING") {
      setMerchantProposalText("title", "Proposal generation claimed");
      setMerchantProposalText("state", "PROPOSING");
      setMerchantProposalText(
        "message",
        "The server has claimed this proposal action. No offer has been submitted.",
      );
      return;
    }
    if (state === "NO_OFFER") {
      setMerchantProposalText("title", "Valid no_offer");
      setMerchantProposalText("state", "VALID NO_OFFER");
      setMerchantProposalText(
        "message",
        "The strict merchant-AI result is final for this market. No offer was submitted and no signing occurred.",
      );
      return;
    }
    if (state === "PROPOSED") {
      const lines = safeProposal.candidate?.lines;
      setMerchantProposalText("title", "Advisory only");
      setMerchantProposalText("state", "PROPOSED · NOT SUBMITTED");
      setMerchantProposalText(
        "message",
        "AI PROPOSAL · ADVISORY ONLY. AI DID NOT SUBMIT AN OFFER.",
      );
      renderMerchantProposalLines(lines, [
        ["SKU ID", "sku_id"],
        ["PROPOSED QUANTITY", "proposed_quantity"],
        ["PROPOSED UNIT PRICE", "proposed_unit_price_paise"],
      ]);
      if (submitMerchantProposal instanceof HTMLButtonElement) {
        submitMerchantProposal.hidden = false;
      }
      return;
    }
    if (state === "SUBMITTED") {
      setMerchantProposalText("title", "Authenticated offer submitted");
      setMerchantProposalText("state", "SIGNED · AUTHENTICATED · SUBMITTED");
      setMerchantProposalText(
        "message",
        "AUTHENTICATED OFFER SUBMITTED. MARKET NOT CLEARED.",
      );
      renderMerchantProposalLines(safeProposal.offer ? [safeProposal.offer] : [], [
        ["OFFER ID", "offer_id"],
        ["QUANTITY", "proposed_quantity"],
        ["UNIT PRICE", "proposed_unit_price_paise"],
        ["RECEIVED", "received_at"],
      ]);
      return;
    }
    setMerchantProposalText("title", "State unavailable");
    setMerchantProposalText("state", "FAILED CLOSED");
    setMerchantProposalText("message", "The server returned an unsupported proposal state.");
  };

  const selectMerchantMarket = (market) => {
    currentMerchantMarketId = String(market.market_id);
    setMerchantMarketText("state", `${String(market.market_state)} · FROZEN`);
    setMerchantMarketText("market-id", market.market_id);
    setMerchantMarketText("requested-quantity", market.requested_quantity);
    setMerchantMarketText("minimum-quantity", market.minimum_acceptable_quantity);
    setMerchantMarketText("max-suppliers", market.max_winners);
    setMerchantMarketText("budget", formatInrFromPaise(market.max_total_payment_paise));
    renderRuleList(
      '[data-merchant-market-field="hard-rules"]',
      market.hard_constraints,
    );
    renderRuleList(
      '[data-merchant-market-field="soft-rules"]',
      market.soft_preferences,
    );
    renderMerchantProposal(market.proposal);
    merchantMarketList?.querySelectorAll("button").forEach((button) => {
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.marketId === currentMerchantMarketId),
      );
    });
    if (merchantMarketReview) merchantMarketReview.hidden = false;
    if (merchantActionStatus) {
      merchantActionStatus.textContent = "State restored from the authoritative merchant market inbox.";
    }
    try {
      window.localStorage.setItem("clear-product-merchant-market-id", currentMerchantMarketId);
    } catch (_error) {
      // The selected market remains usable without browser storage.
    }
  };

  const renderMerchantMarkets = (markets) => {
    if (!merchantMarketList) return;
    merchantMarketList.replaceChildren();
    if (!Array.isArray(markets) || markets.length === 0) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "No eligible open markets are available for this merchant.";
      merchantMarketList.append(empty);
      clearMerchantSelection();
      return;
    }
    markets.forEach((market) => {
      const button = document.createElement("button");
      const title = document.createElement("strong");
      const detail = document.createElement("small");
      button.type = "button";
      button.className = "merchant-market-choice";
      button.dataset.marketId = String(market.market_id);
      button.setAttribute("aria-pressed", "false");
      title.textContent = String(market.market_id);
      detail.textContent = `${String(market.requested_quantity)} REQUESTED · DEADLINE ${String(market.offer_deadline)}`;
      button.append(title, detail);
      button.addEventListener("click", () => selectMerchantMarket(market));
      merchantMarketList.append(button);
    });
  };

  const loadMerchantInbox = async (merchantId, preferredMarketId = null) => {
    const requestNumber = ++merchantInboxRequest;
    currentMerchantId = merchantId;
    currentMerchantInbox = null;
    clearMerchantSelection();
    if (merchantActionStatus) merchantActionStatus.textContent = "Loading server-filtered open markets.";
    try {
      const response = await requestJSON(
        `/api/product-v1/merchants/${encodeURIComponent(merchantId)}/markets`,
        { headers: {} },
      );
      if (
        requestNumber !== merchantInboxRequest ||
        currentMerchantId !== merchantId
      ) {
        return;
      }
      if (
        !response.ok ||
        !response.payload.merchant ||
        !Array.isArray(response.payload.markets)
      ) {
        throw new Error("The authoritative merchant inbox could not be loaded.");
      }
      currentMerchantInbox = response.payload;
      renderMerchantProfile(response.payload.merchant);
      renderMerchantMarkets(response.payload.markets);
      let rememberedMarketId = preferredMarketId;
      if (!rememberedMarketId) {
        try {
          rememberedMarketId = window.localStorage.getItem("clear-product-merchant-market-id");
        } catch (_error) {
          // Market selection remains explicit when storage is unavailable.
        }
      }
      const rememberedMarket = response.payload.markets.find(
        (market) => String(market.market_id) === rememberedMarketId,
      );
      if (rememberedMarket) {
        selectMerchantMarket(rememberedMarket);
      } else {
        try {
          window.localStorage.removeItem("clear-product-merchant-market-id");
        } catch (_error) {
          // No browser storage mutation is required for authority correctness.
        }
        if (merchantActionStatus) {
          merchantActionStatus.textContent = "Select an eligible open market. No AI call has occurred.";
        }
      }
    } catch (error) {
      if (requestNumber !== merchantInboxRequest) return;
      currentMerchantInbox = null;
      if (merchantProfile) merchantProfile.hidden = true;
      renderMerchantMarkets([]);
      if (merchantActionStatus) {
        merchantActionStatus.textContent =
          error instanceof Error ? error.message : "Merchant inbox loading failed closed.";
      }
    }
  };

  const renderMerchantActionFailure = (payload) => {
    const error = payload && typeof payload === "object" ? payload.error : null;
    const code = String(payload?.code || error?.code || "PRODUCT_REQUEST_FAILED");
    const messageText = String(
      payload?.message || error?.message || "The merchant action failed closed.",
    );
    setMerchantProposalText("state", code);
    setMerchantProposalText("message", messageText);
    if (merchantActionStatus) {
      merchantActionStatus.textContent = `${code} · No browser authority was inferred.`;
    }
  };

  if (merchantSelect instanceof HTMLSelectElement) {
    merchantSelect.addEventListener("change", () => {
      const merchantId = merchantSelect.value;
      ++merchantInboxRequest;
      currentMerchantId = merchantId || null;
      currentMerchantInbox = null;
      clearMerchantSelection();
      if (!merchantId) {
        if (merchantProfile) merchantProfile.hidden = true;
        renderMerchantMarkets([]);
        try {
          window.localStorage.removeItem("clear-product-merchant-id");
          window.localStorage.removeItem("clear-product-merchant-market-id");
        } catch (_error) {
          // Clearing the server-independent convenience state is optional.
        }
        if (merchantActionStatus) {
          merchantActionStatus.textContent = "Select a runtime merchant. No AI call has occurred.";
        }
        return;
      }
      try {
        window.localStorage.setItem("clear-product-merchant-id", merchantId);
      } catch (_error) {
        // The server-backed workspace remains available without browser storage.
      }
      loadMerchantInbox(merchantId);
    });
  }

  if (requestMerchantProposal instanceof HTMLButtonElement) {
    requestMerchantProposal.addEventListener("click", async () => {
      if (merchantRunning || !currentMerchantId || !currentMerchantMarketId) return;
      const merchantId = currentMerchantId;
      const marketId = currentMerchantMarketId;
      setMerchantRunning(true);
      if (merchantActionStatus) {
        merchantActionStatus.textContent = "RUNNING · USER INITIATED · ONE MERCHANT AI CALL";
      }
      try {
        const response = await requestJSON(
          `/api/product-v1/merchants/${encodeURIComponent(merchantId)}/markets/${encodeURIComponent(marketId)}/propose`,
          { method: "POST", body: "{}" },
        );
        if (!response.ok || response.payload.result !== "SUCCESS") {
          renderMerchantActionFailure(response.payload);
          return;
        }
        await loadMerchantInbox(merchantId, marketId);
      } catch (error) {
        renderMerchantActionFailure(productErrorPayload(error));
      } finally {
        setMerchantRunning(false);
      }
    });
  }

  if (submitMerchantProposal instanceof HTMLButtonElement) {
    submitMerchantProposal.addEventListener("click", async () => {
      if (merchantRunning || !currentMerchantId || !currentMerchantMarketId) return;
      const merchantId = currentMerchantId;
      const marketId = currentMerchantMarketId;
      setMerchantRunning(true);
      if (merchantActionStatus) {
        merchantActionStatus.textContent =
          "VALIDATING · SIGNING · AUTHENTICATING · NO AI CALL";
      }
      try {
        const response = await requestJSON(
          `/api/product-v1/merchants/${encodeURIComponent(merchantId)}/markets/${encodeURIComponent(marketId)}/submit-proposal`,
          { method: "POST", body: "{}" },
        );
        if (!response.ok || response.payload.result !== "SUCCESS") {
          renderMerchantActionFailure(response.payload);
          return;
        }
        await loadMerchantInbox(merchantId, marketId);
      } catch (error) {
        renderMerchantActionFailure(productErrorPayload(error));
      } finally {
        setMerchantRunning(false);
      }
    });
  }

  const setClearingText = (field, value) => {
    const target = document.querySelector(`[data-clearing-field="${field}"]`);
    if (target) target.textContent = String(value);
  };

  const setClearingResultText = (field, value) => {
    const target = document.querySelector(`[data-clearing-result-field="${field}"]`);
    if (target) target.textContent = String(value);
  };

  const setClearingRunning = (value) => {
    clearingRunning = value;
    if (refreshClearingMarkets instanceof HTMLButtonElement) {
      refreshClearingMarkets.disabled = value;
    }
    if (closeClearingMarket instanceof HTMLButtonElement) {
      closeClearingMarket.disabled = value || currentClearingState !== "OPEN";
    }
    clearingMarketList?.querySelectorAll("button").forEach((button) => {
      button.disabled = value;
    });
  };

  const forgetClearingSelection = () => {
    clearRuntimeAuthorityPresentation();
    currentClearingMarketId = null;
    currentClearingState = null;
    if (clearingSnapshot) clearingSnapshot.hidden = true;
    try {
      window.localStorage.removeItem("clear-product-clearing-market-id");
    } catch (_error) {
      // Clearing convenience state is optional and carries no authority.
    }
  };

  const updateClearingChoice = (market) => {
    clearingMarketList?.querySelectorAll("button").forEach((button) => {
      const selected = button.dataset.marketId === String(market.market_id);
      button.setAttribute("aria-pressed", String(selected));
      if (!selected) return;
      const detail = button.querySelector("small");
      if (detail) {
        detail.textContent = `${String(market.state)} · ${String(market.requested_quantity)} REQUESTED`;
      }
    });
  };

  const renderClearingOffers = (offers) => {
    if (!clearingOfferList) return;
    clearingOfferList.replaceChildren();
    if (!Array.isArray(offers) || offers.length === 0) {
      const empty = document.createElement("p");
      empty.className = "clearing-empty-offers";
      empty.textContent = "No authenticated submitted offers are persisted for this market.";
      clearingOfferList.append(empty);
      return;
    }
    offers.forEach((offer) => {
      const card = document.createElement("article");
      const head = document.createElement("div");
      const identity = document.createElement("div");
      const name = document.createElement("strong");
      const sku = document.createElement("small");
      const state = document.createElement("span");
      const facts = document.createElement("dl");
      card.className = "clearing-offer-card";
      head.className = "clearing-offer-head";
      name.textContent = String(offer.display_name);
      sku.textContent = `${String(offer.product_display_name)} · ${String(offer.merchant_sku)}`;
      state.textContent = "SIGNED · AUTHENTICATED · SUBMITTED";
      identity.append(name, sku);
      head.append(identity, state);
      [
        ["OFFER ID", offer.offer_id],
        ["MERCHANT ID", offer.merchant_id],
        ["SKU ID", offer.sku_id],
        ["QUANTITY", offer.submitted_quantity],
        ["UNIT PRICE", formatInrFromPaise(offer.unit_price_paise)],
        ["RECEIVED", offer.received_at],
      ].forEach(([label, value]) => {
        const fact = document.createElement("div");
        const term = document.createElement("dt");
        const detail = document.createElement("dd");
        term.textContent = String(label);
        detail.textContent = String(value);
        fact.append(term, detail);
        facts.append(fact);
      });
      card.append(head, facts);
      clearingOfferList.append(card);
    });
  };

  const renderClearingWinners = (winners) => {
    if (!clearingWinnerList) return;
    clearingWinnerList.replaceChildren();
    if (!Array.isArray(winners) || winners.length === 0) {
      const empty = document.createElement("p");
      empty.className = "clearing-empty-offers";
      empty.textContent = "No winner identities were produced.";
      clearingWinnerList.append(empty);
      return;
    }
    winners.forEach((winner) => {
      const item = document.createElement("div");
      const name = document.createElement("strong");
      const identity = document.createElement("span");
      name.textContent = String(winner.display_name);
      identity.textContent = String(winner.merchant_id);
      item.append(name, identity);
      clearingWinnerList.append(item);
    });
  };

  const setRuntimeAuthorityText = (field, value) => {
    const target = document.querySelector(`[data-authority-field="${field}"]`);
    if (target) target.textContent = String(value);
  };

  const setRuntimeTamperText = (field, value) => {
    const target = document.querySelector(`[data-tamper-field="${field}"]`);
    if (target) target.textContent = String(value);
  };

  const setRuntimeExecutionText = (field, value) => {
    const target = document.querySelector(`[data-execution-field="${field}"]`);
    if (target) target.textContent = String(value);
  };

  const setRuntimeRazorpayText = (field, value) => {
    const target = document.querySelector(`[data-razorpay-field="${field}"]`);
    if (target) target.textContent = String(value);
  };

  const resetRuntimeTamper = () => {
    ++tamperRequestGeneration;
    if (runtimeTamperResult) runtimeTamperResult.hidden = true;
    setRuntimeTamperText("verifier-failure-code", "—");
    setRuntimeTamperText("governor-failure-code", "—");
    setRuntimeTamperText("control-copy", "—");
    setRuntimeTamperText("money-copy", "—");
  };

  const setAuthorityRunning = (value) => {
    authorityRunning = value;
    if (runtimeTamperButton instanceof HTMLButtonElement) {
      runtimeTamperButton.disabled = value;
    }
    if (runtimeAuthorizeButton instanceof HTMLButtonElement) {
      runtimeAuthorizeButton.disabled = value;
    }
    if (runtimeRazorpayButton instanceof HTMLButtonElement) {
      runtimeRazorpayButton.disabled = value || razorpayRunning;
    }
  };

  const setRazorpayRunning = (value) => {
    razorpayRunning = value;
    if (runtimeRazorpayButton instanceof HTMLButtonElement) {
      runtimeRazorpayButton.disabled = value || authorityRunning;
    }
    if (runtimeTamperButton instanceof HTMLButtonElement) {
      runtimeTamperButton.disabled = value || authorityRunning;
    }
    if (runtimeAuthorizeButton instanceof HTMLButtonElement) {
      runtimeAuthorizeButton.disabled = value || authorityRunning;
    }
  };

  const resetRuntimeRazorpay = () => {
    ++razorpayRequestGeneration;
    currentRuntimeExecutionId = null;
    currentRuntimeOrderAmount = null;
    if (runtimeRazorpayResult) runtimeRazorpayResult.hidden = true;
    if (runtimeRazorpayButton instanceof HTMLButtonElement) {
      runtimeRazorpayButton.hidden = false;
      const label = runtimeRazorpayButton.querySelector("span");
      if (label) label.textContent = "Create Razorpay Test Mode order";
    }
    setRuntimeRazorpayText("state", "NOT DEMONSTRATED");
    setRuntimeRazorpayText("observation", "—");
    setRuntimeRazorpayText("resolution", "—");
    setRuntimeRazorpayText("provider-order-id", "—");
    setRuntimeRazorpayText("execution-id", "—");
    setRuntimeRazorpayText("order-amount", "—");
    setRuntimeRazorpayText("order-amount-raw", "—");
    setRuntimeRazorpayText("receipt", "—");
    if (runtimeRazorpayStatus) {
      runtimeRazorpayStatus.textContent = "No Razorpay order action has been requested.";
    }
    setRazorpayRunning(false);
  };

  const clearRuntimeAuthorityPresentation = () => {
    ++authorizeRequestGeneration;
    ++authoritySnapshotRequest;
    if (runtimeAuthoritySequence) runtimeAuthoritySequence.hidden = true;
    if (runtimeExecutionPlan) runtimeExecutionPlan.hidden = true;
    runtimeCertificateLines?.replaceChildren();
    runtimeTransferLines?.replaceChildren();
    resetRuntimeTamper();
    resetRuntimeRazorpay();
    if (runtimeAuthorizeButton instanceof HTMLButtonElement) {
      runtimeAuthorizeButton.hidden = false;
      const label = runtimeAuthorizeButton.querySelector("span");
      if (label) label.textContent = "Authorize provider-neutral execution";
    }
    setAuthorityRunning(false);
  };

  const runtimeFact = (labelText, value) => {
    const fact = document.createElement("div");
    const label = document.createElement("span");
    const data = document.createElement("strong");
    label.textContent = String(labelText);
    data.textContent = String(value);
    fact.append(label, data);
    return fact;
  };

  const renderRuntimeCertificateLines = (lines) => {
    if (!runtimeCertificateLines) return;
    runtimeCertificateLines.replaceChildren();
    if (!Array.isArray(lines) || lines.length === 0) {
      const empty = document.createElement("p");
      empty.className = "runtime-empty-lines";
      empty.textContent = "No executable allocation lines exist in this valid certificate.";
      runtimeCertificateLines.append(empty);
      return;
    }
    lines.forEach((line) => {
      const card = document.createElement("article");
      const heading = document.createElement("div");
      const name = document.createElement("strong");
      const identity = document.createElement("small");
      const facts = document.createElement("div");
      card.className = "runtime-line-card";
      heading.className = "runtime-line-heading";
      facts.className = "runtime-line-facts";
      name.textContent = String(line.display_name);
      identity.textContent = String(line.merchant_id);
      heading.append(name, identity);
      [
        ["OFFER ID", line.offer_id],
        ["SKU ID", line.sku_id],
        ["ALLOCATED", line.allocated_quantity],
        ["UNIT PAYMENT", formatInrFromPaise(line.unit_payment_paise)],
        ["LINE PAYMENT", formatInrFromPaise(line.line_payment_paise)],
      ].forEach(([label, value]) => facts.append(runtimeFact(label, value)));
      card.append(heading, facts);
      runtimeCertificateLines.append(card);
    });
  };

  const tamperGovernorFailureCode = "CERTIFICATE_NOT_VERIFIED";

  const renderRuntimeTransferLines = (lines) => {
    if (!runtimeTransferLines) return;
    runtimeTransferLines.replaceChildren();
    if (!Array.isArray(lines)) return;
    lines.forEach((line) => {
      const card = document.createElement("article");
      const heading = document.createElement("div");
      const name = document.createElement("strong");
      const recipient = document.createElement("small");
      const facts = document.createElement("div");
      card.className = "runtime-line-card";
      heading.className = "runtime-line-heading";
      facts.className = "runtime-line-facts";
      name.textContent = String(line.display_name);
      recipient.textContent = String(line.recipient_id);
      heading.append(name, recipient);
      [
        ["MERCHANT ID", line.merchant_id],
        ["ALLOCATED", line.allocated_quantity],
        ["TRANSFER", formatInrFromPaise(line.transfer_amount_paise)],
      ].forEach(([label, value]) => facts.append(runtimeFact(label, value)));
      card.append(heading, facts);
      runtimeTransferLines.append(card);
    });
  };

  const renderRuntimeRazorpayState = (providerState) => {
    if (
      !providerState ||
      typeof providerState !== "object" ||
      providerState.provider_status_refreshed !== false
    ) {
      throw new Error("The persisted Razorpay order state failed closed.");
    }
    if (runtimeRazorpayResult) runtimeRazorpayResult.hidden = true;
    if (providerState.state === "NOT_DEMONSTRATED") {
      setRuntimeRazorpayText("state", "NOT DEMONSTRATED");
      if (runtimeRazorpayStatus) {
        runtimeRazorpayStatus.textContent = "No Razorpay order action has been requested.";
      }
      return;
    }
    if (providerState.state === "RECOVERY_REQUIRED") {
      setRuntimeRazorpayText("state", "RECOVERY REQUIRED");
      if (runtimeRazorpayButton instanceof HTMLButtonElement) {
        const label = runtimeRazorpayButton.querySelector("span");
        if (label) label.textContent = "Reconcile Razorpay Test Mode order";
      }
      if (runtimeRazorpayStatus) {
        runtimeRazorpayStatus.textContent =
          "A persisted create intent requires an explicit GET-only reconciliation.";
      }
      return;
    }
    if (
      providerState.state !== "ORDER_REFERENCE_PERSISTED" ||
      typeof providerState.provider_order_id !== "string" ||
      providerState.execution_id !== currentRuntimeExecutionId ||
      providerState.order_amount_paise !== currentRuntimeOrderAmount ||
      providerState.currency !== "INR" ||
      providerState.receipt !== currentRuntimeExecutionId
    ) {
      throw new Error("The persisted Razorpay order reference failed closed.");
    }
    setRuntimeRazorpayText("state", "ORDER REFERENCE PERSISTED");
    setRuntimeRazorpayText("observation", "SERVER LEDGER · NO PROVIDER REFRESH");
    setRuntimeRazorpayText("resolution", "ORDER REFERENCE PERSISTED");
    setRuntimeRazorpayText("provider-order-id", providerState.provider_order_id);
    setRuntimeRazorpayText("execution-id", providerState.execution_id);
    setRuntimeRazorpayText("order-amount", formatInrFromPaise(providerState.order_amount_paise));
    setRuntimeRazorpayText(
      "order-amount-raw",
      `${providerState.order_amount_paise} paise · INR`,
    );
    setRuntimeRazorpayText("receipt", providerState.receipt);
    if (runtimeRazorpayResult) runtimeRazorpayResult.hidden = false;
    if (runtimeRazorpayButton instanceof HTMLButtonElement) {
      const label = runtimeRazorpayButton.querySelector("span");
      if (label) label.textContent = "Resolve existing Razorpay order";
    }
    if (runtimeRazorpayStatus) {
      runtimeRazorpayStatus.textContent =
        "A provider order reference is persisted. This GET did not contact Razorpay.";
    }
  };

  const renderRuntimeAuthority = (payload) => {
    const certificate = payload?.certificate;
    const allocation = certificate?.allocation;
    const verifier = payload?.verifier;
    const governor = payload?.governor;
    if (
      payload?.market?.state !== "CLOSED" ||
      !certificate ||
      typeof certificate !== "object" ||
      !allocation ||
      typeof allocation !== "object" ||
      !Array.isArray(allocation.lines) ||
      verifier?.verified !== true ||
      !governor ||
      typeof governor !== "object"
    ) {
      throw new Error("The runtime authority response failed closed.");
    }
    if (String(payload.market.market_id) !== currentClearingMarketId) return;
    resetRuntimeTamper();
    setRuntimeAuthorityText("proof-id", certificate.certificate_id);
    setRuntimeAuthorityText("proof-digest", certificate.digest_sha256);
    setRuntimeAuthorityText("policy-commitment", certificate.buyer_policy_commitment_sha256);
    setRuntimeAuthorityText("evidence-count", certificate.merchant_offer_evidence_count);
    setRuntimeAuthorityText("replay-state", "VERIFIED");
    renderRuntimeCertificateLines(allocation.lines);
    if (runtimeAuthoritySequence) runtimeAuthoritySequence.hidden = false;
    if (runtimeExecutionPlan) runtimeExecutionPlan.hidden = true;
    if (runtimeAuthorizeButton instanceof HTMLButtonElement) {
      runtimeAuthorizeButton.hidden = false;
      const label = runtimeAuthorizeButton.querySelector("span");
      if (label) label.textContent = "Authorize provider-neutral execution";
    }

    if (governor.state === "AUTHORIZED") {
      const plan = governor.execution_plan;
      if (
        !plan ||
        typeof plan !== "object" ||
        !Array.isArray(plan.transfer_obligations) ||
        typeof plan.execution_id !== "string" ||
        !Number.isSafeInteger(plan.order_amount_paise) ||
        plan.order_amount_paise < 0 ||
        plan.provider_action !==
          (payload?.razorpay_order?.state === "NOT_DEMONSTRATED"
            ? "NOT DEMONSTRATED"
            : payload?.razorpay_order?.state)
      ) {
        throw new Error("The persisted execution plan failed closed.");
      }
      currentRuntimeExecutionId = plan.execution_id;
      currentRuntimeOrderAmount = plan.order_amount_paise;
      setRuntimeAuthorityText("execution-state", "GOVERNOR AUTHORIZED");
      setRuntimeExecutionText("plan-version", plan.execution_plan_version);
      setRuntimeExecutionText("execution-id", plan.execution_id);
      setRuntimeExecutionText("proof-digest", plan.certificate_digest_sha256);
      setRuntimeExecutionText(
        "request-fingerprint",
        plan.execution_request_fingerprint_sha256,
      );
      setRuntimeExecutionText("idempotency-key", plan.idempotency_key);
      setRuntimeExecutionText("order-amount", formatInrFromPaise(plan.order_amount_paise));
      renderRuntimeTransferLines(plan.transfer_obligations);
      if (runtimeExecutionPlan) runtimeExecutionPlan.hidden = false;
      if (runtimeAuthorizeButton instanceof HTMLButtonElement) {
        runtimeAuthorizeButton.hidden = true;
      }
      renderRuntimeRazorpayState(payload.razorpay_order);
      if (runtimeAuthorityStatus) {
        runtimeAuthorityStatus.textContent =
          "Provider-neutral execution authority restored from persisted server state.";
      }
      return;
    }
    if (governor.state === "AUTHORIZING") {
      setRuntimeAuthorityText("execution-state", "AUTHORIZATION NOT CONFIRMED");
      if (runtimeAuthorizeButton instanceof HTMLButtonElement) {
        const label = runtimeAuthorizeButton.querySelector("span");
        if (label) label.textContent = "Resume authorization recovery";
      }
      if (runtimeAuthorityStatus) {
        runtimeAuthorityStatus.textContent =
          "The server retained one authority request. Deliberate recovery is available.";
      }
      return;
    }
    if (governor.state === "NOT_EXECUTABLE") {
      setRuntimeAuthorityText("execution-state", "NO EXECUTABLE ALLOCATION");
      if (runtimeAuthorizeButton instanceof HTMLButtonElement) {
        runtimeAuthorizeButton.hidden = true;
      }
      if (runtimeAuthorityStatus) {
        runtimeAuthorityStatus.textContent =
          "The valid certificate is INFEASIBLE. No execution plan or money action exists.";
      }
      return;
    }
    if (governor.state !== "NOT_AUTHORIZED") {
      throw new Error("The Governor state failed closed.");
    }
    setRuntimeAuthorityText("execution-state", "NO EXECUTION PLAN YET");
    if (runtimeAuthorityStatus) {
      runtimeAuthorityStatus.textContent =
        "No Governor authorization has been requested. No Razorpay action has occurred.";
    }
  };

  const loadRuntimeAuthority = async (marketId, { reconciliation = false } = {}) => {
    const requestNumber = ++authoritySnapshotRequest;
    setAuthorityRunning(true);
    if (runtimeAuthorityStatus) {
      runtimeAuthorityStatus.textContent = "Loading fresh certificate replay from the server.";
    }
    try {
      const response = await requestJSON(
        `/api/product-v1/markets/${encodeURIComponent(marketId)}/authority`,
        { headers: {} },
      );
      if (requestNumber !== authoritySnapshotRequest || currentClearingMarketId !== marketId) {
        return;
      }
      if (!response.ok) throw new Error("The runtime authority could not be verified.");
      renderRuntimeAuthority(response.payload);
      if (
        reconciliation &&
        response.payload?.governor?.state !== "AUTHORIZED" &&
        runtimeAuthorityStatus
      ) {
        runtimeAuthorityStatus.textContent =
          "Authorization was not observed complete. Deliberate recovery remains available.";
      }
    } catch (error) {
      if (requestNumber !== authoritySnapshotRequest) return;
      if (runtimeAuthoritySequence) runtimeAuthoritySequence.hidden = true;
      if (runtimeAuthorityStatus) {
        runtimeAuthorityStatus.textContent =
          error instanceof Error
            ? error.message
            : "The runtime authority could not be verified.";
      }
    } finally {
      if (requestNumber === authoritySnapshotRequest) setAuthorityRunning(false);
    }
  };

  const renderClearingSnapshot = (payload) => {
    const market = payload?.market;
    if (!market || typeof market !== "object" || !Array.isArray(payload.submitted_offers)) {
      throw new Error("The clearing snapshot failed its presentation boundary.");
    }
    if (market.state !== "OPEN" && market.state !== "CLOSED") {
      throw new Error("The clearing snapshot has no authoritative market state.");
    }
    if (market.state === "OPEN" && payload.result !== null) {
      throw new Error("An open market cannot carry a clearing result.");
    }
    if (market.state === "CLOSED" && (!payload.result || typeof payload.result !== "object")) {
      throw new Error("A closed market has no validated clearing result.");
    }
    currentClearingMarketId = String(market.market_id);
    currentClearingState = market.state;
    setClearingText("market-id", market.market_id);
    setClearingText("market-state", market.state);
    setClearingText("requested-quantity", market.requested_quantity);
    setClearingText("minimum-quantity", market.minimum_acceptable_quantity);
    setClearingText("max-suppliers", market.max_winners);
    setClearingText("budget", formatInrFromPaise(market.max_total_payment_paise));
    renderRuleList('[data-clearing-field="hard-rules"]', market.hard_constraints);
    renderRuleList('[data-clearing-field="soft-rules"]', market.soft_preferences);
    renderClearingOffers(payload.submitted_offers);
    updateClearingChoice(market);
    if (clearingSnapshot) clearingSnapshot.hidden = false;

    if (market.state === "OPEN") {
      clearRuntimeAuthorityPresentation();
      if (clearingClosePanel) clearingClosePanel.hidden = false;
      if (clearingResult) clearingResult.hidden = true;
      if (clearingActionStatus) {
        clearingActionStatus.textContent =
          "OPEN · authenticated submissions loaded · no winner exists yet.";
      }
    } else {
      const result = payload.result;
      const confirmed = document.querySelector("[data-clearing-confirmed-result]");
      if (clearingClosePanel) clearingClosePanel.hidden = true;
      if (clearingResult) clearingResult.hidden = false;
      if (confirmed) confirmed.hidden = false;
      setClearingResultText(
        "title",
        result.allocation_status === "FEASIBLE" ? "MARKET CLOSED" : "NO FEASIBLE ALLOCATION",
      );
      setClearingResultText(
        "message",
        "RULES DECIDED.\nAI DID NOT CHOOSE THE WINNERS.",
      );
      setClearingResultText("status", result.allocation_status);
      setClearingResultText("requested-quantity", result.requested_quantity);
      setClearingResultText("fulfilled-quantity", result.fulfilled_quantity);
      setClearingResultText("winner-count", result.winner_count);
      setClearingResultText("total", formatInrFromPaise(result.total_payment_paise));
      renderClearingWinners(result.winners);
      if (clearingActionStatus) {
        clearingActionStatus.textContent =
          "CLOSED · authoritative allocation restored from the server.";
      }
      loadRuntimeAuthority(currentClearingMarketId);
    }
    try {
      window.localStorage.setItem(
        "clear-product-clearing-market-id",
        currentClearingMarketId,
      );
    } catch (_error) {
      // The selected market remains usable without browser storage.
    }
    setClearingRunning(false);
  };

  const renderClearingNotConfirmed = () => {
    const confirmed = document.querySelector("[data-clearing-confirmed-result]");
    currentClearingState = null;
    clearRuntimeAuthorityPresentation();
    if (clearingClosePanel) clearingClosePanel.hidden = true;
    if (clearingResult) clearingResult.hidden = false;
    if (confirmed) confirmed.hidden = true;
    setClearingResultText("title", "CLOSE OUTCOME NOT CONFIRMED");
    setClearingResultText(
      "message",
      "The server state could not be reconciled. No outcome or winner is inferred.",
    );
    if (clearingActionStatus) {
      clearingActionStatus.textContent =
        "CLOSE OUTCOME NOT CONFIRMED · refresh authoritative state before acting.";
    }
    setClearingRunning(false);
  };

  const loadClearingSnapshot = async (marketId) => {
    const requestNumber = ++clearingSnapshotRequest;
    try {
      const response = await requestJSON(
        `/api/product-v1/markets/${encodeURIComponent(marketId)}/clearing`,
        { headers: {} },
      );
      if (requestNumber !== clearingSnapshotRequest || currentClearingMarketId !== marketId) {
        return;
      }
      if (response.status === 404) {
        forgetClearingSelection();
        setClearingRunning(false);
        if (clearingActionStatus) {
          clearingActionStatus.textContent =
            "The server returned 404. Only the remembered clearing selection was cleared.";
        }
        return;
      }
      if (!response.ok) throw new Error("The authoritative clearing snapshot was unavailable.");
      renderClearingSnapshot(response.payload);
    } catch (error) {
      if (requestNumber !== clearingSnapshotRequest) return;
      if (clearingSnapshot) clearingSnapshot.hidden = true;
      if (clearingActionStatus) {
        clearingActionStatus.textContent =
          error instanceof Error
            ? error.message
            : "The authoritative clearing snapshot was unavailable.";
      }
      setClearingRunning(false);
    }
  };

  const selectClearingMarket = (marketId) => {
    clearRuntimeAuthorityPresentation();
    currentClearingMarketId = marketId;
    currentClearingState = null;
    clearingMarketList?.querySelectorAll("button").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.marketId === marketId));
    });
    if (clearingSnapshot) clearingSnapshot.hidden = true;
    if (clearingActionStatus) {
      clearingActionStatus.textContent = "Loading authoritative clearing snapshot.";
    }
    setClearingRunning(true);
    loadClearingSnapshot(marketId);
  };

  const renderClearingMarkets = (markets) => {
    if (!clearingMarketList) return;
    clearingMarketList.replaceChildren();
    if (!Array.isArray(markets) || markets.length === 0) {
      const empty = document.createElement("p");
      empty.className = "clearing-empty-offers";
      empty.textContent = "No persisted runtime markets are available.";
      clearingMarketList.append(empty);
      return;
    }
    markets.forEach((market) => {
      const button = document.createElement("button");
      const title = document.createElement("strong");
      const detail = document.createElement("small");
      button.type = "button";
      button.className = "clearing-market-choice";
      button.dataset.marketId = String(market.market_id);
      button.setAttribute("aria-pressed", "false");
      title.textContent = String(market.market_id);
      detail.textContent = `${String(market.state)} · ${String(market.submitted_offer_count)} SUBMITTED · ${String(market.requested_quantity)} REQUESTED`;
      button.append(title, detail);
      button.addEventListener("click", () => selectClearingMarket(String(market.market_id)));
      clearingMarketList.append(button);
    });
  };

  const loadClearingMarkets = async (preferredMarketId = null) => {
    setClearingRunning(true);
    if (clearingActionStatus) {
      clearingActionStatus.textContent = "Discovering persisted open and closed markets.";
    }
    try {
      const response = await requestJSON("/api/product-v1/markets", { headers: {} });
      if (!response.ok || !Array.isArray(response.payload.markets)) {
        throw new Error("Runtime market discovery failed closed.");
      }
      renderClearingMarkets(response.payload.markets);
      let rememberedMarketId = preferredMarketId;
      if (!rememberedMarketId) {
        try {
          rememberedMarketId = window.localStorage.getItem(
            "clear-product-clearing-market-id",
          );
        } catch (_error) {
          // Selection remains explicit when browser storage is unavailable.
        }
      }
      const rememberedMarket = response.payload.markets.find(
        (market) => String(market.market_id) === rememberedMarketId,
      );
      if (rememberedMarket) {
        selectClearingMarket(String(rememberedMarket.market_id));
        return;
      }
      if (rememberedMarketId) {
        currentClearingMarketId = rememberedMarketId;
        await loadClearingSnapshot(rememberedMarketId);
        return;
      }
      if (response.payload.markets.length > 0) {
        selectClearingMarket(String(response.payload.markets[0].market_id));
        return;
      }
      setClearingRunning(false);
      if (clearingActionStatus) {
        clearingActionStatus.textContent = "No persisted runtime market exists yet.";
      }
    } catch (error) {
      if (clearingActionStatus) {
        clearingActionStatus.textContent =
          error instanceof Error ? error.message : "Runtime market discovery failed closed.";
      }
      setClearingRunning(false);
    }
  };

  const reconcileClearingClose = async (marketId) => {
    try {
      const response = await requestJSON(
        `/api/product-v1/markets/${encodeURIComponent(marketId)}/clearing`,
        { headers: {} },
      );
      if (response.status === 404) {
        forgetClearingSelection();
        if (clearingActionStatus) {
          clearingActionStatus.textContent =
            "The server returned 404. Only the remembered clearing selection was cleared.";
        }
        setClearingRunning(false);
        return;
      }
      if (!response.ok || !response.payload?.market) {
        renderClearingNotConfirmed();
        return;
      }
      if (response.payload.market.state === "CLOSED") {
        renderClearingSnapshot(response.payload);
        return;
      }
      if (response.payload.market.state === "OPEN") {
        renderClearingSnapshot(response.payload);
        if (clearingActionStatus) {
          clearingActionStatus.textContent =
            "CLOSE NOT OBSERVED COMPLETE · deliberate retry is available.";
        }
        return;
      }
    } catch (_error) {
      // The close outcome remains unknown until an authoritative GET succeeds.
    }
    renderClearingNotConfirmed();
  };

  if (closeClearingMarket instanceof HTMLButtonElement) {
    closeClearingMarket.addEventListener("click", async () => {
      if (clearingRunning || currentClearingState !== "OPEN" || !currentClearingMarketId) {
        return;
      }
      const marketId = currentClearingMarketId;
      setClearingRunning(true);
      if (clearingActionStatus) {
        clearingActionStatus.textContent =
          "CLOSING · deterministic production allocation · zero AI calls";
      }
      try {
        await requestJSON(`/api/product-v1/markets/${encodeURIComponent(marketId)}/close`, {
          method: "POST",
          body: "{}",
        });
      } catch (_error) {
        // Response loss is reconciled with one authoritative GET below.
      }
      await reconcileClearingClose(marketId);
    });
  }

  if (refreshClearingMarkets instanceof HTMLButtonElement) {
    refreshClearingMarkets.addEventListener("click", () => {
      if (clearingRunning) return;
      loadClearingMarkets(currentClearingMarketId);
    });
  }

  if (runtimeTamperButton instanceof HTMLButtonElement) {
    runtimeTamperButton.addEventListener("click", async () => {
      if (authorityRunning || currentClearingState !== "CLOSED" || !currentClearingMarketId) {
        return;
      }
      const marketId = currentClearingMarketId;
      setAuthorityRunning(true);
      resetRuntimeTamper();
      const requestGeneration = tamperRequestGeneration;
      try {
        const response = await requestJSON(
          `/api/product-v1/markets/${encodeURIComponent(marketId)}/authority/tamper`,
          { method: "POST", body: "{}" },
        );
        if (
          requestGeneration !== tamperRequestGeneration ||
          currentClearingMarketId !== marketId
        ) {
          return;
        }
        const payload = response.payload;
        const verifier = payload?.verifier;
        const governor = payload?.governor;
        if (
          !response.ok ||
          payload?.market_id !== marketId ||
          payload.persisted_certificate_mutated !== false ||
          !verifier ||
          typeof verifier !== "object" ||
          Array.isArray(verifier) ||
          verifier.verified !== false ||
          verifier.failure_code !== "POLICY_COMMITMENT_MISMATCH" ||
          !governor ||
          typeof governor !== "object" ||
          Array.isArray(governor) ||
          governor.invoked !== true ||
          governor.authorized !== false ||
          governor.failure_code !== tamperGovernorFailureCode ||
          governor.execution_plan_created !== false ||
          governor.persistent_reservation_created !== false ||
          payload.provider_invoked !== false ||
          payload.truth_class !== "DETERMINISTIC FIXTURE" ||
          typeof payload.altered_copy_authority !== "string" ||
          payload.altered_copy_authority.trim().length === 0 ||
          typeof payload.altered_copy_money_action !== "string" ||
          payload.altered_copy_money_action.trim().length === 0
        ) {
          throw new Error("The controlled tamper path failed closed.");
        }
        setRuntimeTamperText("verifier-failure-code", verifier.failure_code);
        setRuntimeTamperText("governor-failure-code", governor.failure_code);
        setRuntimeTamperText("control-copy", payload.altered_copy_authority);
        setRuntimeTamperText("money-copy", payload.altered_copy_money_action);
        if (runtimeTamperResult) runtimeTamperResult.hidden = false;
      } catch (error) {
        if (
          requestGeneration !== tamperRequestGeneration ||
          currentClearingMarketId !== marketId
        ) {
          return;
        }
        if (runtimeAuthorityStatus) {
          runtimeAuthorityStatus.textContent =
            error instanceof Error
              ? error.message
              : "The controlled tamper path failed closed.";
        }
      } finally {
        if (
          requestGeneration === tamperRequestGeneration &&
          currentClearingMarketId === marketId
        ) {
          setAuthorityRunning(false);
        }
      }
    });
  }

  if (runtimeAuthorizeButton instanceof HTMLButtonElement) {
    runtimeAuthorizeButton.addEventListener("click", async () => {
      if (authorityRunning || currentClearingState !== "CLOSED" || !currentClearingMarketId) {
        return;
      }
      const marketId = currentClearingMarketId;
      const requestGeneration = ++authorizeRequestGeneration;
      setAuthorityRunning(true);
      if (runtimeAuthorityStatus) {
        runtimeAuthorityStatus.textContent = "Requesting one explicit Money Governor authorization.";
      }
      try {
        const response = await requestJSON(
          `/api/product-v1/markets/${encodeURIComponent(marketId)}/authority/authorize`,
          { method: "POST", body: "{}" },
        );
        if (
          requestGeneration !== authorizeRequestGeneration ||
          currentClearingMarketId !== marketId
        ) {
          return;
        }
        if (!response.ok) {
          const code = response.payload?.error?.code || response.payload?.code || "AUTHORIZATION_FAILED";
          if (runtimeAuthorityStatus) runtimeAuthorityStatus.textContent = String(code);
          return;
        }
        renderRuntimeAuthority(response.payload);
      } catch (_error) {
        if (
          requestGeneration !== authorizeRequestGeneration ||
          currentClearingMarketId !== marketId
        ) {
          return;
        }
        if (runtimeAuthorityStatus) {
          runtimeAuthorityStatus.textContent =
            "Authorization outcome not confirmed. Re-reading server authority.";
        }
        await loadRuntimeAuthority(marketId, { reconciliation: true });
      } finally {
        if (
          requestGeneration === authorizeRequestGeneration &&
          currentClearingMarketId === marketId
        ) {
          setAuthorityRunning(false);
        }
      }
    });
  }

  if (runtimeRazorpayButton instanceof HTMLButtonElement) {
    runtimeRazorpayButton.addEventListener("click", async () => {
      if (
        authorityRunning ||
        razorpayRunning ||
        currentClearingState !== "CLOSED" ||
        !currentClearingMarketId ||
        !currentRuntimeExecutionId ||
        !Number.isSafeInteger(currentRuntimeOrderAmount)
      ) {
        return;
      }
      const marketId = currentClearingMarketId;
      const executionId = currentRuntimeExecutionId;
      const orderAmount = currentRuntimeOrderAmount;
      const requestGeneration = ++razorpayRequestGeneration;
      setRazorpayRunning(true);
      if (runtimeRazorpayStatus) {
        runtimeRazorpayStatus.textContent =
          "Requesting one explicit Governor-gated Razorpay Test Mode order action.";
      }
      try {
        const response = await requestJSON(
          `/api/product-v1/markets/${encodeURIComponent(marketId)}/authority/razorpay-order`,
          { method: "POST", body: "{}" },
        );
        if (
          requestGeneration !== razorpayRequestGeneration ||
          currentClearingMarketId !== marketId ||
          currentRuntimeExecutionId !== executionId
        ) {
          return;
        }
        const payload = response.payload;
        if (!response.ok) {
          const code = payload?.error?.code || payload?.code || "RAZORPAY_ORDER_FAILED";
          if (runtimeRazorpayStatus) runtimeRazorpayStatus.textContent = String(code);
          return;
        }
        if (
          payload?.result !== "SUCCESS" ||
          payload.market_id !== marketId ||
          payload.mode !== "RAZORPAY TEST MODE" ||
          payload.observation !== "CURRENT-RUN PROVIDER OBSERVATION" ||
          !["CREATED", "EXISTING", "RECOVERED"].includes(payload.resolution) ||
          typeof payload.provider_order_id !== "string" ||
          payload.execution_id !== executionId ||
          payload.order_amount_paise !== orderAmount ||
          payload.currency !== "INR" ||
          payload.receipt !== executionId ||
          payload.provider_contacted !== true
        ) {
          throw new Error("The current-run provider observation failed closed.");
        }
        const state = {
          CREATED: "ORDER CREATED",
          EXISTING: "EXISTING ORDER RESOLVED",
          RECOVERED: "ORDER RECOVERED",
        }[payload.resolution];
        setRuntimeRazorpayText("state", state);
        setRuntimeRazorpayText(
          "observation",
          payload.resolution === "EXISTING"
            ? "CURRENT-RUN PROVIDER OBSERVATION · PROVIDER-BACKED RETRIEVAL"
            : "CURRENT-RUN PROVIDER OBSERVATION",
        );
        setRuntimeRazorpayText("resolution", payload.resolution);
        setRuntimeRazorpayText("provider-order-id", payload.provider_order_id);
        setRuntimeRazorpayText("execution-id", payload.execution_id);
        setRuntimeRazorpayText("order-amount", formatInrFromPaise(payload.order_amount_paise));
        setRuntimeRazorpayText("order-amount-raw", `${payload.order_amount_paise} paise · INR`);
        setRuntimeRazorpayText("receipt", payload.receipt);
        if (runtimeRazorpayResult) runtimeRazorpayResult.hidden = false;
        const label = runtimeRazorpayButton.querySelector("span");
        if (label) label.textContent = "Resolve existing Razorpay order";
        if (runtimeRazorpayStatus) {
          runtimeRazorpayStatus.textContent =
            "Provider order facts were validated against the persisted ExecutionPlanV1.";
        }
      } catch (error) {
        if (
          requestGeneration !== razorpayRequestGeneration ||
          currentClearingMarketId !== marketId ||
          currentRuntimeExecutionId !== executionId
        ) {
          return;
        }
        if (runtimeRazorpayStatus) {
          runtimeRazorpayStatus.textContent =
            error instanceof Error
              ? error.message
              : "The Razorpay Test Mode order action failed closed.";
        }
      } finally {
        if (
          requestGeneration === razorpayRequestGeneration &&
          currentClearingMarketId === marketId &&
          currentRuntimeExecutionId === executionId
        ) {
          setRazorpayRunning(false);
        }
      }
    });
  }

  const renderInterpretationFailure = (payload) => {
    currentMarketId = null;
    if (interpretationPanel) interpretationPanel.hidden = false;
    if (successPanel) successPanel.hidden = true;
    if (validationState) validationState.textContent = `${String(payload.result || "FAILED")} · NOT FROZEN`;
    if (errorCode) {
      errorCode.hidden = false;
      errorCode.textContent = String(payload.code || payload.error?.code || "PRODUCT_REQUEST_FAILED");
    }
    if (diagnosticCode) {
      const value = payload.diagnostic_code;
      diagnosticCode.hidden = typeof value !== "string" || value.length === 0;
      diagnosticCode.textContent = diagnosticCode.hidden ? "" : value;
    }
    renderCandidateDiagnostic(payload.candidate_diagnostic);
    if (message) message.textContent = String(payload.message || payload.error?.message || "The request failed closed.");
    if (actionStatus) actionStatus.textContent = "No market authority was created. You may retry with a new draft.";
    if (newDraftButton instanceof HTMLButtonElement) newDraftButton.hidden = false;
    setStage("interpretation");
  };

  const renderFreezeNotCompleted = (messageText) => {
    if (interpretationPanel) interpretationPanel.hidden = false;
    if (successPanel) successPanel.hidden = false;
    if (diagnosticCode) diagnosticCode.hidden = true;
    if (candidateDiagnostic) {
      candidateDiagnostic.hidden = true;
      candidateDiagnostic.replaceChildren();
    }
    if (validationState) validationState.textContent = "NOT FROZEN · OUTCOME NOT CONFIRMED";
    if (errorCode) {
      errorCode.hidden = false;
      errorCode.textContent = "FREEZE OUTCOME NOT CONFIRMED";
    }
    if (message) message.textContent = messageText;
    if (actionStatus) actionStatus.textContent = "Freeze outcome not confirmed. Reconcile this market before continuing.";
    if (newDraftButton instanceof HTMLButtonElement) newDraftButton.hidden = false;
    setStage("freeze");
  };

  const reconcileFreezeOutcome = async () => {
    if (currentMarketId === null) return;
    const marketId = currentMarketId;
    try {
      const response = await requestJSON(
        `/api/product-v1/markets/${encodeURIComponent(marketId)}`,
        { headers: {} },
      );
      if (response.ok && response.status === 200 && response.payload.buyer_policy_frozen === true) {
        renderFrozen(response.payload);
        return;
      }
      if (response.status === 404) {
        if (interpretationPanel) interpretationPanel.hidden = false;
        if (successPanel) successPanel.hidden = false;
        if (diagnosticCode) diagnosticCode.hidden = true;
        if (candidateDiagnostic) {
          candidateDiagnostic.hidden = true;
          candidateDiagnostic.replaceChildren();
        }
        if (validationState) validationState.textContent = "NOT FROZEN · RETRY AVAILABLE";
        if (errorCode) errorCode.hidden = true;
        if (message) message.textContent = "The server confirmed that this market was not created. Review the interpretation and deliberately retry the freeze.";
        if (actionStatus) actionStatus.textContent = "No market authority exists for this draft. You may deliberately retry the freeze.";
        if (newDraftButton instanceof HTMLButtonElement) newDraftButton.hidden = false;
        setStage("freeze");
        return;
      }
    } catch (_error) {
      // Preserve the market ID and report an unknown outcome below.
    }
    renderFreezeNotCompleted(
      "The browser could not determine whether the freeze completed. No browser authority is inferred. Reconcile this market before continuing.",
    );
  };

  const renderInterpretation = (payload) => {
    const interpreted = payload.interpretation;
    if (!interpreted || payload.result !== "SUCCESS" || payload.state !== "INTERPRETED") {
      renderInterpretationFailure(payload);
      return;
    }
    if (interpretationPanel) interpretationPanel.hidden = false;
    if (successPanel) successPanel.hidden = false;
    if (validationState) validationState.textContent = "VALIDATED · NOT YET MARKET POLICY";
    if (errorCode) errorCode.hidden = true;
    if (diagnosticCode) diagnosticCode.hidden = true;
    if (candidateDiagnostic) {
      candidateDiagnostic.hidden = true;
      candidateDiagnostic.replaceChildren();
    }
    if (message) message.textContent = "Review the interpreted commercial semantics. The model response remains advisory until you freeze it.";
    setText('[data-buyer-field="requested-quantity"]', interpreted.requested_quantity);
    setText('[data-buyer-field="minimum-quantity"]', interpreted.minimum_acceptable_quantity);
    setText('[data-buyer-field="max-suppliers"]', interpreted.max_winners);
    setText(
      '[data-buyer-field="budget"]',
      formatInrFromPaise(interpreted.max_total_payment_paise),
    );
    setText('[data-buyer-field="provider-name"]', payload.provider_name);
    setText('[data-buyer-field="model"]', payload.model);
    renderRuleList('[data-buyer-field="hard-rules"]', interpreted.hard_constraints);
    renderRuleList('[data-buyer-field="soft-rules"]', interpreted.soft_preferences);
    if (actionStatus) actionStatus.textContent = "Interpretation validated. Explicit buyer freeze is still required.";
    if (newDraftButton instanceof HTMLButtonElement) newDraftButton.hidden = false;
    setStage("freeze");
  };

  const productErrorPayload = (error) => ({
    result: "FAILED",
    code: "NETWORK_OR_SERVER_FAILURE",
    message: error instanceof Error ? error.message : "The product request failed closed.",
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (running || currentMarketId !== null) return;
    clearInterpretation();
    setStage("interpretation");
    setRunning(true, "Interpreting · advisory only");
    if (actionStatus) actionStatus.textContent = "RUNNING · USER INITIATED";
    try {
      const merchantIds = checkedMerchantIds();
      const draftResponse = await requestJSON("/api/product-v1/buyer-drafts", {
        method: "POST",
        body: JSON.stringify({
          buyer_text: buyerText.value,
          eligible_merchant_ids: merchantIds,
          offer_deadline: canonicalDeadline(deadline.value),
        }),
      });
      if (!draftResponse.ok) {
        renderInterpretationFailure(draftResponse.payload);
        return;
      }
      currentMarketId = String(draftResponse.payload.market_id);
      const interpretResponse = await requestJSON(
        `/api/product-v1/buyer-drafts/${encodeURIComponent(currentMarketId)}/interpret`,
        { method: "POST", body: "{}" },
      );
      if (!interpretResponse.ok || interpretResponse.payload.result !== "SUCCESS") {
        renderInterpretationFailure(interpretResponse.payload);
        return;
      }
      renderInterpretation(interpretResponse.payload);
    } catch (error) {
      renderInterpretationFailure(productErrorPayload(error));
    } finally {
      setRunning(false, currentMarketId === null ? "Interpret request" : "Interpretation complete");
    }
  });

  const renderFrozen = (payload) => {
    currentMarketId = String(payload.market_id);
    if (interpretationPanel) interpretationPanel.hidden = true;
    if (frozenPanel) frozenPanel.hidden = false;
    setText('[data-frozen-field="market-state"]', payload.market_state);
    setText('[data-frozen-field="market-id"]', payload.market_id);
    setText('[data-frozen-field="commitment"]', payload.buyer_policy_commitment_sha256);
    if (actionStatus) {
      if (payload.market_state === "OPEN") {
        actionStatus.textContent = "Buyer policy frozen. The persisted runtime market is open.";
      } else if (payload.market_state === "CLOSED") {
        actionStatus.textContent = "Buyer policy frozen. The persisted runtime market is closed.";
      } else {
        actionStatus.textContent =
          "Buyer policy frozen. The authoritative runtime market state is unavailable.";
      }
    }
    if (newDraftButton instanceof HTMLButtonElement) newDraftButton.hidden = false;
    setStage("market");
    try {
      window.localStorage.setItem("clear-product-market-id", currentMarketId);
    } catch (_error) {
      // The persisted market remains server-authoritative without browser storage.
    }
    setRunning(false, "Interpretation complete");
  };

  const restoreFrozenMarket = async () => {
    let marketId;
    try {
      marketId = window.localStorage.getItem("clear-product-market-id");
    } catch (_error) {
      return;
    }
    if (!marketId) return;
    try {
      const response = await requestJSON(
        `/api/product-v1/markets/${encodeURIComponent(marketId)}`,
        { headers: {} },
      );
      if (response.status === 404) {
        window.localStorage.removeItem("clear-product-market-id");
        return;
      }
      if (!response.ok || response.payload.buyer_policy_frozen !== true) {
        if (actionStatus) {
          actionStatus.textContent = "The persisted market outcome could not be confirmed. No browser authority is inferred.";
        }
        return;
      }
      renderFrozen(response.payload);
    } catch (_error) {
      if (actionStatus) {
        actionStatus.textContent = "The persisted market could not be reloaded. No browser authority was inferred.";
      }
    }
  };

  if (freezeButton instanceof HTMLButtonElement) {
    freezeButton.addEventListener("click", async () => {
      if (running || currentMarketId === null) return;
      setRunning(true, "Interpretation complete");
      freezeButton.querySelector("span").textContent = "Freezing buyer policy";
      if (actionStatus) actionStatus.textContent = "FREEZING · exact reviewed BuyerPolicyV2 bytes · no AI call";
      try {
        const response = await requestJSON(
          `/api/product-v1/buyer-drafts/${encodeURIComponent(currentMarketId)}/freeze`,
          { method: "POST", body: "{}" },
        );
        if (!response.ok || response.payload.buyer_policy_frozen !== true) {
          await reconcileFreezeOutcome();
          return;
        }
        renderFrozen(response.payload);
      } catch (_error) {
        await reconcileFreezeOutcome();
      } finally {
        freezeButton.querySelector("span").textContent = "Freeze buyer policy";
        setRunning(false, "Interpretation complete");
      }
    });
  }

  if (newDraftButton instanceof HTMLButtonElement) {
    newDraftButton.addEventListener("click", () => {
      currentMarketId = null;
      try {
        window.localStorage.removeItem("clear-product-market-id");
      } catch (_error) {
        // Starting a new in-memory draft remains available without browser storage.
      }
      form.reset();
      merchantList?.querySelectorAll('input[type="checkbox"]').forEach((input) => {
        input.checked = true;
      });
      clearInterpretation();
      setRunning(false, "Interpret request");
      newDraftButton.hidden = true;
      if (actionStatus) actionStatus.textContent = "New draft ready. No market authority exists yet.";
      setStage("draft");
    });
  }

  if (deadline instanceof HTMLInputElement) {
    const initial = new Date(Date.now() + 60 * 60 * 1000);
    initial.setMinutes(Math.ceil(initial.getMinutes() / 5) * 5, 0, 0);
    const local = new Date(initial.getTime() - initial.getTimezoneOffset() * 60_000);
    deadline.value = local.toISOString().slice(0, 16);
    deadline.min = new Date(Date.now() - new Date().getTimezoneOffset() * 60_000)
      .toISOString()
      .slice(0, 16);
  }

  reconcileActiveWorkspace = (view) => {
    if (view === "merchant" && currentMerchantId && !merchantRunning) {
      loadMerchantInbox(currentMerchantId);
    }
    if (view === "buyer" && !running) {
      restoreFrozenMarket();
    }
  };

  setStage("draft");
  loadMerchants();
  loadClearingMarkets();
  restoreFrozenMarket();
})();
