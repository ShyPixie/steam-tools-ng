#!/usr/bin/env python
#
# Lara Maia <dev@lara.click> 2015 ~ 2018
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
import binascii
import logging
import random
from typing import Any

import aiohttp
from gi.repository import Gio, Gtk
from stlib import authenticator, webapi

from . import about, settings, window
from .. import config, i18n

_ = i18n.get_translation
log = logging.getLogger(__name__)


# noinspection PyUnusedLocal
class Application(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="click.lara.SteamToolsNG",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)

        self.window: Gtk.ApplicationWindow = None
        self.steamguard_status = {'running': False, 'message': "SteamGuard is not running"}
        self.confirmations_status = {'running': False, 'message': "Confirmations is not running"}
        self.steamtrades_status = {'running': False, 'message': "Steamtrades is not running", 'trade_id': ''}

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)

        settings_action = Gio.SimpleAction.new('settings')
        settings_action.connect("activate", self.on_settings_activate)
        self.add_action(settings_action)

        about_action = Gio.SimpleAction.new("about")
        about_action.connect("activate", self.on_about_activate)
        self.add_action(about_action)

    def do_activate(self) -> None:
        if not self.window:
            self.window = window.Main(application=self)

        self.window.present()

        asyncio.ensure_future(self.run_steamguard())
        asyncio.ensure_future(self.run_confirmations())
        asyncio.ensure_future(self.run_steamtrades())

    async def run_steamguard(self) -> None:
        while self.window.get_realized():
            shared_secret = config.config_parser.get("login", "shared_secret", fallback='')

            try:
                if not shared_secret:
                    raise TypeError

                auth_code, server_time = authenticator.get_code(shared_secret)
            except (TypeError, binascii.Error):
                self.steamguard_status = {'running': False, 'message': _("The currently secret is invalid")}
                await asyncio.sleep(10)
            except ProcessLookupError:
                self.steamguard_status = {'running': False, 'message': _("Steam Client is not running")}
                await asyncio.sleep(10)
            else:
                self.steamguard_status = {'running': False, 'message': _("Loading...")}

                seconds = 30 - (server_time % 30)

                for past_time in range(seconds * 9):
                    self.steamguard_status = {
                        'running': True,
                        'maximum': seconds * 8,
                        'progress': past_time,
                        'code': auth_code,
                    }

                    await asyncio.sleep(0.125)

    async def run_confirmations(self) -> None:
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            steam_webapi = webapi.SteamWebAPI(session, 'https://lara.click/api')
            old_confirmations = {}

            while self.window.get_realized():
                identity_secret = config.config_parser.get("login", "identity_secret", fallback='')
                steamid = config.config_parser.getint("login", "steamid", fallback=0)
                deviceid = config.config_parser.get("login", "deviceid", fallback='')
                cookies = config.login_cookies()

                if not identity_secret:
                    self.confirmations_status = {
                        'running': False,
                        'message': _("Unable to get confirmations without a valid identity secret"),
                    }
                    await asyncio.sleep(10)
                    continue

                if not deviceid:
                    log.debug(_("Unable to find deviceid. Generating from identity."))
                    deviceid = authenticator.generate_device_id(identity_secret)
                    config.new(config.ConfigType("login", "deviceid", config.ConfigStr(deviceid)))

                if cookies:
                    session.cookie_jar.update_cookies(cookies)
                else:
                    self.confirmations_status = {
                        'running': False,
                        'message': _("Unable to find a valid login data"),
                    }
                    await asyncio.sleep(5)
                    continue

                try:
                    confirmations = await steam_webapi.get_confirmations(identity_secret, steamid, deviceid)
                except AttributeError as exception:
                    log.error("Error when fetch confirmations: %s", exception)
                    confirmations = {}
                except aiohttp.ClientConnectorError:
                    self.confirmations_status = {'running': False, 'message': _("No connection")}
                except ProcessLookupError:
                    self.confirmations_status = {'running': False, 'message': _("Steam is not running")}
                else:
                    if old_confirmations != confirmations:
                        self.confirmations_status = {'running': True, 'update': True, 'confirmations': confirmations}
                    else:
                        self.confirmations_status = {'running': True, 'update': False, 'confirmations': confirmations}

                    old_confirmations = confirmations

                await asyncio.sleep(15)

    async def run_steamtrades(self) -> None:
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            steam_trades = webapi.SteamTrades(session, api_url='https://lara.click/api')

            while self.window.get_realized():
                self.steamtrades_status = {'running': True, 'message': "Loading...", 'trade_id': ''}
                trade_ids = config.config_parser.get("steamtrades", "trade_ids", fallback='')
                wait_min = config.config_parser.getint("steamtrades", "wait_min", fallback=3700)
                wait_max = config.config_parser.getint("steamtrades", "wait_max", fallback=4100)
                cookies = config.login_cookies()

                if not trade_ids:
                    self.steamtrades_status = {
                        'running': False,
                        'message': _("No trade ID found in config file"),
                        'trade_id': '',
                    }
                    await asyncio.sleep(5)
                    continue

                if cookies:
                    session.cookie_jar.update_cookies(cookies)
                    try:
                        await steam_trades.do_openid_login('https://steamtrades.com/?login')
                    except aiohttp.ClientConnectionError:
                        self.steamtrades_status = {'running': False, 'message': _("No connection"), 'trade_id': ''}
                        await asyncio.sleep(15)
                        continue
                else:
                    self.steamtrades_status = {
                        'running': False,
                        'message': "Unable to find a valid login data",
                        'trade_id': '',
                    }
                    await asyncio.sleep(5)
                    continue

                trades = [trade.strip() for trade in trade_ids.split(',')]

                for trade_id in trades:
                    try:
                        trade_info = await steam_trades.get_trade_info(trade_id)
                    except (IndexError, aiohttp.ClientResponseError):
                        self.steamtrades_status = {
                            'running': False,
                            'message': f"Unable to find id {trade_id}",
                            'trade_id': trade_id,
                        }
                        await asyncio.sleep(5)
                        continue
                    except aiohttp.ClientConnectionError:
                        self.steamtrades_status = {'running': False, 'message': _("No connection"), 'trade_id': ''}
                        await asyncio.sleep(15)
                        continue

                    try:
                        if await steam_trades.bump(trade_info):
                            self.steamtrades_status = {
                                'running': True,
                                'message': 'Bumped!',
                                'trade_id': trade_info.id,
                            }
                            await asyncio.sleep(random.randint(1, 5))
                        else:
                            log.critical(f"Unable to bump {trade_info.id}")
                            await asyncio.sleep(5)
                            continue
                    except webapi.NoTradesError as exception:
                        log.error(exception)
                        await asyncio.sleep(15)
                        continue
                    except webapi.NotReadyError as exception:
                        wait_min = exception.time_left * 60
                        wait_max = wait_min + 400
                    except webapi.ClosedError as exception:
                        self.steamtrades_status = {
                            'running': False,
                            'message': str(exception),
                            'trade_id': exception.id,
                        }
                        await asyncio.sleep(5)
                        continue

                wait_offset = random.randint(wait_min, wait_max)
                for past_time in range(wait_offset):
                    self.steamtrades_status = {
                        'running': True,
                        'message': f"Waiting more {round(wait_offset / 60)} minutes",
                        'trade_id': None,
                        'maximum': wait_offset,
                        'progress': past_time,
                    }
                    await asyncio.sleep(1)

    def on_settings_activate(self, action: Any, data: Any) -> None:
        settings_dialog = settings.SettingsDialog(parent_window=self.window)
        settings_dialog.show()

    def on_about_activate(self, action: Any, data: Any) -> None:
        dialog = about.AboutDialog(parent_window=self.window)
        dialog.show()