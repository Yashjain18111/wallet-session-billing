from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from .choices import EndedBy, RechargeStatus, SessionStatus, UserRole


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=10, choices=UserRole.choices, default=UserRole.USER)
    # Only meaningful for providers: price per minute of consultation.
    per_minute_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))


class Wallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet")
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        constraints = [
            # Last line of defence: the DB itself refuses a negative balance.
            models.CheckConstraint(condition=Q(balance__gte=0), name="wallet_balance_non_negative"),
        ]


class RechargeTransaction(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recharges")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=10, choices=RechargeStatus.choices, default=RechargeStatus.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)


class Session(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sessions")
    provider = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="provider_sessions"
    )
    status = models.CharField(max_length=24, choices=SessionStatus.choices, default=SessionStatus.UNASSIGNED)

    # Snapshotted from the provider's rate at start; never changes afterwards.
    per_minute_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    # Billing progress
    billed_minutes = models.PositiveIntegerField(default=0)
    total_billed = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    talk_seconds = models.PositiveIntegerField(default=0)  # actual talk time, persisted at the end

    ended_by = models.CharField(max_length=10, choices=EndedBy.choices, blank=True, default="")
    end_reason = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # A user can never have two in_progress sessions, even under a race.
            models.UniqueConstraint(
                fields=["user"], condition=Q(status="in_progress"), name="one_active_session_per_user"
            ),
        ]


class BillingRecord(models.Model):
    """One row per charged minute. The unique constraint makes double-charging impossible."""

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="billing_records")
    minute_index = models.PositiveIntegerField()  # 1-based
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session", "minute_index"], name="unique_minute_per_session"),
        ]
