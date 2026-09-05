const runButton = document.querySelector("#run-demo");
const tamperButton = document.querySelector("#reveal-tamper");
const runStatus = document.querySelector("#run-status");
const failurePanel = document.querySelector("#demo-failure");
const validResult = document.querySelector("#valid-result");
const tamperResult = document.querySelector("#tamper-result");
const evidenceSection = document.querySelector("#evidence-section");
const historicalSection = document.querySelector("#historical-section");
const limitationsSection = document.querySelector("#limitations-section");
const validPath = document.querySelector("#valid-path");
const tamperPath = document.querySelector("#tamper-path");

let currentPresentation = null;

function element(tagName, className, text) {
  const node = document.createElement(tagName);
  if (className) {
    node.className = className;
  }
  if (text !== undefined) {
    node.textContent = String(text);
  }
  return node;
}

function evidenceBadge(label) {
  const evidenceClasses = new Set([
    "REAL LOCAL PRODUCTION LOGIC",
    "DETERMINISTIC FIXTURE",
    "FAKE/CONTROLLED EXTERNAL TRANSPORT",
    "HISTORICAL LIVE EVIDENCE ONLY",
    "NOT DEMONSTRATED",
  ]);
  if (!evidenceClasses.has(label)) {
    throw new Error("unknown evidence class");
  }
  const badge = element("span", "evidence-badge", label);
  const tones = {
    "REAL LOCAL PRODUCTION LOGIC": "production",
    "DETERMINISTIC FIXTURE": "fixture",
    "FAKE/CONTROLLED EXTERNAL TRANSPORT": "fixture",
    "HISTORICAL LIVE EVIDENCE ONLY": "fixture",
    "NOT DEMONSTRATED": "muted",
  };
  badge.dataset.tone = tones[label] || "muted";
  return badge;
}

function labeledValue(label, value, className = "") {
  const block = element("div", `labeled-value ${className}`.trim());
  block.append(element("span", "value-label", label), element("strong", "value", value));
  return block;
}

function factRow(label, value) {
  const row = element("div", "fact-row");
  row.append(element("span", "fact-label", label), element("span", "fact-value", value));
  return row;
}

function step(number, kicker, title) {
  const item = element("li", "proof-step");
  const marker = element("div", "step-marker", number);
  const body = element("article", "step-body");
  const heading = element("div", "step-heading");
  heading.append(element("p", "eyebrow", kicker), element("h3", "", title));
  body.append(heading);
  item.append(marker, body);
  return { item, body };
}

function renderIntent(data, fixtureContext) {
  const { item, body } = step("01", "Intent", "Advisory input becomes frozen policy.");
  const transition = element("div", "authority-transition");
  const input = element("div", "labeled-value");
  input.append(
    element("span", "value-label", "INPUT CONTEXT"),
    factRow("Requested quantity", fixtureContext.requested_quantity),
    factRow("Max winners", fixtureContext.max_winners),
    element("p", "supporting-copy", data.advisory_boundary),
    evidenceBadge(data.candidate_and_context_evidence),
  );
  const policy = labeledValue("DETERMINISTIC FREEZE", data.policy_type);
  policy.append(
    element("p", "supporting-copy", "The real freeze path produced the authoritative buyer policy."),
    evidenceBadge(data.policy_freeze_evidence),
  );
  transition.append(input, element("span", "transition-arrow", "↓"), policy);
  body.append(transition);
  return item;
}

function renderSupply(data, fixtureContext) {
  const { item, body } = step("02", "Authenticated supply", "Seller inputs become authenticated offers.");
  const merchants = element("div", "merchant-ledger");
  fixtureContext.merchants.forEach((merchant) => {
    const merchantBlock = element("article", "merchant-line");
    merchantBlock.append(
      element("h4", "", merchant.display_name),
      factRow("Capacity", merchant.capacity),
      factRow("Unit price", `${merchant.unit_price_paise} paise`),
      evidenceBadge(merchant.evidence),
    );
    merchants.append(merchantBlock);
  });
  const authenticated = element("div", "step-conclusion");
  authenticated.append(
    element("span", "transition-arrow", "↓"),
    element("strong", "", `${data.authenticated_offer_count} authenticated offers`),
    evidenceBadge(data.offer_evidence),
  );
  body.append(merchants, authenticated);
  return item;
}

function renderClearing(data) {
  const { item, body } = step("03", "Deterministic clearing", "The economic agreement is computed.");
  const metrics = element("div", "clearing-metrics");
  const requested = labeledValue("REQUESTED INPUT", data.requested_quantity);
  requested.append(evidenceBadge(data.requested_quantity_evidence));
  metrics.append(
    requested,
    labeledValue("FULFILLED", data.fulfilled_quantity),
    labeledValue("WINNERS", data.winner_count),
    labeledValue("TOTAL PAYMENT", `${data.total_payment_paise} paise`, "metric-wide"),
  );
  const allocatorOutput = element("div", "allocator-output");
  const winnerIds = element("div", "winner-ids");
  data.winner_merchant_ids.forEach((winnerId) => {
    winnerIds.append(element("code", "merchant-id", winnerId));
  });
  allocatorOutput.append(
    element("span", "value-label", "ALLOCATOR-SELECTED WINNER IDS"),
    winnerIds,
    element("strong", "status-technical", data.allocation_status),
    evidenceBadge(data.computed_evidence),
  );
  body.append(metrics, allocatorOutput);
  return item;
}

function renderProof(data) {
  const { item, body } = step("04", "Proof", "An independently verifiable certificate carries the result.");
  const certificate = element("div", "certificate-block");
  certificate.append(
    element("span", "value-label", data.certificate_type),
    element("code", "digest", data.certificate_digest_sha256),
  );
  const badges = element("div", "badge-row");
  badges.append(evidenceBadge(data.construction_evidence), evidenceBadge(data.verification_evidence));
  const conclusion = element("div", "step-conclusion");
  conclusion.append(
    element("span", "transition-arrow", "↓"),
    element("strong", "status-verified", "Independent verification succeeds"),
    badges,
  );
  body.append(certificate, conclusion);
  return item;
}

function renderAuthority(data) {
  const { item, body } = step("05", "Money authority", "Only verified proof reaches the execution gate.");
  const gate = element("div", "governor-gate");
  gate.append(
    element("span", "gate-input", "VALID CERTIFICATE"),
    element("span", "transition-arrow", "↓"),
    element("strong", "gate-name", data.authority),
    element("span", "transition-arrow", "↓"),
    element("span", "gate-output", data.execution_reserved ? "EXECUTION RESERVED" : "CLOSED"),
  );
  const conclusion = element("div", "step-conclusion");
  conclusion.append(evidenceBadge(data.evidence));
  body.append(gate, conclusion);
  return item;
}

function renderProvider(data) {
  const { item, body } = step("06", "Controlled provider path", "Idempotent order resolution is exercised locally.");
  const orders = element("div", "order-sequence");
  data.orders.forEach((order, index) => {
    const orderBlock = element("article", "order-resolution");
    orderBlock.append(
      element("span", "value-label", index === 0 ? "FIRST ATTEMPT" : "SECOND IDENTICAL CALL"),
      element("strong", "resolution", order.resolution),
      element("p", "supporting-copy", order.copy),
      factRow("Resolution", order.resolution_evidence),
      factRow("Provider boundary", order.provider_boundary),
    );
    orders.append(orderBlock);
    if (index < data.orders.length - 1) {
      orders.append(element("span", "order-arrow", "↓"));
    }
  });
  const counters = element("div", "transport-counters");
  counters.append(
    element("p", "value-label", data.counter_label),
    labeledValue("POST", data.provider_post_count),
    labeledValue("GET", data.provider_get_count),
  );
  body.append(orders, counters);
  return item;
}

function renderValidPath(presentation) {
  const data = presentation.valid_path;
  validPath.replaceChildren(
    renderIntent(data.intent, presentation.fixture_context),
    renderSupply(data.authenticated_supply, presentation.fixture_context),
    renderClearing(data.deterministic_clearing),
    renderProof(data.proof),
    renderAuthority(data.money_authority),
    renderProvider(data.controlled_provider_path),
  );
  document.querySelector("#demo-version").textContent = presentation.demo_version;
}

function renderEvidence(labels) {
  const container = document.querySelector("#evidence-labels");
  container.replaceChildren(...labels.map((label) => evidenceBadge(label)));
}

function renderHistorical(data) {
  document.querySelector("#historical-label").textContent = data.label;
  document.querySelector("#historical-claim").textContent = data.claim;
  document.querySelector("#current-run-notice").textContent = data.current_run_notice;
}

function renderLimitations(limitations) {
  const list = document.querySelector("#limitations");
  list.replaceChildren(
    ...limitations.map((limitation) => {
      const item = element("li", "");
      item.append(element("span", "", limitation.claim), evidenceBadge(limitation.evidence));
      return item;
    }),
  );
}

function tamperSequenceItem(text, detail) {
  const item = element("li", "tamper-step");
  item.append(element("strong", "", text));
  if (detail) {
    item.append(element("span", "", detail));
  }
  return item;
}

function renderTamper(data) {
  const counters = `POST ${data.provider_post_count} / GET ${data.provider_get_count}`;
  tamperPath.replaceChildren(
    tamperSequenceItem(data.altered_claim, "Certified claim differs from the proof"),
    tamperSequenceItem(data.verifier, data.verification_evidence),
    tamperSequenceItem(data.governor_failure_code, "Certificate rejected"),
    tamperSequenceItem(data.governor_state, data.governor_evidence),
    tamperSequenceItem(data.provider_state, `${data.provider_boundary} · ${counters}`),
  );
  document.querySelector("#tamper-outcome").textContent = data.outcome;
  tamperResult.hidden = false;
  tamperButton.disabled = true;
  tamperButton.setAttribute("aria-expanded", "true");
  tamperResult.scrollIntoView({ behavior: "smooth", block: "start" });
}

function clearPresentation() {
  currentPresentation = null;
  validPath.replaceChildren();
  tamperPath.replaceChildren();
  validResult.hidden = true;
  tamperResult.hidden = true;
  evidenceSection.hidden = true;
  historicalSection.hidden = true;
  limitationsSection.hidden = true;
  failurePanel.hidden = true;
  tamperButton.disabled = true;
  tamperButton.setAttribute("aria-expanded", "false");
}

function assertPresentationShape(presentation) {
  if (
    !presentation ||
    presentation.invariant !== "NO VALID CERTIFICATE = NO MONEY ACTION" ||
    !presentation.valid_path ||
    !presentation.tamper_path ||
    !Array.isArray(presentation.evidence_labels)
  ) {
    throw new Error("invalid presentation response");
  }
}

async function runDemo() {
  clearPresentation();
  runButton.disabled = true;
  runButton.setAttribute("aria-busy", "true");
  runStatus.textContent = "Running deterministic local authority path…";
  document.body.dataset.state = "running";

  try {
    const response = await fetch("/api/demo", {
      method: "GET",
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error("demo request failed");
    }
    const presentation = await response.json();
    assertPresentationShape(presentation);
    currentPresentation = presentation;
    renderValidPath(presentation);
    renderEvidence(presentation.evidence_labels);
    renderHistorical(presentation.historical_evidence);
    renderLimitations(presentation.limitations);
    validResult.hidden = false;
    evidenceSection.hidden = false;
    historicalSection.hidden = false;
    limitationsSection.hidden = false;
    tamperButton.disabled = false;
    runStatus.textContent = "Authority path completed from a fresh deterministic run.";
    document.body.dataset.state = "complete";
  } catch (_error) {
    clearPresentation();
    failurePanel.hidden = false;
    runStatus.textContent = "Deterministic authority path unavailable.";
    document.body.dataset.state = "failed";
  } finally {
    runButton.disabled = false;
    runButton.removeAttribute("aria-busy");
  }
}

runButton.addEventListener("click", runDemo);
tamperButton.addEventListener("click", () => {
  if (currentPresentation) {
    renderTamper(currentPresentation.tamper_path);
  }
});
