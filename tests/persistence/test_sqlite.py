import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any, cast

import pytest

from clear_market.persistence import (
    ExecutionReservationDispositionV1,
    ExecutionReservationV1,
    FinancialLedgerEventAppendDispositionV1,
    FinancialLedgerEventV1,
    FinancialLedgerFieldV1,
    FinancialLedgerValueType,
    IdempotencyDispositionV1,
    IdempotencyRecordV1,
    PersistenceError,
    PersistenceErrorCode,
    ProviderReferenceDispositionV1,
    ProviderReferenceV1,
    SQLiteFinancialLedgerV1,
    open_sqlite_financial_ledger_v1,
)
from clear_market.persistence.sqlite import _IdempotencyPairConflict

_TIME = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
_DIGEST_VERSION = "sha256-allocation-certificate-v2-clear-json-v1"


def _uuid(namespace: int, index: int) -> str:
    return f"d{namespace}000000-0000-4000-8000-{index:012x}"


def _reservation(index: int = 1, **changes: object) -> ExecutionReservationV1:
    values: dict[str, object] = {
        "execution_id": _uuid(1, index),
        "certificate_digest_version": _DIGEST_VERSION,
        "certificate_digest_sha256": f"{index:064x}",
        "market_id": _uuid(2, index),
        "execution_request_fingerprint_sha256": f"{index + 100:064x}",
        "reserved_at": _TIME + timedelta(seconds=index),
        **changes,
    }
    return ExecutionReservationV1(**values)


def _field(index: int = 1, **changes: object) -> FinancialLedgerFieldV1:
    values: dict[str, object] = {
        "field_key": f"field.{index}",
        "value_type": FinancialLedgerValueType.INTEGER,
        "value": index,
        **changes,
    }
    return FinancialLedgerFieldV1(**values)


def _event(index: int = 1, **changes: object) -> FinancialLedgerEventV1:
    values: dict[str, object] = {
        "event_id": _uuid(3, index),
        "execution_id": _uuid(1, 1),
        "event_type": f"ledger.event.{index}",
        "occurred_at": _TIME + timedelta(minutes=index),
        "fields": (_field(index),),
        **changes,
    }
    return FinancialLedgerEventV1(**values)


def _reference(index: int = 1, **changes: object) -> ProviderReferenceV1:
    values: dict[str, object] = {
        "provider_name": "example-provider",
        "reference_kind": "order",
        "reference_id": f"reference-{index}",
        "execution_id": _uuid(1, 1),
        "recorded_at": _TIME + timedelta(minutes=index),
        **changes,
    }
    return ProviderReferenceV1(**values)


def _idempotency(index: int = 1, **changes: object) -> IdempotencyRecordV1:
    values: dict[str, object] = {
        "namespace": "provider.request",
        "idempotency_key": f"request-{index}",
        "request_fingerprint_sha256": f"{index + 200:064x}",
        "execution_id": _uuid(1, 1),
        "recorded_at": _TIME + timedelta(minutes=index),
        **changes,
    }
    return IdempotencyRecordV1(**values)


def _idempotency_pair() -> tuple[IdempotencyRecordV1, IdempotencyRecordV1]:
    return (
        _idempotency(10, namespace="pair.first", idempotency_key="first"),
        _idempotency(11, namespace="pair.second", idempotency_key="second"),
    )


def _assert_persistence_error(
    expected: PersistenceErrorCode,
    action: Any,
) -> PersistenceError:
    with pytest.raises(PersistenceError) as caught:
        action()
    assert caught.value.code is expected
    assert str(caught.value) == expected.value
    return caught.value


def test_new_database_schema_version_tables_and_pragmas_are_exact(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        connection = cast(Any, ledger)._connection
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5_000
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert tables == {
            "clear_execution_reservations_v1",
            "clear_financial_events_v1",
            "clear_provider_references_v1",
            "clear_idempotency_records_v1",
            "sqlite_sequence",
        }


def test_file_backed_records_are_durable_across_close_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    reservation = _reservation()
    event = _event()
    reference = _reference()
    idempotency = _idempotency()
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        assert ledger.reserve_execution(reservation).disposition is (
            ExecutionReservationDispositionV1.CREATED
        )
        persisted_event = ledger.append_event(event).persisted_event
        assert ledger.record_provider_reference(reference).disposition is (
            ProviderReferenceDispositionV1.CREATED
        )
        assert ledger.claim_idempotency(idempotency).disposition is (
            IdempotencyDispositionV1.CREATED
        )

    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        assert ledger.get_execution_reservation(reservation.execution_id) == reservation
        assert (
            ledger.get_execution_reservation_by_certificate_digest(
                reservation.certificate_digest_sha256
            )
            == reservation
        )
        assert ledger.get_execution_reservation_by_market_id(reservation.market_id) == reservation
        assert ledger.get_event(event.event_id) == persisted_event
        assert ledger.list_events(reservation.execution_id) == (persisted_event,)
        assert (
            ledger.get_provider_reference(
                provider_name=reference.provider_name,
                reference_kind=reference.reference_kind,
                reference_id=reference.reference_id,
            )
            == reference
        )
        assert ledger.list_provider_references(reservation.execution_id) == (reference,)
        assert (
            ledger.get_idempotency_record(
                namespace=idempotency.namespace,
                idempotency_key=idempotency.idempotency_key,
            )
            == idempotency
        )


def test_execution_reservation_retry_and_conflict_precedence_are_exact(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    first = _reservation(1)
    second = _reservation(2)
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        created = ledger.reserve_execution(first)
        assert created.disposition is ExecutionReservationDispositionV1.CREATED

        later_retry = _reservation(1, reserved_at=first.reserved_at + timedelta(days=1))
        retry = ledger.reserve_execution(later_retry)
        assert retry.disposition is ExecutionReservationDispositionV1.EXISTING_SAME
        assert retry.stored_reservation == first

        execution_conflict = ledger.reserve_execution(
            _reservation(1, execution_request_fingerprint_sha256="f" * 64)
        )
        assert execution_conflict.disposition is (
            ExecutionReservationDispositionV1.EXECUTION_ID_CONFLICT
        )
        assert execution_conflict.stored_reservation == first

        certificate_conflict = ledger.reserve_execution(
            _reservation(3, certificate_digest_sha256=first.certificate_digest_sha256)
        )
        assert certificate_conflict.disposition is (
            ExecutionReservationDispositionV1.CERTIFICATE_ALREADY_RESERVED
        )
        assert certificate_conflict.stored_reservation == first

        market_conflict = ledger.reserve_execution(_reservation(4, market_id=first.market_id))
        assert market_conflict.disposition is (
            ExecutionReservationDispositionV1.MARKET_ALREADY_RESERVED
        )
        assert market_conflict.stored_reservation == first

        assert ledger.reserve_execution(second).disposition is (
            ExecutionReservationDispositionV1.CREATED
        )
        both_conflict = ledger.reserve_execution(
            _reservation(
                5,
                certificate_digest_sha256=first.certificate_digest_sha256,
                market_id=second.market_id,
            )
        )
        assert both_conflict.disposition is (
            ExecutionReservationDispositionV1.CERTIFICATE_ALREADY_RESERVED
        )
        assert both_conflict.stored_reservation == first
        assert ledger.get_execution_reservation(first.execution_id) == first
        assert ledger.get_execution_reservation(second.execution_id) == second


def test_concurrent_certificate_reservation_has_exactly_one_creator(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)):
        pass
    barrier = Barrier(2)
    common_digest = "e" * 64

    def reserve(index: int) -> ExecutionReservationDispositionV1:
        barrier.wait()
        with open_sqlite_financial_ledger_v1(str(path)) as ledger:
            return ledger.reserve_execution(
                _reservation(index, certificate_digest_sha256=common_digest)
            ).disposition

    with ThreadPoolExecutor(max_workers=2) as executor:
        dispositions = tuple(executor.map(reserve, (1, 2)))
    assert sorted(disposition.value for disposition in dispositions) == [
        "CERTIFICATE_ALREADY_RESERVED",
        "CREATED",
    ]
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM clear_execution_reservations_v1 "
            "WHERE certificate_digest_sha256 = ?",
            (common_digest,),
        ).fetchone() == (1,)


def test_event_append_idempotency_conflicts_sequence_and_listing(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    first = _event(1)
    second = _event(2)
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        ledger.reserve_execution(_reservation())
        first_result = ledger.append_event(first)
        assert first_result.disposition is FinancialLedgerEventAppendDispositionV1.CREATED
        assert first_result.persisted_event.sequence_number == 1
        retry = ledger.append_event(first)
        assert retry.disposition is FinancialLedgerEventAppendDispositionV1.EXISTING_SAME
        assert retry.persisted_event == first_result.persisted_event

        for changes in (
            {"execution_id": _uuid(1, 2)},
            {"event_type": "changed.event"},
            {"occurred_at": first.occurred_at + timedelta(microseconds=1)},
            {"fields": (_field(9),)},
        ):
            if changes.get("execution_id") == _uuid(1, 2):
                ledger.reserve_execution(_reservation(2))
            conflict = ledger.append_event(_event(1, **changes))
            assert conflict.disposition is (
                FinancialLedgerEventAppendDispositionV1.EVENT_ID_CONFLICT
            )
            assert conflict.persisted_event == first_result.persisted_event

        second_result = ledger.append_event(second)
        assert second_result.persisted_event.sequence_number == 2
        assert ledger.list_events(_uuid(1, 1)) == (
            first_result.persisted_event,
            second_result.persisted_event,
        )
        assert ledger.list_events(_uuid(1, 1), after_sequence=1) == (second_result.persisted_event,)
        assert ledger.list_events(_uuid(1, 1), limit=1) == (first_result.persisted_event,)
        assert ledger.list_events(_uuid(1, 1), after_sequence=10**100) == ()


def test_event_unknown_execution_and_list_parameter_validation(tmp_path: Path) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _assert_persistence_error(
            PersistenceErrorCode.UNKNOWN_EXECUTION,
            lambda: ledger.append_event(_event()),
        )
        _assert_persistence_error(
            PersistenceErrorCode.UNKNOWN_EXECUTION,
            lambda: ledger.list_events(_uuid(1, 99)),
        )
        for after_sequence in (-1, True, 1.0, "1"):
            with pytest.raises(ValueError):
                ledger.list_events(_uuid(1, 99), after_sequence=cast(Any, after_sequence))
        for limit in (0, 1_001, True, 1.0, "1"):
            with pytest.raises(ValueError):
                ledger.list_events(_uuid(1, 99), limit=cast(Any, limit))


def test_provider_reference_retry_conflict_order_and_unknown_execution(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        ledger.reserve_execution(_reservation(1))
        ledger.reserve_execution(_reservation(2))
        first = _reference(2, provider_name="z-provider", reference_kind="payment")
        second = _reference(1, provider_name="a-provider", reference_kind="order")
        assert ledger.record_provider_reference(first).disposition is (
            ProviderReferenceDispositionV1.CREATED
        )
        assert ledger.record_provider_reference(second).disposition is (
            ProviderReferenceDispositionV1.CREATED
        )
        retry = ledger.record_provider_reference(
            _reference(
                2,
                provider_name="z-provider",
                reference_kind="payment",
                recorded_at=first.recorded_at + timedelta(days=1),
            )
        )
        assert retry.disposition is ProviderReferenceDispositionV1.EXISTING_SAME
        assert retry.stored_reference == first

        conflict = ledger.record_provider_reference(
            _reference(
                2,
                provider_name="z-provider",
                reference_kind="payment",
                execution_id=_uuid(1, 2),
            )
        )
        assert conflict.disposition is ProviderReferenceDispositionV1.REFERENCE_CONFLICT
        assert conflict.stored_reference == first
        assert ledger.list_provider_references(_uuid(1, 1)) == (second, first)
        assert ledger.list_provider_references(_uuid(1, 1), limit=1) == (second,)
        assert ledger.list_provider_references(_uuid(1, 1), limit=1, offset=1) == (first,)
        assert ledger.list_provider_references(_uuid(1, 1), offset=10**100) == ()
        _assert_persistence_error(
            PersistenceErrorCode.UNKNOWN_EXECUTION,
            lambda: ledger.record_provider_reference(_reference(3, execution_id=_uuid(1, 99))),
        )
        _assert_persistence_error(
            PersistenceErrorCode.UNKNOWN_EXECUTION,
            lambda: ledger.list_provider_references(_uuid(1, 99)),
        )


def test_provider_reference_list_parameter_validation(tmp_path: Path) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        for limit in (0, 1_001, True, 1.0, "1"):
            with pytest.raises(ValueError):
                ledger.list_provider_references(_uuid(1, 99), limit=cast(Any, limit))
        for offset in (-1, True, 1.0, "1"):
            with pytest.raises(ValueError):
                ledger.list_provider_references(_uuid(1, 99), offset=cast(Any, offset))


def test_idempotency_retry_conflicts_null_execution_and_unknown_execution(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    first = _idempotency()
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        ledger.reserve_execution(_reservation(1))
        ledger.reserve_execution(_reservation(2))
        assert ledger.claim_idempotency(first).disposition is IdempotencyDispositionV1.CREATED
        retry = ledger.claim_idempotency(
            _idempotency(recorded_at=first.recorded_at + timedelta(days=1))
        )
        assert retry.disposition is IdempotencyDispositionV1.EXISTING_SAME
        assert retry.stored_record == first
        for changes in (
            {"request_fingerprint_sha256": "f" * 64},
            {"execution_id": _uuid(1, 2)},
        ):
            conflict = ledger.claim_idempotency(_idempotency(**changes))
            assert conflict.disposition is IdempotencyDispositionV1.CONFLICT
            assert conflict.stored_record == first

        without_execution = _idempotency(2, execution_id=None)
        assert ledger.claim_idempotency(without_execution).disposition is (
            IdempotencyDispositionV1.CREATED
        )
        assert (
            ledger.get_idempotency_record(
                namespace=without_execution.namespace,
                idempotency_key=without_execution.idempotency_key,
            )
            == without_execution
        )
        _assert_persistence_error(
            PersistenceErrorCode.UNKNOWN_EXECUTION,
            lambda: ledger.claim_idempotency(_idempotency(3, execution_id=_uuid(1, 99))),
        )


def test_idempotency_pair_claims_both_absent_in_one_operation(tmp_path: Path) -> None:
    first, second = _idempotency_pair()
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        ledger.reserve_execution(_reservation())
        results = ledger.claim_idempotency_pair(first, second)
        assert tuple(result.disposition for result in results) == (
            IdempotencyDispositionV1.CREATED,
            IdempotencyDispositionV1.CREATED,
        )
        assert (
            ledger.get_idempotency_record(
                namespace=first.namespace, idempotency_key=first.idempotency_key
            )
            == first
        )
        assert (
            ledger.get_idempotency_record(
                namespace=second.namespace, idempotency_key=second.idempotency_key
            )
            == second
        )


def test_idempotency_pair_first_conflict_does_not_insert_second(tmp_path: Path) -> None:
    first, second = _idempotency_pair()
    conflicting_first = _idempotency(
        12,
        namespace=first.namespace,
        idempotency_key=first.idempotency_key,
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        ledger.reserve_execution(_reservation())
        ledger.claim_idempotency(conflicting_first)
        with pytest.raises(_IdempotencyPairConflict) as caught:
            ledger.claim_idempotency_pair(first, second)
        assert caught.value.index == 0
        assert caught.value.result.disposition is IdempotencyDispositionV1.CONFLICT
        assert (
            ledger.get_idempotency_record(
                namespace=first.namespace, idempotency_key=first.idempotency_key
            )
            == conflicting_first
        )
        assert (
            ledger.get_idempotency_record(
                namespace=second.namespace, idempotency_key=second.idempotency_key
            )
            is None
        )


def test_idempotency_pair_second_conflict_does_not_insert_first(tmp_path: Path) -> None:
    first, second = _idempotency_pair()
    conflicting_second = _idempotency(
        12,
        namespace=second.namespace,
        idempotency_key=second.idempotency_key,
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        ledger.reserve_execution(_reservation())
        ledger.claim_idempotency(conflicting_second)
        with pytest.raises(_IdempotencyPairConflict) as caught:
            ledger.claim_idempotency_pair(first, second)
        assert caught.value.index == 1
        assert caught.value.result.disposition is IdempotencyDispositionV1.CONFLICT
        assert (
            ledger.get_idempotency_record(
                namespace=first.namespace, idempotency_key=first.idempotency_key
            )
            is None
        )
        assert (
            ledger.get_idempotency_record(
                namespace=second.namespace, idempotency_key=second.idempotency_key
            )
            == conflicting_second
        )


def test_idempotency_pair_preserves_existing_and_partial_new_semantics(tmp_path: Path) -> None:
    first, second = _idempotency_pair()
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        ledger.reserve_execution(_reservation())
        ledger.claim_idempotency(first)
        first_existing_second_created = ledger.claim_idempotency_pair(first, second)
        assert tuple(result.disposition for result in first_existing_second_created) == (
            IdempotencyDispositionV1.EXISTING_SAME,
            IdempotencyDispositionV1.CREATED,
        )

    first, second = _idempotency_pair()
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger-second.db")) as ledger:
        ledger.reserve_execution(_reservation())
        ledger.claim_idempotency(second)
        first_created_second_existing = ledger.claim_idempotency_pair(first, second)
        assert tuple(result.disposition for result in first_created_second_existing) == (
            IdempotencyDispositionV1.CREATED,
            IdempotencyDispositionV1.EXISTING_SAME,
        )

    first, second = _idempotency_pair()
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger-both.db")) as ledger:
        ledger.reserve_execution(_reservation())
        ledger.claim_idempotency(first)
        ledger.claim_idempotency(second)
        both_existing = ledger.claim_idempotency_pair(first, second)
        assert tuple(result.disposition for result in both_existing) == (
            IdempotencyDispositionV1.EXISTING_SAME,
            IdempotencyDispositionV1.EXISTING_SAME,
        )


def test_idempotency_pair_unknown_execution_has_no_partial_insert(tmp_path: Path) -> None:
    first, second = _idempotency_pair()
    unknown_second = second.model_copy(update={"execution_id": _uuid(1, 99)})
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        ledger.reserve_execution(_reservation())
        _assert_persistence_error(
            PersistenceErrorCode.UNKNOWN_EXECUTION,
            lambda: ledger.claim_idempotency_pair(first, unknown_second),
        )
        assert (
            ledger.get_idempotency_record(
                namespace=first.namespace, idempotency_key=first.idempotency_key
            )
            is None
        )
        assert (
            ledger.get_idempotency_record(
                namespace=second.namespace, idempotency_key=second.idempotency_key
            )
            is None
        )


def test_idempotency_pair_preserves_fresh_exact_validation(tmp_path: Path) -> None:
    first, second = _idempotency_pair()
    malformed = IdempotencyRecordV1.model_construct(namespace=first.namespace)
    subclass = type("IdempotencyRecordSubclass", (IdempotencyRecordV1,), {})
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        ledger.reserve_execution(_reservation())
        with pytest.raises(ValueError):
            ledger.claim_idempotency_pair(malformed, second)
        with pytest.raises(TypeError):
            ledger.claim_idempotency_pair(subclass(**first.model_dump(mode="python")), second)
        with pytest.raises(ValueError, match="distinct keys"):
            ledger.claim_idempotency_pair(first, first)
        assert (
            ledger.get_idempotency_record(
                namespace=first.namespace, idempotency_key=first.idempotency_key
            )
            is None
        )


def test_idempotency_pair_database_failure_rolls_back_all_inserts(tmp_path: Path) -> None:
    first, second = _idempotency_pair()
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        ledger.reserve_execution(_reservation())
        connection = cast(Any, ledger)._connection
        connection.execute(
            "CREATE TRIGGER fail_pair_second BEFORE INSERT ON clear_idempotency_records_v1 "
            "WHEN NEW.namespace = 'pair.second' BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
        _assert_persistence_error(
            PersistenceErrorCode.DATABASE_OPERATION_FAILED,
            lambda: ledger.claim_idempotency_pair(first, second),
        )
        assert (
            ledger.get_idempotency_record(
                namespace=first.namespace, idempotency_key=first.idempotency_key
            )
            is None
        )
        assert (
            ledger.get_idempotency_record(
                namespace=second.namespace, idempotency_key=second.idempotency_key
            )
            is None
        )


@pytest.mark.parametrize("user_version", [2, 99])
def test_unsupported_schema_version_fails_closed(tmp_path: Path, user_version: int) -> None:
    path = tmp_path / "ledger.db"
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA user_version = {user_version}")
    _assert_persistence_error(
        PersistenceErrorCode.SCHEMA_MISMATCH,
        lambda: open_sqlite_financial_ledger_v1(str(path)),
    )


def test_unversioned_unrelated_database_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
    _assert_persistence_error(
        PersistenceErrorCode.SCHEMA_MISMATCH,
        lambda: open_sqlite_financial_ledger_v1(str(path)),
    )


def test_version_one_with_missing_table_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 1")
    _assert_persistence_error(
        PersistenceErrorCode.SCHEMA_MISMATCH,
        lambda: open_sqlite_financial_ledger_v1(str(path)),
    )


def test_version_one_with_altered_unique_constraint_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)):
        pass
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP TABLE clear_execution_reservations_v1")
        connection.execute(
            "CREATE TABLE clear_execution_reservations_v1 ("
            "execution_id TEXT PRIMARY KEY, certificate_digest_version TEXT NOT NULL, "
            "certificate_digest_sha256 TEXT NOT NULL, market_id TEXT NOT NULL, "
            "execution_request_fingerprint_sha256 TEXT NOT NULL, reserved_at TEXT NOT NULL)"
        )
    _assert_persistence_error(
        PersistenceErrorCode.SCHEMA_MISMATCH,
        lambda: open_sqlite_financial_ledger_v1(str(path)),
    )


def test_version_one_with_missing_event_foreign_key_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)):
        pass
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE clear_financial_events_v1")
        connection.execute(
            "CREATE TABLE clear_financial_events_v1 ("
            "sequence_number INTEGER PRIMARY KEY AUTOINCREMENT, "
            "event_id TEXT NOT NULL UNIQUE, execution_id TEXT NOT NULL, "
            "event_type TEXT NOT NULL, occurred_at TEXT NOT NULL, fields_json TEXT NOT NULL)"
        )
    _assert_persistence_error(
        PersistenceErrorCode.SCHEMA_MISMATCH,
        lambda: open_sqlite_financial_ledger_v1(str(path)),
    )


def test_user_defined_destructive_trigger_fails_schema_verification(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)):
        pass
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TRIGGER delete_inserted_event "
            "AFTER INSERT ON clear_financial_events_v1 "
            "BEGIN "
            "DELETE FROM clear_financial_events_v1 "
            "WHERE sequence_number = NEW.sequence_number; "
            "END"
        )
    _assert_persistence_error(
        PersistenceErrorCode.SCHEMA_MISMATCH,
        lambda: open_sqlite_financial_ledger_v1(str(path)),
    )


def test_sql_like_wildcard_cannot_hide_destructive_trigger(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    trigger_name = "sqliteX_delete_inserted_event"
    assert not trigger_name.startswith("sqlite_")
    with open_sqlite_financial_ledger_v1(str(path)):
        pass
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT ? LIKE 'sqlite_%'",
            (trigger_name,),
        ).fetchone() == (1,)
        connection.execute(
            f"CREATE TRIGGER {trigger_name} "
            "AFTER INSERT ON clear_financial_events_v1 "
            "BEGIN "
            "DELETE FROM clear_financial_events_v1 "
            "WHERE sequence_number = NEW.sequence_number; "
            "END"
        )
    _assert_persistence_error(
        PersistenceErrorCode.SCHEMA_MISMATCH,
        lambda: open_sqlite_financial_ledger_v1(str(path)),
    )


@pytest.mark.parametrize(
    "table",
    [
        "clear_financial_events_v1",
        "clear_provider_references_v1",
        "clear_idempotency_records_v1",
    ],
)
def test_preexisting_orphan_foreign_keys_fail_closed(tmp_path: Path, table: str) -> None:
    path = tmp_path / "ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        ledger.reserve_execution(_reservation())
        ledger.append_event(_event())
        ledger.record_provider_reference(_reference())
        ledger.claim_idempotency(_idempotency())
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            f"UPDATE {table} SET execution_id = ?",
            (_uuid(1, 99),),
        )
    _assert_persistence_error(
        PersistenceErrorCode.CORRUPT_STORED_RECORD,
        lambda: open_sqlite_financial_ledger_v1(str(path)),
    )


@pytest.mark.parametrize(
    ("table", "column", "bad_value", "reader"),
    [
        (
            "clear_execution_reservations_v1",
            "market_id",
            "not-a-uuid",
            lambda ledger: ledger.get_execution_reservation(_uuid(1, 1)),
        ),
        (
            "clear_execution_reservations_v1",
            "certificate_digest_sha256",
            "A" * 64,
            lambda ledger: ledger.get_execution_reservation(_uuid(1, 1)),
        ),
        (
            "clear_execution_reservations_v1",
            "reserved_at",
            "2026-09-04T12:00:01Z",
            lambda ledger: ledger.get_execution_reservation(_uuid(1, 1)),
        ),
        (
            "clear_financial_events_v1",
            "fields_json",
            "{",
            lambda ledger: ledger.get_event(_uuid(3, 1)),
        ),
        (
            "clear_financial_events_v1",
            "fields_json",
            "[" * 1_100 + "]" * 1_100,
            lambda ledger: ledger.get_event(_uuid(3, 1)),
        ),
        (
            "clear_financial_events_v1",
            "fields_json",
            '[{"field_key":"field.1", "value":1,"value_type":"integer"}]',
            lambda ledger: ledger.get_event(_uuid(3, 1)),
        ),
        (
            "clear_financial_events_v1",
            "fields_json",
            '[{"field_key":"field.1","field_key":"field.1","value":1,"value_type":"integer"}]',
            lambda ledger: ledger.get_event(_uuid(3, 1)),
        ),
        (
            "clear_financial_events_v1",
            "fields_json",
            '[{"field_key":"field.1","value":true,"value_type":"integer"}]',
            lambda ledger: ledger.get_event(_uuid(3, 1)),
        ),
        (
            "clear_financial_events_v1",
            "occurred_at",
            "2026-09-04 12:01:00",
            lambda ledger: ledger.get_event(_uuid(3, 1)),
        ),
        (
            "clear_provider_references_v1",
            "recorded_at",
            "2026-09-04 12:01:00",
            lambda ledger: ledger.get_provider_reference(
                provider_name="example-provider",
                reference_kind="order",
                reference_id="reference-1",
            ),
        ),
        (
            "clear_idempotency_records_v1",
            "request_fingerprint_sha256",
            "A" * 64,
            lambda ledger: ledger.get_idempotency_record(
                namespace="provider.request",
                idempotency_key="request-1",
            ),
        ),
    ],
)
def test_corrupt_stored_rows_fail_closed(
    tmp_path: Path,
    table: str,
    column: str,
    bad_value: str,
    reader: Any,
) -> None:
    path = tmp_path / "ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        ledger.reserve_execution(_reservation())
        ledger.append_event(_event())
        ledger.record_provider_reference(_reference())
        ledger.claim_idempotency(_idempotency())
    with sqlite3.connect(path) as connection:
        connection.execute(f"UPDATE {table} SET {column} = ?", (bad_value,))
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        _assert_persistence_error(
            PersistenceErrorCode.CORRUPT_STORED_RECORD,
            lambda: reader(ledger),
        )


def test_fields_json_storage_is_compact_sorted_and_type_explicit(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    event = _event(
        fields=(
            _field(2, field_key="zeta", value_type=FinancialLedgerValueType.BOOLEAN, value=True),
            _field(1, field_key="alpha", value_type=FinancialLedgerValueType.STRING, value="é"),
        )
    )
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        ledger.reserve_execution(_reservation())
        ledger.append_event(event)
    with sqlite3.connect(path) as connection:
        stored = connection.execute(
            "SELECT fields_json FROM clear_financial_events_v1 WHERE event_id = ?",
            (event.event_id,),
        ).fetchone()[0]
    assert stored == (
        '[{"field_key":"alpha","value":"é","value_type":"string"},'
        '{"field_key":"zeta","value":true,"value_type":"boolean"}]'
    )
    assert json.loads(stored)[0]["field_key"] == "alpha"


def test_out_of_order_stored_event_fields_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    event = _event(
        fields=(
            _field(1, field_key="alpha"),
            _field(2, field_key="zeta"),
        )
    )
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        ledger.reserve_execution(_reservation())
        ledger.append_event(event)
    reversed_fields_json = (
        '[{"field_key":"zeta","value":2,"value_type":"integer"},'
        '{"field_key":"alpha","value":1,"value_type":"integer"}]'
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE clear_financial_events_v1 SET fields_json = ? WHERE event_id = ?",
            (reversed_fields_json, event.event_id),
        )
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        _assert_persistence_error(
            PersistenceErrorCode.CORRUPT_STORED_RECORD,
            lambda: ledger.get_event(event.event_id),
        )


def test_close_is_idempotent_and_all_operations_after_close_fail(tmp_path: Path) -> None:
    ledger = open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db"))
    ledger.close()
    ledger.close()
    operations = (
        lambda: ledger.reserve_execution(_reservation()),
        lambda: ledger.get_execution_reservation(_uuid(1, 1)),
        lambda: ledger.append_event(_event()),
        lambda: ledger.get_event(_uuid(3, 1)),
        lambda: ledger.list_events(_uuid(1, 1)),
        lambda: ledger.record_provider_reference(_reference()),
        lambda: ledger.get_provider_reference(
            provider_name="provider", reference_kind="order", reference_id="id"
        ),
        lambda: ledger.list_provider_references(_uuid(1, 1)),
        lambda: ledger.claim_idempotency(_idempotency()),
        lambda: ledger.claim_idempotency_pair(*_idempotency_pair()),
        lambda: ledger.get_idempotency_record(namespace="request", idempotency_key="key"),
    )
    for operation in operations:
        _assert_persistence_error(PersistenceErrorCode.CLOSED, operation)


def test_database_open_failure_is_stable_and_non_sensitive(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "ledger.db"
    error = _assert_persistence_error(
        PersistenceErrorCode.DATABASE_OPEN_FAILED,
        lambda: open_sqlite_financial_ledger_v1(str(path)),
    )
    assert str(path) not in str(error)


@pytest.mark.parametrize("path", ["", "bad\x00path", 1, Path("ledger.db")])
def test_database_path_requires_exact_nonempty_string(path: object) -> None:
    with pytest.raises(ValueError):
        open_sqlite_financial_ledger_v1(cast(Any, path))


def test_unencodable_database_path_maps_to_open_failure() -> None:
    _assert_persistence_error(
        PersistenceErrorCode.DATABASE_OPEN_FAILED,
        lambda: open_sqlite_financial_ledger_v1("\ud800"),
    )


def test_getters_validate_queries_and_return_none_for_absent_values(tmp_path: Path) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        assert ledger.get_execution_reservation(_uuid(1, 1)) is None
        assert ledger.get_execution_reservation_by_certificate_digest("a" * 64) is None
        assert ledger.get_execution_reservation_by_market_id(_uuid(2, 1)) is None
        assert ledger.get_event(_uuid(3, 1)) is None
        assert (
            ledger.get_provider_reference(
                provider_name="provider", reference_kind="order", reference_id="id"
            )
            is None
        )
        assert ledger.get_idempotency_record(namespace="request", idempotency_key="key") is None
        with pytest.raises(ValueError):
            ledger.get_execution_reservation("not-a-uuid")
        with pytest.raises(ValueError):
            ledger.get_execution_reservation_by_certificate_digest("A" * 64)
        with pytest.raises(ValueError):
            ledger.get_provider_reference(
                provider_name="Provider", reference_kind="order", reference_id="id"
            )


class _ReservationSubclass(ExecutionReservationV1):
    pass


def test_write_inputs_require_fresh_exact_models(tmp_path: Path) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        reservation = _reservation()
        with pytest.raises(TypeError):
            ledger.reserve_execution(cast(Any, reservation.model_dump()))
        with pytest.raises(TypeError):
            ledger.reserve_execution(cast(Any, _ReservationSubclass(**reservation.__dict__)))
        malformed = ExecutionReservationV1.model_construct(
            execution_id=reservation.execution_id,
            certificate_digest_version=_DIGEST_VERSION,
            certificate_digest_sha256="A" * 64,
            market_id=reservation.market_id,
            execution_request_fingerprint_sha256=reservation.execution_request_fingerprint_sha256,
            reserved_at=reservation.reserved_at,
        )
        with pytest.raises(ValueError):
            ledger.reserve_execution(malformed)


def test_public_surface_has_no_history_mutation_api() -> None:
    forbidden = (
        "delete_event",
        "update_event",
        "replace_event",
        "delete_reservation",
        "replace_reservation",
        "remap_provider_reference",
        "overwrite_idempotency",
    )
    assert all(not hasattr(SQLiteFinancialLedgerV1, name) for name in forbidden)
