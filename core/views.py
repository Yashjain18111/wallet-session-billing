from django.db.models import Q
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import RechargeTransaction, Session
from .serializers import (
    AssignSerializer, RechargeCallbackSerializer, RechargeInitSerializer, RechargeSerializer,
    RegisterSerializer, SessionSerializer, WalletSerializer,
)


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        s = RegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = s.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {"id": user.id, "username": user.username, "role": user.profile.role, "token": token.key},
            status=status.HTTP_201_CREATED,
        )


class WalletView(APIView):
    def get(self, request):
        return Response(WalletSerializer(request.user.wallet).data)


class RechargeInitView(APIView):
    def post(self, request):
        s = RechargeInitSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        txn = services.initiate_recharge(request.user, s.validated_data["amount"])
        return Response(RechargeSerializer(txn).data, status=status.HTTP_201_CREATED)


class RechargeCallbackView(APIView):
    """Mock payment-gateway webhook. A real one must verify a signature."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        s = RechargeCallbackSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        txn, processed = services.process_recharge_callback(**s.validated_data)
        data = RechargeSerializer(txn).data
        data["already_processed"] = not processed
        return Response(data)


class SessionListCreateView(APIView):
    def get(self, request):
        qs = Session.objects.filter(Q(user=request.user) | Q(provider=request.user)).order_by("-id")
        return Response(SessionSerializer(qs, many=True).data)

    def post(self, request):
        session = services.create_session(request.user)
        return Response(SessionSerializer(session).data, status=status.HTTP_201_CREATED)


class SessionDetailView(APIView):
    def get(self, request, pk):
        try:
            session = Session.objects.get(Q(user=request.user) | Q(provider=request.user), pk=pk)
        except Session.DoesNotExist:
            return Response({"error": "Session not found."}, status=404)
        return Response(SessionSerializer(session).data)


class SessionAction(APIView):
    """Base: subclasses implement `act` and return a Session."""

    def post(self, request, pk):
        session = self.act(request, pk)
        return Response(SessionSerializer(session).data)


class AssignView(SessionAction):
    def act(self, request, pk):
        s = AssignSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return services.assign_session(pk, request.user, s.validated_data["provider_id"])


class AcceptView(SessionAction):
    def act(self, request, pk):
        return services.accept_session(pk, request.user)


class StartView(SessionAction):
    def act(self, request, pk):
        return services.start_session(pk, request.user)


class EndView(SessionAction):
    def act(self, request, pk):
        return services.end_session(pk, request.user)


class CancelView(SessionAction):
    def act(self, request, pk):
        return services.cancel_session(pk, request.user)


class BillView(APIView):
    def post(self, request, pk):
        session, charged = services.bill_session(pk, request.user)
        data = SessionSerializer(session).data
        data["minutes_charged_now"] = charged
        return Response(data)
