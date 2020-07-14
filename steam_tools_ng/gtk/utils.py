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
from collections import OrderedDict
from typing import Any, Callable, List, Tuple, Optional, Union

import cairo
from gi.repository import Gtk, Gdk
from stlib import webapi

from .. import i18n, config

log = logging.getLogger(__name__)
_ = i18n.get_translation


class ClickableLabel(Gtk.EventBox):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._label = Gtk.Label(*args, **kwargs)
        self._label.set_hexpand(True)

        super().connect("enter-notify-event", self._on_enter_notify_event)
        super().connect("leave-notify-event", self._on_leave_notify_event)

        self.add(self._label)
        self._label.show()

    def _on_enter_notify_event(self, *args, **kwargs) -> None:
        hand_cursor = Gdk.Cursor.new(Gdk.CursorType.HAND2)
        self.get_window().set_cursor(hand_cursor)

    def _on_leave_notify_event(self, *args, **kwargs) -> None:
        self.get_window().set_cursor(None)

    def connect(self, signal: str, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        if signal != "clicked":
            raise NotImplementedError

        super().connect("button-press-event", callback)

    def set_text(self, *args, **kwargs) -> None:
        self._label.set_text(*args, **kwargs)

    def set_markup(self, *args, **kwargs) -> None:
        self._label.set_markup(*args, **kwargs)


class VariableButton(Gtk.Button):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        super().connect('clicked', lambda button: self.__callback())
        self._user_callback: Optional[Callable[..., Any]] = None
        self._user_args: Any = None
        self._user_kwargs: Any = None

    def __callback(self) -> None:
        if not self._user_callback:
            return

        self._user_callback(*self._user_args, **self._user_kwargs)

    def connect(self, signal: str, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        if signal != "clicked":
            raise NotImplementedError

        self._user_callback = callback
        self._user_args = args
        self._user_kwargs = kwargs


class AsyncButton(Gtk.Button):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        super().connect('clicked', lambda button: self.__callback())
        self._user_callback: Optional[Callable[..., Any]] = None
        self._user_args: Any = None
        self._user_kwargs: Any = None

    def __callback(self) -> None:
        if not self._user_callback:
            return

        task = self._user_callback(*self._user_args, **self._user_kwargs)
        asyncio.ensure_future(task)

    def connect(self, signal: str, callback: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        if signal != "clicked":
            raise NotImplementedError

        self._user_callback = callback
        self._user_args = args
        self._user_kwargs = kwargs


class SimpleTextTree(Gtk.ScrolledWindow):
    def __init__(
            self,
            elements: Tuple[str, ...],
            overlay_scrolling: bool = True,
            resizable: bool = True,
            fixed_width: int = 0,
            model: Callable[..., Gtk.TreeModel] = Gtk.TreeStore,
    ) -> None:
        super().__init__()
        self._store = model(*[str for number in range(len(elements))])
        self._view = Gtk.TreeView(model=self._store)
        self.add(self._view)

        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_overlay_scrolling(overlay_scrolling)

        renderer = Gtk.CellRendererText()

        for index, header in enumerate(elements):
            column = Gtk.TreeViewColumn(header, renderer, text=index)
            column.set_resizable(resizable)

            if fixed_width:
                column.set_fixed_width(fixed_width)

            self._view.append_column(column)

    @property
    def store(self) -> Gtk.TreeModel:
        return self._store

    @property
    def view(self) -> Gtk.TreeView:
        return self._view


class SimpleStatus(Gtk.Frame):
    def __init__(self) -> None:
        super().__init__()
        self.connect('draw', self.__do_status_draw)

        self._grid = Gtk.Grid()
        self._grid.show()
        self._grid.set_border_width(10)
        self.add(self._grid)

        self._label = Gtk.Label()
        self._label.set_halign(Gtk.Align.START)
        self._label.show()
        self._grid.attach(self._label, 0, 0, 1, 1)

        self._link_grid = Gtk.Grid()
        self._grid.attach(self._link_grid, 0, 1, 1, 1)

        self._before_link_label = Gtk.Label()
        self._link_grid.add(self._before_link_label)
        self._user_callback: Optional[Callable[..., Any]] = None
        self._link_label = ClickableLabel()
        self._link_label.connect("clicked", lambda event, button: self.__callback())
        self._link_grid.add(self._link_label)

        self._after_link_label = Gtk.Label()
        self._link_grid.add(self._after_link_label)

        self.info(_("Waiting"))
        self.set_size_request(100, 60)

    def __callback(self) -> None:
        if not self._user_callback:
            log.error("user callback is not defined!")
            return

        self._link_grid.hide()
        self._user_callback()

    @staticmethod
    def __do_status_draw(frame: Gtk.Frame, cairo_context: cairo.Context) -> None:
        allocation = frame.get_allocation()
        cairo_context.set_source_rgb(0.2, 0.2, 0.2)
        cairo_context.rectangle(0, 0, allocation.width, allocation.height)
        cairo_context.fill()

    def error(self, text: str) -> None:
        self._link_grid.hide()
        self._label.set_markup(markup(text, color='hotpink', face='monospace'))

    def info(self, text: str) -> None:
        self._link_grid.hide()
        self._label.set_markup(markup(text, color='cyan', face='monospace'))

    def append_link(
            self,
            text: str,
            callback: Callable[..., Any],
            add_before: Optional[str] = None,
            add_after: Optional[str] = None,
    ) -> None:
        self._user_callback = callback

        if add_before:
            self._before_link_label.set_markup(markup(add_before, color='cyan', face='monospace'))

        self._link_label.set_markup(markup(text, color='lightblue', face='monospace'))

        if add_after:
            self._after_link_label.set_markup(markup(add_after, color='cyan', face='monospace'))

        self._link_grid.show_all()


class Status(Gtk.Frame):
    def __init__(self, display_size: int, label_text: str) -> None:
        super().__init__()
        self._default_display_text = ' '.join(['_' for n in range(1, display_size)])
        self._gtk_settings = Gtk.Settings.get_default()

        self.set_label(label_text)
        self.set_label_align(0.02, 0.5)

        self._grid = Gtk.Grid()
        self._grid.set_border_width(5)
        self._grid.set_row_spacing(5)
        self.add(self._grid)

        self._display = ClickableLabel()
        self._display.set_markup(markup(self._default_display_text, font_size='large', font_weight='bold'))
        self._display.connect("clicked", self.__on_display_event_changed)
        self._display.set_has_tooltip(True)
        self._grid.attach(self._display, 0, 0, 1, 1)

        self._status = Gtk.Label()
        self._status.set_markup(markup(_("Loading..."), color='green', font_size='small'))
        self._grid.attach(self._status, 0, 1, 1, 1)

        self._info = Gtk.Label()
        self._grid.attach(self._info, 0, 2, 1, 1)

        self._level_bar = Gtk.LevelBar()
        self._grid.attach(self._level_bar, 0, 3, 1, 1)

        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

    def __disable_tooltip(self, event_box: Gtk.EventBox, event_status: Gtk.Label) -> None:
        event_box.set_has_tooltip(False)
        self._grid.remove(event_status)
        self._grid.attach(self._status, 0, 1, 1, 1)
        self._status.show()

    def __on_display_event_changed(self, event_box: Gtk.EventBox, event_button: Gdk.EventButton) -> None:
        if event_button.type == Gdk.EventType.BUTTON_PRESS:
            message = _("Text Copied to Clipboard")

            if self._gtk_settings.props.gtk_application_prefer_dark_theme:
                color = 'lightblue'
            else:
                color = 'blue'

            event_box.set_tooltip_text(message)

            event_status = Gtk.Label()
            self._grid.remove(self._status)
            self._grid.attach(event_status, 0, 1, 1, 1)
            event_status.show()

            event_status.set_markup(markup(message, font_size='small', color=color))
            self.clipboard.set_text(self._display.get_text(), -1)
            asyncio.get_event_loop().call_later(5, self.__disable_tooltip, event_box, event_status)

    def set_display(self, text: str) -> None:
        self._display.set_markup(markup(text, font_size='large', font_weight='bold'))

    def set_status(self, text: str) -> None:
        if self._gtk_settings.props.gtk_application_prefer_dark_theme:
            color = 'lightgreen'
        else:
            color = 'green'

        self._status.set_markup(markup(text, color=color, font_size='small'))

    def set_info(self, text: str) -> None:
        if self._gtk_settings.props.gtk_application_prefer_dark_theme:
            color = 'lightgreen'
        else:
            color = 'green'

        self._info.set_markup(markup(text, color=color, font_size='small'))

    def set_error(self, text: str) -> None:
        if self._gtk_settings.props.gtk_application_prefer_dark_theme:
            color = 'hotpink'
        else:
            color = 'red'

        self._status.set_markup(markup(text, color=color, font_size='small'))

    def set_level(self, value: int, max_value: int) -> None:
        self._level_bar.set_value(value)
        self._level_bar.set_max_value(max_value)

    def unset_display(self) -> None:
        self._display.set_markup(markup(self._default_display_text, font_size='large', font_weight='bold'))

    def unset_level(self) -> None:
        self._level_bar.set_value(0)
        self._level_bar.set_max_value(0)


class Section(Gtk.Frame):
    def __init__(self, name: str, label: str) -> None:
        super().__init__(label=label)
        self.set_label_align(0.03, 0.5)
        self.set_name(name)

        self.grid = Gtk.Grid()
        self.grid.set_name(name)
        self.grid.set_row_spacing(10)
        self.grid.set_column_spacing(10)
        self.grid.set_border_width(10)

        self.add(self.grid)

    def __item_factory(self, children: Callable[..., Gtk.Widget]) -> Any:
        # FIXME: https://github.com/python/mypy/issues/2477
        children_ = children  # type: Any

        class Item(children_):
            def __init__(self, name: str, section_name: str, label: str) -> None:
                super().__init__()

                self.label = Gtk.Label(label)
                self.label.set_name(name)
                self.label.set_halign(Gtk.Align.START)

                self.set_hexpand(True)
                self.set_name(name)
                self._section_name = section_name

            def show_all(self) -> None:
                self.label.show()
                super().show()

            def hide(self) -> None:
                self.label.hide()
                super().hide()

            def get_section_name(self) -> str:
                assert isinstance(self._section_name, str)
                return self._section_name

        return Item

    def new(
            self,
            name: str,
            label: str,
            children: Callable[..., Gtk.Widget],
            *grid_position: int,
            items: 'OrderedDict[str, str]' = None,
    ) -> Gtk.Widget:
        item = self.__item_factory(children)(name, self.get_name(), label)

        self.grid.attach(item.label, *grid_position, 1, 1)
        self.grid.attach_next_to(item, item.label, Gtk.PositionType.RIGHT, 1, 1)

        section = self.get_name()
        option = item.get_name()
        # noinspection PyUnusedLocal
        value: Union[str, bool, int]

        if option.startswith('_'):
            return item

        if isinstance(item, Gtk.ComboBoxText):
            value = config.parser.get(section, option)

            for value_ in items.values():
                item.append_text(value_)

            try:
                current_option = list(items).index(value)
            except ValueError:
                error_message = _("Please, fix your config file. Accepted values for {} are:\n{}").format(
                    option,
                    ', '.join(items.keys()),
                )
                log.exception(error_message)
                fatal_error_dialog(error_message)
                # unset active item
                current_option = -1

            item.set_active(current_option)

        if isinstance(item, Gtk.CheckButton):
            value = config.parser.getboolean(section, option)
            item.set_active(value)

        if isinstance(item, Gtk.Entry):
            value = config.parser.get(section, option)

            if value:
                item.set_text(value)

        return item

    def stackup_section(self, stack: Gtk.Stack) -> None:
        name = self.get_name()
        title = name.capitalize()
        stack.add_titled(self, name, title)


def markup(text: str, **kwargs: Any) -> str:
    markup_string = ['<span']

    for key, value in kwargs.items():
        markup_string.append(f'{key}="{value}"')

    markup_string.append(f'>{text}</span>')

    return ' '.join(markup_string)


def copy_childrens(from_model: Gtk.TreeStore, to_model: Gtk.ListStore, iter_: Gtk.TreeIter, column: int) -> None:
    childrens = from_model.iter_n_children(iter_)

    if childrens:
        for index in range(childrens):
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
    else:
        value = from_model.get_value(iter_, column)
        to_model.append([value])


def safe_confirmation_get(confirmation_: webapi.Confirmation, attribute: str) -> Tuple[str, List[str]]:
    value = getattr(confirmation_, attribute)

    if not value:
        result = _("Nothing")
    elif len(value) == 1:
        result = value[0]
    else:
        result = _("Various")

    return result, value


def remove_letters(text: str) -> str:
    new_text = []

    for char in text:
        if char.isdigit():
            new_text.append(char)

    return ''.join(new_text)


def fatal_error_dialog(error_message: str, transient_for: Optional[Gtk.Window] = None) -> None:
    log.critical(error_message)
    error_dialog = Gtk.MessageDialog(transient_for=transient_for)
    error_dialog.set_title(_("Fatal Error"))
    error_dialog.set_markup(error_message)
    error_dialog.set_position(Gtk.WindowPosition.CENTER)
    error_dialog.run()
