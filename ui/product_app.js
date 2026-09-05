(() => {
  "use strict";

  const viewButtons = [...document.querySelectorAll("[data-view-target]")];
  const viewPanels = [...document.querySelectorAll("[data-app-view]")];
  const evidenceNav = document.querySelector("[data-evidence-nav]");
  const menuToggle = document.querySelector(".menu-toggle");
  const skipLink = document.querySelector(".skip-link");
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

  let currentMarketId = null;
  let running = false;
  let currentMerchantId = null;
  let currentMerchantMarketId = null;
  let currentMerchantInbox = null;
  let merchantRunning = false;
  let merchantInboxRequest = 0;

  const setText = (selector, value) => {
    const target = document.querySelector(selector);
    if (target) target.textContent = String(value);
  };

  const viewFromHash = () => {
    if (["#buyer", "#buyer-workspace"].includes(window.location.hash)) return "buyer";
    if (["#merchant", "#merchant-workspace"].includes(window.location.hash)) return "merchant";
    if (["#evidence", "#top", "#demo", "#supporting", "#architecture"].includes(window.location.hash)) {
      return "evidence";
    }
    return null;
  };

  const setView = (view, { hashMode = "replace", preserveHash = false } = {}) => {
    const selected = ["buyer", "merchant", "evidence"].includes(view) ? view : "buyer";
    document.body.dataset.view = selected;
    viewPanels.forEach((panel) => {
      panel.hidden = panel.dataset.appView !== selected;
    });
    viewButtons.forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.viewTarget === selected));
    });
    if (evidenceNav) evidenceNav.hidden = selected !== "evidence";
    if (menuToggle) menuToggle.hidden = selected !== "evidence";
    if (skipLink instanceof HTMLAnchorElement) {
      skipLink.href =
        selected === "evidence"
          ? "#demo"
          : selected === "merchant"
            ? "#merchant-workspace"
            : "#buyer-workspace";
      skipLink.textContent = selected === "evidence" ? "Skip to demo" : "Skip to workspace";
    }
    try {
      window.localStorage.setItem("clear-product-view", selected);
    } catch (_error) {
      // View selection remains functional when storage is unavailable.
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

  viewButtons.forEach((button) => {
    button.addEventListener("click", () =>
      setView(button.dataset.viewTarget, { hashMode: "push" }),
    );
  });

  const initialView = (() => {
    try {
      return window.localStorage.getItem("clear-product-view");
    } catch (_error) {
      return null;
    }
  })();
  const initialHashView = viewFromHash();
  setView(initialHashView || (["merchant", "evidence"].includes(initialView) ? initialView : "buyer"), {
    preserveHash: initialHashView !== null,
  });

  const routeFromHash = () => {
    const hashView = viewFromHash();
    setView(hashView || document.body.dataset.view, { preserveHash: hashView !== null });
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
    setMerchantText("minimum-price", merchant.minimum_allowed_unit_price_paise);
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
        detail.textContent = String(line[field]);
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
        ["PROPOSED UNIT PRICE · PAISE", "proposed_unit_price_paise"],
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
        ["UNIT PRICE · PAISE", "proposed_unit_price_paise"],
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
    setMerchantMarketText("budget", market.max_total_payment_paise);
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
    setText('[data-buyer-field="budget"]', interpreted.max_total_payment_paise);
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
    if (actionStatus) actionStatus.textContent = "Buyer policy frozen. A persisted runtime market is now open.";
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

  setStage("draft");
  loadMerchants();
  restoreFrozenMarket();
})();
