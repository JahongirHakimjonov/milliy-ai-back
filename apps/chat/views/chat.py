import os

from asgiref.sync import async_to_sync
from django.db import transaction
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
from apps.chat.services.ai import AIService
from apps.shared.exceptions.http404 import get_object_or_404
from apps.shared.pagination.custom import CustomPagination
from apps.shared.utils.logger import logger
from core.settings import SUPPORTED_FILE_FORMATS, SUPPORTED_FILE_SIZE


class ChatRoomList(APIView):
    serializer_class = ChatRoomSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CustomPagination

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

        try:
            with transaction.atomic():
                chat_room = serializer.save(participant=request.user)

                conversation_id = async_to_sync(AIService().create_conversation)()
                vector_store_id = async_to_sync(AIService().create_vector_store)(
                    chat_id=chat_room.id
                )

                chat_room.conversation_id = conversation_id
                chat_room.vector_store_id = vector_store_id
                chat_room.save(update_fields=["conversation_id", "vector_store_id"])

        except Exception as e:
            return Response(
                {
                    "success": False,
                    "message": "Failed to create AI conversation or vector store.",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "success": True,
                "message": "Chat room created successfully.",
                "data": self.serializer_class(chat_room).data,
            },
            status=status.HTTP_201_CREATED,
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
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response(
                {"success": False, "message": "File is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        file_ext = os.path.splitext(uploaded_file.name)[1].lower()
        if file_ext not in SUPPORTED_FILE_FORMATS:
            return Response(
                {
                    "success": False,
                    "message": f"File format not supported. Supported formats: {', '.join(SUPPORTED_FILE_FORMATS)}",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if uploaded_file.size > SUPPORTED_FILE_SIZE:
            return Response(
                {
                    "success": False,
                    "message": f"File is too large. Maximum allowed size is {SUPPORTED_FILE_SIZE // (1024 * 1024)} MB.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.serializer_class(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            logger.error(f"File upload validation error: {e}")
            return Response(
                {
                    "success": False,
                    "message": "Invalid data.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                chat_resource = serializer.save(user=request.user)

                file_path = chat_resource.file.path
                if not os.path.exists(file_path):
                    raise FileNotFoundError(f"File not found on disk: {file_path}")

                with open(file_path, "rb") as f:
                    file_id = async_to_sync(AIService().create_file)(file=f)

                chat_resource.file_id = file_id
                chat_resource.save(update_fields=["file_id"])

        except Exception as e:
            return Response(
                {
                    "success": False,
                    "message": "Failed to upload file to AI.",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "success": True,
                "message": "File uploaded and linked successfully.",
                "data": self.serializer_class(chat_resource).data,
            },
            status=status.HTTP_201_CREATED,
        )
