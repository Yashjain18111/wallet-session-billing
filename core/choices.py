"""All enum-style choices in one place, imported by models, services and serializers."""
from django.db import models


class UserRole(models.TextChoices):
    USER = "USER"
    PROVIDER = "PROVIDER"


class RechargeStatus(models.TextChoices):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class SessionStatus(models.TextChoices):
    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"
    ACCEPTED = "accepted_by_provider"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EndedBy(models.TextChoices):
    USER = "user"
    PROVIDER = "provider"
    SYSTEM = "system"
