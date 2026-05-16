"""
Farm Bot - Entry point.
"""
import sys
import os
import logging

# Dam bao thu muc goc nam trong sys.path (ho tro ca khi dong goi bang PyInstaller)
if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

from ui.app import App


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
