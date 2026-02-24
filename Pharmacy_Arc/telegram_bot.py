"""Backward-compatible shim — makes telegram_bot an alias for telegram.bot.

This ensures ``from telegram_bot import X`` and ``patch("telegram_bot.X", ...)``
work identically to before the package split, because the telegram_bot module
object IS telegram.bot.
"""
import telegram.bot as _bot  # triggers full package import chain
import sys
sys.modules[__name__] = _bot
