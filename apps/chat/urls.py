from django.urls import re_path, path

from apps.chat.consumers.chat import ChatConsumer
from apps.chat.views.chat import ChatRoomList, MessageList, ChatResourceView

urlpatterns = [
    path("chats/", ChatRoomList.as_view(), name="chat"),
    path("resource/", ChatResourceView.as_view(), name="chat-resource"),
    path("messages/<int:chat_id>/", MessageList.as_view(), name="message"),
]

websocket_urlpatterns = [
    re_path(r"ws/chat/(?P<room_id>\w+)/$", ChatConsumer.as_asgi()),
]
