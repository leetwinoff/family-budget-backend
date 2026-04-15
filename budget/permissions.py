import hashlib
import hmac
import json
import time
from urllib.parse import unquote, parse_qsl

from django.conf import settings
from rest_framework.permissions import BasePermission


def verify_telegram_init_data(init_data: str) -> dict | None:
    """
    Verify Telegram WebApp initData signature.
    Returns parsed user/chat data on success, None on failure.
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    try:
        params = dict(parse_qsl(unquote(init_data), keep_blank_values=True))
        received_hash = params.pop('hash', None)
        if not received_hash:
            return None

        # Check expiry (24 hours)
        auth_date = int(params.get('auth_date', 0))
        if time.time() - auth_date > 86400:
            return None

        # Build data-check-string
        data_check_string = '\n'.join(
            f'{k}={v}' for k, v in sorted(params.items())
        )

        # Compute expected hash
        secret_key = hmac.new(
            b'WebAppData',
            settings.TELEGRAM_BOT_TOKEN.encode(),
            hashlib.sha256,
        ).digest()
        expected_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_hash, received_hash):
            return None

        result = dict(params)
        if 'user' in result:
            result['user'] = json.loads(result['user'])
        if 'chat' in result:
            result['chat'] = json.loads(result['chat'])
        return result

    except Exception:
        return None


class TelegramInitDataPermission(BasePermission):
    """
    DRF permission that validates X-Telegram-Init-Data header.
    Attaches parsed telegram_data to request on success.
    """
    message = {'code': 'auth_failed', 'detail': 'Invalid or expired Telegram auth data. Please open the app from the bot.'}

    def has_permission(self, request, view):
        # Allow access in DEBUG when no initData is sent (browser dev testing)
        if settings.DEBUG:
            init_data = request.headers.get('X-Telegram-Init-Data', '')
            if not init_data:
                request.telegram_data = _mock_telegram_data()
                return True

        init_data = request.headers.get('X-Telegram-Init-Data', '')
        if not init_data:
            self.message = {'code': 'auth_missing', 'detail': 'Please open this app from the Telegram bot.'}
            return False

        data = verify_telegram_init_data(init_data)
        if data is None:
            self.message = {'code': 'auth_failed', 'detail': 'Invalid or expired Telegram auth data. Please open the app from the bot.'}
            return False

        request.telegram_data = data
        return True


def _mock_telegram_data() -> dict:
    return {
        'user': {'id': 1, 'first_name': 'Dev', 'username': 'dev'},
        'chat': {'id': -1, 'type': 'group'},
        'chat_instance': '-1',
        'auth_date': str(int(time.time())),
    }
