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
import asyncio
import codecs
import configparser
import locale
import logging
import os
import sys
import time
from typing import Dict, Any, Optional

import aiohttp
from stlib import webapi, client

from . import i18n, logger_handlers

parser = configparser.RawConfigParser()
log = logging.getLogger(__name__)
_ = i18n.get_translation

if os.path.isdir('steam_tools_ng'):
    data_dir = 'config'
    icons_dir = 'icons'
elif hasattr(sys, 'frozen') or sys.platform == 'win32':
    data_dir = os.environ['LOCALAPPDATA']
    icons_dir = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'share', 'icons')
else:
    data_dir = os.getenv('XDG_CONFIG_HOME', os.path.join(os.path.expanduser('~'), '.config'))
    icons_dir = os.path.abspath(os.path.join(os.path.sep, 'usr', 'share', 'steam_tools_ng', 'icons'))

config_file_directory = os.path.join(data_dir, 'steam_tools_ng')
config_file_name = 'steam_tools_ng.config'
config_file = os.path.join(config_file_directory, config_file_name)
log_levels = ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']

if sys.platform == 'win32':
    event_loop = asyncio.ProactorEventLoop()
    file_manager = 'explorer'
else:
    file_manager = 'xdg-open'
    event_loop = asyncio.new_event_loop()

asyncio.set_event_loop(event_loop)


def update_log_level(type_: str, level_string: str) -> None:
    level = getattr(logging, level_string.upper())
    file_handler, console_handler = logging.root.handlers

    if type_ == "console":
        console_handler.setLevel(level)
    else:
        file_handler.setLevel(level)


def init() -> None:
    os.makedirs(config_file_directory, exist_ok=True)

    parser.read_dict(
        {
            'logger': {
                'log_directory': os.path.join(data_dir, 'steam_tools_ng'),
                'log_level': 'debug',
                'log_console_level': 'info',
                'log_color': True,
            },
            'locale': {
                'language': str(locale.getdefaultlocale()[0])
            },
            'steam': {
                'api_url': 'https://api.lara.monster',
            },
            'steamtrades': {
                'wait_min': 3700,
                'wait_max': 4100,
                'trade_ids': '',
            },
            'steamgifts': {
                'wait_min': 3700,
                'wait_max': 4100,
                'giveaway_type': 'main',
                'developer_giveaways': 'True',
                'sort': 'name',
                'reverse_sorting': False,
            },
            'cardfarming': {
                'reverse_sorting': False,
                'wait_min': 480,
                'wait_max': 600,
            },
            'gtk': {
                'theme': 'light',
                'show_close_button': False,
            },
            'plugins': {
                'steamtrades': True,
                'steamgifts': True,
                'cardfarming': True,
                'steamguard': True,
                'confirmations': True,
            },
            'login': {
                'steamid': 0,
                'deviceid': '',
                'token': '',
                'token_secure': '',
                'oauth_token': '',
                'account_name': '',
                'shared_secret': '',
                'identity_secret': '',
                'password': '',
            },
        }
    )

    if os.path.isfile(config_file):
        parser.read(config_file)

    log_directory = parser.get("logger", "log_directory")

    if not os.path.isdir(log_directory):
        log.error(_("Incorrect log directory. Fallbacking to default."))
        log_directory = os.path.join(data_dir, 'steam_tools_ng')
        new("logger", "log_directory", log_directory)

    log_level = parser.get("logger", "log_level")

    if log_level and not log_level.upper() in log_levels:
        raise configparser.Error(
            _("Please, fix your config file. Accepted values for log_level are:\n{}").format(
                ', '.join(log_levels),
            )
        )

    log_console_level = parser.get("logger", "log_console_level")

    if log_console_level and not log_console_level.upper() in log_levels:
        raise configparser.Error(
            _("Please, fix your config file. Accepted values for log_console_level are:\n{}").format(
                ', '.join(log_levels),
            )
        )

    os.makedirs(log_directory, exist_ok=True)


def init_logger() -> None:
    log_directory = parser.get("logger", "log_directory")
    log_level = parser.get("logger", "log_level")
    log_console_level = parser.get("logger", "log_console_level")

    log_file_handler = logger_handlers.RotatingFileHandler(os.path.join(log_directory, 'steam_tools_ng.log'),
                                                           backupCount=1,
                                                           encoding='utf-8')
    log_file_handler.setFormatter(logging.Formatter('%(module)s:%(levelname)s (%(funcName)s) => %(message)s'))
    log_file_handler.setLevel(getattr(logging, log_level.upper()))

    try:
        log_file_handler.doRollover()
    except PermissionError:
        log.debug(_("Unable to open steam_tools_ng.log"))
        log_file_handler.close()
        log_file_handler = logger_handlers.NullHandler()  # type: ignore

    log_console_handler = logger_handlers.ColoredStreamHandler()
    log_console_handler.setLevel(getattr(logging, log_console_level.upper()))

    logging.basicConfig(level=logging.DEBUG, handlers=[log_file_handler, log_console_handler])


def new(section: str, option: str, value: Any) -> None:
    if option == "log_level":
        update_log_level("file", value)
    elif option == "log_console_level":
        update_log_level("console", value)

    if parser.get(section, option) != str(value):
        log.debug(_('Saving %s:%s on config file'), section, option)
        parser.set(section, option, str(value))

        with open(config_file, 'w') as config_file_object:
            parser.write(config_file_object)
    else:
        log.debug(_('Not saving %s:%s because values are already updated'), section, option)


def login_cookies() -> Dict[str, str]:
    steamid = parser.getint("login", "steamid")
    token = parser.get("login", "token")
    token_secure = parser.get("login", "token_secure")

    if not steamid or not token or not token_secure:
        return {}

    return {
        'steamLogin': f'{steamid}%7C%7C{token}',
        'steamLoginSecure': f'{steamid}%7C%7C{token_secure}',
    }


def save_login_data(
        login_data: webapi.LoginData,
        relogin: bool = False,
        raw_password: Optional[bytes] = None,
) -> None:
    if login_data.oauth:
        new_configs = {
            'steamid': login_data.oauth['steamid'],
            'token': login_data.oauth['wgtoken'],
            'token_secure': login_data.oauth['wgtoken_secure'],
            'oauth_token': login_data.oauth['oauth_token'],
            'account_name': login_data.username,
        }

        if not relogin:
            new_configs['shared_secret'] = login_data.auth['shared_secret']
            new_configs['identity_secret'] = login_data.auth['identity_secret']
    else:
        new_configs = {
            'steamid': login_data.auth['transfer_parameters']['steamid'],
            'token': login_data.auth['transfer_parameters']['webcookie'],
            'token_secure': login_data.auth['transfer_parameters']['token_secure'],
            'account_name': login_data.username,
        }

    if raw_password:
        # Just for curious people. It's not even safe.
        key = codecs.encode(raw_password, 'base64')
        out = codecs.encode(key.decode(), 'rot13')
        new_configs['password'] = out

    for key, value in new_configs.items():
        new("login", key, value)


async def time_offset(webapi_session: webapi.SteamWebAPI) -> int:
    try:
        with client.SteamGameServer() as server:
            server_time = server.get_server_time()
    except ProcessLookupError:
        log.warning(_("Steam is not running."))
        log.debug(_("Fallbacking time offset to WebAPI"))

        while True:
            try:
                server_time = await webapi_session.get_server_time()
            except aiohttp.ClientError:
                log.error(_("No Connection"))
                await asyncio.sleep(5)
            else:
                break

    return int(time.time()) - server_time
