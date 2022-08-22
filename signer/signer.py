import esrp
import logging
import util

from azure.core.exceptions import ClientAuthenticationError
from config import is_valid_keycode, settings
from keyvault_util import keyvault_util
from redis import Redis
from retrying import retry
from tempfile import SpooledTemporaryFile
from typing import Dict

redis = Redis(host='localhost')
log = logging.getLogger('uvicorn')


def get_signature_index(task_id: str):
    """
    Just a convenience method for determining the redis key that
    holds the signature for a given request.
    """
    return f'{task_id}_signature'


def import_legacy_key():
    """
    If the legacy signing key is not already present...
    download it from KeyVault and import it into GPG
    """
    # Check for the legacy signing key
    cmd = "/usr/bin/gpg --list-secret-keys"
    res = util.run_cmd_out(cmd.split(" "))
    if res.returncode != 0:
        # Failure listing keys? Try to proceed...
        log.error(f"Exit code {res.returncode} checking gpg key: {res.stderr}")
    if settings.LEGACY_KEY_THUMBPRINT in res.stdout:
        log.debug(f"Found key with thumbprint {settings.LEGACY_KEY_THUMBPRINT}")
        return
    # Download the key
    log.info(f"Downloading legacy signing key from {settings.KEYVAULT} : {settings.LEGACY_KEY}")
    vault_name = settings.KEYVAULT
    key_name = settings.LEGACY_KEY
    kv_util = keyvault_util()
    auth_cert = kv_util.get_secret(vault_name, key_name)
    legacy_key_path = util.write_to_temporary_file(auth_cert.encode(), 'pem')

    # Import the key to gpg and delete the file from disk
    log.info("Importing legacy key from disk")
    cmd = f"/usr/bin/gpg --import {legacy_key_path}"
    res = util.run_cmd_out(cmd.split(" "))
    util.secure_delete(legacy_key_path)
    if res.returncode != 0:
        # Failure importing key
        raise Exception("Error importing gpg key: {res.stderr}")


@retry(stop_max_attempt_number=10, wait_exponential_multiplier=1000, wait_exponential_max=60000)
def sign_legacy(unsigned_file: SpooledTemporaryFile, task_id: str) -> bool:
    """
    Use the legacy signing key, via gpg
    """
    import_legacy_key()
    unsigned_file_path = esrp.write_unsigned_file_to_disk(unsigned_file)
    signature_file = util.get_temporary_file()
    thumbprint = settings.LEGACY_KEY_THUMBPRINT
    cmd = "gpg --quiet --batch --yes --homedir ~/.gnupg/ --detach-sign " + \
    f"--default-key {thumbprint} --armor --output {signature_file} {unsigned_file_path}"
    cmd_split = cmd.split(' ')
    res = util.run_cmd_out(cmd_split)
    if res.returncode == 0:
        signature_key = get_signature_index(task_id)
        redis.set(signature_key, signature_file)
    else:
        raise Exception(f"Error signing with legacy key: {res.stderr}")
    return res

def sign_request(unsigned_file: SpooledTemporaryFile, key_id: str, task_id: str) -> bool:
    '''
    Write the unsigned file to disk
    Submit it to ESRP for signing
    Store the signature for return to the requestor
    '''
    if key_id == "legacy":
        try:
            return sign_legacy(unsigned_file, task_id)
        except Exception as e:
            log.error(f"Fatal error signing with legacy key: {e}")
            return False
    if not is_valid_keycode(key_id):
        log.error(f'Key code {key_id} is not in the list of supported keys for task [{task_id}]')
    try:
        return sign_request_retriable(unsigned_file, task_id, key_id)
    except Exception as e:
        log.error(f'Fatal error to handle request for {task_id}: {e}')
        return False


@retry(stop_max_attempt_number=10, wait_exponential_multiplier=1000, wait_exponential_max=60000)
def sign_request_retriable(unsigned_file: SpooledTemporaryFile, task_id: str, key_id: str) -> bool:
    '''
    Retry the request up to 10 times with exponential backoff
    '''
    try:
        log.info(f'Generating signature for {task_id}')
        # Sign content
        dst_file = esrp.sign_content(unsigned_file, esrp.SigningOperation.detached, key_id)
        signature_key = get_signature_index(task_id)
        log.info(f'Successfully signed file for {task_id}')
        redis.set(signature_key, dst_file)
        return True
    except (esrp.ESRPAuthException, ValueError, ClientAuthenticationError) as e:
        # Non-retriable errors
        log.error(f'[{type(e)}] Fatal error handling request for task [{task_id}]: {e}')
        return False
    except Exception as e:
        # Re-raise exception, which will trigger retry logic.
        log.error(f'[{type(e)}] Retriable error handling request for task [{task_id}]: {e}')
        raise


def get_signature_file(task_id: str) -> Dict:
    """
    Generate a Dict containing the signature for the specified task id
    """
    response = {
        "content": ""
    }
    signature_key = get_signature_index(task_id)
    if not redis.exists(signature_key):
        log.error(f'Key {signature_key} not present in Redis')
        return Response
    sig_file = redis.get(signature_key).decode('utf-8')
    with open(sig_file, 'r') as f:
        response["content"] = f.read()
    return response