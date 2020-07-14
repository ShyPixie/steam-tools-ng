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
import contextlib
import logging
import os
from collections import OrderedDict
from typing import Any

from gi.repository import Gtk

from . import utils, settings
from .. import i18n, config

log = logging.getLogger(__name__)
_ = i18n.get_translation

gtk_themes = OrderedDict([
    ('light', _("Light")),
    ('dark', _("Dark")),
])

log_levels = OrderedDict([
    ('critical', _("Critical")),
    ('error', _("Error")),
    ('warning', _("Warning")),
    ('info', _("Info")),
    ('debug', _("Debug")),
])

translations = OrderedDict([
    ('en', _("English")),
    ('pt_BR', _("Portuguese (Brazil)")),
])

giveaway_types = OrderedDict([
    ('main', _("Main Giveaways")),
    ('new', _("New Giveaways")),
    ('recommended', _("Recommended")),
    ('wishlist', _("Wishlist Only")),
    ('group', _('Group Only')),
])

giveaway_sort_types = OrderedDict([
    ('name', _("Name")),
    ('copies', _("Copies")),
    ('points', _("Points")),
    ('level', _("Level")),
])


# noinspection PyUnusedLocal
class AdvancedSettingsDialog(Gtk.Dialog):
    def __init__(
            self,
            parent_window: Gtk.Window,
            application: Gtk.Application,
            toggle_button: Gtk.ToggleButton,
    ) -> None:
        super().__init__(use_header_bar=True)
        self.parent_window = parent_window
        self.application = application
        self.toggle_button = toggle_button

        self.set_default_size(300, 150)
        self.set_title(_('Advanced Settings'))
        self.set_transient_for(parent_window)
        self.set_modal(True)
        self.set_destroy_with_parent(True)
        self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)

        self.gtk_settings_class = Gtk.Settings.get_default()

        content_area = self.get_content_area()
        content_grid = Gtk.Grid()
        content_grid.set_border_width(10)
        content_grid.set_row_spacing(10)
        content_grid.set_column_spacing(10)
        content_area.add(content_grid)

        login_section = utils.Section("login", _("Login Settings"))

        shared_secret = login_section.new('shared_secret', _("Shared Secret:"), Gtk.Entry, 0, 0)
        shared_secret.connect('changed', settings.on_setting_changed)

        token_item = login_section.new("token", _("Token:"), Gtk.Entry, 0, 1)
        token_item.connect("changed", settings.on_setting_changed)

        token_secure_item = login_section.new("token_secure", _("Token Secure:"), Gtk.Entry, 0, 2)
        token_secure_item.connect("changed", settings.on_setting_changed)

        identity_secret = login_section.new('identity_secret', _("Identity Secret:"), Gtk.Entry, 2, 0)
        identity_secret.connect('changed', settings.on_setting_changed)

        deviceid = login_section.new('deviceid', _("Device ID:"), Gtk.Entry, 2, 1)
        deviceid.connect('changed', settings.on_setting_changed)

        steamid_item = login_section.new("steamid", _("Steam ID:"), Gtk.Entry, 2, 2)
        steamid_item.set_input_purpose(Gtk.InputPurpose.DIGITS)
        steamid_item.connect("changed", settings.on_digit_only_setting_changed)

        reset_button = Gtk.Button(_("Reset Everything (USE WITH CAUTION!!!)"))
        reset_button.set_name("reset_button")
        reset_button.connect("clicked", self.on_reset_clicked)
        login_section.grid.attach(reset_button, 0, 9, 4, 1)
        reset_button.show()

        login_section.show_all()

        self.connect('response', lambda dialog, response_id: self._exit())

        content_grid.attach(login_section, 0, 0, 1, 2)
        content_grid.show()
        self.show()

    @staticmethod
    async def __fast_reset(setup_dialog: Gtk.Dialog) -> bool:
        await asyncio.sleep(5)

        if not setup_dialog.get_realized():
            return False

        with contextlib.suppress(FileNotFoundError):
            os.remove(config.config_file)

        config.parser.clear()
        config.init()

        return True

    def _exit(self) -> None:
        self.toggle_button.set_active(False)
        self.parent_window.reset()
        self.destroy()

    def on_reset_clicked(self, button: Gtk.Button) -> None:
        setup_dialog = setup.SetupDialog(self, self.application)
        setup_dialog.show()
        setup_dialog.status.info(_("Reseting... Please wait!"))
        setup_dialog.status.show()

        main_window = self.parent_window.parent_window
        task = asyncio.ensure_future(self.__fast_reset(setup_dialog))
        task.add_done_callback(self.on_reset_done)

    def on_reset_done(self, future: 'asyncio.Future[Any]') -> None:
        main_window = self.parent_window.parent_window

        if future.result():
            main_window.destroy()
