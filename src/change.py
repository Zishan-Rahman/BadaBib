# change.py
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


from time import time

from .config_manager import get_undo_delay
from .config_manager import get_default_entrytype


UNDO_DELAY = get_undo_delay()
DEFAULT_EDITOR = get_default_entrytype()


class Change:
    class Generic:
        @property
        def main_widget(self):
            window = self.item.row.get_root()
            return window.main_widget

        @property
        def editor(self):
            entrytype = self.item.raw_field("ENTRYTYPE")
            return self.main_widget.get_editor(entrytype)

        @property
        def bibfile(self):
            return self.item.bibfile

        @property
        def source_view(self):
            return self.main_widget.source_view

    class Edit(Generic):
        def __init__(self, item, form, old_value, new_value):
            self.type = "edit"
            self.item = item
            self.form = form
            self.old_value = old_value
            self.new_value = new_value

        def apply(self, redo=False):
            self.item.update_field(self.form.field, self.new_value, True)
            self.update_display(redo)

        def revert(self):
            self.item.update_field(self.form.field, self.old_value, True)
            self.update_display(redo=True)

        def update_display(self, redo=False):
            self.item.row.update_field(self.form.field)
            self.source_view.update(self.item)
            self.form.update(self.item)
            if redo:
                self.bibfile.itemlist.unselect_all()
                self.bibfile.itemlist.select_row(self.item.row)
                self.main_widget.focus_on_current_item()

    class Show(Generic):
        def __init__(self, items):
            self.type = "show"
            self.item = items[0]
            self.form = None
            self.items = items

        def apply(self, redo=False):
            for item in self.items:
                item.deleted = False
            self.bibfile.itemlist.invalidate_filter()
            self.bibfile.itemlist.unselect_all()
            for item in self.items:
                self.bibfile.itemlist.select_row(item.row)
            self.main_widget.focus_on_current_item()

        def revert(self):
            for item in self.items:
                item.deleted = True
            self.bibfile.itemlist.invalidate_filter()
            self.bibfile.itemlist.unselect_all()
            next_row = self.bibfile.itemlist.select_next_row(self.item.row)
            if next_row:
                self.main_widget.focus_on_current_item()
            else:
                self.editor.clear()
                self.source_view.set_status("empty")

    class Hide(Show):
        def apply(self, redo=False):
            super().revert()

        def revert(self):
            super().apply()

    class Replace(Generic):
        def __init__(self, item, old_entry, new_entry):
            self.type = "replace"
            self.item = item
            self.old_entry = old_entry
            self.new_entry = new_entry
            self.form = None

        def apply(self, redo=False):
            self.item.update_entry(self.new_entry, True)
            self.item.row.update()
            self.editor.show_item(self.item)
            if redo:
                self.source_view.update(self.item)
                self.bibfile.itemlist.unselect_all()
                self.bibfile.itemlist.select_row(self.item.row)
                self.main_widget.focus_on_current_item()

        def revert(self):
            self.item.update_entry(self.old_entry, True)
            self.item.row.update()
            self.editor.show_item(self.item)
            self.source_view.update(self.item)
            self.bibfile.itemlist.unselect_all()
            self.bibfile.itemlist.select_row(self.item.row)
            self.main_widget.focus_on_current_item()


class ChangeBuffer:
    def __init__(self):
        self.buffer = [None]
        self.index = 0
        self.saved_index = 0
        self.last_save = time()

    def update_saved_state(self):
        self.saved_index = self.index

    def truncate(self):
        n = len(self.buffer) - 1 - self.index
        if self.saved_index > self.index:
            self.saved_index = -1
        for _ in range(n):
            self.buffer.pop()

    def add_change(self, change):
        self.truncate()
        self.buffer.append(change)
        self.index += 1

    def push_change(self, change):
        previous_change = self.buffer[self.index]
        if (
            previous_change
            and previous_change.type == change.type == "edit"
            and previous_change.form == change.form
            and previous_change.item == change.item
            and time() - self.last_save < UNDO_DELAY
        ):
            previous_change.new_value = change.new_value
        elif (
            previous_change
            and previous_change.type == change.type == "replace"
            and time() - self.last_save < UNDO_DELAY
        ):
            previous_change.new_entry = change.new_entry
        else:
            self.add_change(change)

        change.apply()
        self.last_save = time()
        change.bibfile.set_unsaved(True)

    def redo_change(self):
        if self.index < len(self.buffer) - 1:
            self.index += 1
            change = self.buffer[self.index]
            change.apply(redo=True)
            change.bibfile.set_unsaved(self.index != self.saved_index)
            if change.form:
                change.form.select()
                change.form.grab_focus()

    def undo_change(self):
        change = self.buffer[self.index]
        if change:
            self.index -= 1
            change.revert()
            change.bibfile.set_unsaved(self.index != self.saved_index)
            if change.form:
                change.form.select()
                change.form.grab_focus()
