import os
import sys

# Make the bot's source root importable (bot.py imports `core.*`, `handlers.*`)
SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
