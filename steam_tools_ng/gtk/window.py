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
import os
from typing import Union, Optional, Tuple

from gi.repository import GdkPixbuf, Gio, Gtk

from . import confirmation, utils
from .. import config, i18n, core

_ = i18n.get_translation
log = logging.getLogger(__name__)


# noinspection PyUnusedLocal
class Main(Gtk.ApplicationWindow):
    def __init__(self, application: Gtk.Application, title: str) -> None:
        super().__init__(application=application, title=title)
        self.application = application

        header_bar = Gtk.HeaderBar()
        header_bar.set_show_close_button(True)

        icon = Gtk.Image()
        pix = GdkPixbuf.Pixbuf.new_from_file_at_size(os.path.join(config.icons_dir, 'stng.png'), 28, 28)
        icon.set_from_pixbuf(pix)
        header_bar.pack_start(icon)

        menu = Gio.Menu()
        menu.append(_("Settings"), "app.settings")
        menu.append(_("About"), "app.about")
        menu.append(_("Exit"), "app.exit")

        menu_button = Gtk.MenuButton("☰")
        menu_button.set_relief(Gtk.ReliefStyle.NONE)
        menu_button.set_use_popover(True)
        menu_button.set_menu_model(menu)
        header_bar.pack_end(menu_button)

        self.set_default_size(650, 450)
        self.set_resizable(False)

        if config.parser.getboolean("general", "show_close_button"):
            self.set_deletable(True)
        else:
            self.set_deletable(False)

        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_titlebar(header_bar)
        self.set_title('Steam Tools NG')

        main_grid = Gtk.Grid()
        main_grid.set_border_width(10)
        main_grid.set_row_spacing(10)
        self.add(main_grid)

        self.status_grid = Gtk.Grid()
        self.status_grid.set_column_homogeneous(True)
        main_grid.attach(self.status_grid, 0, 0, 4, 1)

        self.steamtrades_status = utils.Status(5, config.plugins['steamtrades'])
        self.status_grid.attach(self.steamtrades_status, 0, 0, 1, 1)

        self.steamgifts_status = utils.Status(5, config.plugins['steamgifts'])
        self.status_grid.attach(self.steamgifts_status, 1, 0, 1, 1)

        self.steamguard_status = utils.Status(4, config.plugins['steamguard'])
        self.status_grid.attach(self.steamguard_status, 0, 1, 1, 1)

        self.cardfarming_status = utils.Status(6, config.plugins['cardfarming'])
        self.status_grid.attach(self.cardfarming_status, 1, 1, 1, 1)

        self.confirmations_grid = Gtk.Grid()
        self.confirmations_grid.set_row_spacing(10)
        main_grid.attach(self.confirmations_grid, 0, 1, 1, 1)

        self._info_label = Gtk.Label()
        self._info_label.set_text(_("If you have confirmations, they will be shown here. (20 seconds delay)"))
        self.confirmations_grid.attach(self._info_label, 0, 2, 4, 1)

        self._warning_label = Gtk.Label()
        self.confirmations_grid.attach(self._warning_label, 0, 3, 4, 1)

        self.text_tree = utils.SimpleTextTree((_('mode'), _('id'), _('key'), _('give'), _('to'), _('receive')), False)
        self.confirmations_grid.attach(self.text_tree, 0, 4, 4, 1)

        self.text_tree_lock = False

        for index, column in enumerate(self.text_tree.view.get_columns()):
            if index in (0, 1, 2):
                column.set_visible(False)

            if index == 4:
                column.set_fixed_width(140)
            else:
                column.set_fixed_width(220)

        self.text_tree.view.set_has_tooltip(True)
        self.text_tree.view.connect('query-tooltip', self.on_query_confirmations_tooltip)

        tree_selection = self.text_tree.view.get_selection()
        tree_selection.connect("changed", self.on_tree_selection_changed)

        accept_button = Gtk.Button(_('Accept selected'))
        accept_button.connect('clicked', self.on_validate_confirmations, "allow", tree_selection)
        self.confirmations_grid.attach(accept_button, 0, 5, 1, 1)

        cancel_button = Gtk.Button(_('Cancel selected'))
        cancel_button.connect('clicked', self.on_validate_confirmations, "cancel", tree_selection)
        self.confirmations_grid.attach(cancel_button, 1, 5, 1, 1)

        accept_all_button = Gtk.Button(_('Accept all'))
        accept_all_button.connect('clicked', self.on_validate_confirmations, "allow", self.text_tree.store)
        self.confirmations_grid.attach(accept_all_button, 2, 5, 1, 1)

        cancel_all_button = Gtk.Button(_('Cancel all'))
        cancel_all_button.connect('clicked', self.on_validate_confirmations, "cancel", self.text_tree.store)
        self.confirmations_grid.attach(cancel_all_button, 3, 5, 1, 1)

        main_grid.show_all()
        self.confirmations_grid.show_all()
        self.show_all()

        self.connect("destroy", self.application.on_exit_activate)

        loop = asyncio.get_event_loop()
        task = loop.create_task(self.plugin_switch())
        task.add_done_callback(self.application.async_activate_callback)

    async def plugin_switch(self) -> None:
        plugins = []

        while self.get_realized():
            plugins_enabled = []

            for plugin_name in config.plugins.keys():
                plugin_config = config.parser.getboolean("plugins", plugin_name)

                if plugin_name == "confirmations":
                    if plugin_config:
                        self.confirmations_grid.show_all()
                        self.set_size_request(655, 560)
                    else:
                        self.confirmations_grid.hide()
                        self.set_size_request(655, 0)

                    continue

                if plugin_config:
                    plugins_enabled.append(plugin_name)

            if plugins_enabled == plugins:
                await asyncio.sleep(1)
                continue
            else:
                plugins = plugins_enabled

            for widget in self.status_grid.get_children():
                self.status_grid.remove(widget)

            for index, plugin_name in enumerate(plugins_enabled):
                plugin = getattr(self, f'{plugin_name}_status')

                if index == 0:
                    if len(plugins_enabled) >= 2:
                        self.status_grid.attach(plugin, 0, 0, 1, 1)
                    else:
                        self.status_grid.attach(plugin, 0, 0, 2, 1)

                if index == 1 and len(plugins_enabled) >= 2:
                    self.status_grid.attach(plugin, 1, 0, 1, 1)

                if index == 2:
                    if len(plugins_enabled) == 3:
                        self.status_grid.attach(plugin, 0, 1, 2, 1)
                    else:
                        self.status_grid.attach(plugin, 0, 1, 1, 1)

                if index == 3 and len(plugins_enabled) == 4:
                    self.status_grid.attach(plugin, 1, 1, 1, 1)

                plugin.show()

    @staticmethod
    def on_query_confirmations_tooltip(
            tree_view: Gtk.TreeView,
            x: int,
            y: int,
            tip: bool,
            tooltip: Gtk.Tooltip,
    ) -> bool:
        context = tree_view.get_tooltip_context(x, y, tip)

        if context[0]:
            if context.model.iter_depth(context.iter) != 0:
                return False

            tooltip.set_text('Id:{}\nKey:{}'.format(
                context.model.get_value(context.iter, 1),
                context.model.get_value(context.iter, 2),
            ))

            return True

        return False

    def on_validate_confirmations(
            self,
            button: Gtk.Button,
            action: str,
            model: Union[Gtk.TreeModel, Gtk.TreeSelection]) -> None:
        if isinstance(model, Gtk.TreeModel):
            finalize_dialog = confirmation.FinalizeDialog(
                self,
                self.application,
                action,
                model,
                False
            )
        else:
            finalize_dialog = confirmation.FinalizeDialog(
                self,
                self.application,
                action,
                *model.get_selected()
            )

        finalize_dialog.show()

    @staticmethod
    def on_tree_selection_changed(selection: Gtk.TreeSelection) -> None:
        model, iter_ = selection.get_selected()

        if iter_:
            parent = model.iter_parent(iter_)

            if parent:
                selection.select_iter(parent)

    def set_status(
            self,
            module: str,
            module_data: Optional[core.utils.ModuleData] = None,
            *,
            display: Optional[str] = None,
            status: Optional[str] = None,
            info: Optional[str] = None,
            error: Optional[str] = None,
            level: Optional[Tuple[int, int]] = None,
    ) -> None:
        _status = getattr(self, f'{module}_status')

        if not module_data:
            module_data = core.utils.ModuleData(display, status, info, error, level)

        if module_data.display:
            # log.debug(f"display data: {module_data.display}")
            _status.set_display(module_data.display)
        else:
            _status.unset_display()

        if module_data.status:
            # log.debug(f"status data: {module_data.status}")
            _status.set_status(module_data.status)

        if module_data.info:
            # log.debug(f"info data: {module_data.info}")
            _status.set_info(module_data.info)

        if module_data.error:
            log.error(module_data.error)
            _status.set_error(module_data.error)

        if module_data.level:
            _status.set_level(*module_data.level)

    def set_warning(self, message: str) -> None:
        self._warning_label.set_markup(utils.markup(message, color='white', background='red'))

    def unset_warning(self) -> None:
        self._warning_label.set_text("")

    def get_play_event(self, module: str) -> asyncio.Event:
        _status = getattr(self, f'{module}_status')
        return _status.play_event
