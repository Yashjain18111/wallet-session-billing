from django.contrib.auth import get_user_model
from rest_framework import serializers

from .choices import RechargeStatus, UserRole
from .models import RechargeTransaction, Session, Wallet


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=6)
    role = serializers.ChoiceField(choices=UserRole.choices, default=UserRole.USER)
    per_minute_rate = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, min_value=0)

    def validate_username(self, value):
        if get_user_model().objects.filter(username=value).exists():
            raise serializers.ValidationError("Username already taken.")
        return value

    def validate(self, data):
        if data["role"] == UserRole.PROVIDER and not data.get("per_minute_rate"):
            raise serializers.ValidationError({"per_minute_rate": "Providers must set a per_minute_rate > 0."})
        return data

    def create(self, validated):
        user = get_user_model().objects.create_user(username=validated["username"], password=validated["password"])
        profile = user.profile  # created by signal
        profile.role = validated["role"]
        if validated["role"] == UserRole.PROVIDER:
            profile.per_minute_rate = validated["per_minute_rate"]
        profile.save()
        return user


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ["balance"]


class RechargeInitSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=1)


class RechargeCallbackSerializer(serializers.Serializer):
    reference = serializers.CharField()
    status = serializers.ChoiceField(choices=[RechargeStatus.SUCCESS, RechargeStatus.FAILED])


class RechargeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RechargeTransaction
        fields = ["reference", "amount", "status", "created_at", "completed_at"]


class AssignSerializer(serializers.Serializer):
    provider_id = serializers.IntegerField()


class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Session
        fields = [
            "id", "user", "provider", "status", "per_minute_cost", "started_at", "ended_at",
            "billed_minutes", "total_billed", "talk_seconds", "ended_by", "end_reason", "created_at",
        ]
        read_only_fields = fields
