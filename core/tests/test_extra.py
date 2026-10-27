"""Extra coverage: constraints, roles, per-minute-cost freezing, management command."""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from core.models import Profile, Session, Wallet

from .base import BaseTestCase


class ExtraTests(BaseTestCase):
    def test_only_one_in_progress_session_per_user(self):
        self.recharge(self.user_client, 1000)
        self.started_session()
        sid2 = self.accepted_session()
        res = self.user_client.post(f"/api/sessions/{sid2}/start/")
        self.assertEqual(res.status_code, 400)
        self.assertIn("already have a session in progress", res.data["error"])

    def test_db_constraint_blocks_second_active_session(self):
        a = Session.objects.create(user_id=self.user_id, status="in_progress")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Session.objects.create(user_id=self.user_id, status="in_progress")
        self.assertTrue(a.pk)

    def test_db_constraint_blocks_negative_wallet(self):
        w = Wallet.objects.get(user_id=self.user_id)
        w.balance = Decimal("-1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            w.save()

    def test_per_minute_cost_is_frozen_after_start(self):
        self.recharge(self.user_client, 1000)
        sid = self.started_session()
        p = Profile.objects.get(user_id=self.provider_id)
        p.per_minute_rate = Decimal("999.00")  # provider raises price mid-session
        p.save()
        self.clock.advance(60)
        self.user_client.post(f"/api/sessions/{sid}/bill/")
        self.assertEqual(self.session(sid).per_minute_cost, Decimal("50.00"))
        self.assertEqual(self.balance(), Decimal("900.00"))

    def test_role_enforcement(self):
        # provider cannot create sessions
        self.assertEqual(self.provider_client.post("/api/sessions/").status_code, 403)
        sid = self.user_client.post("/api/sessions/").data["id"]
        # assigning to a non-provider is rejected
        res = self.user_client.post(f"/api/sessions/{sid}/assign/", {"provider_id": self.user_id}, format="json")
        self.assertEqual(res.status_code, 400)
        self.user_client.post(f"/api/sessions/{sid}/assign/", {"provider_id": self.provider_id}, format="json")
        # a stranger provider cannot accept; the user cannot accept their own session
        other, _ = self.register("dr_eve", "PROVIDER", rate="10")
        self.assertEqual(other.post(f"/api/sessions/{sid}/accept/").status_code, 403)
        self.assertEqual(self.user_client.post(f"/api/sessions/{sid}/accept/").status_code, 403)

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get("/api/wallet/").status_code, 401)

    def test_cancel_before_start(self):
        sid = self.accepted_session()
        res = self.provider_client.post(f"/api/sessions/{sid}/cancel/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.session(sid).status, "cancelled")

    def test_management_command_bills_and_ends_sessions(self):
        self.recharge(self.user_client, 250)
        sid = self.started_session()
        self.clock.advance(60)
        out = StringIO()
        call_command("bill_active_sessions", stdout=out)
        self.assertEqual(self.session(sid).billed_minutes, 2)
        call_command("bill_active_sessions", stdout=out)  # idempotent
        self.assertEqual(self.session(sid).billed_minutes, 2)

    def test_login_returns_token(self):
        res = APIClient().post("/api/auth/login/", {"username": "alice", "password": "secret123"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("token", res.data)

    def test_recharge_validation(self):
        self.assertEqual(self.user_client.post("/api/wallet/recharge/", {"amount": "0"}, format="json").status_code, 400)
        self.assertEqual(self.user_client.post("/api/wallet/recharge/", {"amount": "-5"}, format="json").status_code, 400)
