from rest_framework import serializers

from apps.users.models.users import User


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "username",
            "first_name",
            "last_name",
            "avatar",
            "created_at",
            "updated_at",
        ]
