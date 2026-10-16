#!/usr/bin/env python3
"""Routine: a kanban board for daily habits.

State lives in data.json next to this file. Changes made in the app are saved
immediately, and edits made to data.json while the app is open are picked up
within a couple of seconds.

A list holds habits and sublists (lists nested inside it, to any depth). Every
list can be ticked off as a whole and rolled up to hide its contents.
"""
import copy
import json
import os
import tempfile
import tkinter as tk
import uuid
from datetime import date
from tkinter import filedialog
from tkinter import font as tkfont

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data.json")
UNDO_STEPS = 200

C = {
    "bg": "#161619", "column": "#1f1f24", "surface": "#2a2a30", "hover": "#383840",
    "text": "#e8e6e1", "muted": "#9a978f", "faint": "#5c5a55", "border": "#45454d",
    "accent": "#5fbf8f", "accent_hover": "#78d3a5", "danger": "#e0705e", "placeholder": "#26262b",
    "box": "#34343b", "box_hover": "#3f3f48", "sub": "#242429",
}
COL_W = 300
CHECK_W = 52
ROLL_W = 40
INDENT = 14
POLL_MS = 1500


def today():
    return date.today().isoformat()


def new_id():
    return uuid.uuid4().hex[:12]


def new_list(title):
    return {"id": new_id(), "title": title, "done": False, "collapsed": False, "items": []}


def seed():
    def mk(title, items):
        lst = new_list(title)
        lst["items"] = [{"id": new_id(), "text": t, "done": False} for t in items]
        return lst
    return {
        "day": today(),
        "autoReset": True,
        "lists": [
            mk("Morning", ["Drink a glass of water", "Stretch 10 min", "Make the bed"]),
            mk("Day", ["Walk outside", "Read 20 pages"]),
            mk("Evening", ["Tidy up for 10 min", "No screens after 22:00", "Journal"]),
        ],
    }


def is_list(entry):
    return "items" in entry


def walk(entries, parent=None):
    """Yield (entry, parent list or None) for every list and habit, depth first."""
    for e in entries:
        yield e, parent
        if is_list(e):
            yield from walk(e["items"], e)


def normalize(s):
    """Validate state and fill in anything missing (e.g. ids on hand-edited entries)."""
    if not isinstance(s, dict) or not isinstance(s.get("lists"), list):
        raise ValueError("expected an object with a 'lists' array")
    s.setdefault("day", today())
    s.setdefault("autoReset", True)
    s.setdefault("editMode", False)
    for lst in s["lists"]:
        normalize_entry(lst, must_be_list=True)
    return s


def normalize_entry(e, must_be_list=False):
    if not isinstance(e, dict):
        raise ValueError("lists and habits must be objects")
    if must_be_list or "items" in e:
        if not isinstance(e.get("title"), str) or not isinstance(e.get("items"), list):
            raise ValueError("each list needs a 'title' and an 'items' array")
        e["collapsed"] = bool(e.get("collapsed", False))
        for child in e["items"]:
            normalize_entry(child)
    elif not isinstance(e.get("text"), str):
        raise ValueError("each habit needs a 'text'")
    e.setdefault("id", new_id())
    e["done"] = bool(e.get("done", False))


def read_file(path):
    with open(path, encoding="utf-8") as f:
        return normalize(json.load(f))


def write_file(path, state):
    # Write atomically so a crash never leaves a half-written file.
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".data-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def mtime(path):
    try:
        return os.stat(path).st_mtime_ns
    except FileNotFoundError:
        return None


def conf(widget, **kw):
    """Configure only options that actually change, so unchanged widgets aren't redrawn."""
    changed = {k: v for k, v in kw.items() if str(widget.cget(k)) != str(v)}
    if changed:
        widget.config(**changed)


def regrid(widget, master, row, column, **kw):
    """Grid a widget into master at (row, column). Returns False if it was already there."""
    info = widget.grid_info()
    if info and str(info["in"]) == str(master) and int(info["row"]) == row and int(info["column"]) == column:
        return False
    widget.grid(in_=master, row=row, column=column, **kw)
    return True


def show(widget, visible, **pack):
    """Pack or unpack a widget, leaving it alone if it's already in the wanted state."""
    if visible and not widget.winfo_manager():
        widget.pack(**pack)
    elif not visible and widget.winfo_manager():
        widget.pack_forget()


class FlatButton(tk.Label):
    """A label that behaves like a flat button (tk.Button can't be styled well on X11)."""

    def __init__(self, parent, text, command, fg=None, hover_fg=None, bg=None, hover_bg=None, **kw):
        bg = bg or parent["bg"]
        fg = fg or C["muted"]
        kw.setdefault("padx", 8)
        kw.setdefault("pady", 3)
        super().__init__(parent, text=text, fg=fg, bg=bg, cursor="hand2", **kw)
        self.bind("<Enter>", lambda e: self.config(bg=hover_bg or C["hover"], fg=hover_fg or C["text"]))
        self.bind("<Leave>", lambda e: self.config(bg=bg, fg=fg))
        self.bind("<Button-1>", lambda e: (command(), "break")[1])


class CheckBox(tk.Frame):
    """A square check area: grey with an empty box, or green with a tick."""

    def __init__(self, parent, size, mark, font, command):
        super().__init__(parent, width=size, height=size, cursor="hand2")
        self.tick = tk.Label(self, text="✔", font=font, fg=C["bg"], cursor="hand2")
        self.box = tk.Frame(self, width=mark, height=mark, cursor="hand2",
                            highlightthickness=2, highlightbackground=C["border"])
        self.done = False
        self.hover = False
        for w in (self, self.tick, self.box):
            w.bind("<Enter>", lambda e: self.set_hover(True))
            w.bind("<Leave>", lambda e: self.set_hover(False))
            w.bind("<Button-1>", lambda e: (command(), "break")[1])
        self.paint(False)

    def set_hover(self, hover):
        self.hover = hover
        self.paint()

    def paint(self, done=None):
        if done is not None:
            self.done = done
        colors = (C["accent"], C["accent_hover"]) if self.done else (C["box"], C["box_hover"])
        for w in (self, self.tick, self.box):
            conf(w, bg=colors[self.hover])
        shown, hidden = (self.tick, self.box) if self.done else (self.box, self.tick)
        if hidden.winfo_manager():
            hidden.place_forget()
        if not shown.winfo_manager():
            shown.place(relx=0.5, rely=0.5, anchor="center")


class RollBox(tk.Frame):
    """A square button showing ▼ (open) or ▶ (rolled up), sized like the check box."""

    def __init__(self, parent, width, height, font, command):
        super().__init__(parent, width=width, height=height, cursor="hand2")
        self.glyph = tk.Label(self, font=font, fg=C["muted"], cursor="hand2")
        self.glyph.place(relx=0.5, rely=0.5, anchor="center")
        self.hover = False
        for w in (self, self.glyph):
            w.bind("<Enter>", lambda e: self.set_hover(True))
            w.bind("<Leave>", lambda e: self.set_hover(False))
            w.bind("<Button-1>", lambda e: (command(), "break")[1])
        self.paint(False)

    def set_hover(self, hover):
        self.hover = hover
        self.paint()

    def paint(self, collapsed=None):
        if collapsed is not None:
            conf(self.glyph, text="▶" if collapsed else "▼")
        bg = C["box_hover"] if self.hover else C["box"]
        conf(self, bg=bg)
        conf(self.glyph, bg=bg, fg=C["text"] if self.hover else C["muted"])


class ListView:
    """What columns and sublists share: check box, roll-up arrow, title, count,
    a grid of children, and the add-habit / add-sublist footer.

    Views are kept alive across renders; update() syncs them to the state.
    """

    def __init__(self, app):
        self.app = app
        self.entry = None
        self.depth = 0
        self.title = None
        self.title_editing = None
        self.composing = "unbuilt"  # not None: None means "footer shows the add buttons"

    def build_body(self, bg, padx=0, footer_padx=0):
        self.body = tk.Frame(self.frame, bg=bg)
        self.children = tk.Frame(self.body, bg=bg)
        self.children.pack(fill="x", padx=padx)
        self.children.columnconfigure(0, weight=1)
        tk.Frame(self.children, height=2, bg=bg).grid(row=0, column=0)  # keeps empty lists droppable
        self.footer = tk.Frame(self.body, bg=bg)
        self.footer_padx = footer_padx

    def delete(self):
        lst, app = self.entry, self.app
        label = "list" if self.depth == 0 else "sublist"
        app.with_undo(f"Deleted {label} “{lst['title']}”", lambda: app.container_of(lst).remove(lst))

    def update(self, lst, depth):
        self.entry, self.depth = lst, depth
        app = self.app

        editing = app.editing == ("list", lst["id"])
        if editing != self.title_editing:
            self.title_editing = editing
            if self.title:
                self.title.destroy()
            if editing:
                self.title = app.inline_entry(self.title_slot, lst["title"], lambda v: self.entry.update(title=v),
                                              font=app.f_bold)
            else:
                self.title = tk.Label(self.title_slot, bg=self.title_slot["bg"], anchor="w", justify="left")
                # "break" so click_away doesn't see this click and close the field it just opened.
                self.title.bind("<Double-Button-1>", lambda e: (app.start_edit(("list", self.entry["id"])), "break")[1])
                app.bind_drag(self.title, self)
            self.title.pack(fill="x", expand=True)
        if not editing:
            conf(self.title, text=lst["title"], wraplength=self.title_wrap(),
                 fg=C["muted"] if lst["done"] else C["text"],
                 font=app.f_bold_strike if lst["done"] else app.f_bold)

        self.check.paint(lst["done"])
        self.arrow.paint(lst["collapsed"])
        n = len(lst["items"])
        done = sum(e["done"] for e in lst["items"])
        conf(self.count, text=f"{done}/{n}")

        if lst["collapsed"]:
            if self.body.winfo_manager():
                self.body.pack_forget()
        elif not self.body.winfo_manager():
            self.body.pack(fill="x", **self.body_pack)

        e = app.editing
        composing = e[0] if e and e[0] in ("compose", "compose-list") and e[1] == lst["id"] else None
        if composing != self.composing:
            self.composing = composing
            for w in self.footer.winfo_children():
                w.destroy()
            if composing:
                app.build_composer(self.footer, self, composing)
            else:
                row = tk.Frame(self.footer, bg=self.footer["bg"])
                row.pack(fill="x", pady=(2, 4))
                FlatButton(row, "+ Add habit", lambda: app.start_edit(("compose", self.entry["id"])),
                           pady=5).pack(side="left")
                FlatButton(row, "+ Sublist", lambda: app.start_edit(("compose-list", self.entry["id"])),
                           pady=5).pack(side="left")
        show(self.footer, app.edit_mode, fill="x", padx=self.footer_padx)
        show(self.tools, app.edit_mode, side="right", before=self.check, **self.tools_pack)
        return n, done


class ColumnView(ListView):
    """A top-level list, shown as a column on the board."""

    def __init__(self, app):
        super().__init__(app)
        self.ratio = None
        self.child_padx = 8
        self.body_pack = {}

        self.frame = tk.Frame(app.board, bg=C["column"], pady=4)
        tk.Frame(self.frame, width=COL_W, height=0, bg=C["column"]).pack()

        head = tk.Frame(self.frame, bg=C["column"], padx=8, pady=2, cursor="fleur")
        head.pack(fill="x")
        self.check = CheckBox(head, 26, 12, app.f_check_small, lambda: app.toggle(self.entry))
        self.check.pack(side="left", padx=(2, 2))
        self.arrow = RollBox(head, 26, 26, app.f_roll_small, lambda: app.toggle_collapsed(self.entry))
        self.arrow.pack(side="left", padx=(2, 4))
        self.tools = tk.Frame(head, bg=C["column"])
        self.tools_pack = {}
        FlatButton(self.tools, "✕", self.delete, padx=5, pady=0, hover_fg=C["danger"]).pack()
        FlatButton(head, "↺", lambda: (app.clear_done([self.entry]), app.commit()), padx=5, pady=0).pack(side="right")
        self.count = tk.Label(head, fg=C["muted"], bg=C["column"], font=app.f_small)
        self.count.pack(side="right", padx=4)
        self.title_slot = tk.Frame(head, bg=C["column"])
        self.title_slot.pack(side="left", fill="x", expand=True, padx=(2, 0))
        app.bind_drag(head, self)
        app.bind_drag(self.title_slot, self)

        track = tk.Frame(self.frame, bg=C["border"], height=3)
        track.pack(fill="x", padx=12, pady=(4, 6))
        self.fill = tk.Frame(track, bg=C["accent"])

        self.build_body(C["column"], footer_padx=8)

    def title_wrap(self):
        return COL_W - 170

    def update(self, lst, depth):
        n, done = super().update(lst, depth)
        ratio = done / n if n else 0
        if ratio != self.ratio:
            self.ratio = ratio
            if ratio:
                self.fill.place(relwidth=ratio, relheight=1)
            else:
                self.fill.place_forget()


class SublistView(ListView):
    """A list inside another list, shown as a card with its contents indented below."""

    def __init__(self, app):
        super().__init__(app)
        self.child_padx = (0, 6)
        self.body_pack = {"pady": (0, 4)}

        self.frame = tk.Frame(app.board, bg=C["sub"])
        head = tk.Frame(self.frame, bg=C["surface"], cursor="fleur")
        head.pack(fill="x")
        self.check = CheckBox(head, CHECK_W, 24, app.f_check, lambda: app.toggle(self.entry))
        self.check.pack(side="left", fill="y")
        self.arrow = RollBox(head, ROLL_W, CHECK_W, app.f_roll, lambda: app.toggle_collapsed(self.entry))
        self.arrow.pack(side="left", fill="y", padx=(2, 0))
        self.tools = tk.Frame(head, bg=C["surface"])
        self.tools_pack = {"anchor": "n", "padx": (0, 6), "pady": 10}
        FlatButton(self.tools, "✕", self.delete, fg=C["faint"], hover_fg=C["danger"], padx=3, pady=0).pack()
        self.count = tk.Label(head, fg=C["muted"], bg=C["surface"], font=app.f_small)
        self.count.pack(side="right", anchor="n", padx=4, pady=12)
        self.title_slot = tk.Frame(head, bg=C["surface"])
        self.title_slot.pack(side="left", fill="x", expand=True, padx=(10, 0), pady=12)
        app.bind_drag(head, self)
        app.bind_drag(self.title_slot, self)

        self.build_body(C["sub"], padx=(INDENT, 0), footer_padx=(INDENT - 8, 0))

    def title_wrap(self):
        return COL_W - 150 - ROLL_W - (self.depth - 1) * (INDENT + 6)


class CardView:
    """Widgets for one habit card. Kept alive across renders, even when moved between lists."""

    def __init__(self, app):
        self.app = app
        self.entry = None
        self.depth = 1
        self.editing = None
        self.text = None
        self.body = []

        self.frame = tk.Frame(app.board, bg=C["surface"], cursor="fleur")
        # The whole left edge of the card is the check box.
        self.check = CheckBox(self.frame, CHECK_W, 24, app.f_check, lambda: app.toggle(self.entry))
        self.check.pack(side="left", fill="y")
        self.tools = tk.Frame(self.frame, bg=C["surface"])
        FlatButton(self.tools, "✎", lambda: app.start_edit(("item", self.entry["id"])),
                   fg=C["faint"], padx=3, pady=0).pack(side="left")
        FlatButton(self.tools, "✕", self.delete, fg=C["faint"], hover_fg=C["danger"], padx=3, pady=0).pack(side="left")
        app.bind_drag(self.frame, self)

    def delete(self):
        item, app = self.entry, self.app
        app.with_undo("Deleted habit", lambda: app.container_of(item).remove(item))

    def update(self, item, depth):
        self.entry, self.depth = item, depth
        app = self.app
        editing = app.editing == ("item", item["id"])
        if editing != self.editing:
            self.editing = editing
            for w in self.body:
                w.destroy()
            if editing:
                entry = app.inline_entry(self.frame, item["text"], lambda v: self.entry.update(text=v))
                entry.pack(side="left", fill="x", expand=True, padx=(12, 6), pady=10)
                self.body, self.text = [entry], None
            else:
                self.text = tk.Label(self.frame, bg=C["surface"], anchor="w", justify="left")
                self.text.pack(side="left", fill="x", expand=True, padx=(12, 0), pady=12)
                self.text.bind("<Double-Button-1>", lambda e: (app.start_edit(("item", self.entry["id"])), "break")[1])
                app.bind_drag(self.text, self)
                self.body = [self.text]
        show(self.tools, app.edit_mode, side="right", anchor="n", padx=(0, 6), pady=10, before=self.check)
        done = item["done"]
        if self.text is not None:
            conf(self.text, text=item["text"], wraplength=COL_W - 140 - (depth - 1) * (INDENT + 6),
                 fg=C["muted"] if done else C["text"], font=app.f_strike if done else app.f_text)
        self.check.paint(done)


class NewListView:
    """The "+ New list" button at the end of the board, which turns into a form."""

    def __init__(self, app):
        self.app = app
        self.editing = None
        self.body = None
        self.frame = tk.Frame(app.board, bg=C["bg"])
        tk.Frame(self.frame, width=COL_W, height=0, bg=C["bg"]).pack()

    def update(self):
        app = self.app
        editing = app.editing == ("new-list",)
        if editing == self.editing:
            return
        self.editing = editing
        if self.body:
            self.body.destroy()
        if editing:
            self.body = tk.Frame(self.frame, bg=C["column"], padx=8, pady=8)
            app.inline_entry(self.body, "", lambda v: app.state["lists"].append(new_list(v))).pack(fill="x")
            row = tk.Frame(self.body, bg=C["column"])
            row.pack(fill="x", pady=(6, 0))
            app.form_buttons(row, "Add list")
        else:
            self.body = FlatButton(self.frame, "+ New list (Ctrl+N)", lambda: app.start_edit(("new-list",)),
                                   bg=C["column"], anchor="w", padx=12, pady=8)
        self.body.pack(fill="x")


class App:
    def __init__(self, root):
        self.root = root
        self.state = None
        self.mtime = None
        # ("item", id) | ("list", id) | ("compose", list_id) | ("compose-list", list_id) | ("new-list",)
        self.editing = None
        self.finish_edit = None  # commits whatever is being edited
        self.focus_pending = None
        self.press = None        # pointer-down / drag in progress
        self.undo_stack = []  # (message, state before the change), newest last
        self.redo_stack = []  # (message, state after the change), newest last
        self.toast_job = None
        self.warned_mtime = None
        self.views = {}          # entry id -> ColumnView | SublistView | CardView
        self.containers = []     # expanded lists, outermost first, for drag and drop
        self.top = []            # (list, ColumnView) in board order

        base = tkfont.nametofont("TkDefaultFont")
        base.configure(size=11)
        self.f_text = base
        self.f_bold = base.copy()
        self.f_bold.configure(weight="bold")
        self.f_bold_strike = base.copy()
        self.f_bold_strike.configure(weight="bold", overstrike=1)
        self.f_title = base.copy()
        self.f_title.configure(size=15, weight="bold")
        self.f_strike = base.copy()
        self.f_strike.configure(overstrike=1)
        self.f_check = base.copy()
        self.f_check.configure(size=20)
        self.f_check_small = base.copy()
        self.f_check_small.configure(size=11)
        self.f_roll = base.copy()
        self.f_roll.configure(size=14)
        self.f_roll_small = base.copy()
        self.f_roll_small.configure(size=10)
        self.f_small = base.copy()
        self.f_small.configure(size=9)

        root.title("Routine")
        root.geometry("1000x640")
        root.minsize(420, 300)
        root.configure(bg=C["bg"])

        self.build_chrome()
        self.load()
        self.snapshot = copy.deepcopy(self.state)  # the state as last committed

        root.bind_all("<Control-z>", lambda e: self.undo())
        root.bind_all("<Control-Z>", lambda e: self.redo())  # Ctrl+Shift+Z
        root.bind_all("<Control-y>", lambda e: self.redo())
        root.bind_all("<Control-e>", lambda e: self.toggle_edit_mode())
        root.bind_all("<Control-n>", lambda e: self.add_list_shortcut())
        root.bind_all("<Button-1>", self.click_away, add="+")
        root.bind_all("<B1-Motion>", self.drag_motion, add="+")
        root.bind_all("<ButtonRelease-1>", self.drag_release, add="+")
        for seq in ("<Button-4>", "<Button-5>", "<Shift-Button-4>", "<Shift-Button-5>", "<MouseWheel>"):
            root.bind_all(seq, self.wheel)

        self.check_day()
        self.render()
        root.after(POLL_MS, self.poll)
        root.after(60_000, self.tick)

    # ---------- persistence ----------

    def load(self):
        if mtime(DATA) is None:
            self.state = normalize(seed())
            self.save()
            return
        try:
            self.state = read_file(DATA)
            self.mtime = mtime(DATA)
        except (ValueError, OSError) as e:
            # Never overwrite a file we couldn't read: that's the user's data.
            raise SystemExit(f"Could not read {DATA}: {e}\nFix or move the file and start again.")

    def save(self):
        write_file(DATA, self.state)
        self.mtime = mtime(DATA)

    def commit(self, message=None):
        self.record(message)
        self.save()
        self.render()

    def record(self, message=None):
        """Make the change since the last commit an undo step (if anything changed)."""
        def undoable(state):  # the date and edit mode aren't part of the board
            return {k: v for k, v in state.items() if k not in ("day", "editMode")}
        if undoable(self.state) != undoable(self.snapshot):
            self.undo_stack = (self.undo_stack + [(message, self.snapshot)])[-UNDO_STEPS:]
            self.redo_stack = []  # a new change makes the undone steps unreachable
        self.snapshot = copy.deepcopy(self.state)

    def poll(self):
        """Reload when data.json was changed by something else (an editor, Claude, git)."""
        m = mtime(DATA)
        if m != self.mtime and not self.busy():
            if m is None:
                self.save()
            else:
                try:
                    self.state = read_file(DATA)
                    self.mtime = m
                    self.record("Change to data.json")
                    self.render()
                except (ValueError, OSError) as e:
                    if self.warned_mtime != m:
                        self.warned_mtime = m
                        self.toast(f"data.json changed but can't be read ({e}); keeping what's shown")
        self.root.after(POLL_MS, self.poll)

    def busy(self):
        return self.editing is not None or (self.press is not None and self.press["active"])

    def tick(self):
        self.check_day()
        self.root.after(60_000, self.tick)

    def check_day(self):
        if self.state["day"] != today():
            if self.state["autoReset"]:
                self.clear_done(self.state["lists"])
            self.state["day"] = today()
            self.commit()
        self.date_label.config(text=date.today().strftime("%A %-d %B"))

    # ---------- state helpers ----------

    def container_of(self, entry):
        """The array holding entry: a list's items, or the board's top-level lists."""
        for e, parent in walk(self.state["lists"]):
            if e is entry:
                return parent["items"] if parent else self.state["lists"]
        raise ValueError("entry not in state")

    @staticmethod
    def clear_done(entries):
        """Untick these lists/habits and everything inside them, and unroll the lists."""
        for e, _ in walk(entries):
            e["done"] = False
            if is_list(e):
                e["collapsed"] = False

    def with_undo(self, message, fn):
        """Make a change that deserves a toast with an Undo button (e.g. deleting)."""
        fn()
        self.commit(message)
        self.toast(message, "Undo (Ctrl+Z)", self.undo)

    def undo(self):
        if not self.undo_stack or self.busy():
            return
        message, state = self.undo_stack.pop()
        self.redo_stack.append((message, self.snapshot))
        self.restore(state)
        self.toast(f"Undone: {message}" if message else "Undone", "Redo (Ctrl+Shift+Z)", self.redo)

    def redo(self):
        if not self.redo_stack or self.busy():
            return
        message, state = self.redo_stack.pop()
        self.undo_stack.append((message, self.snapshot))
        self.restore(state)
        self.toast(f"Redone: {message}" if message else "Redone", "Undo (Ctrl+Z)", self.undo)

    def restore(self, state):
        """Show a state from the undo/redo stacks, without recording it as a new step."""
        state = copy.deepcopy(state)
        state["day"] = today()
        state["editMode"] = self.state["editMode"]
        self.state = state
        self.snapshot = copy.deepcopy(state)
        self.save()
        self.render()

    def parent_of(self, entry):
        return next(parent for e, parent in walk(self.state["lists"]) if e is entry)

    def toggle(self, entry):
        entry["done"] = not entry["done"]
        if entry["done"]:
            self.complete(entry)
        elif is_list(entry):
            entry["collapsed"] = False  # unticking a list opens it again
        self.commit()

    def complete(self, entry):
        """Something was just ticked: a list rolls up, and if that was the last open
        item in its parent list, the parent is ticked (if it wasn't already) and rolls up too."""
        if is_list(entry):
            entry["collapsed"] = True
        parent = self.parent_of(entry)
        if parent and all(e["done"] for e in parent["items"]):
            parent["done"] = True
            self.complete(parent)

    def toggle_collapsed(self, lst):
        lst["collapsed"] = not lst["collapsed"]
        self.commit()

    # ---------- chrome: header, scrollable board, toast ----------

    def build_chrome(self):
        head = tk.Frame(self.root, bg=C["bg"], padx=16, pady=10)
        head.pack(fill="x")
        tk.Label(head, text="Routine", font=self.f_title, fg=C["text"], bg=C["bg"]).pack(side="left")
        self.date_label = tk.Label(head, fg=C["muted"], bg=C["bg"], font=self.f_small)
        self.date_label.pack(side="left", padx=(10, 0), pady=(4, 0))

        btn = dict(bg=C["surface"], fg=C["text"], padx=10, pady=4)
        FlatButton(head, "Import…", self.import_file, **btn).pack(side="right", padx=(6, 0))
        FlatButton(head, "Export…", self.export_file, **btn).pack(side="right", padx=(6, 0))
        FlatButton(head, "Reset all", lambda: self.with_undo(
            "Cleared all done marks", lambda: self.clear_done(self.state["lists"])), **btn).pack(side="right", padx=(6, 0))
        self.auto_btn = FlatButton(head, "", self.toggle_auto)
        self.auto_btn.pack(side="right", padx=(0, 6))
        self.edit_btn = FlatButton(head, "", self.toggle_edit_mode)
        self.edit_btn.pack(side="right", padx=(0, 6))

        wrap = tk.Frame(self.root, bg=C["bg"])
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=C["bg"], highlightthickness=0)
        sb = dict(bg=C["surface"], troughcolor=C["bg"], activebackground=C["hover"],
                  highlightthickness=0, bd=0, width=10)
        xs = tk.Scrollbar(wrap, orient="horizontal", command=self.canvas.xview, **sb)
        ys = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview, **sb)
        self.canvas.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
        xs.pack(side="bottom", fill="x")
        ys.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.board = tk.Frame(self.canvas, bg=C["bg"], padx=16, pady=4)
        self.canvas.create_window(0, 0, window=self.board, anchor="nw")
        self.board.bind("<Configure>", lambda e: self.fit_scroll())
        self.new_list = NewListView(self)

        self.help = tk.Label(self.root, fg=C["faint"], bg=C["bg"], font=self.f_small, anchor="w", padx=16, pady=4)
        self.help.pack(fill="x")

        self.toast_frame = tk.Frame(self.root, bg=C["text"], padx=12, pady=6)
        self.toast_label = tk.Label(self.toast_frame, fg=C["bg"], bg=C["text"])
        self.toast_label.pack(side="left")
        self.toast_command = None
        self.toast_action = FlatButton(self.toast_frame, "", lambda: self.toast_command(), fg=C["bg"],
                                       hover_fg=C["bg"], bg=C["text"], hover_bg=C["muted"], font=self.f_bold)

        # Opens up where a dragged entry would land, pushing its neighbours apart.
        self.gap = tk.Frame(self.board, bg=C["placeholder"], highlightthickness=1,
                            highlightbackground=C["accent"])

    @property
    def edit_mode(self):
        return self.state["editMode"]

    def toggle_edit_mode(self):
        if self.finish_edit:
            self.finish_edit(True)
        self.editing = None
        self.state["editMode"] = not self.state["editMode"]
        self.commit()

    def add_list_shortcut(self):
        """Ctrl+N: open the new-list form, switching edit mode on if needed."""
        if self.finish_edit:
            self.finish_edit(True)
        self.state["editMode"] = True
        self.start_edit(("new-list",))
        self.root.update_idletasks()
        self.canvas.xview_moveto(1.0)  # the form sits after the last column

    def toggle_auto(self):
        self.state["autoReset"] = not self.state["autoReset"]
        self.state["day"] = today()
        self.commit()

    def toast(self, message, action_label=None, action=None):
        self.toast_label.config(text=message)
        if self.toast_action:
            self.toast_action.destroy()
            self.toast_command = None
        self.toast_action = FlatButton(self.toast_frame, "", lambda: self.toast_command(), fg=C["bg"],
                                       hover_fg=C["bg"], bg=C["text"], hover_bg=C["muted"], font=self.f_bold)
        if action:
            self.toast_action = FlatButton(self.toast_frame, action_label, action, fg=C["bg"], hover_fg=C["bg"],
                                           bg=C["text"], hover_bg=C["muted"], font=self.f_bold)
            self.toast_action.pack(side="left", padx=(12, 0))
        self.toast_frame.place(relx=0.5, rely=1.0, anchor="s", y=-28)
        self.toast_frame.lift()
        if self.toast_job:
            self.root.after_cancel(self.toast_job)
        self.toast_job = self.root.after(6000, self.hide_toast)

    def hide_toast(self):
        self.toast_frame.place_forget()

    def fit_scroll(self):
        """Update the scrollable area. Tk lets a canvas scroll even when its content fits,
        which slides the board sideways and leaves a blank strip; snap back if so."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        if self.canvas.xview() == (0.0, 1.0):
            self.canvas.xview_moveto(0)
        if self.canvas.yview() == (0.0, 1.0):
            self.canvas.yview_moveto(0)

    def scrollable(self, horizontal):
        """Whether the board is bigger than the window in that direction."""
        return (self.canvas.xview() if horizontal else self.canvas.yview()) != (0.0, 1.0)

    def wheel(self, e):
        horizontal = e.state & 0x1  # Shift
        step = -1 if (e.num == 4 or getattr(e, "delta", 0) > 0) else 1
        if horizontal:
            if self.scrollable(True):
                self.canvas.xview_scroll(step * 3, "units")
        elif self.scrollable(False):
            self.canvas.yview_scroll(step * 3, "units")

    # ---------- rendering ----------
    #
    # Widgets are kept between renders and reconciled against the state by id, so
    # only what actually changed is created, destroyed or reconfigured. Rebuilding
    # the board from scratch makes the whole window flicker.
    #
    # Entries sit in even grid rows (columns, on the board) so the drop gap shown
    # while dragging can slot into the odd one between them without moving anything.
    #
    # Every view's frame is a child of the board and is gridded *into* its list's
    # children area, so moving an entry anywhere just re-grids it. Because they're
    # all siblings, a list's frame must stay stacked beneath its contents: whenever
    # a view is (re)placed it's raised, and so is everything inside it.

    def render(self):
        if self.press and self.press["active"]:
            return
        self.seen = set()
        self.containers = []
        self.top = []
        for ci, lst in enumerate(self.state["lists"]):
            col = self.view_for(lst, ColumnView)
            col.update(lst, 0)
            raised = self.place(col, self.board, 0, 2 * ci + 2, False, sticky="n", padx=(0, 12))
            self.top.append((lst, col))
            self.render_children(col, True, raised)
        for key in [k for k in self.views if k not in self.seen]:
            self.views.pop(key).frame.destroy()
        if self.edit_mode:
            regrid(self.new_list.frame, self.board, 0, 2 * len(self.state["lists"]) + 2, sticky="n")
            self.new_list.update()
        elif self.new_list.frame.winfo_manager():
            self.new_list.frame.grid_forget()

        conf(self.auto_btn, text=("☑" if self.state["autoReset"] else "☐") + "  Auto-reset each day")
        conf(self.edit_btn, text=("☑" if self.edit_mode else "☐") + "  Edit mode (Ctrl+E)")
        conf(self.help, text="Drag to move · drop a list into another to nest it, or onto the header row to "
                             "un-nest · double-click to rename · Ctrl+E leaves edit mode · Ctrl+Z undoes, Ctrl+Shift+Z redoes"
             if self.edit_mode else
             "Click a box to tick · ▾ rolls up · drag to move · Ctrl+E (or ☐ Edit mode) to add, rename or delete"
             " · Ctrl+Z undoes")
        if self.focus_pending:
            self.root.after_idle(self.focus_pending)
            self.focus_pending = None

    def render_children(self, view, visible, raised):
        lst = view.entry
        shown = visible and not lst["collapsed"]
        if shown:
            container = {"owner": lst, "view": view, "children": []}
            self.containers.append(container)
        for ri, e in enumerate(lst["items"]):
            child = self.view_for(e, SublistView if is_list(e) else CardView)
            child.update(e, view.depth + 1)
            child_raised = False
            if shown:
                child_raised = self.place(child, view.children, 2 * ri + 2, 0, raised,
                                          sticky="ew", padx=view.child_padx, pady=3)
                container["children"].append((e, child.frame))
            elif child.frame.winfo_manager():
                child.frame.grid_forget()  # inside a rolled-up list
            if is_list(e):
                self.render_children(child, shown, child_raised)

    def view_for(self, entry, cls):
        self.seen.add(entry["id"])
        view = self.views.get(entry["id"])
        if type(view) is not cls:  # new, or e.g. a column that became a sublist
            if view:
                view.frame.destroy()
            view = self.views[entry["id"]] = cls(self)
        return view

    def place(self, view, master, row, column, force_raise, **kw):
        moved = regrid(view.frame, master, row, column, **kw)
        if moved or force_raise:
            view.frame.lift()
            return True
        return False

    def build_composer(self, parent, view, mode):
        habit = mode == "compose"
        box = tk.Frame(parent, bg=parent["bg"], pady=4)
        box.pack(fill="x")
        if not habit:
            tk.Label(box, text="New sublist", fg=C["muted"], bg=parent["bg"], font=self.f_small,
                     anchor="w").pack(fill="x")

        def add(v):
            view.entry["items"].append({"id": new_id(), "text": v, "done": False} if habit else new_list(v))
        # Enter adds a habit and keeps the composer open for the next one.
        self.inline_entry(box, "", add, keep_open=habit).pack(fill="x")
        row = tk.Frame(box, bg=parent["bg"])
        row.pack(fill="x", pady=(6, 4))
        self.form_buttons(row, "Add" if habit else "Add sublist")

    def form_buttons(self, row, label):
        FlatButton(row, label, lambda: self.finish_edit(True), bg=C["accent"], fg=C["bg"],
                   hover_bg=C["accent"], hover_fg=C["bg"], font=self.f_bold).pack(side="left")
        FlatButton(row, "Cancel", lambda: self.finish_edit(False)).pack(side="left", padx=(6, 0))

    # ---------- editing ----------

    def start_edit(self, what):
        if not self.edit_mode:
            return
        if self.finish_edit:
            self.finish_edit(True)
        self.editing = what
        self.render()

    def inline_entry(self, parent, value, on_save, keep_open=False, font=None):
        """Text field that saves on Enter / clicking elsewhere and cancels on Escape.

        Shift+Enter starts a new line; the field grows to fit its text.
        """
        entry = tk.Text(parent, bg=C["surface"], fg=C["text"], insertbackground=C["text"],
                        relief="flat", highlightthickness=1, highlightcolor=C["accent"],
                        highlightbackground=C["accent"], font=font or self.f_text,
                        width=1, height=1, wrap="word", padx=2, pady=2)
        entry.insert("1.0", value)
        done = False

        def fit(e=None):
            n = entry.count("1.0", "end", "displaylines")
            n = max(1, (n[0] if isinstance(n, tuple) else n) or 1)
            if int(entry["height"]) != n:
                entry.configure(height=n)

        def select_all():
            entry.tag_add("sel", "1.0", "end-1c")
            entry.mark_set("insert", "end-1c")

        def finish(keep, stay_open=False):
            nonlocal done
            if done:
                return "break"
            v = entry.get("1.0", "end-1c").strip()
            if keep and v:
                on_save(v)
            if stay_open:
                entry.delete("1.0", "end")
                fit()
            else:
                done = True
                self.editing = None
                self.finish_edit = None
            self.commit()
            return "break"

        def newline():
            entry.insert("insert", "\n")
            entry.see("insert")
            return "break"

        entry.bind("<Return>", lambda e: finish(True, stay_open=keep_open))
        entry.bind("<KP_Enter>", lambda e: finish(True, stay_open=keep_open))
        entry.bind("<Shift-Return>", lambda e: newline())
        entry.bind("<Shift-KP_Enter>", lambda e: newline())
        entry.bind("<Escape>", lambda e: finish(False))
        entry.bind("<Tab>", lambda e: (entry.tk_focusNext().focus_set(), "break")[1])
        entry.bind("<Control-a>", lambda e: (select_all(), "break")[1])
        entry.bind("<KeyRelease>", fit, add="+")
        entry.bind("<Configure>", fit, add="+")
        self.finish_edit = finish

        def focus():
            if entry.winfo_exists():
                entry.focus_set()
                select_all()
                fit()
        self.focus_pending = focus
        return entry

    def click_away(self, e):
        """Clicking anywhere outside the field being edited saves it."""
        if self.finish_edit and not isinstance(e.widget, tk.Text):
            self.finish_edit(True)

    # ---------- drag and drop ----------

    def bind_drag(self, widget, view):
        # Motion and release are bound globally (in __init__): the dragged widget is
        # taken out of the layout mid-drag, so it stops receiving pointer events.
        widget.bind("<ButtonPress-1>", lambda e: self.drag_press(e, view))

    def drag_press(self, e, view):
        self.press = {"view": view, "source": view.frame, "x": e.x_root, "y": e.y_root, "active": False}

    def drag_motion(self, e):
        p = self.press
        if not p:
            return
        if not p["active"]:
            if abs(e.x_root - p["x"]) + abs(e.y_root - p["y"]) < 6 or not p["source"].winfo_exists():
                return
            p["active"] = True
            obj = p["obj"] = p["view"].entry
            ghost = tk.Toplevel(self.root, bg=C["accent"], padx=1, pady=1)
            ghost.overrideredirect(True)
            try:
                ghost.attributes("-alpha", 0.92)
            except tk.TclError:
                pass
            tk.Label(ghost, text=obj["title"] if is_list(obj) else obj["text"], bg=C["hover"], fg=C["text"],
                     anchor="w", justify="left", font=self.f_bold if is_list(obj) else self.f_text,
                     wraplength=COL_W - 60, padx=12, pady=8).pack(fill="both")
            p["ghost"] = ghost
            # Lift the entry out of its list; the gap stands in for it wherever it would land.
            p["width"], p["height"] = p["source"].winfo_width(), p["source"].winfo_height()
            p["source"].grid_remove()
        # Keep the ghost off the pointer so it never hides what's underneath.
        p["ghost"].geometry(f"+{e.x_root + 14}+{e.y_root + 10}")
        self.autoscroll(e)
        self.show_gap(self.drop_target(e.x_root, e.y_root))

    def drag_release(self, e):
        p, self.press = self.press, None
        if not p or not p["active"]:
            return
        p["ghost"].destroy()
        target = self.drop_target(e.x_root, e.y_root, p)
        self.gap.grid_forget()
        if target is None:
            return self.render()  # put the entry back where it was
        obj = p["obj"]
        self.container_of(obj).remove(obj)
        dest, index, _ = target
        dest.insert(index, obj)
        self.commit()

    def drop_target(self, x, y, p=None):
        """Where a drop at screen (x, y) would land: (destination array, index, gap placement).

        Anything can be dropped into any expanded list's body; the innermost one under
        the pointer wins, and every body reaches at least a little way below its header
        so empty lists are easy to hit. A dragged list also goes into a column when it's
        anywhere over the column's middle (over the header: at the start), and beside
        it when near its left or right edge. Elsewhere, a list becomes a top-level
        column. A list can't be dropped inside itself.
        """
        p = p or self.press
        obj = p["obj"]
        banned = {e["id"] for e, _ in walk([obj])} if is_list(obj) else set()
        containers = [c for c in self.containers if c["owner"]["id"] not in banned]

        def inside(c):
            body = c["view"].body
            rx, ry = body.winfo_rootx(), body.winfo_rooty()
            reach = 90 if c["view"].depth == 0 else 30
            return rx <= x < rx + body.winfo_width() and ry <= y < ry + max(body.winfo_height(), reach)

        hits = [c for c in containers if inside(c)]  # containers are listed outermost first
        if is_list(obj):
            nested = [c for c in hits if c["view"].depth > 0]
            column = self.column_under(x, y, containers)
            if nested:
                c = nested[-1]
            elif column:
                c = column
            else:
                return self.top_level_target(x, obj, p)
        elif hits:
            c = hits[-1]
        else:
            columns = [c for c in containers if c["view"].depth == 0]
            if not columns:
                return None

            def distance(c):
                left = c["view"].frame.winfo_rootx()
                right = left + c["view"].frame.winfo_width()
                return 0 if left <= x <= right else min(abs(x - left), abs(x - right))
            c = min(columns, key=distance)

        others = [w for e, w in c["children"] if e is not obj]
        index = sum(1 for w in others if y > w.winfo_rooty() + w.winfo_height() / 2)
        if index < len(others):
            row = int(others[index].grid_info()["row"]) - 1
        elif others:
            row = int(others[-1].grid_info()["row"]) + 1
        else:
            row = 1
        view = c["view"]
        place = (view.children, row, 0, {"sticky": "ew", "padx": view.child_padx, "pady": 3},
                 0, min(p["height"], 120))
        return c["owner"]["items"], index, place

    def column_under(self, x, y, containers):
        """The expanded column whose middle (not its side edges) is under the pointer."""
        edge = 40
        for c in containers:
            if c["view"].depth:
                continue
            frame = c["view"].frame
            left, top = frame.winfo_rootx(), frame.winfo_rooty()
            bottom = max(top + frame.winfo_height(), c["view"].body.winfo_rooty() + 90)
            if left + edge <= x < left + frame.winfo_width() - edge and top <= y < bottom:
                return c
        return None

    def top_level_target(self, x, obj, p):
        cols = [v for lst, v in self.top if lst is not obj]
        index = sum(1 for v in cols if x > v.frame.winfo_rootx() + v.frame.winfo_width() / 2)
        if index < len(cols):
            column = int(cols[index].frame.grid_info()["column"]) - 1
        elif cols:
            column = int(cols[-1].frame.grid_info()["column"]) + 1
        else:
            column = 1
        # The index counts columns other than obj; obj is removed before inserting.
        # A slim bar rather than a full-width slot, so columns barely shift under the pointer.
        place = (self.board, 0, column, {"sticky": "ns", "padx": (0, 12)}, 6, 60)
        return self.state["lists"], index, place

    def show_gap(self, target):
        if target is None:
            self.gap.grid_forget()
            return
        master, row, column, opts, width, height = target[-1]
        conf(self.gap, width=width, height=height)
        if regrid(self.gap, master, row, column, **opts):
            self.gap.lift()

    def autoscroll(self, e):
        cx, cy = self.canvas.winfo_rootx(), self.canvas.winfo_rooty()
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if self.scrollable(True):
            if e.x_root < cx + 50:
                self.canvas.xview_scroll(-1, "units")
            elif e.x_root > cx + cw - 50:
                self.canvas.xview_scroll(1, "units")
        if self.scrollable(False):
            if e.y_root < cy + 30:
                self.canvas.yview_scroll(-1, "units")
            elif e.y_root > cy + ch - 30:
                self.canvas.yview_scroll(1, "units")

    # ---------- import / export ----------

    def export_file(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="Export habits",
                                            initialfile=f"routine-{today()}.json",
                                            defaultextension=".json", filetypes=[("JSON", "*.json")])
        if path:
            write_file(path, self.state)
            self.toast(f"Exported to {os.path.basename(path)}")

    def import_file(self):
        path = filedialog.askopenfilename(parent=self.root, title="Import habits",
                                          filetypes=[("JSON", "*.json"), ("All files", "*")])
        if not path:
            return
        try:
            data = read_file(path)
        except (ValueError, OSError) as e:
            return self.toast(f"Import failed: {e}")
        data["day"] = today()

        def replace():
            self.state = data
        self.with_undo(f"Imported {os.path.basename(path)}", replace)


def main():
    root = tk.Tk(className="Routine")
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
