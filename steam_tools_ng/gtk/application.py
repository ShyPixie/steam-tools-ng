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
import binascii
import itertools
import logging
import os
import random
import ssl
import sys
import time
from typing import Any, List, Optional

import aiohttp
from gi.repository import Gio, Gtk
from stlib import universe, client, plugins, webapi

from . import about, settings, login, window, utils
from .. import config, i18n

_ = i18n.get_translation
log = logging.getLogger(__name__)


# noinspection PyUnusedLocal
class SteamToolsNG(Gtk.Application):
    def __init__(self, plugin_manager: plugins.Manager) -> None:
        super().__init__(application_id="click.lara.SteamToolsNG",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)

        self._session = None
        self._webapi_session = None
        self.plugin_manager = plugin_manager

        self._main_window_id = 0
        self.gtk_settings = Gtk.Settings.get_default()

        self.api_login: Optional[webapi.Login] = None
        self._time_offset = 0
        self.api_url = config.parser.get("steam", "api_url")

    @property
    def main_window(self) -> Gtk.ApplicationWindow:
        current_window = self.get_window_by_id(self._main_window_id)
        assert isinstance(current_window, Gtk.ApplicationWindow), "main window has not been created"
        return self.get_window_by_id(self._main_window_id)

    @property
    def time_offset(self) -> int:
        return self._time_offset

    @property
    def session(self) -> aiohttp.ClientSession:
        assert isinstance(self._session, aiohttp.ClientSession), "session has not been created"
        return self._session

    @property
    def webapi_session(self) -> webapi.SteamWebAPI:
        assert isinstance(self._webapi_session, webapi.SteamWebAPI), "webapi session has not been created"
        return self._webapi_session

    @property
    def steamid(self) -> Optional[int]:
        return config.parser.get("login", "steamid")

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)

        settings_action = Gio.SimpleAction.new('settings')
        settings_action.connect("activate", self.on_settings_activate)
        self.add_action(settings_action)

        about_action = Gio.SimpleAction.new("about")
        about_action.connect("activate", self.on_about_activate)
        self.add_action(about_action)

        exit_action = Gio.SimpleAction.new("exit")
        exit_action.connect("activate", self.on_exit_activate)
        self.add_action(exit_action)

        theme = config.parser.get("gtk", "theme")

        if theme == 'dark':
            self.gtk_settings.props.gtk_application_prefer_dark_theme = True
        else:
            self.gtk_settings.props.gtk_application_prefer_dark_theme = False

    def do_activate(self) -> None:
        current_window = window.Main(application=self, title="Steam Tools NG")
        self._main_window_id = current_window.get_id()
        current_window.show()

        task = asyncio.gather(self.async_activate())
        task.add_done_callback(self.async_activate_callback)

    def async_activate_callback(self, future: 'asyncio.Future[Any]') -> None:
        exception = future.exception()

        if exception and not isinstance(exception, asyncio.CancelledError):
            log.critical(repr(exception))
            utils.fatal_error_dialog(str(future.exception()), self.main_window)
            self.main_window.destroy()  # type: ignore

    async def do_login(self, *, block: bool = True, auto: bool = False) -> None:
        login_dialog = login.LoginDialog(self.main_window, self)
        login_dialog.show()

        if auto:
            encrypted_password = config.parser.get("login", "password")
            login_dialog.set_password(encrypted_password)
            login_dialog.login_button.clicked()

        if block:
            while self.main_window.get_realized():
                if login_dialog.has_user_data:
                    break

                await asyncio.sleep(1)

    async def async_activate(self) -> None:
        ssl_context = ssl.SSLContext()

        if hasattr(sys, 'frozen'):
            _executable_path = os.path.dirname(sys.executable)
            ssl_context.load_verify_locations(cafile=os.path.join(_executable_path, 'etc', 'cacert.pem'))

        tcp_connector = aiohttp.TCPConnector(ssl=ssl_context)
        self._session = aiohttp.ClientSession(raise_for_status=True, connector=tcp_connector)
        self._webapi_session = webapi.SteamWebAPI(self.session, self.api_url)
        self._time_offset = await config.time_offset(self.webapi_session)

        self.main_window.set_login_icon('steam', 'yellow')
        self.main_window.set_warning(_("Logging on Steam. Please wait!"))
        log.info(_("Logging on Steam"))

        token = config.parser.get("login", "token")
        token_secure = config.parser.get("login", "token_secure")

        if not token or not token_secure or not self.steamid:
            await self.do_login()

        self.session.cookie_jar.update_cookies(config.login_cookies())  # type: ignore

        try:
            if await self.webapi_session.is_logged_in(self.steamid):
                self.main_window.set_login_icon("steam", "green")
                log.info("Steam login Successful")
            else:
                await self.do_login(auto=True)
        except aiohttp.ClientError as exception:
            log.exception(str(exception))
            utils.fatal_error_dialog(
                _("No Connection. Please, check your connection and try again."),
                self.main_window,
            )
            self.main_window.destroy()
            return None

        self.main_window.unset_warning()

        modules = {
            "confirmations": asyncio.ensure_future(self.run_confirmations()),
            "steamguard": asyncio.ensure_future(self.run_steamguard()),
            "steamtrades": asyncio.ensure_future(self.run_steamtrades()),
            "steamgifts": asyncio.ensure_future(self.run_steamgifts()),
            "cardfarming": asyncio.ensure_future(self.run_cardfarming()),
        }

        while self.main_window.get_realized():
            for module_name, task in modules.items():
                if config.parser.getboolean("plugins", module_name):
                    if task.cancelled():
                        if module_name != "confirmations":
                            self.main_window.set_status(module_name, status=_("Loading"))
                        coro = getattr(self, f"run_{module_name}")
                        modules[module_name] = asyncio.ensure_future(coro())
                else:
                    if not task.cancelled():
                        task.cancel()

                        try:
                            await task
                        except asyncio.CancelledError:
                            if module_name != "confirmations":
                                self.main_window.set_status(module_name, status=_("Disabled"))

            await asyncio.sleep(3)

    async def run_steamguard(self) -> None:
        while self.main_window.get_realized():
            shared_secret = config.parser.get("login", "shared_secret")

            try:
                if not shared_secret:
                    raise ValueError

                server_time = int(time.time()) - self.time_offset
                auth_code = universe.generate_steam_code(server_time, shared_secret)
            except (ValueError, binascii.Error):
                log.debug(_("The current shared secret is invalid."))
                config.new("plugins", "steamguard", False)
                await asyncio.sleep(10)
            except ProcessLookupError:
                self.main_window.set_status("steamguard", error=_("Steam Client is not running"))
                await asyncio.sleep(10)
            else:
                self.main_window.set_status("steamguard", status=_("Loading..."))

                seconds = 30 - (server_time % 30)

                for past_time in range(seconds * 9):
                    self.main_window.set_status(
                        "steamguard",
                        display=auth_code,
                        status=_("Running"),
                        info=_("New code in {} seconds").format(seconds * 9 - past_time),
                        level=(past_time, seconds * 8)
                    )

                    await asyncio.sleep(0.125)

    async def run_cardfarming(self) -> None:
        while self.main_window.get_realized():
            reverse_sorting = config.parser.getboolean("cardfarming", "reverse_sorting")
            wait_min = config.parser.getint("cardfarming", "wait_min")
            wait_max = config.parser.getint("cardfarming", "wait_max")
            cookies = config.login_cookies()

            if not self.steamid:
                raise NotImplementedError

            if cookies:
                self.session.cookie_jar.update_cookies(cookies)  # type: ignore
            else:
                self.main_window.set_status("cardfarming", error=_("Unable to find a valid login data"))
                await asyncio.sleep(5)
                continue

            try:
                badges = sorted(
                    await self.webapi_session.get_badges(self.steamid),
                    key=lambda badge_: badge_.cards,
                    reverse=reverse_sorting
                )
            except aiohttp.ClientError:
                self.main_window.set_status("cardfarming", error=_("No Connection"))
                await asyncio.sleep(10)
                continue

            if not badges:
                self.main_window.set_status("cardfarming", status=_("Stopped"), info=_("No more cards to drop."))
                break

            for badge in badges:
                self.main_window.set_status(
                    "cardfarming",
                    display=badge.game_id,
                    status=_("Running {}").format(badge.game_name),
                )

                wait_offset = random.randint(wait_min, wait_max)

                while badge.cards != 0:
                    executor = client.SteamApiExecutor(badge.game_id)

                    while self.main_window.get_realized():
                        try:
                            await executor.init()
                            break
                        except client.SteamAPIError:
                            log.error(_("Invalid game_id %s. Ignoring."), badge.game_id)
                            # noinspection PyProtectedMember
                            badge = badge._replace(cards=0)
                            break
                        except ProcessLookupError:
                            self.main_window.set_status("cardfarming", error=_("Steam Client is not running."))
                            await asyncio.sleep(5)

                    for past_time in range(wait_offset):
                        self.main_window.set_status(
                            "cardfarming",
                            display=badge.game_id,
                            info=_("Waiting drops for {} minutes").format(round((wait_offset - past_time) / 60)),
                            level=(past_time, wait_offset),
                        )

                        await asyncio.sleep(1)

                    self.main_window.set_status(
                        "cardfarming",
                        display=badge.game_id,
                        info=_("{} ({})").format(_("Updating drops"), badge.game_name),
                    )

                    await executor.shutdown()
                    await asyncio.sleep(60)

                    while self.main_window.get_realized():
                        try:
                            badge = await self.webapi_session.update_badge_drops(badge, self.steamid)
                            break
                        except aiohttp.ClientError:
                            self.main_window.set_status("cardfarming", error=_("No connection"))
                            await asyncio.sleep(10)
                        except webapi.BadgeError:
                            self.main_window.set_status("cardfarming", error=_("Steam Server is busy"))
                            await asyncio.sleep(20)

                self.main_window.set_status(
                    "cardfarming",
                    display=badge.game_id,
                    info=_("{} ({})").format(_("Done"), badge.game_name),
                )

    async def run_confirmations(self) -> None:
        old_confirmations: List[webapi.Confirmation] = []

        while self.main_window.get_realized():
            identity_secret = config.parser.get("login", "identity_secret")
            deviceid = config.parser.get("login", "deviceid")
            # cookies = config.login_cookies()

            if not identity_secret:
                log.debug(_("The current identity secret is invalid."))
                config.new("plugins", "confirmations", False)
                await asyncio.sleep(10)
                continue

            if not deviceid:
                log.debug(_("Unable to find deviceid. Generating from identity."))
                deviceid = universe.generate_device_id(identity_secret)
                config.new("login", "deviceid", deviceid)

            # if not cookies:
            #    self.main_window.set_warning(_("Unable to find a valid login data"))
            #    await asyncio.sleep(5)
            #    continue

            # self.session.cookie_jar.update_cookies(cookies)  # type: ignore

            if self.main_window.text_tree_lock:
                self.main_window.set_warning(_("Waiting another confirmation process"))
                await asyncio.sleep(5)
                continue

            try:
                confirmations = await self.webapi_session.get_confirmations(
                    identity_secret,
                    self.steamid,
                    deviceid,
                    time_offset=self.time_offset,
                )
            except AttributeError as exception:
                log.warning(repr(exception))
                self.main_window.set_warning(_("Error when fetch confirmations"))
            except ProcessLookupError:
                self.main_window.set_warning(_("Steam is not running"))
            except webapi.LoginError as exception:
                log.warning(repr(exception))
                self.main_window.set_warning(_("User is not logged in"))
                await self.do_login(auto=True)
            except aiohttp.ClientError as exception:
                log.warning(repr(exception))
                self.main_window.set_warning(_("No connection"))
            else:
                self.main_window.unset_warning()
                if old_confirmations != confirmations:
                    self.main_window.text_tree.store.clear()

                    for confirmation_ in confirmations:
                        safe_give, give = utils.safe_confirmation_get(confirmation_, 'give')
                        safe_receive, receive = utils.safe_confirmation_get(confirmation_, 'receive')

                        iter_ = self.main_window.text_tree.store.append(None, [
                            confirmation_.mode,
                            str(confirmation_.id),
                            str(confirmation_.key),
                            safe_give,
                            confirmation_.to,
                            safe_receive,
                        ])

                        for item in itertools.zip_longest(give, receive):
                            self.main_window.text_tree.store.append(iter_, ['', '', '', item[0], '', item[1]])
                else:
                    log.debug(_("Skipping confirmations update because data doesn't seem to have changed"))

                old_confirmations = confirmations

            await asyncio.sleep(20)

    async def run_steamtrades(self) -> None:
        try:
            if self.plugin_manager.has_plugin("steamtrades"):
                steamtrades = self.plugin_manager.load_plugin("steamtrades")
                steamtrades_session = steamtrades.Main(self.session, api_url=self.api_url)
            else:
                raise ImportError
        except ImportError:
            self.main_window.set_status("steamtrades", error=_("Unable to find Steamtrades plugin"))
            return

        assert isinstance(self.main_window, Gtk.Window), "No window"

        while self.main_window.get_realized():
            self.main_window.set_status("steamtrades", info=_("Loading"))
            trade_ids = config.parser.get("steamtrades", "trade_ids")
            wait_min = config.parser.getint("steamtrades", "wait_min")
            wait_max = config.parser.getint("steamtrades", "wait_max")
            cookies = config.login_cookies()

            if not trade_ids:
                self.main_window.set_status("steamtrades", error=_("No trade ID found in config file"))
                await asyncio.sleep(5)
                continue

            self.main_window.set_login_icon('steamtrades', 'yellow')
            self.session.cookie_jar.update_cookies(cookies)  # type: ignore

            try:
                if not cookies:
                    raise webapi.LoginError

                await steamtrades_session.do_login()
            except webapi.LoginError:
                self.main_window.set_login_icon('steamtrades', 'red')
                self.main_window.set_status("steamtrades", error=_("User is not logged in"))
                await self.do_login(auto=True)
                await asyncio.sleep(15)
                continue
            except aiohttp.ClientError:
                self.main_window.set_login_icon('steamtrades', 'red')
                self.main_window.set_status("steamtrades", error=_("No connection"))
                await asyncio.sleep(15)
                continue

            self.main_window.set_login_icon('steamtrades', 'green')

            trades = [trade.strip() for trade in trade_ids.split(',')]
            bumped = False

            for trade_id in trades:
                try:
                    trade_info = await steamtrades_session.get_trade_info(trade_id)
                except (IndexError, aiohttp.ClientResponseError):
                    self.main_window.set_status("steamtrades", error=_("Unable to find trade id"))
                    bumped = False
                    break
                except aiohttp.ClientError:
                    self.main_window.set_login_icon('steamtrades', 'red')
                    self.main_window.set_status("steamtrades", error=_("No connection"))
                    bumped = False
                    break

                self.main_window.set_status("steamtrades", display=trade_info.id, info=trade_info.title)
                max_ban_wait = random.randint(5, 15)
                for past_time in range(max_ban_wait):
                    try:
                        self.main_window.steamtrades_status.set_level(past_time, max_ban_wait)
                    except KeyError:
                        self.main_window.steamtrades_status.set_level(0, 0)

                    await asyncio.sleep(1)

                try:
                    if await steamtrades_session.bump(trade_info):
                        self.main_window.set_status("steamtrades", display=trade_id, info=_("Bumped!"))
                        bumped = True
                    else:
                        self.main_window.set_status("steamtrades", display=trade_id, error=_("Unable to bump"))
                        await asyncio.sleep(5)
                        continue
                except steamtrades.NoTradesError as exception:
                    log.error(str(exception))
                    await asyncio.sleep(15)
                    continue
                except steamtrades.TradeNotReadyError as exception:
                    wait_min = exception.time_left * 60
                    wait_max = wait_min + 400
                    bumped = True
                except steamtrades.TradeClosedError as exception:
                    log.error(str(exception))
                    self.main_window.set_status("steamtrades", error=str(exception))
                    await asyncio.sleep(5)
                    continue
                except webapi.LoginError as exception:
                    log.error(str(exception))
                    self.main_window.set_login_icon("steamtrades", "red")
                    self.main_window.set_status("steamtrades", error=_("Login is lost. Trying to relogin."))
                    await asyncio.sleep(5)
                    bumped = False
                    break

            if not bumped:
                await asyncio.sleep(10)
                continue

            wait_offset = random.randint(wait_min, wait_max)
            log.debug(_("Setting wait_offset from steamtrades to %s"), wait_offset)
            for past_time in range(wait_offset):
                self.main_window.set_status(
                    "steamtrades",
                    info=_("Waiting more {} minutes").format(round(wait_offset / 60)),
                    level=(past_time, wait_offset),
                )

                await asyncio.sleep(1)

    async def run_steamgifts(self) -> None:
        try:
            if self.plugin_manager.has_plugin("steamgifts"):
                steamgifts = self.plugin_manager.load_plugin("steamgifts")
                steamgifts_session = steamgifts.Main(self.session, api_url=self.api_url)
            else:
                raise ImportError
        except ImportError:
            self.main_window.set_status("steamgifts", error=_("Unable to find Steamgifts plugin"))
            return

        assert isinstance(self.main_window, Gtk.Window), "No window"

        while self.main_window.get_realized():
            self.main_window.set_status("steamgifts", status=_("Loading"))
            wait_min = config.parser.getint("steamgifts", "wait_min")
            wait_max = config.parser.getint("steamgifts", "wait_max")
            giveaway_type = config.parser.get("steamgifts", "giveaway_type")
            pinned_giveaways = config.parser.get("steamgifts", "developer_giveaways")
            cookies = config.login_cookies()

            self.main_window.set_login_icon('steamgifts', 'yellow')
            self.session.cookie_jar.update_cookies(cookies)  # type: ignore

            try:
                if not cookies:
                    raise webapi.LoginError

                await steamgifts_session.do_login()
            except aiohttp.ClientConnectionError:
                self.main_window.set_login_icon('steamgifts', 'red')
                self.main_window.set_status("steamgifts", error=_("No Connection"))
                await asyncio.sleep(15)
                continue
            except webapi.LoginError:
                self.main_window.set_login_icon('steamgifts', 'red')
                self.main_window.set_status("steamgifts", error=_("User is not logged in"))
                await self.do_login(auto=True)
                await asyncio.sleep(15)
                continue

            self.main_window.set_login_icon('steamgifts', 'green')

            try:
                await steamgifts_session.configure()
            except steamgifts.ConfigureError:
                self.main_window.set_status("steamgifts", error=_("Unable to configure steamgifts"))
                await asyncio.sleep(20)
                continue

            giveaways = await steamgifts_session.get_giveaways(giveaway_type, pinned_giveaways=pinned_giveaways)
            joined = False

            if giveaways:
                sort_giveaways = config.parser.get("steamgifts", "sort")
                reverse_sorting = config.parser.getboolean("steamgifts", "reverse_sorting")

                if sort_giveaways:
                    # FIXME: check if config is valid
                    giveaways = sorted(
                        giveaways,
                        key=lambda giveaway_: getattr(giveaway_, sort_giveaways),
                        reverse=reverse_sorting,
                    )
            else:
                self.main_window.set_status("steamgifts", status=_("No giveaways to join."))
                joined = True
                wait_min //= 2
                wait_max //= 2

            for index, giveaway in enumerate(giveaways):
                self.main_window.steamgifts_status.set_level(index, len(giveaway))

                max_ban_wait = random.randint(5, 15)
                for past_time in range(max_ban_wait):
                    try:
                        self.main_window.steamgifts_status.set_level(past_time, max_ban_wait)
                    except KeyError:
                        self.main_window.steamgifts_status.set_level(0, 0)

                    await asyncio.sleep(1)

                try:
                    if await steamgifts_session.join(giveaway):

                        self.main_window.set_status(
                            "steamgifts",
                            display=giveaway.id,
                            status="{} {} ({}:{}:{})".format(_("Joined!"), *giveaway[:4]),
                        )

                        joined = True
                    else:
                        self.main_window.set_status("steamgifts", display=giveaway.id, error=_("Unable to join {}"))
                        await asyncio.sleep(5)
                        continue
                except steamgifts.NoGiveawaysError as exception:
                    log.error(str(exception))
                    await asyncio.sleep(15)
                    continue
                except steamgifts.GiveawayEndedError as exception:
                    log.error(str(exception))
                    self.main_window.set_status("steamgifts", error=_("Giveaway is already ended."))
                    await asyncio.sleep(5)
                    continue
                except webapi.LoginError as exception:
                    log.error(repr(exception))
                    self.main_window.set_login_icon('steamgifts', 'red')
                    self.main_window.set_status("steamgifts", error=_("Login is lost. Trying to relogin."))
                    await asyncio.sleep(5)
                    joined = False
                    break
                except steamgifts.NoLevelError as exception:
                    log.error(str(exception))
                    self.main_window.set_status("steamgifts", error=_("User don't have required level to join"))
                    await asyncio.sleep(5)
                    continue
                except steamgifts.NoPointsError as exception:
                    log.error(str(exception))
                    self.main_window.set_status("steamgifts", error=_("User don't have required points to join"))
                    await asyncio.sleep(5)

                    if steamgifts_session.user_info.points <= 2:
                        break
                    else:
                        continue

            if not joined:
                await asyncio.sleep(10)
                continue

            wait_offset = random.randint(wait_min, wait_max)
            log.debug(_("Setting wait_offset from steamgifts to %s"), wait_offset)
            for past_time in range(wait_offset):
                self.main_window.set_status(
                    "steamgifts",
                    info=_("Waiting more {} minutes").format(round((wait_offset - past_time) / 60)),
                    level=(past_time, wait_offset),
                )

                await asyncio.sleep(1)

    def on_settings_activate(self, *args: Any) -> None:
        settings_dialog = settings.SettingsDialog(self.main_window, self)
        settings_dialog.show()

    def on_about_activate(self, *args: Any) -> None:
        dialog = about.AboutDialog(self.main_window)
        dialog.show()

    def on_exit_activate(self, *args: Any) -> None:
        loop = asyncio.get_running_loop()
        loop.stop()
        self.main_window.destroy()
