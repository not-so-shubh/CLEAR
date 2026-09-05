"""Transactional SQLite storage for immutable local financial ledger facts.

Persistence records facts already decided by its caller. It does not verify certificates, authorize
money, approve execution, or establish that a provider action occurred.
"""

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, cast

from pydantic import BaseModel, TypeAdapter, ValidationError

from clear_market.canonical import canonical_json_bytes, canonical_utc_datetime
from clear_market.domain import CanonicalUUID4
from clear_market.persistence.models import (
    ExecutionReservationDispositionV1,
    ExecutionReservationResultV1,
    ExecutionReservationV1,
    FinancialLedgerEventAppendDispositionV1,
    FinancialLedgerEventAppendResultV1,
    FinancialLedgerEventV1,
    FinancialLedgerFieldV1,
    FinancialLedgerValueType,
    IdempotencyDispositionV1,
    IdempotencyRecordV1,
    IdempotencyResultV1,
    PersistedFinancialLedgerEventV1,
    ProviderReferenceDispositionV1,
    ProviderReferenceResultV1,
    ProviderReferenceV1,
    _validate_event_namespace,
    _validate_idempotency_key,
    _validate_provider_name,
    _validate_reference_id,
    _validate_sha256_hex,
)

SQLITE_FINANCIAL_LEDGER_SCHEMA_VERSION: Final[int] = 1

_STORAGE_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z",
    flags=re.ASCII,
)
_SQLITE_SIGNED_INT_MAX: Final[int] = 9_223_372_036_854_775_807
_UUID_ADAPTER: TypeAdapter[str] = TypeAdapter(CanonicalUUID4)

_CREATE_EXECUTION_RESERVATIONS = """\
CREATE TABLE clear_execution_reservations_v1 (
    execution_id TEXT PRIMARY KEY,
    certificate_digest_version TEXT NOT NULL,
    certificate_digest_sha256 TEXT NOT NULL UNIQUE,
    market_id TEXT NOT NULL UNIQUE,
    execution_request_fingerprint_sha256 TEXT NOT NULL,
    reserved_at TEXT NOT NULL
)"""

_CREATE_FINANCIAL_EVENTS = """\
CREATE TABLE clear_financial_events_v1 (
    sequence_number INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    execution_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    FOREIGN KEY (execution_id)
        REFERENCES clear_execution_reservations_v1 (execution_id)
        ON DELETE RESTRICT
)"""

_CREATE_PROVIDER_REFERENCES = """\
CREATE TABLE clear_provider_references_v1 (
    provider_name TEXT NOT NULL,
    reference_kind TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (provider_name, reference_kind, reference_id),
    FOREIGN KEY (execution_id)
        REFERENCES clear_execution_reservations_v1 (execution_id)
        ON DELETE RESTRICT
)"""

_CREATE_IDEMPOTENCY_RECORDS = """\
CREATE TABLE clear_idempotency_records_v1 (
    namespace TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_fingerprint_sha256 TEXT NOT NULL,
    execution_id TEXT,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (namespace, idempotency_key),
    FOREIGN KEY (execution_id)
        REFERENCES clear_execution_reservations_v1 (execution_id)
        ON DELETE RESTRICT
)"""

_EXPECTED_SCHEMA: Final[dict[str, str]] = {
    "clear_execution_reservations_v1": _CREATE_EXECUTION_RESERVATIONS,
    "clear_financial_events_v1": _CREATE_FINANCIAL_EVENTS,
    "clear_provider_references_v1": _CREATE_PROVIDER_REFERENCES,
    "clear_idempotency_records_v1": _CREATE_IDEMPOTENCY_RECORDS,
}


class PersistenceErrorCode(StrEnum):
    DATABASE_OPEN_FAILED = "DATABASE_OPEN_FAILED"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    DATABASE_OPERATION_FAILED = "DATABASE_OPERATION_FAILED"
    CORRUPT_STORED_RECORD = "CORRUPT_STORED_RECORD"
    UNKNOWN_EXECUTION = "UNKNOWN_EXECUTION"
    CLOSED = "CLOSED"


class PersistenceError(RuntimeError):
    """Stable persistence failure without paths, SQL, or stored financial values."""

    __slots__ = ("_code",)

    def __init__(self, code: PersistenceErrorCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> PersistenceErrorCode:
        return self._code


class _IdempotencyPairConflict(RuntimeError):
    """Internal signal for an atomic idempotency-pair conflict."""

    __slots__ = ("_index", "_result")

    def __init__(self, index: int, result: IdempotencyResultV1) -> None:
        self._index = index
        self._result = result
        super().__init__("idempotency pair conflict")

    @property
    def index(self) -> int:
        return self._index

    @property
    def result(self) -> IdempotencyResultV1:
        return self._result


class _DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _normalize_schema_sql(value: str) -> str:
    return " ".join(value.split()).rstrip(";")


def _configure_connection(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute("PRAGMA busy_timeout = 5000")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise PersistenceError(PersistenceErrorCode.DATABASE_OPEN_FAILED)
    if connection.execute("PRAGMA synchronous").fetchone()[0] != 2:
        raise PersistenceError(PersistenceErrorCode.DATABASE_OPEN_FAILED)
    if connection.execute("PRAGMA busy_timeout").fetchone()[0] != 5_000:
        raise PersistenceError(PersistenceErrorCode.DATABASE_OPEN_FAILED)


def _user_schema_objects(connection: sqlite3.Connection) -> tuple[tuple[str, str], ...]:
    rows = connection.execute("SELECT type, name FROM sqlite_master ORDER BY type, name").fetchall()
    result: list[tuple[str, str]] = []
    for row in rows:
        object_type = cast(str, row[0])
        name = cast(str, row[1])
        if not name.startswith("sqlite_"):
            result.append((object_type, name))
    return tuple(result)


def _verify_schema(connection: sqlite3.Connection) -> None:
    expected_objects = tuple(("table", name) for name in sorted(_EXPECTED_SCHEMA))
    if _user_schema_objects(connection) != expected_objects:
        raise PersistenceError(PersistenceErrorCode.SCHEMA_MISMATCH)
    rows = connection.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type = 'table' AND name IN (?, ?, ?, ?) ORDER BY name",
        tuple(sorted(_EXPECTED_SCHEMA)),
    ).fetchall()
    actual = {cast(str, name): cast(str, sql) for name, sql in rows}
    if set(actual) != set(_EXPECTED_SCHEMA):
        raise PersistenceError(PersistenceErrorCode.SCHEMA_MISMATCH)
    for name, expected_sql in _EXPECTED_SCHEMA.items():
        if _normalize_schema_sql(actual[name]) != _normalize_schema_sql(expected_sql):
            raise PersistenceError(PersistenceErrorCode.SCHEMA_MISMATCH)


def _verify_foreign_key_integrity(connection: sqlite3.Connection) -> None:
    try:
        violation = connection.execute("PRAGMA foreign_key_check").fetchone()
    except sqlite3.Error:
        raise PersistenceError(PersistenceErrorCode.DATABASE_OPEN_FAILED) from None
    if violation is not None:
        raise PersistenceError(PersistenceErrorCode.CORRUPT_STORED_RECORD)


def _initialize_schema(connection: sqlite3.Connection) -> None:
    row = connection.execute("PRAGMA user_version").fetchone()
    if row is None or type(row[0]) is not int:
        raise PersistenceError(PersistenceErrorCode.SCHEMA_MISMATCH)
    user_version = row[0]
    if user_version == 0:
        if _user_schema_objects(connection):
            raise PersistenceError(PersistenceErrorCode.SCHEMA_MISMATCH)
        try:
            connection.execute("BEGIN IMMEDIATE")
            for statement in _EXPECTED_SCHEMA.values():
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {SQLITE_FINANCIAL_LEDGER_SCHEMA_VERSION}")
            connection.execute("COMMIT")
        except sqlite3.Error:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise PersistenceError(PersistenceErrorCode.SCHEMA_MISMATCH) from None
    elif user_version != SQLITE_FINANCIAL_LEDGER_SCHEMA_VERSION:
        raise PersistenceError(PersistenceErrorCode.SCHEMA_MISMATCH)
    _verify_schema(connection)
    _verify_foreign_key_integrity(connection)


def _fresh_exact_model[ModelT: BaseModel](
    value: object,
    expected_type: type[ModelT],
    message: str,
) -> ModelT:
    if type(value) is not expected_type:
        raise TypeError(message)
    try:
        fields = {name: value.__dict__[name] for name in expected_type.model_fields}
        return expected_type.model_validate(fields)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError(message) from None


def _validate_uuid(value: object, message: str) -> str:
    try:
        return _UUID_ADAPTER.validate_python(value)
    except ValidationError:
        raise ValueError(message) from None


def _validate_exact_int(value: object, *, minimum: int, maximum: int | None, name: str) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} is outside its exact integer bound")
    return value


def _parse_storage_timestamp(value: object) -> datetime:
    if type(value) is not str or _STORAGE_TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise PersistenceError(PersistenceErrorCode.CORRUPT_STORED_RECORD)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        raise PersistenceError(PersistenceErrorCode.CORRUPT_STORED_RECORD) from None
    if canonical_utc_datetime(parsed) != value:
        raise PersistenceError(PersistenceErrorCode.CORRUPT_STORED_RECORD)
    return parsed


def _serialize_event_fields(fields: tuple[FinancialLedgerFieldV1, ...]) -> str:
    projection = [
        {
            "field_key": field.field_key,
            "value_type": field.value_type.value,
            "value": field.value,
        }
        for field in fields
    ]
    return canonical_json_bytes(projection).decode("utf-8", errors="strict")


def _parse_event_fields(value: object) -> tuple[FinancialLedgerFieldV1, ...]:
    if type(value) is not str:
        raise PersistenceError(PersistenceErrorCode.CORRUPT_STORED_RECORD)
    try:
        parsed = json.loads(value, object_pairs_hook=_reject_duplicate_keys)
        if type(parsed) is not list:
            raise ValueError
        fields: list[FinancialLedgerFieldV1] = []
        for item in cast(list[object], parsed):
            if type(item) is not dict:
                raise ValueError
            item_data = cast(dict[str, object], item)
            if set(item_data) != {"field_key", "value_type", "value"}:
                raise ValueError
            if type(item_data["value_type"]) is not str:
                raise ValueError
            fields.append(
                FinancialLedgerFieldV1(
                    field_key=cast(str, item_data["field_key"]),
                    value_type=FinancialLedgerValueType(item_data["value_type"]),
                    value=cast(str | int | bool, item_data["value"]),
                )
            )
        field_keys = tuple(field.field_key for field in fields)
        if len(set(field_keys)) != len(field_keys):
            raise ValueError
        result = tuple(sorted(fields, key=lambda field: field.field_key))
        if _serialize_event_fields(result) != value:
            raise ValueError
        return result
    except (
        _DuplicateKeyError,
        json.JSONDecodeError,
        RecursionError,
        UnicodeError,
        ValueError,
        ValidationError,
    ):
        raise PersistenceError(PersistenceErrorCode.CORRUPT_STORED_RECORD) from None


def _reservation_from_row(row: sqlite3.Row) -> ExecutionReservationV1:
    try:
        return ExecutionReservationV1(
            execution_id=row["execution_id"],
            certificate_digest_version=row["certificate_digest_version"],
            certificate_digest_sha256=row["certificate_digest_sha256"],
            market_id=row["market_id"],
            execution_request_fingerprint_sha256=row["execution_request_fingerprint_sha256"],
            reserved_at=_parse_storage_timestamp(row["reserved_at"]),
        )
    except (IndexError, TypeError, ValueError, ValidationError):
        raise PersistenceError(PersistenceErrorCode.CORRUPT_STORED_RECORD) from None


def _event_from_row(row: sqlite3.Row) -> PersistedFinancialLedgerEventV1:
    try:
        event = FinancialLedgerEventV1(
            event_id=row["event_id"],
            execution_id=row["execution_id"],
            event_type=row["event_type"],
            occurred_at=_parse_storage_timestamp(row["occurred_at"]),
            fields=_parse_event_fields(row["fields_json"]),
        )
        return PersistedFinancialLedgerEventV1(
            sequence_number=row["sequence_number"],
            event=event,
        )
    except PersistenceError:
        raise
    except (IndexError, TypeError, ValueError, ValidationError):
        raise PersistenceError(PersistenceErrorCode.CORRUPT_STORED_RECORD) from None


def _reference_from_row(row: sqlite3.Row) -> ProviderReferenceV1:
    try:
        return ProviderReferenceV1(
            provider_name=row["provider_name"],
            reference_kind=row["reference_kind"],
            reference_id=row["reference_id"],
            execution_id=row["execution_id"],
            recorded_at=_parse_storage_timestamp(row["recorded_at"]),
        )
    except PersistenceError:
        raise
    except (IndexError, TypeError, ValueError, ValidationError):
        raise PersistenceError(PersistenceErrorCode.CORRUPT_STORED_RECORD) from None


def _idempotency_from_row(row: sqlite3.Row) -> IdempotencyRecordV1:
    try:
        return IdempotencyRecordV1(
            namespace=row["namespace"],
            idempotency_key=row["idempotency_key"],
            request_fingerprint_sha256=row["request_fingerprint_sha256"],
            execution_id=row["execution_id"],
            recorded_at=_parse_storage_timestamp(row["recorded_at"]),
        )
    except PersistenceError:
        raise
    except (IndexError, TypeError, ValueError, ValidationError):
        raise PersistenceError(PersistenceErrorCode.CORRUPT_STORED_RECORD) from None


class SQLiteFinancialLedgerV1:
    """File-capable transactional storage; reservation existence grants no authority."""

    def __init__(self, database_path: str) -> None:
        if type(database_path) is not str or not database_path or "\x00" in database_path:
            raise ValueError("database_path must be an exact nonempty string without NUL")
        try:
            connection = sqlite3.connect(database_path, isolation_level=None)
            connection.row_factory = sqlite3.Row
            _configure_connection(connection)
            _initialize_schema(connection)
        except PersistenceError:
            if "connection" in locals():
                connection.close()
            raise
        except (sqlite3.Error, UnicodeError):
            if "connection" in locals():
                connection.close()
            raise PersistenceError(PersistenceErrorCode.DATABASE_OPEN_FAILED) from None
        self._connection: sqlite3.Connection | None = connection

    def __enter__(self) -> "SQLiteFinancialLedgerV1":
        self._ensure_open()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()

    def _ensure_open(self) -> sqlite3.Connection:
        if self._connection is None:
            raise PersistenceError(PersistenceErrorCode.CLOSED)
        return self._connection

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._ensure_open()
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.Error:
            raise PersistenceError(PersistenceErrorCode.DATABASE_OPERATION_FAILED) from None
        try:
            yield connection
        except sqlite3.Error:
            raise PersistenceError(PersistenceErrorCode.DATABASE_OPERATION_FAILED) from None
        else:
            try:
                connection.execute("COMMIT")
            except sqlite3.Error:
                raise PersistenceError(PersistenceErrorCode.DATABASE_OPERATION_FAILED) from None
        finally:
            if connection.in_transaction:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass

    def close(self) -> None:
        connection = self._connection
        if connection is None:
            return
        self._connection = None
        try:
            connection.close()
        except sqlite3.Error:
            raise PersistenceError(PersistenceErrorCode.DATABASE_OPERATION_FAILED) from None

    def _query_one(self, sql: str, parameters: tuple[object, ...]) -> sqlite3.Row | None:
        connection = self._ensure_open()
        try:
            return cast(sqlite3.Row | None, connection.execute(sql, parameters).fetchone())
        except sqlite3.Error:
            raise PersistenceError(PersistenceErrorCode.DATABASE_OPERATION_FAILED) from None

    def _execution_exists(self, connection: sqlite3.Connection, execution_id: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM clear_execution_reservations_v1 WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            is not None
        )

    def reserve_execution(
        self,
        reservation: ExecutionReservationV1,
    ) -> ExecutionReservationResultV1:
        self._ensure_open()
        requested = _fresh_exact_model(
            reservation,
            ExecutionReservationV1,
            "reservation must be a valid exact ExecutionReservationV1",
        )
        select = (
            "SELECT execution_id, certificate_digest_version, certificate_digest_sha256, "
            "market_id, execution_request_fingerprint_sha256, reserved_at "
            "FROM clear_execution_reservations_v1"
        )
        with self._write_transaction() as connection:
            row = connection.execute(
                f"{select} WHERE execution_id = ?", (requested.execution_id,)
            ).fetchone()
            if row is not None:
                stored = _reservation_from_row(row)
                same = (
                    stored.certificate_digest_version == requested.certificate_digest_version
                    and stored.certificate_digest_sha256 == requested.certificate_digest_sha256
                    and stored.market_id == requested.market_id
                    and stored.execution_request_fingerprint_sha256
                    == requested.execution_request_fingerprint_sha256
                )
                disposition = (
                    ExecutionReservationDispositionV1.EXISTING_SAME
                    if same
                    else ExecutionReservationDispositionV1.EXECUTION_ID_CONFLICT
                )
                return ExecutionReservationResultV1(
                    disposition=disposition,
                    stored_reservation=stored,
                )

            row = connection.execute(
                f"{select} WHERE certificate_digest_sha256 = ?",
                (requested.certificate_digest_sha256,),
            ).fetchone()
            if row is not None:
                return ExecutionReservationResultV1(
                    disposition=ExecutionReservationDispositionV1.CERTIFICATE_ALREADY_RESERVED,
                    stored_reservation=_reservation_from_row(row),
                )

            row = connection.execute(
                f"{select} WHERE market_id = ?", (requested.market_id,)
            ).fetchone()
            if row is not None:
                return ExecutionReservationResultV1(
                    disposition=ExecutionReservationDispositionV1.MARKET_ALREADY_RESERVED,
                    stored_reservation=_reservation_from_row(row),
                )

            connection.execute(
                "INSERT INTO clear_execution_reservations_v1 "
                "(execution_id, certificate_digest_version, certificate_digest_sha256, market_id, "
                "execution_request_fingerprint_sha256, reserved_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    requested.execution_id,
                    requested.certificate_digest_version,
                    requested.certificate_digest_sha256,
                    requested.market_id,
                    requested.execution_request_fingerprint_sha256,
                    canonical_utc_datetime(requested.reserved_at),
                ),
            )
            return ExecutionReservationResultV1(
                disposition=ExecutionReservationDispositionV1.CREATED,
                stored_reservation=requested,
            )

    def get_execution_reservation(self, execution_id: str) -> ExecutionReservationV1 | None:
        self._ensure_open()
        validated = _validate_uuid(execution_id, "execution_id must be a canonical UUIDv4 string")
        row = self._query_one(
            "SELECT execution_id, certificate_digest_version, certificate_digest_sha256, "
            "market_id, execution_request_fingerprint_sha256, reserved_at "
            "FROM clear_execution_reservations_v1 WHERE execution_id = ?",
            (validated,),
        )
        return None if row is None else _reservation_from_row(row)

    def get_execution_reservation_by_certificate_digest(
        self,
        certificate_digest_sha256: str,
    ) -> ExecutionReservationV1 | None:
        self._ensure_open()
        validated = _validate_sha256_hex(certificate_digest_sha256)
        row = self._query_one(
            "SELECT execution_id, certificate_digest_version, certificate_digest_sha256, "
            "market_id, execution_request_fingerprint_sha256, reserved_at "
            "FROM clear_execution_reservations_v1 WHERE certificate_digest_sha256 = ?",
            (validated,),
        )
        return None if row is None else _reservation_from_row(row)

    def get_execution_reservation_by_market_id(
        self,
        market_id: str,
    ) -> ExecutionReservationV1 | None:
        self._ensure_open()
        validated = _validate_uuid(market_id, "market_id must be a canonical UUIDv4 string")
        row = self._query_one(
            "SELECT execution_id, certificate_digest_version, certificate_digest_sha256, "
            "market_id, execution_request_fingerprint_sha256, reserved_at "
            "FROM clear_execution_reservations_v1 WHERE market_id = ?",
            (validated,),
        )
        return None if row is None else _reservation_from_row(row)

    def append_event(
        self,
        event: FinancialLedgerEventV1,
    ) -> FinancialLedgerEventAppendResultV1:
        self._ensure_open()
        requested = _fresh_exact_model(
            event,
            FinancialLedgerEventV1,
            "event must be a valid exact FinancialLedgerEventV1",
        )
        with self._write_transaction() as connection:
            if not self._execution_exists(connection, requested.execution_id):
                raise PersistenceError(PersistenceErrorCode.UNKNOWN_EXECUTION)
            row = connection.execute(
                "SELECT sequence_number, event_id, execution_id, event_type, occurred_at, "
                "fields_json FROM clear_financial_events_v1 WHERE event_id = ?",
                (requested.event_id,),
            ).fetchone()
            if row is not None:
                persisted = _event_from_row(row)
                disposition = (
                    FinancialLedgerEventAppendDispositionV1.EXISTING_SAME
                    if persisted.event == requested
                    else FinancialLedgerEventAppendDispositionV1.EVENT_ID_CONFLICT
                )
                return FinancialLedgerEventAppendResultV1(
                    disposition=disposition,
                    persisted_event=persisted,
                )
            cursor = connection.execute(
                "INSERT INTO clear_financial_events_v1 "
                "(event_id, execution_id, event_type, occurred_at, fields_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    requested.event_id,
                    requested.execution_id,
                    requested.event_type,
                    canonical_utc_datetime(requested.occurred_at),
                    _serialize_event_fields(requested.fields),
                ),
            )
            if type(cursor.lastrowid) is not int:
                raise PersistenceError(PersistenceErrorCode.DATABASE_OPERATION_FAILED)
            persisted = PersistedFinancialLedgerEventV1(
                sequence_number=cursor.lastrowid,
                event=requested,
            )
            return FinancialLedgerEventAppendResultV1(
                disposition=FinancialLedgerEventAppendDispositionV1.CREATED,
                persisted_event=persisted,
            )

    def get_event(self, event_id: str) -> PersistedFinancialLedgerEventV1 | None:
        self._ensure_open()
        validated = _validate_uuid(event_id, "event_id must be a canonical UUIDv4 string")
        row = self._query_one(
            "SELECT sequence_number, event_id, execution_id, event_type, occurred_at, fields_json "
            "FROM clear_financial_events_v1 WHERE event_id = ?",
            (validated,),
        )
        return None if row is None else _event_from_row(row)

    def list_events(
        self,
        execution_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> tuple[PersistedFinancialLedgerEventV1, ...]:
        self._ensure_open()
        validated_execution_id = _validate_uuid(
            execution_id,
            "execution_id must be a canonical UUIDv4 string",
        )
        validated_after = _validate_exact_int(
            after_sequence,
            minimum=0,
            maximum=None,
            name="after_sequence",
        )
        validated_limit = _validate_exact_int(limit, minimum=1, maximum=1_000, name="limit")
        connection = self._ensure_open()
        try:
            if not self._execution_exists(connection, validated_execution_id):
                raise PersistenceError(PersistenceErrorCode.UNKNOWN_EXECUTION)
            if validated_after > _SQLITE_SIGNED_INT_MAX:
                return ()
            rows = connection.execute(
                "SELECT sequence_number, event_id, execution_id, event_type, occurred_at, "
                "fields_json FROM clear_financial_events_v1 "
                "WHERE execution_id = ? AND sequence_number > ? "
                "ORDER BY sequence_number ASC LIMIT ?",
                (validated_execution_id, validated_after, validated_limit),
            ).fetchall()
        except sqlite3.Error:
            raise PersistenceError(PersistenceErrorCode.DATABASE_OPERATION_FAILED) from None
        return tuple(_event_from_row(row) for row in rows)

    def record_provider_reference(
        self,
        reference: ProviderReferenceV1,
    ) -> ProviderReferenceResultV1:
        self._ensure_open()
        requested = _fresh_exact_model(
            reference,
            ProviderReferenceV1,
            "reference must be a valid exact ProviderReferenceV1",
        )
        with self._write_transaction() as connection:
            if not self._execution_exists(connection, requested.execution_id):
                raise PersistenceError(PersistenceErrorCode.UNKNOWN_EXECUTION)
            row = connection.execute(
                "SELECT provider_name, reference_kind, reference_id, execution_id, recorded_at "
                "FROM clear_provider_references_v1 "
                "WHERE provider_name = ? AND reference_kind = ? AND reference_id = ?",
                (requested.provider_name, requested.reference_kind, requested.reference_id),
            ).fetchone()
            if row is not None:
                stored = _reference_from_row(row)
                disposition = (
                    ProviderReferenceDispositionV1.EXISTING_SAME
                    if stored.execution_id == requested.execution_id
                    else ProviderReferenceDispositionV1.REFERENCE_CONFLICT
                )
                return ProviderReferenceResultV1(
                    disposition=disposition,
                    stored_reference=stored,
                )
            connection.execute(
                "INSERT INTO clear_provider_references_v1 "
                "(provider_name, reference_kind, reference_id, execution_id, recorded_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    requested.provider_name,
                    requested.reference_kind,
                    requested.reference_id,
                    requested.execution_id,
                    canonical_utc_datetime(requested.recorded_at),
                ),
            )
            return ProviderReferenceResultV1(
                disposition=ProviderReferenceDispositionV1.CREATED,
                stored_reference=requested,
            )

    def get_provider_reference(
        self,
        *,
        provider_name: str,
        reference_kind: str,
        reference_id: str,
    ) -> ProviderReferenceV1 | None:
        self._ensure_open()
        provider = _validate_provider_name(provider_name)
        kind = _validate_event_namespace(reference_kind)
        reference = _validate_reference_id(reference_id)
        row = self._query_one(
            "SELECT provider_name, reference_kind, reference_id, execution_id, recorded_at "
            "FROM clear_provider_references_v1 "
            "WHERE provider_name = ? AND reference_kind = ? AND reference_id = ?",
            (provider, kind, reference),
        )
        return None if row is None else _reference_from_row(row)

    def list_provider_references(
        self,
        execution_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[ProviderReferenceV1, ...]:
        self._ensure_open()
        validated_execution_id = _validate_uuid(
            execution_id,
            "execution_id must be a canonical UUIDv4 string",
        )
        validated_limit = _validate_exact_int(limit, minimum=1, maximum=1_000, name="limit")
        validated_offset = _validate_exact_int(offset, minimum=0, maximum=None, name="offset")
        connection = self._ensure_open()
        try:
            if not self._execution_exists(connection, validated_execution_id):
                raise PersistenceError(PersistenceErrorCode.UNKNOWN_EXECUTION)
            if validated_offset > _SQLITE_SIGNED_INT_MAX:
                return ()
            rows = connection.execute(
                "SELECT provider_name, reference_kind, reference_id, execution_id, recorded_at "
                "FROM clear_provider_references_v1 WHERE execution_id = ? "
                "ORDER BY provider_name, reference_kind, reference_id LIMIT ? OFFSET ?",
                (validated_execution_id, validated_limit, validated_offset),
            ).fetchall()
        except sqlite3.Error:
            raise PersistenceError(PersistenceErrorCode.DATABASE_OPERATION_FAILED) from None
        return tuple(_reference_from_row(row) for row in rows)

    def claim_idempotency(self, record: IdempotencyRecordV1) -> IdempotencyResultV1:
        self._ensure_open()
        requested = _fresh_exact_model(
            record,
            IdempotencyRecordV1,
            "record must be a valid exact IdempotencyRecordV1",
        )
        with self._write_transaction() as connection:
            if requested.execution_id is not None and not self._execution_exists(
                connection, requested.execution_id
            ):
                raise PersistenceError(PersistenceErrorCode.UNKNOWN_EXECUTION)
            row = connection.execute(
                "SELECT namespace, idempotency_key, request_fingerprint_sha256, execution_id, "
                "recorded_at FROM clear_idempotency_records_v1 "
                "WHERE namespace = ? AND idempotency_key = ?",
                (requested.namespace, requested.idempotency_key),
            ).fetchone()
            if row is not None:
                stored = _idempotency_from_row(row)
                same = (
                    stored.request_fingerprint_sha256 == requested.request_fingerprint_sha256
                    and stored.execution_id == requested.execution_id
                )
                return IdempotencyResultV1(
                    disposition=(
                        IdempotencyDispositionV1.EXISTING_SAME
                        if same
                        else IdempotencyDispositionV1.CONFLICT
                    ),
                    stored_record=stored,
                )
            connection.execute(
                "INSERT INTO clear_idempotency_records_v1 "
                "(namespace, idempotency_key, request_fingerprint_sha256, execution_id, "
                "recorded_at) VALUES (?, ?, ?, ?, ?)",
                (
                    requested.namespace,
                    requested.idempotency_key,
                    requested.request_fingerprint_sha256,
                    requested.execution_id,
                    canonical_utc_datetime(requested.recorded_at),
                ),
            )
            return IdempotencyResultV1(
                disposition=IdempotencyDispositionV1.CREATED,
                stored_record=requested,
            )

    def claim_idempotency_pair(
        self,
        first: IdempotencyRecordV1,
        second: IdempotencyRecordV1,
    ) -> tuple[IdempotencyResultV1, IdempotencyResultV1]:
        """Atomically claim two distinct idempotency keys or persist neither new claim."""
        self._ensure_open()
        requested = (
            _fresh_exact_model(
                first,
                IdempotencyRecordV1,
                "record must be a valid exact IdempotencyRecordV1",
            ),
            _fresh_exact_model(
                second,
                IdempotencyRecordV1,
                "record must be a valid exact IdempotencyRecordV1",
            ),
        )
        if (
            requested[0].namespace,
            requested[0].idempotency_key,
        ) == (
            requested[1].namespace,
            requested[1].idempotency_key,
        ):
            raise ValueError("idempotency pair records must use distinct keys")

        with self._write_transaction() as connection:
            for record in requested:
                if record.execution_id is not None and not self._execution_exists(
                    connection, record.execution_id
                ):
                    raise PersistenceError(PersistenceErrorCode.UNKNOWN_EXECUTION)

            results: list[IdempotencyResultV1 | None] = []
            for index, record in enumerate(requested):
                row = connection.execute(
                    "SELECT namespace, idempotency_key, request_fingerprint_sha256, execution_id, "
                    "recorded_at FROM clear_idempotency_records_v1 "
                    "WHERE namespace = ? AND idempotency_key = ?",
                    (record.namespace, record.idempotency_key),
                ).fetchone()
                if row is None:
                    results.append(None)
                    continue

                stored = _idempotency_from_row(row)
                same = (
                    stored.request_fingerprint_sha256 == record.request_fingerprint_sha256
                    and stored.execution_id == record.execution_id
                )
                result = IdempotencyResultV1(
                    disposition=(
                        IdempotencyDispositionV1.EXISTING_SAME
                        if same
                        else IdempotencyDispositionV1.CONFLICT
                    ),
                    stored_record=stored,
                )
                if result.disposition is IdempotencyDispositionV1.CONFLICT:
                    raise _IdempotencyPairConflict(index, result)
                results.append(result)

            for index, record in enumerate(requested):
                if results[index] is not None:
                    continue
                connection.execute(
                    "INSERT INTO clear_idempotency_records_v1 "
                    "(namespace, idempotency_key, request_fingerprint_sha256, execution_id, "
                    "recorded_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        record.namespace,
                        record.idempotency_key,
                        record.request_fingerprint_sha256,
                        record.execution_id,
                        canonical_utc_datetime(record.recorded_at),
                    ),
                )
                results[index] = IdempotencyResultV1(
                    disposition=IdempotencyDispositionV1.CREATED,
                    stored_record=record,
                )

            return cast(
                tuple[IdempotencyResultV1, IdempotencyResultV1],
                tuple(results),
            )

    def get_idempotency_record(
        self,
        *,
        namespace: str,
        idempotency_key: str,
    ) -> IdempotencyRecordV1 | None:
        self._ensure_open()
        validated_namespace = _validate_event_namespace(namespace)
        validated_key = _validate_idempotency_key(idempotency_key)
        row = self._query_one(
            "SELECT namespace, idempotency_key, request_fingerprint_sha256, execution_id, "
            "recorded_at FROM clear_idempotency_records_v1 "
            "WHERE namespace = ? AND idempotency_key = ?",
            (validated_namespace, validated_key),
        )
        return None if row is None else _idempotency_from_row(row)


def open_sqlite_financial_ledger_v1(database_path: str) -> SQLiteFinancialLedgerV1:
    """Open or create one schema-v1 ledger without granting execution authority."""
    return SQLiteFinancialLedgerV1(database_path)
