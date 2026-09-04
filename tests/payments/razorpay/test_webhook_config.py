import pytest

from clear_market.payments.razorpay import RazorpayWebhookVerificationConfigV1

_SECRET = "clear-review-webhook-secret-v1"


def _config(**changes: object) -> RazorpayWebhookVerificationConfigV1:
    values: dict[str, object] = {
        "expected_account_id": "acc_CLEARPRIMARY01",
        "secrets": (_SECRET,),
        **changes,
    }
    return RazorpayWebhookVerificationConfigV1(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("account_id", ["acc_A", "acc_0123456789ABCD", "acc_CLEARPRIMARY01"])
def test_expected_account_id_accepts_exact_ascii_grammar(account_id: str) -> None:
    assert _config(expected_account_id=account_id).expected_account_id == account_id


@pytest.mark.parametrize(
    "account_id",
    [
        "",
        "acc_",
        "acc_0123456789ABCDE",
        " account",
        "acc_CLEARPRIMARY01 ",
        "ACC_CLEARPRIMARY01",
        "account_CLEAR",
        "acc_CLEAR-PRIMARY",
        "acc_é",
    ],
)
def test_expected_account_id_rejects_without_normalization(account_id: str) -> None:
    with pytest.raises(ValueError):
        _config(expected_account_id=account_id)


def test_secrets_require_an_exact_nonempty_tuple_with_at_most_eight_values() -> None:
    assert _config(secrets=tuple(f"secret-{index}" for index in range(8))).expected_account_id == (
        "acc_CLEARPRIMARY01"
    )
    for secrets in ([], (), tuple(f"secret-{index}" for index in range(9))):
        with pytest.raises(ValueError):
            _config(secrets=secrets)


@pytest.mark.parametrize(
    "secret",
    [
        "",
        "bad\x00secret",
        "é" * 257,
        "\ud800",
        b"secret",
        1,
        None,
    ],
)
def test_secret_requires_1_to_512_valid_utf8_bytes_without_coercion(secret: object) -> None:
    with pytest.raises(ValueError):
        _config(secrets=(secret,))


def test_secret_whitespace_is_data_and_is_never_trimmed() -> None:
    config = _config(secrets=(" secret ",))
    assert config.expected_account_id == "acc_CLEARPRIMARY01"
    assert not hasattr(config, "secrets")


def test_duplicate_secrets_are_rejected() -> None:
    with pytest.raises(ValueError):
        _config(secrets=(_SECRET, _SECRET))


def test_config_is_slots_based_immutable_and_exactly_redacted() -> None:
    config = _config()
    assert not hasattr(config, "__dict__")
    assert repr(config) == "RazorpayWebhookVerificationConfigV1(<redacted>)"
    assert str(config) == "RazorpayWebhookVerificationConfigV1(<redacted>)"
    assert _SECRET not in repr(config)
    assert _SECRET not in str(config)
    with pytest.raises(AttributeError):
        config.expected_account_id = "acc_CHANGED000001"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        config.extra = True  # type: ignore[attr-defined]


def test_config_has_no_public_serialization_or_secret_surface() -> None:
    config = _config()
    for name in ("model_dump", "model_dump_json", "json", "secret", "secrets"):
        assert not hasattr(config, name)


def test_config_documents_test_mode_provenance_limit() -> None:
    doc = " ".join((RazorpayWebhookVerificationConfigV1.__doc__ or "").split())
    assert "intended Razorpay Test Mode endpoint" in doc
    assert "does not establish whether" in doc


def test_constructor_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        RazorpayWebhookVerificationConfigV1(
            "acc_CLEARPRIMARY01",  # type: ignore[misc]
            (_SECRET,),  # type: ignore[misc]
        )


def test_config_rejects_non_string_account_id() -> None:
    with pytest.raises(ValueError):
        _config(expected_account_id=1)
