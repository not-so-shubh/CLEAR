"""Deterministic AgentMarketBench V1 economic comparators."""

from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from itertools import combinations

from clear_market.agentmarketbench.admission import _admit_with_reports
from clear_market.agentmarketbench.method_models import (
    AgentMarketBenchAdmissionV1,
    AgentMarketBenchDecisionLineV1,
    AgentMarketBenchMethodResultV1,
    AgentMarketBenchMethodStatusV1,
)
from clear_market.agentmarketbench.models import (
    AgentMarketBenchBaselineV1,
    AgentMarketBenchMarketInputV1,
    AgentMarketBenchReportedOfferV1,
)
from clear_market.commerce import (
    BuyerPolicyV2,
    CatalogAttributeV2,
    ComparisonOperator,
    HardConstraint,
    SoftPreference,
)
from clear_market.domain import Money
from clear_market.mechanism.v2 import allocate_market_v2
from clear_market.mechanism.v2.contracts import AllocationStatusV2


@dataclass(frozen=True, slots=True)
class _QualifiedLine:
    source_offer_id: str
    merchant_id: str
    sku_id: str
    max_quantity: int
    unit_price_paise: int
    soft_match_count: int
    attributes: tuple[CatalogAttributeV2, ...]
    receipt_order: int

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.merchant_id, self.sku_id, self.source_offer_id)


def _fresh_market_input(value: object) -> AgentMarketBenchMarketInputV1:
    if type(value) is not AgentMarketBenchMarketInputV1:
        raise TypeError("market_input must be exactly an AgentMarketBenchMarketInputV1")
    try:
        return AgentMarketBenchMarketInputV1.model_validate(value)
    except Exception as error:
        raise ValueError("market_input failed fresh validation") from error


def _compare(actual: object, expected: object, operator: ComparisonOperator) -> bool:
    if operator is ComparisonOperator.EQ:
        return actual == expected
    if operator is ComparisonOperator.NE:
        return actual != expected
    if type(actual) is not int or type(expected) is not int:
        return False
    if operator is ComparisonOperator.LT:
        return actual < expected
    if operator is ComparisonOperator.LTE:
        return actual <= expected
    if operator is ComparisonOperator.GT:
        return actual > expected
    if operator is ComparisonOperator.GTE:
        return actual >= expected
    return False


def _attribute_satisfies_rule(
    attributes: tuple[CatalogAttributeV2, ...],
    rule: HardConstraint | SoftPreference,
) -> bool:
    attribute = next(
        (candidate for candidate in attributes if candidate.attribute_key == rule.attribute_key),
        None,
    )
    if attribute is None or attribute.provenance not in rule.allowed_provenance:
        return False
    if attribute.value.value_type is not rule.operand.value_type:
        return False
    return _compare(attribute.value.value, rule.operand.value, rule.operator)


def _hard_qualifies(
    attributes: tuple[CatalogAttributeV2, ...],
    constraints: tuple[HardConstraint, ...],
) -> bool:
    return all(_attribute_satisfies_rule(attributes, rule) for rule in constraints)


def _soft_score(
    attributes: tuple[CatalogAttributeV2, ...],
    preferences: tuple[SoftPreference, ...],
) -> int:
    return sum(_attribute_satisfies_rule(attributes, preference) for preference in preferences)


def _qualified_lines(
    policy: BuyerPolicyV2,
    reports: tuple[AgentMarketBenchReportedOfferV1, ...],
) -> tuple[_QualifiedLine, ...]:
    output: list[_QualifiedLine] = []
    for receipt_order, report in enumerate(reports):
        signed = report.signed_offer
        for line in signed.offer.lines:
            if not _hard_qualifies(line.attributes, policy.market_spec.hard_constraints):
                continue
            output.append(
                _QualifiedLine(
                    source_offer_id=signed.offer.offer_id,
                    merchant_id=signed.offer.merchant_id,
                    sku_id=line.sku_id,
                    max_quantity=min(
                        line.max_offer_quantity,
                        policy.market_spec.requested_quantity,
                    ),
                    unit_price_paise=line.unit_price.amount_paise,
                    soft_match_count=_soft_score(
                        line.attributes,
                        policy.market_spec.soft_preferences,
                    ),
                    attributes=line.attributes,
                    receipt_order=receipt_order,
                )
            )
    return tuple(sorted(output, key=lambda item: item.key))


def _zero_result(
    *,
    method: AgentMarketBenchBaselineV1,
    market_id: str,
    admission: AgentMarketBenchAdmissionV1,
    status: AgentMarketBenchMethodStatusV1 = AgentMarketBenchMethodStatusV1.INFEASIBLE,
) -> AgentMarketBenchMethodResultV1:
    return AgentMarketBenchMethodResultV1(
        method=method,
        market_id=market_id,
        status=status,
        admission=admission,
        fulfilled_quantity=0,
        total_payment=Money(amount_paise=0),
        winner_count=0,
        lines=(),
    )


def _result_from_quantities(
    *,
    method: AgentMarketBenchBaselineV1,
    market_id: str,
    admission: AgentMarketBenchAdmissionV1,
    lines: tuple[_QualifiedLine, ...],
    quantities: tuple[int, ...],
    minimum_quantity: int,
) -> AgentMarketBenchMethodResultV1:
    decisions: list[AgentMarketBenchDecisionLineV1] = []
    for line, quantity in zip(lines, quantities, strict=True):
        if quantity <= 0:
            continue
        unit_payment = Money(amount_paise=line.unit_price_paise)
        decisions.append(
            AgentMarketBenchDecisionLineV1(
                source_offer_id=line.source_offer_id,
                merchant_id=line.merchant_id,
                sku_id=line.sku_id,
                allocated_quantity=quantity,
                unit_payment=unit_payment,
                line_payment=unit_payment.checked_multiply(quantity),
            )
        )
    fulfilled = sum(line.allocated_quantity for line in decisions)
    total = sum(line.line_payment.amount_paise for line in decisions)
    if fulfilled < minimum_quantity:
        return _zero_result(method=method, market_id=market_id, admission=admission)
    return AgentMarketBenchMethodResultV1(
        method=method,
        market_id=market_id,
        status=AgentMarketBenchMethodStatusV1.FEASIBLE,
        admission=admission,
        fulfilled_quantity=fulfilled,
        total_payment=Money(amount_paise=total),
        winner_count=len({line.merchant_id for line in decisions}),
        lines=tuple(decisions),
    )


def _greedy_allocation(
    policy: BuyerPolicyV2,
    lines: Iterable[_QualifiedLine],
    *,
    max_winners: int | None = None,
) -> tuple[tuple[_QualifiedLine, ...], tuple[int, ...]]:
    requested = policy.market_spec.requested_quantity
    budget = policy.max_total_payment.amount_paise
    winner_limit = max_winners if max_winners is not None else policy.market_spec.max_winners
    selected: list[_QualifiedLine] = []
    quantities: list[int] = []
    winners: set[str] = set()
    remaining = requested
    remaining_budget = budget
    for line in lines:
        if remaining <= 0:
            break
        if line.merchant_id not in winners and len(winners) >= winner_limit:
            continue
        quantity = min(line.max_quantity, remaining)
        if line.unit_price_paise > 0:
            quantity = min(quantity, remaining_budget // line.unit_price_paise)
        if quantity <= 0:
            continue
        selected.append(line)
        quantities.append(quantity)
        remaining -= quantity
        remaining_budget -= quantity * line.unit_price_paise
        winners.add(line.merchant_id)
    return tuple(selected), tuple(quantities)


def _merchant_greedy(
    policy: BuyerPolicyV2,
    merchant_lines: tuple[_QualifiedLine, ...],
) -> tuple[tuple[_QualifiedLine, ...], tuple[int, ...]]:
    return _greedy_allocation(
        policy,
        sorted(
            merchant_lines,
            key=lambda line: (line.unit_price_paise, -line.soft_match_count, line.key),
        ),
        max_winners=1,
    )


def _single_seller_candidates(
    policy: BuyerPolicyV2,
    lines: tuple[_QualifiedLine, ...],
) -> tuple[tuple[tuple[_QualifiedLine, ...], tuple[int, ...]], ...]:
    by_merchant: dict[str, list[_QualifiedLine]] = {}
    for line in lines:
        by_merchant.setdefault(line.merchant_id, []).append(line)
    candidates = []
    for merchant_id in sorted(by_merchant):
        candidate_lines, quantities = _merchant_greedy(policy, tuple(by_merchant[merchant_id]))
        if sum(quantities) >= policy.market_spec.minimum_acceptable_quantity:
            candidates.append((candidate_lines, quantities))
    return tuple(candidates)


def _random_qualifying(
    policy: BuyerPolicyV2,
    lines: tuple[_QualifiedLine, ...],
) -> tuple[tuple[_QualifiedLine, ...], tuple[int, ...]] | None:
    candidates = _single_seller_candidates(policy, lines)
    if not candidates:
        return None
    ranked = []
    market_id = policy.market_spec.market_id
    for candidate_lines, quantities in candidates:
        merchant_id = candidate_lines[0].merchant_id
        digest = sha256(
            (
                "agent-market-bench-methods-v1|RANDOM_QUALIFYING_SELLER|"
                f"market_id={market_id}|merchant_id={merchant_id}"
            ).encode("ascii")
        ).hexdigest()
        ranked.append((digest, merchant_id, candidate_lines, quantities))
    _, _, selected_lines, selected_quantities = min(ranked, key=lambda item: item[:2])
    return selected_lines, selected_quantities


def _cheapest_qualifying(
    policy: BuyerPolicyV2,
    lines: tuple[_QualifiedLine, ...],
) -> tuple[tuple[_QualifiedLine, ...], tuple[int, ...]] | None:
    candidates = _single_seller_candidates(policy, lines)
    if not candidates:
        return None
    ranked = []
    for candidate_lines, quantities in candidates:
        quantity = sum(quantities)
        payment = sum(
            line.unit_price_paise * q for line, q in zip(candidate_lines, quantities, strict=True)
        )
        merchant_id = candidate_lines[0].merchant_id
        ranked.append(
            (
                Fraction(payment, quantity),
                -quantity,
                payment,
                merchant_id,
                candidate_lines,
                quantities,
            )
        )
    _, _, _, _, selected_lines, selected_quantities = min(ranked, key=lambda item: item[:4])
    return selected_lines, selected_quantities


def _attribute_component(
    attributes: tuple[CatalogAttributeV2, ...],
    key: str,
) -> object | None:
    attribute = next((item for item in attributes if item.attribute_key == key), None)
    return None if attribute is None else attribute.value.value


def _static_score(policy: BuyerPolicyV2, line: _QualifiedLine) -> int:
    reference = max(
        1, policy.max_total_payment.amount_paise // policy.market_spec.requested_quantity
    )
    price_score = max(0, 1000 - min(1000, line.unit_price_paise * 1000 // reference))
    quality = _attribute_component(line.attributes, "quality_score")
    quality_score = max(0, min(1000, quality * 100)) if type(quality) is int else 0
    sla = _attribute_component(line.attributes, "sla_days")
    sla_score = max(0, min(1000, (8 - sla) * 1000 // 7)) if type(sla) is int else 0
    eco = _attribute_component(line.attributes, "eco_certified")
    eco_score = 1000 if type(eco) is bool and eco else 0
    return 40 * price_score + 30 * quality_score + 20 * sla_score + 10 * eco_score


def _run_non_clear(
    *,
    method: AgentMarketBenchBaselineV1,
    market_input: AgentMarketBenchMarketInputV1,
    admission: AgentMarketBenchAdmissionV1,
    reports: tuple[AgentMarketBenchReportedOfferV1, ...],
) -> AgentMarketBenchMethodResultV1:
    policy = market_input.buyer_policy
    lines = _qualified_lines(policy, reports)
    if method is AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER:
        candidate = _random_qualifying(policy, lines)
        if candidate is None:
            return _zero_result(
                method=method, market_id=policy.market_spec.market_id, admission=admission
            )
        selected, quantities = candidate
        return _result_from_quantities(
            method=method,
            market_id=policy.market_spec.market_id,
            admission=admission,
            lines=selected,
            quantities=quantities,
            minimum_quantity=policy.market_spec.minimum_acceptable_quantity,
        )
    if method is AgentMarketBenchBaselineV1.CHEAPEST_QUALIFYING:
        candidate = _cheapest_qualifying(policy, lines)
        if candidate is None:
            return _zero_result(
                method=method, market_id=policy.market_spec.market_id, admission=admission
            )
        selected, quantities = candidate
        return _result_from_quantities(
            method=method,
            market_id=policy.market_spec.market_id,
            admission=admission,
            lines=selected,
            quantities=quantities,
            minimum_quantity=policy.market_spec.minimum_acceptable_quantity,
        )
    if method is AgentMarketBenchBaselineV1.STATIC_WEIGHTED_SCORE:
        ranked = tuple(
            sorted(
                lines,
                key=lambda line: (
                    -_static_score(policy, line),
                    line.unit_price_paise,
                    -line.soft_match_count,
                    line.key,
                ),
            )
        )
        selected, quantities = _greedy_allocation(policy, ranked)
    elif method is AgentMarketBenchBaselineV1.BILATERAL_NEGOTIATION:
        selected_merchant = next(
            (
                report.signed_offer.offer.merchant_id
                for report in reports
                if any(line.merchant_id == report.signed_offer.offer.merchant_id for line in lines)
            ),
            None,
        )
        if selected_merchant is None:
            return _zero_result(
                method=method, market_id=policy.market_spec.market_id, admission=admission
            )
        selected, quantities = _merchant_greedy(
            policy,
            tuple(line for line in lines if line.merchant_id == selected_merchant),
        )
    elif method is AgentMarketBenchBaselineV1.SEQUENTIAL_NEGOTIATION:
        selected_list: list[_QualifiedLine] = []
        quantity_list: list[int] = []
        for report in reports:
            merchant_id = report.signed_offer.offer.merchant_id
            merchant_lines = tuple(
                sorted(
                    (line for line in lines if line.merchant_id == merchant_id),
                    key=lambda line: (line.unit_price_paise, -line.soft_match_count, line.key),
                )
            )
            if not merchant_lines:
                continue
            remaining_quantity = policy.market_spec.requested_quantity - sum(quantity_list)
            remaining_budget = policy.max_total_payment.amount_paise - sum(
                line.unit_price_paise * q
                for line, q in zip(selected_list, quantity_list, strict=True)
            )
            if (
                remaining_quantity <= 0
                or len({line.merchant_id for line in selected_list})
                >= policy.market_spec.max_winners
            ):
                break
            for line in merchant_lines:
                quantity = min(line.max_quantity, remaining_quantity)
                if line.unit_price_paise > 0:
                    quantity = min(quantity, remaining_budget // line.unit_price_paise)
                if quantity > 0:
                    selected_list.append(line)
                    quantity_list.append(quantity)
                    remaining_quantity -= quantity
                    remaining_budget -= quantity * line.unit_price_paise
                if remaining_quantity <= 0:
                    break
        selected, quantities = tuple(selected_list), tuple(quantity_list)
    elif method is AgentMarketBenchBaselineV1.FIRST_PRICE_REVERSE_AUCTION:
        merchants = tuple(sorted({line.merchant_id for line in lines}))
        if not merchants:
            return _zero_result(
                method=method, market_id=policy.market_spec.market_id, admission=admission
            )
        k = min(policy.market_spec.max_winners, len(merchants))
        best: (
            tuple[int, int, tuple[int, ...], tuple[_QualifiedLine, ...], tuple[int, ...]] | None
        ) = None
        for subset in combinations(merchants, k):
            subset_lines = tuple(
                sorted(
                    (line for line in lines if line.merchant_id in subset),
                    key=lambda line: (line.unit_price_paise, line.key),
                )
            )
            candidate_lines, candidate_quantities = _greedy_allocation(
                policy, subset_lines, max_winners=k
            )
            vector = tuple(
                next(
                    (
                        q
                        for line, q in zip(candidate_lines, candidate_quantities, strict=True)
                        if line.key == original.key
                    ),
                    0,
                )
                for original in lines
            )
            quantity = sum(candidate_quantities)
            payment = sum(
                line.unit_price_paise * q
                for line, q in zip(candidate_lines, candidate_quantities, strict=True)
            )
            key = (quantity, -payment, vector)
            if best is None or key > best[:3]:
                best = (quantity, -payment, vector, candidate_lines, candidate_quantities)
        if best is None:
            return _zero_result(
                method=method, market_id=policy.market_spec.market_id, admission=admission
            )
        _, _, _, selected, quantities = best
    elif method is AgentMarketBenchBaselineV1.REVERSE_VICKREY:
        by_merchant: dict[str, list[_QualifiedLine]] = {}
        for line in lines:
            by_merchant.setdefault(line.merchant_id, []).append(line)
        candidates = [items[0] for items in by_merchant.values() if len(items) == 1]
        if len(candidates) < 2 or len(candidates) != len(by_merchant):
            return _zero_result(
                method=method,
                market_id=policy.market_spec.market_id,
                admission=admission,
                status=AgentMarketBenchMethodStatusV1.NOT_APPLICABLE,
            )
        relevant_keys = {rule.attribute_key for rule in policy.market_spec.hard_constraints}
        relevant_keys.update(rule.attribute_key for rule in policy.market_spec.soft_preferences)
        for relevant_key in sorted(relevant_keys):
            values: list[tuple[str, object, object]] = []
            for candidate_line in candidates:
                matching = tuple(
                    attribute
                    for attribute in candidate_line.attributes
                    if attribute.attribute_key == relevant_key
                )
                if len(matching) != 1:
                    return _zero_result(
                        method=method,
                        market_id=policy.market_spec.market_id,
                        admission=admission,
                        status=AgentMarketBenchMethodStatusV1.NOT_APPLICABLE,
                    )
                attribute = matching[0]
                values.append(
                    (attribute.attribute_key, attribute.value.value_type, attribute.value.value)
                )
            if any(value != values[0] for value in values[1:]):
                return _zero_result(
                    method=method,
                    market_id=policy.market_spec.market_id,
                    admission=admission,
                    status=AgentMarketBenchMethodStatusV1.NOT_APPLICABLE,
                )
        if (
            policy.market_spec.requested_quantity != 1
            or policy.market_spec.minimum_acceptable_quantity != 1
            or policy.market_spec.max_winners != 1
            or any(candidate.max_quantity < 1 for candidate in candidates)
        ):
            return _zero_result(
                method=method,
                market_id=policy.market_spec.market_id,
                admission=admission,
                status=AgentMarketBenchMethodStatusV1.NOT_APPLICABLE,
            )
        ranked = tuple(sorted(candidates, key=lambda line: (line.unit_price_paise, line.key)))
        if ranked[1].unit_price_paise > policy.max_total_payment.amount_paise:
            return _zero_result(
                method=method, market_id=policy.market_spec.market_id, admission=admission
            )
        winner = ranked[0]
        selected = (winner,)
        quantities = (1,)
        # The second-price payment is represented after selecting the winner.
        payment_line = AgentMarketBenchDecisionLineV1(
            source_offer_id=winner.source_offer_id,
            merchant_id=winner.merchant_id,
            sku_id=winner.sku_id,
            allocated_quantity=1,
            unit_payment=Money(amount_paise=ranked[1].unit_price_paise),
            line_payment=Money(amount_paise=ranked[1].unit_price_paise),
        )
        return AgentMarketBenchMethodResultV1(
            method=method,
            market_id=policy.market_spec.market_id,
            status=AgentMarketBenchMethodStatusV1.FEASIBLE,
            admission=admission,
            fulfilled_quantity=1,
            total_payment=payment_line.line_payment,
            winner_count=1,
            lines=(payment_line,),
        )
    else:
        raise AssertionError("unsupported ordinary method")
    return _result_from_quantities(
        method=method,
        market_id=policy.market_spec.market_id,
        admission=admission,
        lines=selected,
        quantities=quantities,
        minimum_quantity=policy.market_spec.minimum_acceptable_quantity,
    )


def run_agent_market_bench_method_v1(
    *,
    method: AgentMarketBenchBaselineV1,
    market_input: AgentMarketBenchMarketInputV1,
) -> AgentMarketBenchMethodResultV1:
    """Run one deterministic public-input comparator and return evidence only."""

    if type(method) is not AgentMarketBenchBaselineV1:
        raise TypeError("method must be exactly an AgentMarketBenchBaselineV1")
    if method is AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE:
        raise ValueError(
            "FULL_INFORMATION_ORACLE requires the case-aware "
            "run_agent_market_bench_full_information_oracle_v1 API"
        )
    fresh_input = _fresh_market_input(market_input)
    admitted_reports, admission = _admit_with_reports(fresh_input)
    market_id = fresh_input.buyer_policy.market_spec.market_id
    if method is AgentMarketBenchBaselineV1.CLEAR:
        allocation = allocate_market_v2(
            buyer_policy=fresh_input.buyer_policy,
            signed_offers=tuple(report.signed_offer for report in admitted_reports),
        )
        if allocation.status is AllocationStatusV2.INFEASIBLE:
            return _zero_result(method=method, market_id=market_id, admission=admission)
        lines = tuple(
            AgentMarketBenchDecisionLineV1(
                source_offer_id=line.offer_id,
                merchant_id=line.merchant_id,
                sku_id=line.sku_id,
                allocated_quantity=line.allocated_quantity,
                unit_payment=line.unit_payment,
                line_payment=line.line_payment,
            )
            for line in allocation.lines
        )
        return AgentMarketBenchMethodResultV1(
            method=method,
            market_id=market_id,
            status=AgentMarketBenchMethodStatusV1.FEASIBLE,
            admission=admission,
            fulfilled_quantity=allocation.fulfilled_quantity,
            total_payment=allocation.total_payment,
            winner_count=allocation.winner_count,
            lines=lines,
        )
    return _run_non_clear(
        method=method,
        market_input=fresh_input,
        admission=admission,
        reports=admitted_reports,
    )


__all__ = ("run_agent_market_bench_method_v1",)
