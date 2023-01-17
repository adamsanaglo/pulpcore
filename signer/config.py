import logging
from pydantic import BaseSettings
import sys


class Settings(BaseSettings):
    KEYVAULT: str
    AUTH_CERT_PATH: str  # path to the on-disk esrp auth cert
    SIGN_CERT: str
    LEGACY_KEY_PATH: str  # path to the on-disk private legacy signing key
    APP_ID: str
    TENANT_ID: str
    # Separate multiple key-codes with ';'
    KEY_CODES: str = ""
    LEGACY_KEY_THUMBPRINT: str = ""

    class Config:
        env_file = ".env"


settings = Settings()


logging.basicConfig(
    level=logging.INFO, format="signer %(asctime)s %(levelname)s: %(message)s", stream=sys.stdout
)
log = logging.getLogger("signer")


def is_valid_keycode(key_id: str) -> bool:
    key_codes = settings.KEY_CODES.split(";")
    return key_id in key_codes
