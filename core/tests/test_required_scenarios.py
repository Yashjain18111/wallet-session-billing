"""The six scenarios required by the assignment."""
from decimal import Decimal

from core.models import BillingRecord, RechargeTransaction

from .base import BaseTestCase


class RequiredScenarios(BaseTestCase):
    # 1 -------------------------------------------------------------
    def test_1_insufficient_balance_cannot_start(self):
        self.recharge(self.user_client, 249)  # < 5 x 50 = 250
        sid = self.accepted_session()
        res = self.user_client.post(f"/api/sessions/{sid}/start/")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Insufficient balance", res.data["error"])
        self.assertEqual(self.session(sid).status, "accepted_by_provider")
        self.assertEqual(self.balance(), Decimal("249.00"))

    def test_1b_exact_minimum_balance_can_start(self):
        self.recharge(self.user_client, 250)
        self.started_session()

    # 2 -------------------------------------------------------------
    def test_2_happy_path(self):
        self.recharge(self.user_client, 500)
        self.assertEqual(self.user_client.get("/api/wallet/").data["balance"], "500.00")

        sid = self.started_session()  # minute 1 charged on start
        self.assertEqual(self.balance(), Decimal("450.00"))

        self.clock.advance(60)  # minute 2 begins
        res = self.user_client.post(f"/api/sessions/{sid}/bill/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["minutes_charged_now"], 1)
        self.assertEqual(self.balance(), Decimal("400.00"))

        self.clock.advance(30)  # still inside minute 2 -> nothing more due
        res = self.user_client.post(f"/api/sessions/{sid}/end/")
        self.assertEqual(res.status_code, 200)

        s = self.session(sid)
        self.assertEqual(s.status, "completed")
        self.assertEqual(s.ended_by, "user")
        self.assertEqual(s.billed_minutes, 2)
        self.assertEqual(s.total_billed, Decimal("100.00"))
        self.assertEqual(s.talk_seconds, 90)
        self.assertEqual(self.balance(), Decimal("400.00"))  # 500 - 2 x 50
        self.assertEqual(BillingRecord.objects.filter(session=s).count(), 2)

    def test_2b_provider_can_end_session(self):
        self.recharge(self.user_client, 500)
        sid = self.started_session()
        self.clock.advance(10)
        self.assertEqual(self.provider_client.post(f"/api/sessions/{sid}/end/").status_code, 200)
        self.assertEqual(self.session(sid).ended_by, "provider")

    # 3 -------------------------------------------------------------
    def test_3_balance_runs_out_ends_session(self):
        self.recharge(self.user_client, 270)  # enough for 5 full minutes, 20 left over
        sid = self.started_session()
        self.clock.advance(5 * 60 + 5)  # minute 6 is due but only 20 left
        res = self.user_client.post(f"/api/sessions/{sid}/bill/")
        self.assertEqual(res.status_code, 200)

        s = self.session(sid)
        self.assertEqual(s.status, "completed")
        self.assertEqual(s.ended_by, "system")
        self.assertEqual(s.end_reason, "Insufficient Balance")
        self.assertEqual(s.billed_minutes, 5)
        self.assertEqual(s.talk_seconds, 300)  # paid talk time, not the late bill time
        self.assertEqual(self.balance(), Decimal("20.00"))  # never negative, 20 untouched
        self.assertGreaterEqual(self.balance(), 0)

    def test_3b_catch_up_after_long_gap_stops_at_first_unpayable_minute(self):
        self.recharge(self.user_client, 250)
        sid = self.started_session()
        self.clock.advance(3600)  # nobody billed for an hour
        self.user_client.post(f"/api/sessions/{sid}/bill/")
        s = self.session(sid)
        self.assertEqual((s.status, s.ended_by, s.billed_minutes), ("completed", "system", 5))
        self.assertEqual(self.balance(), Decimal("0.00"))

    # 4 -------------------------------------------------------------
    def test_4_invalid_transition_returns_400(self):
        self.recharge(self.user_client, 500)
        sid = self.user_client.post("/api/sessions/").data["id"]

        # end before it ever started (unassigned)
        res = self.user_client.post(f"/api/sessions/{sid}/end/")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Cannot 'end'", res.data["error"])

        # start before provider accepted
        self.user_client.post(f"/api/sessions/{sid}/assign/", {"provider_id": self.provider_id}, format="json")
        self.assertEqual(self.user_client.post(f"/api/sessions/{sid}/start/").status_code, 400)

        # ending a session that is only accepted
        self.provider_client.post(f"/api/sessions/{sid}/accept/")
        self.assertEqual(self.user_client.post(f"/api/sessions/{sid}/end/").status_code, 400)

        # double accept / double assign
        self.assertEqual(self.provider_client.post(f"/api/sessions/{sid}/accept/").status_code, 400)
        res = self.user_client.post(f"/api/sessions/{sid}/assign/", {"provider_id": self.provider_id}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_4b_cannot_act_on_completed_session(self):
        self.recharge(self.user_client, 500)
        sid = self.started_session()
        self.user_client.post(f"/api/sessions/{sid}/end/")
        for action in ("start", "end", "bill", "cancel"):
            self.assertEqual(self.user_client.post(f"/api/sessions/{sid}/{action}/").status_code, 400, action)

    # 5 -------------------------------------------------------------
    def test_5_duplicate_recharge_callback_credits_once(self):
        res = self.user_client.post("/api/wallet/recharge/", {"amount": "300"}, format="json")
        ref = res.data["reference"]
        payload = {"reference": ref, "status": "success"}

        first = self.client.post("/api/wallet/recharge/callback/", payload, format="json")
        second = self.client.post("/api/wallet/recharge/callback/", payload, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.data["already_processed"])
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.data["already_processed"])
        self.assertEqual(self.balance(), Decimal("300.00"))
        self.assertEqual(RechargeTransaction.objects.get(reference=ref).status, "success")

    def test_5b_failed_callback_does_not_credit_and_cannot_flip_to_success(self):
        ref = self.user_client.post("/api/wallet/recharge/", {"amount": "300"}, format="json").data["reference"]
        self.client.post("/api/wallet/recharge/callback/", {"reference": ref, "status": "failed"}, format="json")
        self.assertEqual(self.balance(), Decimal("0.00"))
        res = self.client.post("/api/wallet/recharge/callback/", {"reference": ref, "status": "success"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.balance(), Decimal("0.00"))

    # 6 -------------------------------------------------------------
    def test_6_duplicate_billing_does_not_double_charge(self):
        self.recharge(self.user_client, 500)
        sid = self.started_session()
        self.clock.advance(60)

        r1 = self.user_client.post(f"/api/sessions/{sid}/bill/")
        r2 = self.user_client.post(f"/api/sessions/{sid}/bill/")
        r3 = self.provider_client.post(f"/api/sessions/{sid}/bill/")

        self.assertEqual(r1.data["minutes_charged_now"], 1)
        self.assertEqual(r2.data["minutes_charged_now"], 0)
        self.assertEqual(r3.data["minutes_charged_now"], 0)
        self.assertEqual(self.balance(), Decimal("400.00"))  # 2 minutes only
        self.assertEqual(self.session(sid).billed_minutes, 2)
        self.assertEqual(BillingRecord.objects.filter(session_id=sid).count(), 2)

    def test_6b_billing_twice_at_session_start_charges_one_minute(self):
        self.recharge(self.user_client, 500)
        sid = self.started_session()
        self.user_client.post(f"/api/sessions/{sid}/bill/")
        self.user_client.post(f"/api/sessions/{sid}/bill/")
        self.assertEqual(self.balance(), Decimal("450.00"))
