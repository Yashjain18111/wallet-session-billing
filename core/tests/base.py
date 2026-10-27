from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest.mock import patch

from rest_framework.test import APIClient, APITestCase

from core.models import Session, Wallet

RATE = Decimal("50.00")


class FakeClock:
    """Deterministic clock so tests never sleep."""

    def __init__(self):
        self.t = datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt_tz.utc)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += timedelta(seconds=seconds)


class BaseTestCase(APITestCase):
    def setUp(self):
        self.clock = FakeClock()
        patcher = patch("core.services.now", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.user_client, self.user_id = self.register("alice", "USER")
        self.provider_client, self.provider_id = self.register("dr_bob", "PROVIDER", rate="50.00")

    # -- helpers
    def register(self, username, role, rate=None):
        client = APIClient()
        payload = {"username": username, "password": "secret123", "role": role}
        if rate:
            payload["per_minute_rate"] = rate
        res = client.post("/api/auth/register/", payload, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        client.credentials(HTTP_AUTHORIZATION=f"Token {res.data['token']}")
        return client, res.data["id"]

    def recharge(self, client, amount, callback_twice=False):
        res = client.post("/api/wallet/recharge/", {"amount": str(amount)}, format="json")
        self.assertEqual(res.status_code, 201)
        ref = res.data["reference"]
        cb = APIClient().post("/api/wallet/recharge/callback/", {"reference": ref, "status": "success"}, format="json")
        self.assertEqual(cb.status_code, 200)
        return ref

    def balance(self, user_id=None):
        return Wallet.objects.get(user_id=user_id or self.user_id).balance

    def accepted_session(self):
        sid = self.user_client.post("/api/sessions/").data["id"]
        res = self.user_client.post(f"/api/sessions/{sid}/assign/", {"provider_id": self.provider_id}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(self.provider_client.post(f"/api/sessions/{sid}/accept/").status_code, 200)
        return sid

    def started_session(self):
        sid = self.accepted_session()
        res = self.user_client.post(f"/api/sessions/{sid}/start/")
        self.assertEqual(res.status_code, 200, res.data)
        return sid

    def session(self, sid):
        return Session.objects.get(pk=sid)
