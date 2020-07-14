#!/usr/bin/env python
#
# Lara Maia <dev@lara.monster> 2015 ~ 2020
#
# The Steam Tools NG is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 3 of
# the License, or (at your option) any later version.
#
# The Steam Tools NG is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see http://www.gnu.org/licenses/.
#
import codecs
import getpass
import logging
import os
import ssl
import sys
import tempfile
from typing import Optional, Union, List

import aiohttp
from stlib import webapi, universe

from .. import i18n, config

log = logging.getLogger(__name__)
_ = i18n.get_translation


async def add_authenticator(
        webapi_session: webapi.SteamWebAPI,
        login_data: webapi.LoginData,
        time_offset: int,
) -> Optional[webapi.LoginData]:
    if not login_data.has_phone:
        # FIXME: Impossible to add an authenticator without a phone
        raise NotImplementedError

    deviceid = universe.generate_device_id(token=login_data.oauth['oauth_token'])
    config.new("login", "deviceid", deviceid)

    try:
        login_data = await webapi_session.add_authenticator(login_data, deviceid)
    except aiohttp.ClientError:
        log.critical(_("No Connection. Please, check your connection and try again."))
        sys.exit(1)

    while True:
        sms_code = safe_input(_("Write code received by SMS"))

        try:
            complete = await webapi_session.finalize_add_authenticator(login_data, sms_code, time_offset=time_offset)
        except webapi.SMSCodeError:
            log.error(_("Invalid SMS Code. Please, check the code and try again."))
            continue
        except aiohttp.ClientError:
            log.critical(_("No Connection. Please, check your connection and try again."))
            continue

        break

    if complete:
        log.info(_("Success!"))
        return login_data

    log.error(_("Unable to add a new authenticator"))
    return None


async def check_login(
        session: aiohttp.ClientSession,
        webapi_session: webapi.SteamWebAPI,
        time_offset: int,
        captcha_gid: int = -1,
        captcha_text: str = '',
        mail_code: str = '',
) -> bool:
    token = config.parser.get("login", "token")
    token_secure = config.parser.get("login", "token_secure")
    steamid = config.parser.getint("login", "steamid")
    mobile_login = bool(config.parser.get("login", "oauth_token"))
    add_auth_after_login = False
    advanced = False
    relogin = True

    if not token or not token_secure or not steamid:
        relogin = False
        log.error(_("STNG is not configured."))
        log.info("Welcome to STNG Setup")
        log.info("How do you want to log-in?")

        user_input = safe_input(_(
            "[1] Use STNG as Steam Authenticator\n"
            "[2] Use custom secrets (advanced users only!)\n"
        ), custom_choices=["1", "2"])

        if user_input == '1':
            mobile_login = True
            add_auth_after_login = True
            advanced = False
        else:
            mobile_login = False
            add_auth_after_login = False
            advanced = True

    if not token or not token_secure or not steamid:
        is_logged_in = False
    else:
        session.cookie_jar.update_cookies(config.login_cookies())  # type: ignore

        try:
            is_logged_in = await webapi_session.is_logged_in(steamid)
        except aiohttp.ClientError:
            log.critical(_("No Connection. Please, check your connection and try again."))
            sys.exit(1)

    if is_logged_in:
        return True

    log.error(_("User is not logged in."))

    username = config.parser.get("login", "account_name")
    encrypted_password = config.parser.get("login", "password")
    __password = None

    if encrypted_password:
        # Just for curious people. It's not even safe.
        key = codecs.decode(encrypted_password, 'rot13')
        raw = codecs.decode(key.encode(), 'base64')
        __password = raw.decode()

    if not username:
        user_input = safe_input(_("Please, write your username"))
        assert isinstance(user_input, str), "Safe input is returning bool when it should return str"
        username = user_input

    if not __password:
        __password = getpass.getpass(_("Please, write your password (it's hidden, and will be not saved)"))

    if not username or not __password:
        log.error(_("Unable to log-in!\nUsername or password is blank."))
        sys.exit(1)

    login_session = webapi.Login(session, webapi_session, username, __password)
    kwargs = {'emailauth': mail_code, 'mobile_login': mobile_login}

    # no reason to send captcha_text if no gid is found
    if captcha_gid != -1:
        kwargs['captcha_text'] = captcha_text
        kwargs['captcha_gid'] = captcha_gid

    # identity_secret is required for openid login
    if advanced:
        shared_secret = safe_input(_("Write your shared secret"))
        # it's required for openid login
        identity_secret = safe_input(_("Write your identity secret"))

        if not shared_secret or not identity_secret:
            log.critical(_("Unable to log-in!\nshared secret or identity secret is blank."))
            sys.exit(1)

        config.new("login", "shared_secret", shared_secret)
        config.new("login", "identity_secret", identity_secret)
    else:
        shared_secret = config.parser.get("login", "shared_secret")
        # it's required for openid login
        identity_secret = config.parser.get("login", "identity_secret")

        if not shared_secret or not identity_secret:
            if relogin:
                log.critical(_("Unable to relogin without a valid shared secret and identity secret"))
                sys.exit(1)
            else:
                log.warning(_("No shared secret found. Trying to log-in without two-factor authentication."))

    kwargs['shared_secret'] = shared_secret
    kwargs['time_offset'] = time_offset
    log.info(_("Waiting Steam Server..."))

    while True:
        try:
            login_data = await login_session.do_login(**kwargs)
        except webapi.MailCodeError:
            user_input = safe_input(_("Write code received by email"))
            assert isinstance(user_input, str), "safe_input is returning bool when it should return str"
            mail_code = user_input
            continue
        except webapi.TwoFactorCodeError:
            if mobile_login and not relogin:
                log.error(_("Unable to log-in! You already have a Steam Authenticator active on current account."))
                log.error(_("¬ To log-in, remove authenticator from your account and try again."))
                log.error(_("¬ (STNG will add itself as Steam Authenticator in your account)"))
            else:
                log.error(_("Unable to log-in! The secret keys are invalid!"))

            return False
        except webapi.LoginBlockedError:
            log.error(_("Your network is blocked! It'll take some time until unblocked. Please, try again later."))
            return False
        except webapi.CaptchaError as exception:
            log.info(_("Steam server is requesting a captcha code."))

            with tempfile.TemporaryFile('w', prefix='stng_', suffix='.captcha') as temp_file:
                temp_file.write(exception.captcha)

            user_input = safe_input(
                _("Open {} in an image view and write captcha code that it shows").format(temp_file.name),
            )

            kwargs['captcha_text'] = user_input
            kwargs['captcha_gid'] = exception.captcha_gid
            continue
        except webapi.LoginError:
            log.error(_("Unable to log-in! Please, check your username/password and try again."))
            log.error(_("(If you change your password, run steam_tools_ng --reset-password and try again.)"))
            log.error(
                _("(If you removed the authenticator from your account, run steam_tools_ng --reset and try again.)")
            )

            return False
        except aiohttp.ClientError:
            log.error(_("No Connection"))
            return False

        if add_auth_after_login:
            login_data = await add_authenticator(webapi_session, login_data, time_offset)

            print(_("WRITE DOWN THE RECOVERY CODE: %s"), login_data.auth['revocation_code'])
            print(_("YOU WILL NOT ABLE TO VIEW IT AGAIN!"))

        args = [login_data, relogin]

        if not encrypted_password:
            save_password = safe_input(_("Do you want to save the password?"), True)

            if save_password:
                args.append(__password.encode())

        config.save_login_data(*args)

        break

    return True


def safe_input(
        msg: str,
        default_response: Optional[bool] = None,
        custom_choices: Optional[List[str]] = None,
) -> Union[bool, str]:
    if default_response and custom_choices:
        raise AttributeError("You can not use both default_response and custom_choices")

    if default_response is True:
        options = _('[Y/n]')
    elif default_response is False:
        options = _('[y/N]')
    elif custom_choices:
        options = f"Your choice [{'/'.join(custom_choices)}]"
    else:
        options = ''

    while True:
        try:
            user_input = input(f'{msg} {options}: ')

            if custom_choices:
                if not user_input:
                    raise ValueError(_('Invalid response from user'))

                if user_input.lower() in custom_choices:
                    return user_input.lower()

                raise ValueError(_('{} is not an accepted value').format(user_input))

            if default_response is None:
                if len(user_input) > 2:
                    return user_input

                raise ValueError(_('Invalid response from user'))

            if not user_input:
                return default_response

            if user_input.lower() == _('y'):
                return True
            elif user_input.lower() == _('n'):
                return False
            else:
                raise ValueError(_('{} is not an accepted value').format(user_input))
        except ValueError as exception:
            log.error(exception.args[0])
            log.error(_('Please, try again.'))


async def http_session(raise_for_status: bool = True) -> None:
    ssl_context = ssl.SSLContext()

    if hasattr(sys, 'frozen'):
        _executable_path = os.path.dirname(sys.executable)
        ssl_context.load_verify_locations(cafile=os.path.join(_executable_path, 'etc', 'cacert.pem'))

    tcp_connector = aiohttp.TCPConnector(ssl=ssl_context)
    return aiohttp.ClientSession(raise_for_status=raise_for_stattus, connector=tcp_connector)
