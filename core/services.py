"""All business logic lives here so views stay thin and tests can drive it directly.

Billing model (prepaid, per started minute):
  * Minute N is due the moment minute N begins, i.e. due_minutes = floor(elapsed / 60) + 1.
  * Minute 1 is charged when the session starts.
  * Each due minute is charged at most once (BillingRecord unique on session+minute).
  * If a due minute can't be paid, the session ends right there; the wallet is untouched.
"""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .choices import EndedBy, RechargeStatus, SessionStatus, UserRole
from .errors import DomainError, Forbidden, InsufficientBalance, InvalidTransition
from .models import BillingRecord, RechargeTransaction, Session, Wallet

S = SessionStatus
INSUFFICIENT_REASON = "Insufficient Balance"

# action -> (allowed source states, target state)
TRANSITIONS = {
    "assign": ({S.UNASSIGNED}, S.ASSIGNED),
    "accept": ({S.ASSIGNED}, S.ACCEPTED),
    "start": ({S.ACCEPTED}, S.IN_PROGRESS),
    "end": ({S.IN_PROGRESS}, S.COMPLETED),
    "cancel": ({S.UNASSIGNED, S.ASSIGNED, S.ACCEPTED}, S.CANCELLED),
}


def now():
    """Single clock for the whole app (tests patch this)."""
    return timezone.now()


# ----------------------------------------------------------------- helpers
def _check_transition(session, action):
    allowed, _ = TRANSITIONS[action]
    if session.status not in allowed:
        allowed_txt = ", ".join(sorted(s.value for s in allowed))
        raise InvalidTransition(
            f"Cannot '{action}' a session that is '{session.status}' (allowed from: {allowed_txt})."
        )


def _lock_session(session_id):
    try:
        return Session.objects.select_for_update().get(pk=session_id)
    except Session.DoesNotExist:
        raise DomainError("Session not found.")


def _require_role(user, role):
    if user.profile.role != role:
        raise Forbidden(f"Only {role} accounts can do this.")


def _require_owner(session, user):
    if session.user_id != user.id:
        raise Forbidden("Only the session's user can do this.")


def _require_assigned_provider(session, user):
    if session.provider_id != user.id:
        raise Forbidden("Only the assigned provider can do this.")


# ------------------------------------------------------------------ wallet
def initiate_recharge(user, amount):
    amount = Decimal(amount)
    if amount <= 0:
        raise DomainError("Amount must be greater than zero.")
    return RechargeTransaction.objects.create(user=user, amount=amount, reference=f"rch_{uuid.uuid4().hex}")


@transaction.atomic
def process_recharge_callback(reference, status):
    """Idempotent: a given transaction credits the wallet at most once.

    Returns (txn, processed). processed=False means it was a replay of a terminal state.
    """
    try:
        txn = RechargeTransaction.objects.select_for_update().get(reference=reference)
    except RechargeTransaction.DoesNotExist:
        raise DomainError("Unknown recharge reference.")

    if txn.status != RechargeStatus.PENDING:
        if txn.status == status:
            return txn, False  # duplicate callback -> no-op
        raise DomainError(f"Transaction is already '{txn.status}' and cannot become '{status}'.")

    if status == RechargeStatus.SUCCESS:
        wallet = Wallet.objects.select_for_update().get(user=txn.user)
        wallet.balance += txn.amount
        wallet.save(update_fields=["balance"])
    txn.status = status
    txn.completed_at = now()
    txn.save(update_fields=["status", "completed_at"])
    return txn, True


# ---------------------------------------------------------------- sessions
def create_session(user):
    _require_role(user, UserRole.USER)
    return Session.objects.create(user=user)


@transaction.atomic
def assign_session(session_id, actor, provider_id):
    session = _lock_session(session_id)
    _require_owner(session, actor)
    _check_transition(session, "assign")
    try:
        provider = get_user_model().objects.select_related("profile").get(pk=provider_id)
    except get_user_model().DoesNotExist:
        raise DomainError("Provider not found.")
    if provider.profile.role != UserRole.PROVIDER:
        raise DomainError("The selected account is not a provider.")
    if provider.profile.per_minute_rate <= 0:
        raise DomainError("Provider has no per-minute rate configured.")
    session.provider = provider
    session.status = TRANSITIONS["assign"][1]
    session.save(update_fields=["provider", "status"])
    return session


@transaction.atomic
def accept_session(session_id, actor):
    session = _lock_session(session_id)
    _require_assigned_provider(session, actor)
    _check_transition(session, "accept")
    session.status = TRANSITIONS["accept"][1]
    session.save(update_fields=["status"])
    return session


@transaction.atomic
def cancel_session(session_id, actor):
    session = _lock_session(session_id)
    if actor.id not in (session.user_id, session.provider_id):
        raise Forbidden("Only a participant can cancel this session.")
    _check_transition(session, "cancel")
    session.status = TRANSITIONS["cancel"][1]
    session.ended_at = now()
    session.ended_by = EndedBy.USER if actor.id == session.user_id else EndedBy.PROVIDER
    session.save(update_fields=["status", "ended_at", "ended_by"])
    return session


@transaction.atomic
def start_session(session_id, actor):
    session = _lock_session(session_id)
    _require_owner(session, actor)
    _check_transition(session, "start")

    wallet = Wallet.objects.select_for_update().get(user=actor)
    if Session.objects.filter(user=actor, status=S.IN_PROGRESS).exclude(pk=session.pk).exists():
        raise InvalidTransition("You already have a session in progress.")

    rate = session.provider.profile.per_minute_rate
    required = rate * settings.MIN_BALANCE_MINUTES
    if wallet.balance < required:
        raise InsufficientBalance(
            f"Insufficient balance: need at least {required} "
            f"({settings.MIN_BALANCE_MINUTES} x {rate}) to start, wallet has {wallet.balance}."
        )

    session.per_minute_cost = rate  # fixed for the lifetime of the session
    session.status = TRANSITIONS["start"][1]
    session.started_at = now()
    session.save(update_fields=["per_minute_cost", "status", "started_at"])
    _bill_locked(session, wallet, session.started_at)  # charge minute 1
    return session


def _finish(session, *, at, ended_by, reason="", talk_seconds):
    session.status = TRANSITIONS["end"][1]
    session.ended_at = at
    session.ended_by = ended_by
    session.end_reason = reason
    session.talk_seconds = talk_seconds


def _bill_locked(session, wallet, at):
    """Charge every due-but-unbilled minute. Caller must hold locks on session and wallet.

    Returns the number of minutes charged in this call.
    """
    if session.status != S.IN_PROGRESS:
        return 0

    elapsed = max(0, (at - session.started_at).total_seconds())
    due_minutes = int(elapsed // 60) + 1
    charged = 0

    while session.billed_minutes < due_minutes:
        if wallet.balance < session.per_minute_cost:
            # End exactly where paid time stops; wallet is left untouched.
            paid_seconds = session.billed_minutes * 60
            _finish(
                session,
                at=session.started_at + timedelta(seconds=paid_seconds),
                ended_by=EndedBy.SYSTEM,
                reason=INSUFFICIENT_REASON,
                talk_seconds=paid_seconds,
            )
            break
        minute_index = session.billed_minutes + 1
        BillingRecord.objects.create(session=session, minute_index=minute_index, amount=session.per_minute_cost)
        wallet.balance -= session.per_minute_cost
        session.billed_minutes = minute_index
        session.total_billed += session.per_minute_cost
        charged += 1

    wallet.save(update_fields=["balance"])
    session.save()
    return charged


@transaction.atomic
def bill_session(session_id, actor=None):
    """Public billing operation: safe to call repeatedly (idempotent per minute)."""
    session = _lock_session(session_id)
    if actor is not None and actor.id not in (session.user_id, session.provider_id):
        raise Forbidden("Only a participant can bill this session.")
    if session.status != S.IN_PROGRESS:
        raise InvalidTransition(f"Cannot bill a session that is '{session.status}'.")
    wallet = Wallet.objects.select_for_update().get(user=session.user)
    charged = _bill_locked(session, wallet, now())
    return session, charged


@transaction.atomic
def end_session(session_id, actor):
    session = _lock_session(session_id)
    if actor.id not in (session.user_id, session.provider_id):
        raise Forbidden("Only a participant can end this session.")
    _check_transition(session, "end")

    at = now()
    wallet = Wallet.objects.select_for_update().get(user=session.user)
    _bill_locked(session, wallet, at)  # catch up on any due minutes first
    if session.status == S.IN_PROGRESS:  # not already ended by the system
        ended_by = EndedBy.USER if actor.id == session.user_id else EndedBy.PROVIDER
        _finish(
            session,
            at=at,
            ended_by=ended_by,
            talk_seconds=int((at - session.started_at).total_seconds()),
        )
        session.save()
    return session


def bill_all_active_sessions():
    """Entry point for a cron / management command."""
    results = []
    for pk in Session.objects.filter(status=S.IN_PROGRESS).values_list("pk", flat=True):
        try:
            session, charged = bill_session(pk)
            results.append((pk, charged, session.status))
        except DomainError:
            continue
    return results
