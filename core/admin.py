from django.contrib import admin

from .models import BillingRecord, Profile, RechargeTransaction, Session, Wallet


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "per_minute_rate")
    list_filter = ("role",)
    search_fields = ("user__username",)


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("user", "balance")
    search_fields = ("user__username",)
    # Balance is read-only on purpose: money must only move through the service layer
    # (recharge callback / billing) so every change is traceable.
    readonly_fields = ("user", "balance")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RechargeTransaction)
class RechargeTransactionAdmin(admin.ModelAdmin):
    list_display = ("reference", "user", "amount", "status", "created_at", "completed_at")
    list_filter = ("status",)
    search_fields = ("reference", "user__username")
    readonly_fields = ("user", "amount", "reference", "status", "created_at", "completed_at")

    def has_add_permission(self, request):
        return False


class BillingRecordInline(admin.TabularInline):
    model = BillingRecord
    extra = 0
    can_delete = False
    readonly_fields = ("minute_index", "amount", "created_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = (
        "id", "user", "provider", "status", "per_minute_cost",
        "billed_minutes", "total_billed", "talk_seconds", "ended_by", "end_reason",
    )
    list_filter = ("status", "ended_by")
    search_fields = ("user__username", "provider__username")
    inlines = [BillingRecordInline]
    readonly_fields = [f.name for f in Session._meta.fields]  # view-only: state changes go through the API

    def has_add_permission(self, request):
        return False


@admin.register(BillingRecord)
class BillingRecordAdmin(admin.ModelAdmin):
    list_display = ("session", "minute_index", "amount", "created_at")
    list_filter = ("session",)
    readonly_fields = ("session", "minute_index", "amount", "created_at")

    def has_add_permission(self, request):
        return False
