#!/usr/bin/env python3
"""weightChanger: GUI utility to search and update token weights in chatLog.

Tokens (words, numbers, punctuation) live at even positions inside each
space-separated pair field; weights live at odd positions.  A numeric search
term such as "1" matches only tokens whose text is "1" -- never the weight
value "1" that follows some other token.  Likewise, changing a weight rewrites
only the weight slot of matching tokens, not other tokens whose text happens to
equal the new weight value.

TODO bulk change of weights
TODO change of weights of certain abonent
"""
import os
import tkinter as tk
from tkinter import messagebox

ROOT = os.path.dirname(os.path.abspath(__file__))
CHATLOG = os.path.join(ROOT, "memory", "chatLog")

# ── chatLog I/O (mirrors writerToDatabase layout) ───────────────────────────

def _parse_pairs(field):
    parts = field.split(" ") if field else []
    pairs = []
    for i in range(0, len(parts) - 1, 2):
        pairs.append([parts[i], int(parts[i + 1])])
    return pairs


def _serialize_pairs(pairs):
    return " ".join(f"{tok} {w}" for tok, w in pairs)


def _load():
    lines = []
    if os.path.exists(CHATLOG):
        with open(CHATLOG, "r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.rstrip("\n")
                if not raw:
                    continue
                f = raw.split("\t")
                lines.append([
                    f[0],
                    _parse_pairs(f[1] if len(f) > 1 else ""),
                    _parse_pairs(f[2] if len(f) > 2 else ""),
                    _parse_pairs(f[3] if len(f) > 3 else ""),
                ])
    return lines


def _write(lines):
    os.makedirs(os.path.join(ROOT, "memory"), exist_ok=True)
    tmp = CHATLOG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for direction, media, ts, words in lines:
            fh.write("\t".join([
                direction,
                _serialize_pairs(media),
                _serialize_pairs(ts),
                _serialize_pairs(words),
            ]) + "\n")
    os.replace(tmp, CHATLOG)

# ── token operations ─────────────────────────────────────────────────────────

def find_weight(token):
    """Return current weight of *token* (exact text match at token position),
    or None if the token is not present in chatLog."""
    for _, media, ts, words in _load():
        for section in (media, ts, words):
            for tok, w in section:
                if tok == token:
                    return w
    return None


def set_weight(token, new_weight):
    """Overwrite the weight of every pair whose TOKEN equals *token*.
    Weight values of other tokens are never inspected or changed.
    Returns True when at least one occurrence was updated."""
    lines = _load()
    changed = False
    for _, media, ts, words in lines:
        for section in (media, ts, words):
            for pair in section:
                if pair[0] == token:       # match on token slot, not weight slot
                    pair[1] = new_weight
                    changed = True
    if changed:
        _write(lines)
    return changed

# ── GUI ──────────────────────────────────────────────────────────────────────

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
            self._msg.config(text="Token no longer in log.", fg="red")
            self._found_row.pack_forget()


if __name__ == "__main__":
    App().mainloop()
