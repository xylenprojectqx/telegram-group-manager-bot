"""
Telegram Group Manager Bot - Configuration
=============================================
Anti-spam, welcome messages, warn/ban, captcha, and more.
"""

# === TELEGRAM SETTINGS ===
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

# === ADMIN ===
# Bot owner (super admin - can't be overridden)
OWNER_ID = 123456789

# === WELCOME MESSAGE ===
# Use {name} for user's name, {group} for group title, {count} for member count
WELCOME_MESSAGE = "👋 Welcome {name} to {group}!\n\nPlease read the rules and enjoy your stay."
WELCOME_ENABLED = True

# === GOODBYE MESSAGE ===
GOODBYE_MESSAGE = "👋 {name} left the group."
GOODBYE_ENABLED = False

# === ANTI-SPAM ===
ANTISPAM_ENABLED = True
# Max messages per user in 10 seconds
SPAM_THRESHOLD = 5
# Action: "mute", "warn", "kick", "ban"
SPAM_ACTION = "mute"
# Mute duration in minutes (0 = forever until admin unmutes)
MUTE_DURATION_MINUTES = 5

# === ANTI-LINK ===
ANTILINK_ENABLED = True
# Delete messages with links from non-admins
ANTILINK_WARN = True  # Warn user when deleting

# === ANTI-FLOOD ===
# Same message repeated X times = flood
FLOOD_THRESHOLD = 3
FLOOD_ACTION = "mute"

# === CAPTCHA ===
CAPTCHA_ENABLED = True
# Time in seconds for new user to solve captcha (0 = disabled)
CAPTCHA_TIMEOUT = 60
# Action if captcha not solved: "kick", "ban", "mute"
CAPTCHA_FAIL_ACTION = "kick"

# === WARN SYSTEM ===
# Max warns before action
MAX_WARNS = 3
# Action at max warns: "kick", "ban", "mute"
WARN_ACTION = "ban"

# === WORD FILTER ===
WORDFILTER_ENABLED = False
BANNED_WORDS = [
    # Add words to filter here
    # "badword1", "badword2",
]

# === NIGHT MODE ===
# Lock group at night (only admins can send)
NIGHTMODE_ENABLED = False
NIGHTMODE_START = "23:00"  # 24h format
NIGHTMODE_END = "07:00"

# === LANGUAGE ===
DEFAULT_LANGUAGE = "en"
