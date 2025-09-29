from rest_framework import serializers

from apps.chat.models.chat import ChatRoom, Message, ChatResource
from apps.users.serializers.me import MeSerializer


class ChatResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatResource
        fields = (
            "id",
            "user",
            "name",
            "file",
            "size",
            "type",
            "created_at",
        )
        read_only_fields = ("user", "name", "size", "type", "created_at")


class ChatRoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatRoom
        fields = (
            "id",
            "name",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("name", "created_at", "updated_at", "id")


class MessageSerializer(serializers.ModelSerializer):
    chat = ChatRoomSerializer(read_only=True)
    sender = MeSerializer(read_only=True)
    file = ChatResourceSerializer(read_only=True, many=True)

    class Meta:
        model = Message
        fields = (
            "id",
            "chat",
            "sender",
            "message",
            "file",
            "created_at",
            "updated_at",
        )
