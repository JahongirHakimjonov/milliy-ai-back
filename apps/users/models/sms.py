from datetime import timedelta

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.shared.models.base import AbstractBaseModel


class SmsConfirm(AbstractBaseModel):
    SMS_EXPIRY_SECONDS = 120
    RESEND_BLOCK_MINUTES = 10
    TRY_BLOCK_MINUTES = 2
    RESEND_COUNT = 5
    TRY_COUNT = 10

    code = models.IntegerField(verbose_name=_("Code"), db_index=True)
    try_count = models.IntegerField(
        default=0, verbose_name=_("Attempt count"), db_index=True
    )
    resend_count = models.IntegerField(
        default=0, verbose_name=_("Resend count"), db_index=True
    )
    email = models.CharField(max_length=255, verbose_name=_("Email"), db_index=True)
    expire_time = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Expiry time"), db_index=True
    )
    unlock_time = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Unlock time"), db_index=True
    )
    resend_unlock_time = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Resend unlock time"),
        db_index=True,
    )

    def sync_limits(self):
        now = timezone.now()

        if self.resend_count >= self.RESEND_COUNT:
            self.try_count = 0
            self.resend_count = 0
            self.resend_unlock_time = now + timedelta(minutes=self.RESEND_BLOCK_MINUTES)

        elif self.try_count >= self.TRY_COUNT:
            self.try_count = 0
            self.unlock_time = now + timedelta(minutes=self.TRY_BLOCK_MINUTES)

        if self.resend_unlock_time is not None and self.resend_unlock_time < now:
            self.resend_unlock_time = None

        if self.unlock_time is not None and self.unlock_time < now:
            self.unlock_time = None

        self.save()

    def is_expired(self):
        if self.expire_time is None:
            return None
        return self.expire_time < timezone.now()

    def is_block(self):
        return self.unlock_time is not None

    def reset_limits(self):
        self.try_count = 0
        self.resend_count = 0
        self.unlock_time = None

    def interval(self, time):
        diff = time - timezone.now()
        total_seconds = max(int(diff.total_seconds()), 0)

        minutes = total_seconds // 60
        seconds = total_seconds % 60

        return f"{minutes:02d}:{seconds:02d}"

    def __str__(self) -> str:
        return f"{self.email} | {self.code}"

    class Meta:
        verbose_name = _("SMS Confirmation")
        verbose_name_plural = _("SMS Confirmations")
        ordering = ["-created_at"]
        db_table = "sms_confirm"


class ResetToken(AbstractBaseModel):
    token = models.CharField(max_length=255, unique=True, verbose_name=_("Token"))
    user = models.ForeignKey(
        "users.User", on_delete=models.CASCADE, verbose_name=_("User")
    )

    def __str__(self):
        return self.token

    class Meta:
        verbose_name = _("Password Reset Token")
        verbose_name_plural = _("Password Reset Tokens")
        db_table = "reset_token"
