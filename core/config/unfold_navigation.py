from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _


def user_has_group_or_permission(user, permission):
    if user.is_superuser:
        return True

    group_names = user.groups.values_list("name", flat=True)
    if not group_names:
        return True

    return user.groups.filter(permissions__codename=permission).exists()


PAGES = [
    {
        "seperator": True,
        "items": [
            {
                "title": _("Bosh sahifa"),
                "icon": "home",
                "link": reverse_lazy("admin:index"),
            },
        ],
    },
    {
        "seperator": True,
        "title": _("Foydalanuvchilar"),
        "items": [
            {
                "title": _("Guruhlar"),
                "icon": "person_add",
                "link": reverse_lazy("admin:auth_group_changelist"),
                "permission": lambda request: user_has_group_or_permission(
                    request.user, "view_group"
                ),
            },
            {
                "title": _("Foydalanuvchilar"),
                "icon": "person_add",
                "link": reverse_lazy("admin:users_user_changelist"),
                "permission": lambda request: user_has_group_or_permission(
                    request.user, "view_user"
                ),
            },
            {
                "title": _("SMS"),
                "icon": "sms",
                "link": reverse_lazy("admin:users_smsconfirm_changelist"),
                "permission": lambda request: user_has_group_or_permission(
                    request.user, "view_smsconfirm"
                ),
            },
        ],
    },
    {
        "seperator": True,
        "title": _("Models"),
        "items": [
            {
                "title": _("Chat Roms"),
                "icon": "robot_2",
                "link": reverse_lazy("admin:chat_chatroom_changelist"),
                "permission": lambda request: user_has_group_or_permission(
                    request.user, "view_chatroom"
                ),
            },
            {
                "title": _("Messages"),
                "icon": "forum",
                "link": reverse_lazy("admin:chat_message_changelist"),
                "permission": lambda request: user_has_group_or_permission(
                    request.user, "view_message"
                ),
            },
            {
                "title": _("Files"),
                "icon": "attach_file",
                "link": reverse_lazy("admin:chat_chatresource_changelist"),
                "permission": lambda request: user_has_group_or_permission(
                    request.user, "view_chatresource"
                ),
            },
            {
                "title": _("User Context"),
                "icon": "star",
                "link": reverse_lazy("admin:chat_usercontext_changelist"),
                "permission": lambda request: user_has_group_or_permission(
                    request.user, "view_usercontext"
                ),
            },
            {
                "title": _("Specializations"),
                "icon": "star",
                "link": reverse_lazy("admin:chat_specialization_changelist"),
                "permission": lambda request: user_has_group_or_permission(
                    request.user, "view_specialization"
                ),
            },
        ],
    },
]

TABS = [
    {
        "models": [
            "auth.user",
            "auth.group",
        ],
        "items": [
            {
                "title": _("Foydalanuvchilar"),
                "link": reverse_lazy("admin:auth_user_changelist"),
            },
            {
                "title": _("Guruhlar"),
                "link": reverse_lazy("admin:auth_group_changelist"),
            },
        ],
    },
]
