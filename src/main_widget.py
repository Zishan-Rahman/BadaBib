# main_widget.py
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


import gi
gi.require_version("Gtk", "3.0")

from gi.repository import Gtk, Gdk, GLib

from os.path import split

from time import sleep

from threading import Thread

from .config_manager import add_to_recent
from .config_manager import remove_from_recent
from .config_manager import get_editor_layout
from .config_manager import get_parse_on_fly
from .config_manager import SourceViewStatus
from .config_manager import get_new_file_name
from .config_manager import get_default_entrytype

from .layout_manager import string_to_layout

from .bibitem import entries_equal

from .forms import SourceView

from .change import Change

from .editor import Editor

from .watcher import Watcher

from .itemlist import Itemlist
from .itemlist import ItemlistNotebook
from .itemlist import ItemlistToolbar
from .itemlist import ItemlistSearchBar

from .dialogs import FilterPopover
from .dialogs import SortPopover
from .dialogs import SaveChanges
from .dialogs import WarningDialog
from .dialogs import SaveDialog
from .dialogs import DuplicateKeys
from .dialogs import EmptyKeys


DEFAULT_EDITOR = get_default_entrytype()


class MainWidget(Gtk.Paned):
    def __init__(self, window, store):
        Gtk.Paned.__init__(self)
        self.set_orientation(Gtk.Orientation.HORIZONTAL)

        self.window = window
        self.store = store
        self.itemlists = {}
        self.editors = {}
        self.watchers = {}
        self.copy_paste_buffer = None
        self.search_sensitive = True

        self.assemble_left_pane()
        self.assemble_right_pane()

        self.show_all()

        self.add_editor(DEFAULT_EDITOR)
        self.outer_stack.set_visible_child_name("editor")

    def assemble_left_pane(self):
        # notebook to hold itemlists, searchbar and toolbar
        self.notebook = ItemlistNotebook()
        self.notebook.connect("switch_page", self.on_switch_page)

        # Toolbar
        self.toolbar = ItemlistToolbar()
        self.toolbar.new_button.connect("clicked", self.add_item)
        self.toolbar.delete_button.connect("clicked", self.delete_item)
        self.toolbar.sort_button.connect("clicked", self.sort_itemlist)
        self.toolbar.filter_button.connect("clicked", self.filter_itemlist)
        self.toolbar.goto_button.connect("clicked", self.focus_on_current_row)
        self.toolbar.search_button.connect("clicked", self.search_itemlist)

        # Searchbar
        self.searchbar = ItemlistSearchBar()
        self.searchbar.search_entry.connect("search_changed", self.set_search_string)

        # box notebook and tool/search bar
        self.left_pane = Gtk.Box()
        self.left_pane.set_orientation(Gtk.Orientation.VERTICAL)
        self.left_pane.pack_start(self.notebook, True, True, 0)
        self.left_pane.pack_start(self.searchbar, False, False, 0)
        self.left_pane.pack_start(self.toolbar, False, False, 5)

        self.add1(self.left_pane)

    def assemble_right_pane(self):
        # editors
        self.editor_stack = Gtk.Stack()
        editor_stack_scrolled = Gtk.ScrolledWindow()
        editor_stack_scrolled.set_propagate_natural_width(True)
        editor_stack_scrolled.add(self.editor_stack)

        # source view
        self.source_view = SourceView()
        self.source_view.buffer.connect("end_user_action", self.on_source_view_modified)
        self.source_view.apply_button.connect("clicked", self.update_bibtex)
        self.source_view.form.connect("key-press-event", self.on_source_view_key_pressed)

        # stack of editors and source view
        self.outer_stack = Gtk.Stack()
        self.outer_stack.add_titled(editor_stack_scrolled, "editor", "Editor")
        self.outer_stack.add_titled(self.source_view, "source", "BibTeX")

        # switcher
        outer_stack_switcher = Gtk.StackSwitcher()
        outer_stack_switcher.set_stack(self.outer_stack)
        switcher_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        switcher_box.set_center_widget(outer_stack_switcher)

        # editors
        right_pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right_pane.pack_start(switcher_box, False, False, 5)
        right_pane.pack_end(self.outer_stack, True, True, 0)

        self.add2(right_pane)

    def show_editor(self, entrytype):
        editor = self.get_editor(entrytype)
        self.editor_stack.set_visible_child_name(entrytype)
        return editor

    def add_editor(self, entrytype):
        layout_string = get_editor_layout(entrytype)
        layout = string_to_layout(layout_string, self.window)
        editor = Editor(layout, entrytype)
        self.editor_stack.add_named(editor, entrytype)
        self.editors[entrytype] = editor
        return editor

    def update_editor(self, entrytype):
        if entrytype in self.editors:
            editor = self.editors.pop(entrytype)
            editor.destroy()
        row = self.get_current_row()
        if row:
            row.unselect()
            row.select()
        else:
            self.show_editor(DEFAULT_EDITOR)

    def get_editor(self, entrytype):
        if entrytype not in self.editors:
            editor = self.add_editor(entrytype)
        else:
            editor = self.editors[entrytype]
        return editor

    def get_current_editor(self):
        return self.editor_stack.get_visible_child()

    def add_itemlist(self, bibfile, state=None, change_buffer=None):
        itemlist = Itemlist(bibfile, state, change_buffer)
        itemlist.connect("row-selected", self.on_row_selected)
        itemlist.connect("key-press-event", self.on_itemlist_key_pressed)
        itemlist.header.close_button.connect("clicked", self.on_close_tab)

        bibfile.itemlist = itemlist
        self.itemlists[bibfile.name] = itemlist
        self.notebook.append_itemlist(itemlist)

        if len(bibfile.items) == 0:
            self.source_view.set_status(SourceViewStatus.empty, True)
            self.get_current_editor().clear()

        self.show_all()

        return itemlist

    def remove_itemlist(self, filename):
        itemlist = self.itemlists.pop(filename)
        self.store.bibfiles[filename].itemlist = None
        row = itemlist.get_selected_row()
        if row:
            self.editors[row.item.entry["ENTRYTYPE"]].clear()
        self.source_view.set_status(SourceViewStatus.empty, True)
        self.notebook.remove_page(itemlist.on_page)
        itemlist.destroy()

    def get_current_itemlist(self):
        page = self.notebook.get_current_page()
        scrolled = self.notebook.get_nth_page(page)
        return scrolled.get_child().get_child()

    def on_itemlist_key_pressed(self, _widget, event):
        if event.keyval == Gdk.KEY_Delete:
            self.delete_item()
            self.focus_on_current_row()
        if event.keyval == Gdk.KEY_Return:
            self.focus_on_current_row()

    def get_current_file(self):
        return self.get_current_itemlist().bibfile

    def get_current_row(self):
        return self.get_current_itemlist().get_selected_row()

    def get_current_item(self):
        row = self.get_current_row()
        if row:
            return row.item
        return None

    def add_item(self, _button=None, bibtex=None):
        itemlist = self.get_current_itemlist()
        item = itemlist.bibfile.append_item(bibtex)
        itemlist.add_row(item)
        itemlist.show_all()
        item.row.grab_focus()

        change = Change.Show(item)
        itemlist.change_buffer.push_change(change)

    def delete_item(self, _button=None):
        item = self.get_current_item()
        if item:
            change = Change.Hide(item)
            item.bibfile.itemlist.change_buffer.push_change(change)

    def sort_itemlist(self, button):
        itemlist = self.get_current_itemlist()
        SortPopover(button, itemlist)

    def focus_on_current_row(self, _button=None):
        row = self.get_current_row()
        if row:
            row.grab_focus()

    def filter_itemlist(self, button):
        itemlist = self.get_current_itemlist()
        FilterPopover(button, itemlist)

    def search_itemlist(self, _button=None):
        searchbar = self.searchbar
        searchbar.set_search_mode(not searchbar.get_search_mode())

    def set_search_string(self, search_entry):
        if self.search_sensitive:
            itemlist = self.get_current_itemlist()
            itemlist.search_string = search_entry.get_text()
            itemlist.invalidate_filter()

    def on_row_selected(self, _itemlist, row):
        if row:
            entrytype = row.item.entry["ENTRYTYPE"]
            editor = self.show_editor(entrytype)
            editor.show_item(row.item)

            row.item.update_bibtex()
            self.source_view.set_status(SourceViewStatus.valid)
            self.source_view.form.set_sensitive(True)
            self.source_view.form.set_text(row.item.bibtex)

    def on_close_tab(self, button=None):
        if button is None:
            itemlist = self.get_current_itemlist()
        else:
            itemlist = button.get_parent().itemlist
        self.close_file(itemlist.bibfile.name)
        if self.notebook.get_n_pages() == 0:
            self.new_file()

    def on_switch_page(self, _notebook, scrolled, _page_num):
        try:
            itemlist = scrolled.get_child().get_child()
        except AttributeError:
            return

        self.search_sensitive = False
        self.searchbar.search_entry.set_text(itemlist.search_string)
        self.search_sensitive = True
        self.searchbar.set_search_mode(len(itemlist.search_string) > 0)

        row = itemlist.get_selected_row()
        if row:
            self.on_row_selected(itemlist, row)
        else:
            self.source_view.set_status(SourceViewStatus.empty, True)
            self.get_current_editor().clear()

    def generate_key(self):
        item = self.get_current_item()
        new_key = item.bibfile.generate_key_for_item(item)
        if new_key != item.entry["ID"]:
            editor = self.get_current_editor()
            form = editor.forms["ID"]
            old_key = item.entry["ID"]
            change = Change.Edit(item, form, old_key, new_key)
            item.bibfile.itemlist.change_buffer.push_change(change)

    def on_source_view_modified(self, _buffer):
        if get_parse_on_fly():
            self.update_bibtex()
        else:
            self.source_view.set_status(SourceViewStatus.modified)

    def on_source_view_key_pressed(self, _widget, event):
        if event.state == Gdk.ModifierType.CONTROL_MASK and event.keyval == Gdk.KEY_Return:
            self.update_bibtex()
            return True
        return False

    def update_bibtex(self, _button=None):
        bibtex = self.source_view.form.get_text()
        if bibtex:
            item = self.get_current_item()
            bibfile = self.get_current_file()
            new_entry = bibfile.parse_entry(bibtex)
            old_entry = item.entry
            if new_entry:
                self.source_view.set_status(SourceViewStatus.valid)
                if not entries_equal(old_entry, new_entry):
                    change = Change.Replace(item, old_entry, new_entry)
                    item.bibfile.itemlist.change_buffer.push_change(change)
            else:
                self.source_view.set_status(SourceViewStatus.invalid)

    def add_watcher(self, window, filename):
        watcher = Watcher(window, filename)
        thread = Thread(target=watcher.watch_file)
        thread.start()
        self.watchers[filename] = watcher, thread

    def remove_watcher(self, filename):
        if filename in self.watchers:
            watcher, thread = self.watchers.pop(filename)
            watcher.stop()
            thread.join()

    def open_files(self, filenames, states=None, select_file=None):
        # make sure 'filenames' is a list
        if isinstance(filenames, str):
            filenames = [filenames]
        N = len(filenames)

        # close default empty file
        if self.notebook.contains_empty_new_file():
            self.close_file(get_new_file_name())

        # initialize empty state string list
        if not states:
            states = N * [None]

        # add loading pages and select first one
        n_pages = self.notebook.get_n_pages()
        self.notebook.add_loading_pages(N)
        self.notebook.set_current_page(n_pages)

        # open files in thread
        GLib.idle_add(self.open_files_thread, filenames, states, select_file)

    def open_files_thread(self, filenames, states, select_file):
        # read databases
        statuses = [self.store.add_file(filename) for filename in filenames]

        # remove loading pages
        self.notebook.remove_loading_pages()

        # add itemlists
        first = True
        messages = []
        for filename, status, state in zip(filenames, statuses, states):

            # file does not exist or cannot be read
            if "file_error" in status or "parse_error" in status:
                remove_from_recent(filename)
                self.window.update_recent_file_menu()
                if not self.store.bibfiles:
                    self.new_file()
                message = "Cannot read file '{}'.".format(filename)
                messages.append(message)
                continue

            # file is empty
            if "empty" in status:
                message = "No BibTeX entries found in file '{}'.".format(filename)
                messages.append(message)

            # could not create backup
            if "no_backup" in status:
                message = (
                    "Bada Bib! could not create a backup for '{}'".format(filename)
                    + "\n\n"
                    + "To fix this, try deleting or renaming any .bak-files that were not created by Bada Bib!"
                    + "\n\n"
                    + "<b>Be careful when editing this file!</b>"
                )
                messages.append(message)

            if "file_open" in status:
                # get itemlist if file is already open
                itemlist = self.itemlists[filename]
            else:
                # or add itemlist and watcher
                itemlist = self.add_itemlist(self.store.bibfiles[filename], state)
                self.add_watcher(self.window, filename)

            # select first or requested page
            if first or self.store.bibfiles[filename].name == select_file:
                self.notebook.set_current_page(itemlist.on_page)
                first = False

        # display warnings, if any
        for message in messages:
            WarningDialog(message, window=self.window)

    def new_file(self):
        bibfile = self.store.new_file()
        itemlist = self.add_itemlist(bibfile)
        self.notebook.set_current_page(itemlist.on_page)

    def reload_file(self, filename):
        itemlist = self.itemlists[filename]
        state = itemlist.state_to_string()
        page = itemlist.on_page
        n_pages = self.notebook.get_n_pages()

        self.notebook.add_loading_pages(1)
        loading_page = self.notebook.get_nth_page(n_pages)
        self.notebook.reorder_child(loading_page, page)
        self.notebook.set_current_page(page)

        self.close_file(filename, True)
        GLib.idle_add(self.open_files_thread, [filename], state, None)

        thread = Thread(target=self.move_new_tab, args=(filename, page, n_pages))
        thread.start()

    def move_new_tab(self, filename, page, n_pages):
        while True:
            if filename in self.itemlists and self.notebook.get_n_pages() == n_pages:
                break
            sleep(0.05)

        new_page = self.notebook.get_nth_page(n_pages-1)
        self.notebook.reorder_child(new_page, page)

    def declare_file_created(self, filename):
        self.store.bibfiles[filename].created = True
        self.itemlists[filename].set_unsaved(True)
        self.watchers.pop(filename)

    def confirm_close_file(self, filename):
        itemlist = self.itemlists[filename]
        if itemlist.unsaved:
            self.notebook.set_current_page(itemlist.on_page)

            dialog = SaveChanges(self.window, filename)
            response = dialog.run()
            dialog.destroy()

            if response == Gtk.ResponseType.CANCEL:
                return False
            elif response == Gtk.ResponseType.OK:
                filename = self.save_file(filename)
                if not filename:
                    return False
        return True

    def close_file(self, filename, force=False, close_app=False):
        if force:
            close = True
        else:
            close = self.confirm_close_file(filename)

        if close:
            bibfile = self.store.bibfiles[filename]
            if not bibfile.created and not close_app:
                add_to_recent(bibfile)
                self.window.update_recent_file_menu()
            self.remove_itemlist(filename)
            self.remove_watcher(filename)
            self.store.remove_file(filename)

        return close

    def close_all_files(self, close_app=False):
        files = list(self.store.bibfiles.keys())
        for file in files:
            close = self.confirm_close_file(file)
            if not close:
                return False

        for file in files:
            self.close_file(file, force=True, close_app=True)

        return True

    def save_file(self, filename=None):
        if not filename:
            itemlist = self.get_current_itemlist()
            filename = itemlist.bibfile.name
        else:
            itemlist = self.itemlists[filename]
        bibfile = itemlist.bibfile

        if itemlist.unsaved:
            if bibfile.created:
                filename = self.save_file_as()
            else:
                self.save_file_as(filename, filename)
        return filename

    def save_all_files(self):
        for filename in self.store.bibfiles:
            self.save_file(filename)

    def save_file_as(self, new_filename=None, old_filename=None):
        if not old_filename:
            itemlist = self.get_current_itemlist()
            old_filename = itemlist.bibfile.name
        else:
            itemlist = self.itemlists[old_filename]
        bibfile = itemlist.bibfile

        has_empty_keys = bibfile.has_empty_keys()
        if has_empty_keys:
            dialog = EmptyKeys(self.window, old_filename)
            response = dialog.run()
            dialog.destroy()
            if response != Gtk.ResponseType.YES:
                return None

        duplicate_keys = bibfile.get_duplicate_keys()
        if duplicate_keys:
            dialog = DuplicateKeys(self.window, old_filename, duplicate_keys)
            response = dialog.run()
            dialog.destroy()
            if response != Gtk.ResponseType.YES:
                return None

        if not new_filename:
            dialog = SaveDialog(self.window)
            dialog.set_current_name(split(bibfile.name)[1])
            response = dialog.run()
            if response == Gtk.ResponseType.ACCEPT:
                new_filename = dialog.get_filename()
                dialog.destroy()
                new_filename = new_filename.strip()
                if new_filename[-4:] != ".bib":
                    new_filename = new_filename + ".bib"
            else:
                dialog.destroy()
                return None

        if new_filename != old_filename:
            if new_filename in self.store.bibfiles:
                self.close_file(new_filename, force=True)

            if not bibfile.created:
                add_to_recent(bibfile)
                self.window.update_recent_file_menu()

            self.itemlists.pop(old_filename)
            self.store.rename_file(old_filename, new_filename)
            self.itemlists[new_filename] = itemlist
            itemlist.update_filename(new_filename)

        bibfile.created = False
        self.remove_watcher(old_filename)
        self.store.save_file(new_filename)
        self.add_watcher(self.window, new_filename)
        itemlist.set_unsaved(False)
        itemlist.change_buffer.update_saved_state()

        return new_filename
