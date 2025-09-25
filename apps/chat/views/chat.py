from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chat.models.chat import ChatRoom
from apps.chat.serializers.chat import (
    ChatRoomSerializer,
    MessageSerializer,
    ChatResourceSerializer,
)
from apps.shared.exceptions.http404 import get_object_or_404
from apps.shared.pagination.custom import CustomPagination


class ChatRoomList(APIView):
    serializer_class = ChatRoomSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CustomPagination

    def post(self, request):
        sender_user = request.user
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "message": "Invalid data.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer.save(participant=sender_user)
        return Response(
            {
                "success": True,
                "message": "Chat room created successfully.",
                "data": serializer.data,
            }
        )

    def get(self, request):
        sender_user = request.user
        queryset = ChatRoom.objects.filter(participant=sender_user)
        paginator = self.pagination_class()
        paginated_queryset = paginator.paginate_queryset(queryset, request)
        serializer = self.serializer_class(paginated_queryset, many=True)
        return paginator.get_paginated_response(serializer.data)


class MessageList(APIView):
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CustomPagination

    def get(self, request, chat_id):
        chat_room = get_object_or_404(ChatRoom, id=chat_id, participant=request.user)
        queryset = chat_room.messages.order_by("created_at").all()
        paginator = self.pagination_class()
        paginated_queryset = paginator.paginate_queryset(queryset, request)
        serializer = self.serializer_class(
            paginated_queryset, many=True, context={"request": request}
        )
        return paginator.get_paginated_response(serializer.data)


class ChatResourceView(APIView):
    serializer_class = ChatResourceSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "message": "Invalid data.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"success": True, "message": "OK", "data": serializer.data})
