from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token

from . import views

urlpatterns = [
    path("auth/register/", views.RegisterView.as_view()),
    path("auth/login/", obtain_auth_token),
    path("wallet/", views.WalletView.as_view()),
    path("wallet/recharge/", views.RechargeInitView.as_view()),
    path("wallet/recharge/callback/", views.RechargeCallbackView.as_view()),
    path("sessions/", views.SessionListCreateView.as_view()),
    path("sessions/<int:pk>/", views.SessionDetailView.as_view()),
    path("sessions/<int:pk>/assign/", views.AssignView.as_view()),
    path("sessions/<int:pk>/accept/", views.AcceptView.as_view()),
    path("sessions/<int:pk>/start/", views.StartView.as_view()),
    path("sessions/<int:pk>/end/", views.EndView.as_view()),
    path("sessions/<int:pk>/cancel/", views.CancelView.as_view()),
    path("sessions/<int:pk>/bill/", views.BillView.as_view()),
]
