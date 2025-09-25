from typing import Any, Dict

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenVerifyView

from apps.users.serializers.custom import (
    CustomTokenObtainPairSerializer,
    CustomTokenRefreshSerializer,
)


def make_response(
    success: bool,
    message: str,
    data: Dict[str, Any] | None = None,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    """Consistent API response helper"""
    return Response(
        {
            "success": success,
            "message": message,
            "data": data or {},
        },
        status=status_code,
    )


class CustomTokenObtainPairView(TokenObtainPairView):
    permission_classes = [AllowAny]
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        tokens = serializer.validated_data

        return make_response(
            True,
            "Successfully logged in",
            data={
                "access": tokens["access"],
                "refresh": tokens["refresh"],
                "user": tokens["user"],
            },
            status_code=status.HTTP_200_OK,
        )


class CustomTokenRefreshView(APIView):
    permission_classes = [AllowAny]
    serializer_class = CustomTokenRefreshSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        refresh_str = serializer.validated_data["refresh"]

        try:
            refresh_token = RefreshToken(refresh_str)
            new_access = str(refresh_token.access_token)

            return make_response(
                True,
                "Successfully refreshed",
                data={
                    "access": new_access,
                    "refresh": str(refresh_token),
                    "user": refresh_token.get("user_id"),
                },
            )
        except TokenError as e:
            return make_response(
                False,
                "Invalid refresh token",
                data={"error": str(e)},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        except Exception as e:
            return make_response(
                False,
                "Unexpected error",
                data={"error": str(e)},
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CustomTokenVerifyView(TokenVerifyView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        try:
            response = super().post(request, *args, **kwargs)
            return make_response(
                True,
                "Token is valid",
                data=response.data,
                status_code=response.status_code,
            )
        except InvalidToken as e:
            return make_response(
                False,
                "Token is invalid",
                data={"error": str(e)},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        except Exception as e:
            return make_response(
                False,
                "Unexpected error",
                data={"error": str(e)},
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
