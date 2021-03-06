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
import binascii
import codecs
import logging

import aiohttp
from gi.repository import Gtk, Gdk, GdkPixbuf
from stlib import login

from . import utils
from .. import i18n, config

log = logging.getLogger(__name__)
_ = i18n.get_translation


# noinspection PyUnusedLocal
class LoginDialog(Gtk.Dialog):
    def __init__(
            self,
            parent_window: Gtk.Window,
            application: Gtk.Application,
            mobile_login: bool = True,
    ) -> None:
        super().__init__(use_header_bar=True)
        self.application = application
        self._login_session = None
        self.mobile_login = mobile_login
        self.has_user_data = False

        self.header_bar = self.get_header_bar()
        self.header_bar.set_show_close_button(True)

        self.login_button = utils.AsyncButton(_("Log-in"))
        self.login_button.connect("clicked", self.on_login_button_clicked)
        self.header_bar.pack_end(self.login_button)

        self.parent_window = parent_window
        self.set_default_size(400, 100)
        self.set_title(_('Login'))
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

        self.user_details_section = utils.Section("login", _("User Details"))
        self.content_area.add(self.user_details_section)

        self.username_item = self.user_details_section.new("account_name", _("Username:"), Gtk.Entry, 0, 0)

        self.__password_item = self.user_details_section.new("_password", _("Password:"), Gtk.Entry, 0, 1)
        self.__password_item.set_visibility(False)
        self.__password_item.set_invisible_char('*')

        self.steam_code_item = self.user_details_section.new("_steam_code", _("Steam Code:"), Gtk.Entry, 0, 2)
        self.mail_code_item = self.user_details_section.new("_mail_code", _("Mail Code:"), Gtk.Entry, 0, 2)

        self.captcha_gid = -1
        self.captcha_item = self.user_details_section.new("_captcha", _("Code:"), Gtk.Image, 0, 3)
        self.captcha_text_item = self.user_details_section.new(
            "_captcha_text", _("Captcha Text:"), Gtk.Entry, 0, 4,
        )

        self.save_password_item = self.user_details_section.new("_savepwd", _("Save Password:"), Gtk.CheckButton, 0, 5)
        self.save_password_item.set_active(True)

        self.advanced_login = utils.ClickableLabel()
        self.advanced_login.set_markup(utils.markup(_("Advanced Login"), font_size='x-small', color='blue'))
        self.advanced_login.set_halign(Gtk.Align.END)
        self.advanced_login.connect("clicked", self.on_advanced_login_clicked)
        self.content_area.add(self.advanced_login)

        self.advanced_login_section = utils.Section("login", _("Advanced Login"))
        self.content_area.add(self.advanced_login_section)

        self.identity_secret_item = self.advanced_login_section.new(
            'identity_secret',
            _("Identity Secret:"),
            Gtk.Entry,
            0, 0,
        )

        self.shared_secret_item = self.advanced_login_section.new(
            'shared_secret',
            _("Shared Secret:"),
            Gtk.Entry,
            0, 1,
        )

        self.connect('response', lambda dialog, _action: dialog.destroy())
        self.connect('key-release-event', self.on_key_release_event)

        self.content_area.show_all()
        self.steam_code_item.hide()
        self.mail_code_item.hide()
        self.captcha_item.hide()
        self.captcha_text_item.hide()
        self.advanced_login_section.hide()
        self.login_button.show()
        self.check_login_availability()

    @property
    def login_session(self) -> login.Login:
        assert isinstance(self._login_session, login.Login)
        return self._login_session

    @property
    def username(self) -> str:
        return self.username_item.get_text()

    @property
    def __password(self) -> str:
        return self.__password_item.get_text()

    def set_password(self, encrypted_password: str) -> None:
        key = codecs.decode(encrypted_password, 'rot13')
        raw = codecs.decode(key.encode(), 'base64')
        self.__password_item.set_text(raw.decode())

    @property
    def mail_code(self) -> str:
        return self.mail_code_item.get_text()

    @property
    def steam_code(self) -> str:
        return self.steam_code_item.get_text()

    @property
    def captcha_text(self) -> str:
        return self.captcha_text_item.get_text()

    @property
    def shared_secret(self) -> str:
        return self.shared_secret_item.get_text()

    @property
    def identity_secret(self) -> str:
        return self.identity_secret_item.get_text()

    def check_login_availability(self) -> None:
        if not self.username or not self.__password:
            self.login_button.set_sensitive(False)
        else:
            self.login_button.set_sensitive(True)

    def on_key_release_event(self, _dialog: Gtk.Dialog, event: Gdk.Event) -> None:
        self.check_login_availability()

        if event.keyval == Gdk.KEY_Return:
            if not self.username or not self.__password:
                self.status.error(_("Username or Password is blank!"))
            else:
                self.login_button.clicked()

    async def on_login_button_clicked(self, *args) -> None:
        self.status.info(_("Retrieving user data"))
        self.username_item.set_sensitive(False)
        self.__password_item.set_sensitive(False)
        self.save_password_item.set_sensitive(False)
        self.login_button.set_sensitive(False)

        self._login_session = login.get_session(
            0,
            self.username,
            self.__password,
            http_session=self.application.session,
        )

        kwargs = {'emailauth': self.mail_code, 'mobile_login': self.mobile_login}

        # no reason to send captcha_text if no gid is found
        if self.captcha_gid != -1:
            kwargs['captcha_text'] = self.captcha_text
            kwargs['captcha_gid'] = self.captcha_gid
            # if login fails for any reason, gid must be unset
            # CaptchaError exception will reset it if needed
            self.captcha_gid = -1

        if not self.shared_secret or not self.identity_secret:
            log.warning(_("No shared secret found. Trying to log-in without two-factor authentication."))
            # self.code_item.show()

        kwargs['shared_secret'] = self.shared_secret
        kwargs['time_offset'] = self.application.time_offset
        kwargs['authenticator_code'] = self.steam_code

        self.status.info(_("Logging in"))
        self.captcha_item.hide()
        self.captcha_text_item.hide()
        self.steam_code_item.hide()
        self.mail_code_item.hide()

        try:
            login_data = await self.login_session.do_login(**kwargs)
        except login.MailCodeError:
            self.status.info(_("Write code received by email\nand click on 'Log-in' button"))
            self.mail_code_item.set_text("")
            self.mail_code_item.show_all()
            self.mail_code_item.grab_focus()
        except login.TwoFactorCodeError:
            self.status.error(_("Write Steam Code bellow and click on 'Log-in'"))
            self.steam_code_item.set_text("")
            self.steam_code_item.show_all()
            self.steam_code_item.grab_focus()
        except login.LoginBlockedError:
            self.status.error(_(
                "Your network is blocked!\n"
                "It'll take some time until unblocked. Please, try again later\n"
            ))
            self.user_details_section.hide()
            self.advanced_login.hide()
            self.advanced_login_section.hide()
            self.login_button.hide()
            self.set_deletable(True)
        except login.CaptchaError as exception:
            self.status.info(_("Write captcha code as shown bellow\nand click on 'Log-in' button"))
            self.captcha_gid = exception.captcha_gid

            pixbuf_loader = GdkPixbuf.PixbufLoader()
            pixbuf_loader.write(exception.captcha)
            pixbuf_loader.close()
            self.captcha_item.set_from_pixbuf(pixbuf_loader.get_pixbuf())

            self.captcha_item.show()
            self.captcha_text_item.set_text("")
            self.captcha_text_item.show()
            self.captcha_text_item.grab_focus()
        except login.LoginError as exception:
            log.error("Login error: %s", exception)
            self.__password_item.set_text('')
            self.__password_item.grab_focus()

            self.status.error(_(
                "Unable to log-in!\n"
                "Please, check your username/password and try again.\n"
            ))
            self.username_item.set_sensitive(True)
            self.__password_item.set_sensitive(True)
            self.__password_item.grab_focus()
        except aiohttp.ClientError:
            self.status.error(_("Check your connection. (server down?)"))
            self.username_item.set_sensitive(True)
            self.__password_item.set_sensitive(True)
        except binascii.Error:
            self.status.error(_("shared secret is invalid!"))
            self.username_item.set_sensitive(True)
            self.__password_item.set_sensitive(True)
            self.shared_secret_item.grab_focus()
        else:
            new_configs = {"account_name": self.username}

            if "shared_secret" in login_data.auth:
                new_configs["shared_secret"] = login_data.auth["shared_secret"]
            elif self.shared_secret:
                new_configs["shared_secret"] = self.shared_secret

            if "identity_secret" in login_data.auth:
                new_configs['identity_secret'] = login_data.auth['identity_secret']
            elif self.identity_secret:
                new_configs["identity_secret"] = self.identity_secret

            if self.save_password_item.get_active():
                # Just for curious people. It's not even safe.
                key = codecs.encode(self.__password.encode(), 'base64')
                out = codecs.encode(key.decode(), 'rot13')
                new_configs["password"] = out

            if login_data.oauth:
                new_configs['steamid'] = login_data.oauth['steamid']
                new_configs['token'] = login_data.oauth['wgtoken']
                new_configs['token_secure'] = login_data.oauth['wgtoken_secure']
                new_configs['oauth_token'] = login_data.oauth['oauth_token']
            else:
                new_configs['steamid'] = login_data.auth['transfer_parameters']['steamid']
                new_configs['token'] = login_data.auth['transfer_parameters']['webcookie']
                new_configs['token_secure'] = login_data.auth['transfer_parameters']['token_secure']

            for key, value in new_configs.items():
                config.new("login", key, value)

            self.has_user_data = True
            self.destroy()
        finally:
            self.save_password_item.set_sensitive(True)
            self.login_button.set_sensitive(True)
            self.set_size_request(400, 100)

    def on_advanced_login_clicked(self, *args) -> None:
        if self.advanced_login_section.props.visible:
            self.identity_secret_item.set_text('')
            self.shared_secret_item.set_text('')
            self.advanced_login_section.hide()
            self.set_size_request(400, 100)
        else:
            self.advanced_login_section.show()
