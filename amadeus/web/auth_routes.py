from __future__ import annotations

import logging
from typing import cast

from authlib.integrations.starlette_client import OAuth  # type: ignore[import-untyped]
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from amadeus.auth import AuthService
from amadeus.auth.service import AuthenticationError, LoginTokens

auth_router = APIRouter(prefix="/auth", tags=["auth"])
ACCESS_COOKIE = "amadeus_access"
REFRESH_COOKIE = "amadeus_refresh"
logger = logging.getLogger(__name__)


def configure_oauth(request: Request) -> OAuth:
    oauth = OAuth()
    config = request.app.state.auth_config
    oauth.register(
        name="github",
        client_id=config.github_client_id,
        client_secret=config.github_client_secret,
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
        client_kwargs={"scope": "read:user"},
    )
    return oauth


@auth_router.get("/github/login")
async def github_login(request: Request) -> Response:
    oauth = configure_oauth(request)
    callback = f"{request.app.state.auth_config.public_base_url}/auth/github/callback"
    redirect = await oauth.github.authorize_redirect(request, callback)
    return cast(Response, redirect)


@auth_router.get("/github/callback")
async def github_callback(request: Request) -> Response:
    try:
        oauth = configure_oauth(request)
        token = await oauth.github.authorize_access_token(request)
        response = await oauth.github.get("user", token=token)
        response.raise_for_status()
        profile = response.json()
        subject = str(profile.get("id") or "")
        if not subject.isdigit():
            raise AuthenticationError("Invalid GitHub identity")
        tokens = _auth_service(request).login_github_user(subject)
    except Exception as error:
        logger.warning(
            "GitHub OAuth callback failed: error_type=%s",
            type(error).__name__,
        )
        if isinstance(error, AuthenticationError):
            raise HTTPException(status_code=401, detail="GitHub 登录失败") from error
        raise HTTPException(status_code=401, detail="GitHub 登录失败") from error
    redirect = RedirectResponse(url="/", status_code=303)
    _set_cookies(redirect, tokens, _auth_service(request))
    return redirect


@auth_router.post("/refresh", status_code=204)
async def refresh(request: Request) -> Response:
    token = request.cookies.get(REFRESH_COOKIE)
    try:
        tokens = _auth_service(request).refresh(token or "")
    except AuthenticationError:
        failure_response = JSONResponse(
            status_code=401,
            content={"detail": "登录已过期"},
        )
        _clear_cookies(failure_response)
        return failure_response
    response = Response(status_code=204)
    _set_cookies(response, tokens, _auth_service(request))
    return response


@auth_router.post("/logout", status_code=204)
async def logout(request: Request) -> Response:
    _auth_service(request).logout(request.cookies.get(REFRESH_COOKIE))
    response = Response(status_code=204)
    _clear_cookies(response)
    return response


def _auth_service(request: Request) -> AuthService:
    return cast(AuthService, request.app.state.auth_service)


def _set_cookies(
    response: Response,
    tokens: LoginTokens,
    auth_service: AuthService,
) -> None:
    response.set_cookie(
        ACCESS_COOKIE,
        tokens.access_token,
        max_age=auth_service.config.access_ttl_seconds,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=auth_service.config.refresh_ttl_seconds,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/auth",
    )


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/auth")
