from typing import Any, Dict

from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    email_field = "email"

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        email = attrs.get(self.email_field)
        password = attrs.get("password")

        request = self.context.get("request")

        user = authenticate(request=request, email=email, password=password)
        if user is None:
            try:
                lookup_user = User.objects.filter(**{self.email_field: email}).first()
                if lookup_user:
                    user = authenticate(
                        request=request,
                        username=lookup_user.get_username(),
                        password=password,
                    )
            except Exception:
                user = None

        if user is None:
            raise serializers.ValidationError(
                {"detail": "Invalid credentials"}, code="authorization"
            )

        self.user = user

        token = self.get_token(user)

        # You can put custom claims here
        token["email"] = user.email

        refresh = str(token)
        access = str(token.access_token)

        return {"refresh": refresh, "access": access, "user": user.id}


class CustomTokenRefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        from rest_framework_simplejwt.tokens import RefreshToken
        from rest_framework_simplejwt.exceptions import TokenError

        refresh_str = attrs.get("refresh")
        if not refresh_str:
            raise serializers.ValidationError({"refresh": "This field is required."})

        try:
            token = RefreshToken(refresh_str)
        except TokenError as e:
            raise serializers.ValidationError(
                {"refresh": "Invalid or expired token", "detail": str(e)}
            )

        return {"refresh": str(token)}
