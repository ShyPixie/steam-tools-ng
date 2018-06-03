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
import functools
import logging
from typing import Any, Dict, Optional

import aiohttp
from gi.repository import Gtk
from stlib import webapi

from . import utils
from .. import config, i18n

log = logging.getLogger(__name__)
_ = i18n.get_translation


# noinspection PyUnusedLocal
class FinalizeDialog(Gtk.Dialog):
    def __init__(
            self,
            parent_window: Gtk.Widget,
            action: str,
            model: Gtk.TreeModel,
            iter_: Gtk.TreeIter
    ) -> None:
        super().__init__(use_header_bar=True)
        self.action = action

        self.header_bar = self.get_header_bar()
        self.header_bar.set_show_close_button(False)

        self.parent_window = parent_window
        self.set_default_size(300, 90)
        self.set_title(_('Finalize Confirmation'))
        self.set_transient_for(self.parent_window)
        self.set_modal(True)
        self.set_destroy_with_parent(True)
        self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)

        self.content_area = self.get_content_area()
        self.content_area.set_orientation(Gtk.Orientation.VERTICAL)
        self.content_area.set_border_width(10)
        self.content_area.set_spacing(10)

        self.status_section = utils.new_section(_("Status"))
        self.content_area.add(self.status_section.frame)

        self.status_label = Gtk.Label()
        self.status_label.set_markup(utils.markup(_("Waiting"), color='green'))
        self.status_section.grid.attach(self.status_label, 0, 0, 1, 1)

        self.spin = Gtk.Spinner()
        self.content_area.add(self.spin)

        if not iter_:
            self.status_label.set_markup(
                utils.markup(_("You must select an item before accept/cancel"), color='red')
            )
            self.header_bar.set_show_close_button(True)
        else:
            self.data = model[iter_]

            self.give_label = Gtk.Label()
            self.give_label.set_markup(
                utils.markup(_("You are trading the following items with {}:").format(self.data[4]), color='blue')
            )
            self.content_area.add(self.give_label)

            self.grid = Gtk.Grid()
            self.content_area.add(self.grid)

            self.cell_renderer = Gtk.CellRendererText()

            self.list_store_give = Gtk.ListStore(str)
            self.tree_view_give = Gtk.TreeView(model=self.list_store_give)
            self.grid.attach(self.tree_view_give, 0, 0, 1, 1)

            self.column_give = Gtk.TreeViewColumn("You will Lost", self.cell_renderer, text=0)
            self.column_give.set_fixed_width(300)
            self.tree_view_give.append_column(self.column_give)

            self.copy_childrens(model, self.list_store_give, iter_, 3)

            self.arrow = Gtk.Image()
            self.arrow.set_from_icon_name('emblem-symbolic-link', Gtk.IconSize.DIALOG)
            self.grid.attach(self.arrow, 1, 0, 1, 1)

            self.list_store_receive = Gtk.ListStore(str)
            self.tree_view_receive = Gtk.TreeView(model=self.list_store_receive)
            self.grid.attach(self.tree_view_receive, 2, 0, 1, 1)

            self.column_receive = Gtk.TreeViewColumn("You will Receive", self.cell_renderer, text=0)
            self.column_receive.set_fixed_width(300)
            self.tree_view_receive.append_column(self.column_receive)

            self.copy_childrens(model, self.list_store_receive, iter_, 5)

            self.info_label = Gtk.Label()
            self.info_label.set_justify(Gtk.Justification.CENTER)

            self.info_label.set_markup(
                utils.markup(_("Do you really want to {} that?").format(action), font_size='larger') +
                utils.markup(_("\nIt can't be undone!"), color='red', font_weight='ultrabold')
            )

            self.content_area.add(self.info_label)

            self.yes_button = Gtk.Button(_("Yes"))
            self.yes_button.connect("clicked", self.on_yes_button_clicked)
            self.content_area.add(self.yes_button)

            self.no_button = Gtk.Button(_("No"))
            self.no_button.connect("clicked", self.on_no_button_clicked)
            self.content_area.add(self.no_button)

        self.content_area.show_all()

        self.connect('response', self.on_response)

    @staticmethod
    def on_response(dialog: Gtk.Dialog, response_id: int) -> None:
        dialog.destroy()

    def on_yes_button_clicked(self, button: Gtk.Button) -> None:
        self.spin.start()
        task = asyncio.ensure_future(finalize(self.action, self.data))
        task.add_done_callback(functools.partial(finalize_callback, dialog=self))

    def on_no_button_clicked(self, button: Gtk.Button) -> None:
        self.destroy()

    @staticmethod
    def copy_childrens(from_model, to_model, iter_, column):
        for index in range(from_model.iter_n_children(iter_)):
            children_iter = from_model.iter_nth_child(iter_, index)
            value = from_model.get_value(children_iter, column)

            if value:
                to_model.append([value])
            else:
                log.debug(
                    _("Ignoring value from %s on column %s item %s because value is empty"),
                    children_iter,
                    column,
                    index
                )


@config.Check("authenticator")
async def finalize(
        action: str,
        data: Any,
        identity_secret: Optional[config.ConfigStr] = None,
        steamid: Optional[config.ConfigInt] = None,
        deviceid: Optional[config.ConfigStr] = None,
) -> Dict[str, bool]:
    async with aiohttp.ClientSession(raise_for_status=True) as session:
        session.cookie_jar.update_cookies(config.login_cookies())
        http = webapi.Http(session, 'https://lara.click/api')

        result = await http.finalize_confirmation(
            identity_secret,
            steamid,
            deviceid,
            data[1],
            data[2],
            action,
        )

        return result


def finalize_callback(future: Any, dialog) -> None:
    log.debug("confirmation finalized. The return is %s", future.result)
    dialog.destroy()
