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
import configparser
import contextlib
import itertools
import logging
import random
import sys
from typing import Any, List, Optional

import aiohttp
import binascii
from gi.repository import Gio, Gtk
from stlib import authenticator, client, plugins, webapi

from . import about, settings, setup, window, utils
from .. import config, i18n

_ = i18n.get_translation
log = logging.getLogger(__name__)


# noinspection PyUnusedLocal
class Application(Gtk.Application):
    def __init__(self, session: aiohttp.ClientSession, plugin_manager: plugins.Manager) -> None:
        super().__init__(application_id="click.lara.SteamToolsNG",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)

        self.session = session
        self.api_url = config.parser.get('steam', 'api_url')
        self.webapi_session = webapi.SteamWebAPI(session, self.api_url)
        self.plugin_manager = plugin_manager

        self.window: Optional[Gtk.Window] = None
        self.gtk_settings = Gtk.Settings.get_default()

        self.api_login: Optional[webapi.Login] = None

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)

        settings_action = Gio.SimpleAction.new('settings')
        settings_action.connect("activate", self.on_settings_activate)
        self.add_action(settings_action)

        about_action = Gio.SimpleAction.new("about")
        about_action.connect("activate", self.on_about_activate)
        self.add_action(about_action)

        theme = config.parser.get("gtk", "theme")

        if theme == 'dark':
            self.gtk_settings.props.gtk_application_prefer_dark_theme = True
        else:
            self.gtk_settings.props.gtk_application_prefer_dark_theme = False

    def do_activate(self) -> None:
        if not self.window:
            try:
                self.window = window.Main(application=self)
            except configparser.Error as exception:
                utils.fatal_error_dialog(str(exception), self.window)
                sys.exit(1)

        self.window.present()  # type: ignore

        task = asyncio.gather(self.async_activate())
        task.add_done_callback(self.async_activate_callback)

    def async_activate_callback(self, future: 'asyncio.Future[Any]') -> None:
        if future.exception() and not isinstance(future.exception(), asyncio.CancelledError):
            utils.fatal_error_dialog(str(future.exception()), self.window)
            sys.exit(1)

    async def async_activate(self) -> None:
        setup_requested = False
        login_requested = False

        assert isinstance(self.window, Gtk.Window), "No window is found"

        while self.window.get_realized():
            token = config.parser.get("login", "token")
            token_secure = config.parser.get("login", "token_secure")
            steamid = config.parser.getint("login", "steamid")
            nickname = config.parser.get("login", "nickname")
            mobile_login = True if config.parser.get("login", "oauth_token") else False

            if not token or not token_secure or not steamid:
                if not setup_requested:
                    log.debug(_("Unable to find a valid configuration. Calling Magic Box."))
                    setup_dialog = setup.SetupDialog(self.window, self.session, self.webapi_session)
                    setup_dialog.login_mode()
                    setup_dialog.show()
                    setup_requested = True

                await asyncio.sleep(5)
                continue

            setup_requested = False

            if not nickname:
                log.debug(_("Unable to find a valid nickname. Generating a new one."))
                try:
                    nickname = await self.webapi_session.get_nickname(steamid)
                except ValueError:
                    raise NotImplementedError
                else:
                    config.new('login', 'nickname', nickname)

            self.session.cookie_jar.update_cookies(config.login_cookies())  # type: ignore

            if not await self.webapi_session.is_logged_in(nickname):
                if not login_requested:
                    log.debug(_("User is not logged-in. Calling Magic Box."))
                    setup_dialog = setup.SetupDialog(
                        self.window,
                        self.session,
                        self.webapi_session,
                        mobile_login=mobile_login,
                        relogin=True,
                        destroy_after_run=True,
                    )

                    setup_dialog.prepare_login()
                    setup_dialog.previous_button.hide()
                    setup_dialog.status.info(_("Could not connect to the Steam Servers.\nPlease, relogin."))
                    setup_dialog.status.show()
                    setup_dialog.show()
                    login_requested = True

                await asyncio.sleep(5)
                continue

            login_requested = False

            break

        modules = [
            self.window.update_login_icons(),
            self.run_confirmations(),
            self.run_steamguard(),
            self.run_steamtrades(),
            self.run_steamgifts(),
        ]

        with contextlib.suppress(asyncio.CancelledError):
            done, pending = await asyncio.wait(modules, return_when=asyncio.FIRST_EXCEPTION)
            utils.fatal_error_dialog(str(done.pop().exception()), self.window)
            sys.exit(1)

    async def run_steamguard(self) -> None:
        assert isinstance(self.window, Gtk.Window), "No window"

        while self.window.get_realized():
            if not config.parser.getboolean("plugins", "steamguard"):
                await asyncio.sleep(5)
                continue

            shared_secret = config.parser.get("login", "shared_secret")

            try:
                if not shared_secret:
                    raise ValueError

                with client.SteamGameServer() as server:
                    server_time = server.get_server_time()

                auth_code = authenticator.get_code(server_time, shared_secret)
            except (ValueError, binascii.Error):
                self.window.steamguard_status.set_error(_("The currently secret is invalid"))
                await asyncio.sleep(10)
            except ProcessLookupError:
                self.window.steamguard_status.set_error(_("Steam Client is not running"))
                await asyncio.sleep(10)
            else:
                self.window.steamguard_status.set_error(_("Loading..."))

                seconds = 30 - (server_time % 30)

                for past_time in range(seconds * 9):
                    self.window.steamguard_status.set_current(auth_code)
                    self.window.steamguard_status.set_info(_("Running"))
                    self.window.steamguard_status.set_level(past_time, seconds * 8)

                    await asyncio.sleep(0.125)

    async def run_confirmations(self) -> None:
        old_confirmations: List[webapi.Confirmation] = []

        def warning(message: str) -> None:
            assert isinstance(self.window, Gtk.Window), "No window"
            self.window.warning_label.set_markup(utils.markup(message, color='white', background='red'))
            self.window.warning_label.show()

        assert isinstance(self.window, Gtk.Window), "No window"

        while self.window.get_realized():
            identity_secret = config.parser.get("login", "identity_secret")
            steamid = config.parser.getint("login", "steamid")
            deviceid = config.parser.get("login", "deviceid")
            cookies = config.login_cookies()

            if not identity_secret:
                warning(_("Unable to get confirmations without a valid identity secret"))
                await asyncio.sleep(10)
                continue

            if not deviceid:
                log.debug(_("Unable to find deviceid. Generating from identity."))
                deviceid = authenticator.generate_device_id(identity_secret)
                config.new("login", "deviceid", deviceid)

            if cookies:
                self.session.cookie_jar.update_cookies(cookies)  # type: ignore
            else:
                warning(_("Unable to find a valid login data"))
                await asyncio.sleep(5)
                continue

            try:
                confirmations = await self.webapi_session.get_confirmations(
                    identity_secret,
                    steamid,
                    deviceid,
                )
            except AttributeError as exception:
                warning(_("Error when fetch confirmations"))
            except aiohttp.ClientConnectorError:
                warning(_("No connection"))
            except ProcessLookupError:
                warning(_("Steam is not running"))
            except webapi.LoginError:
                warning(_("User is not logged in"))
            else:
                self.window.warning_label.hide()
                if old_confirmations != confirmations:
                    self.window.text_tree.store.clear()

                    for confirmation_index, confirmation_ in enumerate(confirmations):
                        safe_give, give = utils.safe_confirmation_get(confirmation_, 'give')
                        safe_receive, receive = utils.safe_confirmation_get(confirmation_, 'receive')

                        iter_ = self.window.text_tree.store.append(None, [
                            confirmation_.mode,
                            str(confirmation_.id),
                            str(confirmation_.key),
                            safe_give,
                            confirmation_.to,
                            safe_receive,
                        ])

                        if len(give) > 1 or len(receive) > 1:
                            for item_index, item in enumerate(itertools.zip_longest(give, receive)):
                                self.window.text_tree.store.append(iter_, ['', '', '', item[0], '', item[1]])
                else:
                    log.debug(_("Skipping confirmations update because data doesn't seem to have changed"))

                old_confirmations = confirmations

            await asyncio.sleep(15)

    async def run_steamtrades(self) -> None:
        def error(message: str) -> None:
            assert isinstance(self.window, Gtk.Window), "No window"
            self.window.steamtrades_status.set_current('_ _ _ _ _')
            self.window.steamtrades_status.set_error(message)

        def info(message: str, tradeid: str = '_ _ _ _ _') -> None:
            assert isinstance(self.window, Gtk.Window), "No window"
            self.window.steamtrades_status.set_current(tradeid)
            self.window.steamtrades_status.set_info(message)

        if self.plugin_manager.has_plugin("steamtrades"):
            steamtrades = self.plugin_manager.load_plugin("steamtrades")
            steamtrades_session = steamtrades.Main(self.session, api_url=self.api_url)
        else:
            error(_("Unable to find Steamtrades plugin"))
            return

        assert isinstance(self.window, Gtk.Window), "No window"

        while self.window.get_realized():
            if not config.parser.getboolean("plugins", "steamtrades"):
                await asyncio.sleep(5)
                continue

            info(_("Loading"))
            trade_ids = config.parser.get("steamtrades", "trade_ids")
            wait_min = config.parser.getint("steamtrades", "wait_min")
            wait_max = config.parser.getint("steamtrades", "wait_max")
            cookies = config.login_cookies()

            if not trade_ids:
                error(_("No trade ID found in config file"))
                await asyncio.sleep(5)
                continue

            if cookies:
                self.session.cookie_jar.update_cookies(cookies)  # type: ignore
                try:
                    await steamtrades_session.do_login()
                except aiohttp.ClientConnectionError:
                    error(_("No connection"))
                    await asyncio.sleep(15)
                    continue
                except webapi.LoginError:
                    error(_("User is not logged in"))
                    await asyncio.sleep(15)
                    continue
            else:
                error(_("Unable to find a valid login data"))
                await asyncio.sleep(5)
                continue

            trades = [trade.strip() for trade in trade_ids.split(',')]
            bumped = False

            for trade_id in trades:
                try:
                    trade_info = await steamtrades_session.get_trade_info(trade_id)
                except (IndexError, aiohttp.ClientResponseError):
                    error(_("Unable to find TradeID {}").format(trade_id))
                    bumped = False
                    break
                except aiohttp.ClientConnectionError:
                    error(_("No connection"))
                    bumped = False
                    break

                info(_("Waiting anti-ban timer"))
                await asyncio.sleep(random.randint(3, 8))

                try:
                    if await steamtrades_session.bump(trade_info):
                        info(_("Bumped!"), trade_info.id)
                        bumped = True
                    else:
                        error(_("Unable to bump {}").format(trade_info.id))
                        await asyncio.sleep(5)
                        continue
                except steamtrades.NoTradesError as exception:
                    log.error(str(exception))
                    await asyncio.sleep(15)
                    continue
                except steamtrades.NotReadyError as exception:
                    wait_min = exception.time_left * 60
                    wait_max = wait_min + 400
                    bumped = True
                except steamtrades.TradeClosedError as exception:
                    self.error(str(exception))
                    await asyncio.sleep(5)
                    continue
                except webapi.LoginError as exception:
                    self.error(str(exception))
                    await asyncio.sleep(5)
                    bumped = False
                    break

            if not bumped:
                await asyncio.sleep(10)
                continue

            wait_offset = random.randint(wait_min, wait_max)
            log.debug(_("Setting wait_offset from steamtrades to %s"), wait_offset)
            for past_time in range(wait_offset):
                info(_("Waiting more {} minutes").format(round(wait_offset / 60)))

                try:
                    self.window.steamtrades_status.set_level(past_time, wait_offset)
                except KeyError:
                    self.window.steamtrades_status.set_level(0, 0)

                await asyncio.sleep(1)

    async def run_steamgifts(self) -> None:
        def error(message: str) -> None:
            assert isinstance(self.window, Gtk.Window), "No window"
            self.window.steamgifts_status.set_current('_ _ _ _ _')
            self.window.steamgifts_status.set_error(message)

        if self.plugin_manager.has_plugin("steamgifts"):
            steamgifts = self.plugin_manager.load_plugin("steamgifts")
            steamgifts_session = steamgifts.Main(self.session, api_url=self.api_url)
        else:
            error(_("Unable to find Steamgifts plugin"))
            return

        def info(message: str, giveaway_: Optional[Any] = None) -> None:
            assert isinstance(self.window, Gtk.Window), "No window"

            if giveaway_:
                assert isinstance(giveaway_, steamgifts.GiveawayInfo), "Steamgifts giveaway has wrong type"
                self.window.steamgifts_status.set_current(giveaway_.id)
                self.window.steamgifts_status.set_info('{} {} ({}:{}:{})'.format(
                    message,
                    giveaway_.name,
                    giveaway_.copies,
                    giveaway_.points,
                    giveaway_.level,
                ))
            else:
                self.window.steamgifts_status.set_current('_ _ _ _ _')
                self.window.steamgifts_status.set_info(message)

        assert isinstance(self.window, Gtk.Window), "No window"

        while self.window.get_realized():
            if not config.parser.getboolean("plugins", "steamgifts"):
                await asyncio.sleep(5)
                continue

            info(_("Loading"))
            wait_min = config.parser.getint("steamgifts", "wait_min")
            wait_max = config.parser.getint("steamgifts", "wait_max")
            giveaway_type = config.parser.get("steamgifts", "giveaway_type")
            cookies = config.login_cookies()

            if cookies:
                self.session.cookie_jar.update_cookies(cookies)  # type: ignore
                try:
                    await steamgifts_session.do_login()
                except aiohttp.ClientConnectionError:
                    error(_("No Connection"))
                    await asyncio.sleep(15)
                    continue
                except webapi.LoginError:
                    error(_("User is not logged in"))
                    await asyncio.sleep(15)
                    continue
            else:
                error(_("Unable to find a valid login data"))
                await asyncio.sleep(5)
                continue

            try:
                await steamgifts_session.configure()
            except steamgifts.ConfigureError:
                error(_("Unable to configure steamgifts"))
                await asyncio.sleep(20)
                continue

            giveaways = await steamgifts_session.get_giveaways(giveaway_type)
            joined = False

            for giveaway in giveaways:
                try:
                    user = await steamgifts_session.get_user_info()
                except aiohttp.ClientConnectionError:
                    error(_("No connection"))
                    joined = False
                    break

                if user.level < giveaway.level or user.points < giveaway.points:
                    info(_("User don't meet all the requirements to join"), giveaway)
                    await asyncio.sleep(5)
                    continue

                info(_("Waiting anti-ban timer"), giveaway)
                await asyncio.sleep(random.randint(3, 8))
                # FIXME: stlib should return join status
                await steamgifts_session.join(giveaway)
                info(_("Joined!"), giveaway)
                joined = True

            if not joined:
                await asyncio.sleep(10)
                continue

            wait_offset = random.randint(wait_min, wait_max)
            log.debug(_("Setting wait_offset from steamgifts to %s"), wait_offset)
            for past_time in range(wait_offset):
                info(_("Waiting more {} minutes").format(round(wait_offset / 60)))

                try:
                    self.window.steamgifts_status.set_level(past_time, wait_offset)
                except KeyError:
                    self.window.steamgifts_status.set_level(0, 0)

                await asyncio.sleep(1)

    def on_settings_activate(self, action: Any, data: Any) -> None:
        settings_dialog = settings.SettingsDialog(self.window, self.session, self.webapi_session)
        settings_dialog.show()

    def on_about_activate(self, action: Any, data: Any) -> None:
        dialog = about.AboutDialog(self.window)
        dialog.show()
