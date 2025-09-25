from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils.timezone import now

from apps.shared.utils.logger import logger


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def send_confirm(self, email: str, code: str) -> None:
    """
    Asynchronous task to send confirmation email to users.

    Args:
        email (str): Recipient's email address.
        code (str): Unique activation code.
    """
    try:
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", settings.EMAIL_HOST_USER)
        if not from_email:
            raise ValueError(
                "No sender email configured. Set DEFAULT_FROM_EMAIL or EMAIL_HOST_USER."
            )

        subject = "Activate Your Account"
        context = {
            "code": code,
            "current_year": now().year,
            "domain": settings.DOMAIN,
            "email": email,
        }

        # Render HTML & Plaintext versions
        html_content = render_to_string("activate.html", context)
        text_content = strip_tags(html_content)

        # Use EmailMultiAlternatives (better than send_mail for multi-part messages)
        message = EmailMultiAlternatives(
            subject, text_content, f"Shop <{from_email}>", [email]
        )
        message.attach_alternative(html_content, "text/html")
        message.send(fail_silently=False)

        logger.info(f"Confirmation email successfully sent to {email}")

    except Exception as e:
        logger.error(f"Failed to send confirmation email to {email}: {e}")
        raise self.retry(exc=e)  # retries with exponential backoff
