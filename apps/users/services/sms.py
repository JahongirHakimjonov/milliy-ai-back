import random
from datetime import timedelta

from django.utils import timezone

from apps.users.exceptions.sms import SmsException
from apps.users.models.sms import SmsConfirm
from apps.users.tasks.sms import send_confirm
from core import settings


class SmsService:
    @staticmethod
    def send_confirm(email):
        code = 1111
        if not settings.DEBUG:
            code = random.randint(1000, 9999)
        sms_confirm, status = SmsConfirm.objects.get_or_create(
            email=email, defaults={"code": code}
        )

        sms_confirm.sync_limits()

        if sms_confirm.resend_unlock_time is not None:
            expired = sms_confirm.interval(sms_confirm.resend_unlock_time)
            exception = SmsException(
                f"Resend blocked, please try again later: {expired}",
                expired=expired,
            )
            raise exception

        sms_confirm.code = code
        sms_confirm.try_count = 0
        sms_confirm.resend_count += 1
        sms_confirm.email = email
        sms_confirm.expired_time = timezone.now() + timedelta(
            seconds=SmsConfirm.SMS_EXPIRY_SECONDS
        )
        sms_confirm.resend_unlock_time = timezone.now() + timedelta(
            seconds=SmsConfirm.SMS_EXPIRY_SECONDS
        )
        sms_confirm.save()
        send_confirm.delay(email, code)
        return True

    @staticmethod
    def check_confirm(email, code):
        sms_confirm = SmsConfirm.objects.filter(email=email).first()

        if sms_confirm is None:
            raise SmsException("Invalid confirmation code")

        sms_confirm.sync_limits()

        if sms_confirm.is_expired():
            raise SmsException("Time for confirmation has expired")

        if sms_confirm.is_block():
            expired = sms_confirm.interval(sms_confirm.unlock_time)
            raise SmsException(f"Try again in {expired}")

        if sms_confirm.code == code:
            sms_confirm.delete()
            return True

        sms_confirm.try_count += 1
        sms_confirm.save()

        raise SmsException("Invalid confirmation code")
