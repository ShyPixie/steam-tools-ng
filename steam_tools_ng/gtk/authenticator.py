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
import logging

import aiohttp
from gi.repository import Gtk, Gdk
from stlib import universe, webapi, login

from . import utils
from .. import i18n, config

log = logging.getLogger(__name__)
_ = i18n.get_translation


# noinspection PyUnusedLocal
class NewAuthenticatorDialog(Gtk.Dialog):
    def __init__(self, parent_window: Gtk.Window, application: Gtk.Application) -> None:
        super().__init__(use_header_bar=True)
        self.application = application
        self._login_data = None

        self.header_bar = self.get_header_bar()
        self.header_bar.set_show_close_button(True)

        self.add_authenticator_button = utils.AsyncButton(_("Add Authenticator"))
        self.add_authenticator_button.connect("clicked", self.on_add_authenticator_clicked)
        self.header_bar.pack_end(self.add_authenticator_button)

        self.parent_window = parent_window
        self.set_default_size(400, 100)
        self.set_title(_('New Authenticator'))
        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_destroy_with_parent(True)
        self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)

        self.content_area = self.get_content_area()
        self.content_area.set_orientation(Gtk.Orientation.VERTICAL)
        self.content_area.set_border_width(10)
        self.content_area.set_spacing(10)

        self.status = utils.SimpleStatus()
        self.content_area.add(self.status)

        self.user_details_section = utils.Section("Login", _("User Details"))
        self.content_area.add(self.user_details_section)

        self.sms_code_item = self.user_details_section.new("_sms_code", _("SMS Code:"), Gtk.Entry, 0, 1)

        self.connect('response', lambda dialog, _action: dialog.destroy())
        self.connect('key-release-event', self.on_key_release_event)

        self.status.show()
        self.add_authenticator_button.show()
        self.add_authenticator_button.clicked()

    @property
    def sms_code(self) -> str:
        return self.sms_code_item.get_text()

    @property
    def oauth_token(self) -> None:
        return config.parser.get("login", "oauth_token")

    @property
    def steamid(self) -> None:
        return config.parser.get("login", "steamid")

    def on_key_release_event(self, _dialog: Gtk.Dialog, event: Gdk.Event) -> None:
        if event.keyval == Gdk.KEY_Return:
            self.add_authenticator_button.clicked()

    async def on_add_authenticator_clicked(self, button: Gtk.Button) -> None:
        self.status.info(_("Retrieving user data"))
        button.set_sensitive(False)
        self.user_details_section.hide()
        self.set_size_request(0, 0)

        if not self.oauth_token or not self.steamid:
            self.status.error(_(
                "Some login data is missing. If the problem persists, go to:\n"
                "Settings -> Login -> Advanced -> and click on RESET Everything."
            ))

            return

        deviceid = universe.generate_device_id(token=self.oauth_token)
        oauth = {'steamid': self.steamid, 'oauth_token': self.oauth_token}
        login_data = login.LoginData(auth={}, oauth=oauth)

        if not self._login_data or not self.sms_code:
            try:
                self._login_data = await self.application.webapi_session.add_authenticator(login_data, deviceid)
            except aiohttp.ClientError:
                self.status.error(_("Check your connection. (server down?)"))
            except webapi.AuthenticatorExists:
                self.status.error(_(
                    "There's already an authenticator active for that account.\n"
                    "Remove your current steam authenticator and try again."
                ))
            except webapi.PhoneNotRegistered:
                self.status.error(_(
                    "You must have a phone registered on your steam account to proceed.\n"
                    "Go to your Steam Account Settings, add a Phone Number, and try again."
                ))
            except NotImplementedError as exception:
                import sys, traceback
                utils.fatal_error_dialog(exception, traceback.print_tb(sys.exc_info), self.parent_window)
                self.application.on_exit_activate()
            else:
                self.status.info(_("Enter bellow the code received by SMS\nand click on 'Add Authenticator' button"))
                self.user_details_section.show_all()
                self.sms_code_item.set_text('')
                self.sms_code_item.grab_focus()
            finally:
                button.set_sensitive(True)
                return

        self.status.info(_("Adding authenticator"))

        try:
            await self.application.webapi_session.finalize_add_authenticator(
                self._login_data, self.sms_code, time_offset=self.application.time_offset,
            )
        except webapi.SMSCodeError:
            self.status.info(_("Invalid SMS Code. Please,\ncheck the code and try again."))
            self.user_details_section.show_all()
            self.sms_code_item.set_text('')
            self.sms_code_item.grab_focus()
        except aiohttp.ClientError:
            self.status.error(_("Check your connection. (server down?)"))
            self.user_details_section.show_all()
            self.sms_code_item.set_text('')
            self.sms_code_item.grab_focus()
        except Exception as exception:
            import sys, traceback
            utils.fatal_error_dialog(exception, traceback.print_tb(sys.exc_info), self.parent_window)
            self.application.on_exit_activate()
        else:
            self.status.info(_("Saving new secrets"))
            config.new("login", "shared_secret", self._login_data.auth['shared_secret'])
            config.new("login", "identity_secret", self._login_data.auth['identity_secret'])
            config.new("plugins", "steamguard", True)
            config.new("plguins", "confirmations", True)

            self.status.info(_(
                "RECOVERY CODE\n\n"
                "You will need this code to recovery your Steam Account\n"
                "if you lose access to STNG Authenticator. So, write"
                "down this recovery code.\n\n"
                "YOU WILL NOT ABLE TO VIEW IT AGAIN!\n"
            ))

            revocation_code = self._login_data.auth['revocation_code']

            self.add_authenticator_button.hide()

            revocation_status = utils.Status(6, _("Recovery Code"))
            revocation_status.set_pausable(False)
            revocation_status.set_display(revocation_code)
            revocation_status.set_status('')
            self.content_area.add(revocation_status)

            revocation_status.show_all()

            self.set_deletable(False)

            max_value = 30 * 3
            for offset in range(max_value):
                revocation_status.set_level(offset, max_value)
                await asyncio.sleep(0.3)

            self.set_deletable(True)
        finally:
            button.set_sensitive(True)
