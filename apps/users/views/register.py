import os

import redis
from django.db import IntegrityError
from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.users.exceptions.sms import SmsException
from apps.users.models.users import User
from apps.users.serializers.register import (
    RegisterSerializer,
    ConfirmSerializer,
)
from apps.users.services.sms import SmsService
from apps.users.services.users import UserService

redis_instance = redis.StrictRedis.from_url(os.getenv("REDIS_CACHE_URL"))


class BaseAPIView(APIView):
    """Base API View with unified response helpers."""

    @staticmethod
    def success_response(message, data=None, status_code=status.HTTP_200_OK):
        return Response(
            {"success": True, "message": message, "data": data},
            status=status_code,
        )

    @staticmethod
    def error_response(message, errors=None, status_code=status.HTTP_400_BAD_REQUEST):
        return Response(
            {"success": False, "message": message, "data": errors},
            status=status_code,
        )


class RegisterView(BaseAPIView, UserService):
    permission_classes = [AllowAny]
    throttle_classes = [UserRateThrottle]
    serializer_class = RegisterSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return self.error_response(_("Invalid data."), errors=serializer.errors)

        email = serializer.validated_data["email"]

        if User.objects.filter(email=email).exists():
            return self.error_response(_("Email already exists."))

        # Save user registration data temporarily in Redis
        redis_instance.hset(email, mapping=serializer.validated_data)

        # Send confirmation code
        self.send_confirmation(self, email)

        return self.success_response(
            _(
                f"Registration data saved. Please confirm your code. "
                f"SMS sent to {email}."
            ),
            status_code=status.HTTP_201_CREATED,
        )


class ConfirmView(BaseAPIView):
    permission_classes = [AllowAny]
    serializer_class = ConfirmSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return self.error_response(_("Invalid data."), errors=serializer.errors)

        email = serializer.validated_data["email"]
        code = serializer.validated_data["code"]

        try:
            if not SmsService.check_confirm(email, code=code):
                return self.error_response(_("Invalid email or code."))

            user_data = redis_instance.hgetall(email)
            if not user_data:
                return self.error_response(_("No registration data found."))

            # Create user
            try:
                user = User.objects.create_user(
                    email=email,
                    first_name=user_data[b"first_name"].decode(),
                    last_name=user_data[b"last_name"].decode(),
                    password=user_data[b"password"].decode(),
                )
                redis_instance.delete(email)
            except IntegrityError as e:
                if "duplicate key value violates unique constraint" in str(e):
                    return self.error_response(_("Email already exists."))
                return self.error_response(str(e))

            # Generate tokens
            token = user.tokens()
            refresh_token = token["refresh"]
            access_token = token["access"]
            user_id = token["user"]

            return self.success_response(
                _("User created."),
                data={
                    "access": access_token,
                    "refresh": refresh_token,
                    "user": user_id,
                },
                status_code=status.HTTP_201_CREATED,
            )

        except SmsException as e:
            return self.error_response(str(e))
        except Exception as e:
            return self.error_response(str(e))
