from apps.users.exceptions.response import ResponseException
from apps.users.exceptions.sms import SmsException
from apps.users.models.users import User
from apps.users.services.sms import SmsService


class UserService(SmsService):
    @staticmethod
    def send_confirmation(self, email) -> bool:
        try:
            self.send_confirm(email)
            return True
        except SmsException as e:
            raise ResponseException(
                success=False,
                message=str(e),
                data={"expired": str(e.kwargs.get("expired"))},
            )
        except Exception as e:
            raise ResponseException(
                success=False, message=str(e), data={"expired": False}
            )

    @staticmethod
    def change_password(email, password):
        """
        Change password
        """
        user = User.objects.filter(email=email).first()
        user.set_password(password)
        user.save()
