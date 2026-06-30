#!/usr/bin/env python3
"""weightChanger: GUI utility to search and update token weights.

Tokens are looked up and updated in the SQLite store (memory/weights.db)
via db.py.  `find_weight` reads token_weights.total_weight; `set_weight`
overwrites it directly -- the same manual-override semantics as the legacy
flat-file version.

Note: `occurrences.initial_weight` rows (the per-occurrence deltas) are not
changed by set_weight.  Run `tools/dbMaintain.py rebuild-weights` afterwards
if you need the cache and the occurrence history to agree.

TODO bulk change of weights
TODO change of weights of certain abonent
"""
import os
import sqlite3
import tkinter as tk
from tkinter import messagebox

ROOT       = os.path.dirname(os.path.abspath(__file__))
WEIGHTS_DB = os.path.join(ROOT, "memory", "weights.db")

# ── token operations ──────────────────────────────────────────────────────────

def find_weight(token):
    """Return current total weight of *token*, or None if not in the store."""
    if not os.path.exists(WEIGHTS_DB):
        return None
    conn = sqlite3.connect(WEIGHTS_DB)
    try:
        row = conn.execute(
            "SELECT total_weight FROM token_weights WHERE form = ?", (token,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def set_weight(token, new_weight):
    """Overwrite total_weight for *token* in token_weights.
    Returns True when an existing row was updated, False when the token is not found."""
    if not os.path.exists(WEIGHTS_DB):
        return False
    conn = sqlite3.connect(WEIGHTS_DB)
    try:
        cur = conn.execute(
            "UPDATE token_weights SET total_weight = ? WHERE form = ?",
            (new_weight, token)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()

# ── GUI ───────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("weightChanger")
        self.resizable(False, False)
        self._current_token = None
        self._build()

    def _build(self):
        outer = tk.Frame(self, padx=14, pady=14)
        outer.pack()

        # ── search row ──────────────────────────────────────────────────────
        row_search = tk.Frame(outer)
        row_search.pack(fill="x")

        self._word_var = tk.StringVar()
        self._entry = tk.Entry(row_search, textvariable=self._word_var, width=30)
        self._entry.pack(side="left", padx=(0, 6))
        self._entry.bind("<Return>", lambda _e: self._search())
        self._entry.focus_set()

        self._btn(row_search, "Search", self._search).pack(side="left")
        self._btn(row_search, "Clear",  self._clear ).pack(side="left", padx=(6, 0))

        # ── feedback area ───────────────────────────────────────────────────
        feedback = tk.Frame(outer)
        feedback.pack(fill="x", pady=(10, 0))

        self._msg = tk.Label(feedback, text="", anchor="w")
        self._msg.pack(fill="x")

        # found sub-row (hidden until a match is found)
        self._found_row = tk.Frame(feedback)

        # "Token:" label + read-only token display (prevents ambiguity for numbers)
        tk.Label(self._found_row, text="Token:").pack(side="left")
        self._token_label = tk.Label(
            self._found_row, text="", relief="sunken",
            width=18, anchor="w", padx=4
        )
        self._token_label.pack(side="left", padx=(2, 12))

        tk.Label(self._found_row, text="Weight:").pack(side="left")
        self._weight_var = tk.StringVar()
        self._weight_entry = tk.Entry(
            self._found_row, textvariable=self._weight_var, width=10
        )
        self._weight_entry.pack(side="left", padx=(2, 8))
        self._weight_entry.bind("<Return>", lambda _e: self._change())

        self._btn(self._found_row, "Change", self._change).pack(side="left")

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _btn(parent, text, cmd):
        """Create a Button that responds to both mouse click and Enter key."""
        b = tk.Button(parent, text=text, command=cmd)
        b.bind("<Return>", lambda _e: cmd())
        return b

    # ── actions ──────────────────────────────────────────────────────────────

    def _clear(self):
        self._word_var.set("")
        self._found_row.pack_forget()
        self._msg.config(text="", fg="black")
        self._current_token = None
        self._entry.focus_set()

    def _search(self):
        token = self._word_var.get()          # preserve case; strip nothing
        if not token:
            return

        self._found_row.pack_forget()
        self._msg.config(text="", fg="black")

        weight = find_weight(token)

        if weight is None:
            self._msg.config(text="Not found", fg="red")
        else:
            self._current_token = token
            self._token_label.config(text=token)
            self._weight_var.set(str(weight))
            self._msg.config(text="Found:", fg="black")
            self._found_row.pack(anchor="w", pady=(4, 0))
            self._weight_entry.focus_set()
            self._weight_entry.selection_range(0, "end")

    def _change(self):
        raw = self._weight_var.get().strip()
        try:
            new_w = int(raw)
        except ValueError:
            messagebox.showerror("Invalid input", "Weight must be an integer.")
            return

        if set_weight(self._current_token, new_w):
            self._msg.config(
                text=f'Weight of "{self._current_token}" set to {new_w}.',
                fg="dark green",
            )
        else:
            self._msg.config(text="Token no longer in store.", fg="red")
            self._found_row.pack_forget()


if __name__ == "__main__":
    App().mainloop()
