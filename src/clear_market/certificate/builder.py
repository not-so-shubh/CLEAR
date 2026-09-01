from clear_market.certificate.models import AllocationCertificate
from clear_market.crypto import buyer_policy_commitment
from clear_market.domain import BuyerPolicy
from clear_market.lifecycle import AdmissionDecision, AdmissionState, admit_signed_bid
from clear_market.mechanism import allocate_market


def build_allocation_certificate(
    certificate_id: str,
    buyer_policy: BuyerPolicy,
    admission_decisions: tuple[AdmissionDecision, ...],
) -> AllocationCertificate:
    """Replay the included ordered transcript before recording production allocation evidence."""
    if not isinstance(buyer_policy, BuyerPolicy):
        raise TypeError("buyer_policy must be a BuyerPolicy")
    if type(admission_decisions) is not tuple:
        raise TypeError("admission_decisions must be a tuple")
    if any(not isinstance(decision, AdmissionDecision) for decision in admission_decisions):
        raise TypeError("admission_decisions must contain only AdmissionDecision values")

    replay_state = AdmissionState(buyer_policy)
    for declared_decision in admission_decisions:
        replayed_decision = admit_signed_bid(
            replay_state,
            declared_decision.signed_bid,
            declared_decision.context,
        )
        if replayed_decision != declared_decision:
            raise ValueError("declared admission decision does not match ordered replay")

    allocation = allocate_market(replay_state)
    return AllocationCertificate(
        certificate_id=certificate_id,
        buyer_policy=buyer_policy,
        buyer_policy_commitment=buyer_policy_commitment(buyer_policy),
        admission_decisions=admission_decisions,
        allocation=allocation,
    )
