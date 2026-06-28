#!/usr/bin/env python3
"""pythonInput: a Tkinter window for entering a lot of text, with a Send button.

Pressing Send publishes the box contents to the ``input.events`` bus channel with
media ``python anonymous`` and clears the box.
"""
import tkinter as tk

import bus

MEDIA = "python anonymous"


def send(text_widget):
    text = text_widget.get("1.0", "end-1c")
    if text.strip():
        bus.publish("input.events", MEDIA, text)
    text_widget.delete("1.0", "end")


def main():
    root = tk.Tk()
    root.title("pythonInput")

    box = tk.Text(root, width=60, height=12, wrap="word")
    box.pack(padx=8, pady=8, fill="both", expand=True)

    tk.Button(root, text="Send", command=lambda: send(box)).pack(pady=(0, 8))

    box.focus_set()
    root.mainloop()


if __name__ == "__main__":
    main()
