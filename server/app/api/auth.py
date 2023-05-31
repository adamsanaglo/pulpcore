import re

import jwt
from aiocache import cached  # type: ignore
from aioshutil import sync_to_async
from cryptography.exceptions import InvalidSignature
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm.exc import NoResultFound
from sqlmodel import select

from app.core.config import settings
from app.core.db import AsyncSession, get_session
from app.core.models import Account, RepoAccess, Role
from app.core.schemas import RepoId
from app.services.model import signature

SUPPORT = "Contact your team's PMC Account Admin or PMC Support for assistance."
JWKS_URL = f"https://login.microsoftonline.com/{settings.TENANT_ID}/discovery/v2.0/keys"
ISSUERS = {
    "1.0": f"https://sts.windows.net/{settings.TENANT_ID}/",
    "2.0": f"https://login.microsoftonline.com/{settings.TENANT_ID}/v2.0",
}
ALGORITHMS = ["RS256"]


class AsyncPyJWKClient(jwt.PyJWKClient):
    async_get_signing_key_from_jwt = sync_to_async(jwt.PyJWKClient.get_signing_key_from_jwt)


@cached(ttl=1800)  # type: ignore
async def get_jwks_client() -> AsyncPyJWKClient:
    """Cache the jwt client for half an hour so its own internal token cache actually works."""
    return AsyncPyJWKClient(JWKS_URL, lifespan=1800)


async def authenticate(request: Request) -> str:
    """Authenticate a request and return the oid."""
    jwks_client: AsyncPyJWKClient = await get_jwks_client()
    auth_header = request.headers.get("Authorization", "")

    # parse the auth token
    if not (match := re.match(r"^bearer\s+(.*)", auth_header, re.IGNORECASE)):
        raise HTTPException(status_code=401, detail="Missing or invalid auth token.")
    token = match.group(1)

    # find the signing key
    try:
        signing_key = await jwks_client.async_get_signing_key_from_jwt(token)
    except jwt.DecodeError as e:
        raise HTTPException(status_code=401, detail=f"Failed to parse auth token: {e}.")
    except jwt.exceptions.PyJWKClientConnectionError:
        # if we encountered a connection error, retry the request once
        signing_key = await jwks_client.async_get_signing_key_from_jwt(token)
    except jwt.PyJWKClientError as e:
        raise HTTPException(status_code=401, detail=f"Failed to retrieve signing key: {e}.")

    # get the issuer and audience based on the token version
    try:
        unverified = jwt.decode(token, options={"require": ["ver"], "verify_signature": False})
        token_version = unverified["ver"]
        if token_version == "1.0":
            issuer = ISSUERS["1.0"]
            audience = f"api://{settings.APP_CLIENT_ID}"
        elif token_version == "2.0":
            issuer = ISSUERS["2.0"]
            audience = settings.APP_CLIENT_ID
        else:
            raise ValueError(token_version)
    except (ValueError, jwt.PyJWTError) as e:
        raise HTTPException(status_code=401, detail=f"Invalid/missing token version: {e}.")

    # decode and validate the token
    try:
        data = jwt.decode(
            token,
            signing_key.key,
            algorithms=ALGORITHMS,
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "aud", "iss"]},
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Authentication failure: {e}.")

    try:
        assert isinstance(data["oid"], str)
        return data["oid"]
    except KeyError:
        raise HTTPException(status_code=401, detail="Missing or invalid oid format.")


async def get_active_account(
    request: Request, session: AsyncSession = Depends(get_session)
) -> Account:
    """
    Authenticates the incoming request, looks them up in the db, and ensures the account is active.
    If any of these fail then raise an appropriate exception.
    """
    # oid is a UUID for an account that we get from Azure Active Directory.
    # https://docs.microsoft.com/en-us/azure/active-directory/develop/access-tokens#payload-claims
    oid = await authenticate(request)

    statement = select(Account).where(Account.oid == oid)
    try:
        results = await session.exec(statement)
        account = results.one()
    except NoResultFound:
        raise HTTPException(
            status_code=403, detail=f"Domain UUID {oid} is not provisioned in PMC. {SUPPORT}"
        )

    try:
        signature.verify(account.hash(), bytes.fromhex(account.signature))
    except InvalidSignature:
        raise HTTPException(
            status_code=403, detail=f"Invalid signature for account: {account.name}"
        )

    if not account.is_enabled:
        raise HTTPException(status_code=403, detail=f"PMC access for {oid} is disabled. {SUPPORT}")

    return account


async def requires_account_admin(account: Account = Depends(get_active_account)) -> None:
    if account.role != Role.Account_Admin:
        raise HTTPException(
            status_code=403, detail=f"Account {account.id} is not an Account Admin. {SUPPORT}"
        )


async def requires_repo_admin(account: Account = Depends(get_active_account)) -> None:
    if account.role != Role.Repo_Admin:
        raise HTTPException(
            status_code=403, detail=f"Account {account.id} is not a Repo Admin. {SUPPORT}"
        )


# TODO: [MIGRATE] Remove this function
async def requires_repo_admin_or_migration(account: Account = Depends(get_active_account)) -> None:
    if account.role not in [Role.Repo_Admin, Role.Migration]:
        raise HTTPException(
            status_code=403, detail=f"Account {account.id} is not a Repo Admin. {SUPPORT}"
        )


async def requires_package_admin(account: Account = Depends(get_active_account)) -> None:
    if account.role != Role.Package_Admin:
        raise HTTPException(
            status_code=403, detail=f"Account {account.id} is not a Package Admin. {SUPPORT}"
        )


async def requires_package_admin_or_publisher(
    account: Account = Depends(get_active_account),
) -> None:
    if account.role not in (Role.Package_Admin, Role.Publisher):
        raise HTTPException(
            status_code=403, detail=f"Account {account.id} is not a Publisher. {SUPPORT}"
        )


async def requires_repo_permission(
    id: RepoId,
    account: Account = Depends(get_active_account),
    session: AsyncSession = Depends(get_session),
) -> None:
    """
    For the routes that require this permission, Repo Admins can do whatever they want, and
    Publishers can do things only if they've been granted access to this repo.
    """
    if account.role == Role.Repo_Admin:
        return

    # TODO: [MIGRATE] Remove this if
    if account.role == Role.Migration:
        return

    if account.role == Role.Publisher:
        statement = select(RepoAccess).where(
            RepoAccess.account_id == account.id, RepoAccess.repo_id == id
        )
        if (await session.exec(statement)).one_or_none():
            return

    raise HTTPException(
        status_code=403, detail=f"Account {account.id} does not have access to repo {id}. {SUPPORT}"
    )
