"""Public authenticated admission for AgentMarketBench market inputs."""

from clear_market.agentmarketbench.method_models import (
    AgentMarketBenchAdmissionRejectionReasonV1,
    AgentMarketBenchAdmissionRejectionV1,
    AgentMarketBenchAdmissionV1,
)
from clear_market.agentmarketbench.models import (
    AgentMarketBenchMarketInputV1,
    AgentMarketBenchReportedOfferV1,
)
from clear_market.commerce import (
    MerchantOfferVerificationError,
    canonical_signed_merchant_offer_v2_bytes,
    verify_canonical_signed_merchant_offer_v2,
)


def _fresh_market_input(value: object) -> AgentMarketBenchMarketInputV1:
    if type(value) is not AgentMarketBenchMarketInputV1:
        raise TypeError("market_input must be exactly an AgentMarketBenchMarketInputV1")
    try:
        return AgentMarketBenchMarketInputV1.model_validate(value)
    except Exception as error:
        raise ValueError("market_input failed fresh validation") from error


def _admit_with_reports(
    market_input: AgentMarketBenchMarketInputV1,
) -> tuple[tuple[AgentMarketBenchReportedOfferV1, ...], AgentMarketBenchAdmissionV1]:
    fresh_input = _fresh_market_input(market_input)
    reports = fresh_input.reported_offers
    indexes = tuple(report.submission_index for report in reports)
    if indexes != tuple(range(len(reports))):
        raise ValueError("reported submission indexes must equal tuple order")

    observed = {merchant.merchant_id: merchant for merchant in fresh_input.observed_merchants}
    admitted: list[AgentMarketBenchReportedOfferV1] = []
    rejections: list[AgentMarketBenchAdmissionRejectionV1] = []
    admitted_offer_ids: set[str] = set()
    admitted_merchants: set[str] = set()

    for report in reports:
        offer = report.signed_offer.offer
        reason: AgentMarketBenchAdmissionRejectionReasonV1 | None = None
        if report.received_at > fresh_input.buyer_policy.offer_deadline:
            reason = AgentMarketBenchAdmissionRejectionReasonV1.LATE_OFFER
        else:
            merchant = observed.get(offer.merchant_id)
            if merchant is None:
                reason = AgentMarketBenchAdmissionRejectionReasonV1.UNKNOWN_MERCHANT
            else:
                try:
                    verify_canonical_signed_merchant_offer_v2(
                        data=canonical_signed_merchant_offer_v2_bytes(report.signed_offer),
                        signing_identity=merchant.signing_identity,
                        buyer_policy=fresh_input.buyer_policy,
                        catalog=merchant.catalog,
                        inventory=merchant.inventory_snapshot,
                    )
                except MerchantOfferVerificationError:
                    reason = AgentMarketBenchAdmissionRejectionReasonV1.AUTHENTICATION_FAILED

        if reason is None and offer.offer_id in admitted_offer_ids:
            reason = AgentMarketBenchAdmissionRejectionReasonV1.DUPLICATE_OFFER_ID
        elif reason is None and offer.merchant_id in admitted_merchants:
            reason = AgentMarketBenchAdmissionRejectionReasonV1.DUPLICATE_MERCHANT

        if reason is not None:
            rejections.append(
                AgentMarketBenchAdmissionRejectionV1(
                    submission_index=report.submission_index,
                    reason=reason,
                )
            )
            continue

        admitted.append(report)
        admitted_offer_ids.add(offer.offer_id)
        admitted_merchants.add(offer.merchant_id)

    summary = AgentMarketBenchAdmissionV1(
        admitted_submission_indices=tuple(report.submission_index for report in admitted),
        rejections=tuple(rejections),
    )
    return tuple(admitted), summary


def admit_agent_market_bench_market_input_v1(
    market_input: AgentMarketBenchMarketInputV1,
) -> AgentMarketBenchAdmissionV1:
    """Return deterministic public admission evidence without exposing latent state."""

    return _admit_with_reports(market_input)[1]


__all__ = ("admit_agent_market_bench_market_input_v1",)
