from rest_framework.response import Response
from rest_framework.views import exception_handler

from .errors import DomainError


def handler(exc, context):
    if isinstance(exc, DomainError):
        return Response({"error": exc.message}, status=exc.status_code)
    return exception_handler(exc, context)
