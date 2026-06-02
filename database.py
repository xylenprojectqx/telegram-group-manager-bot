"""
Database - JSON based storage
===============================
Stores group settings, warns, user data.
"""

import json
import os
from datetime import datetime

DB_FILE = "database.json"


def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"groups": {}, "users": {}}
    return {"groups": {}, "users": {}}


def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


# === GROUP FUNCTIONS ===

def get_group(chat_id):
    """Get group settings."""
    db = load_db()
    cid = str(chat_id)
    if cid not in db["groups"]:
        db["groups"][cid] = {
            "admins": [],
            "welcome": True,
            "antilink": True,
            "antispam": True,
            "captcha": True,
            "warns": {},
            "muted": [],
            "banned_words": [],
            "rules": "",
        }
        save_db(db)
    return db["groups"][cid]


def update_group(chat_id, key, value):
    """Update a group setting."""
    db = load_db()
    cid = str(chat_id)
    if cid not in db["groups"]:
        get_group(chat_id)
        db = load_db()
    db["groups"][cid][key] = value
    save_db(db)


# === WARN FUNCTIONS ===

def get_warns(chat_id, user_id):
    """Get warn count for user in group."""
    db = load_db()
    cid = str(chat_id)
    uid = str(user_id)
    if cid in db["groups"]:
        warns = db["groups"][cid].get("warns", {})
        return warns.get(uid, 0)
    return 0


def add_warn(chat_id, user_id):
    """Add a warn and return new count."""
    db = load_db()
    cid = str(chat_id)
    uid = str(user_id)
    if cid not in db["groups"]:
        get_group(chat_id)
        db = load_db()
    if "warns" not in db["groups"][cid]:
        db["groups"][cid]["warns"] = {}
    current = db["groups"][cid]["warns"].get(uid, 0)
    db["groups"][cid]["warns"][uid] = current + 1
    save_db(db)
    return current + 1


def reset_warns(chat_id, user_id):
    """Reset warns for a user."""
    db = load_db()
    cid = str(chat_id)
    uid = str(user_id)
    if cid in db["groups"] and "warns" in db["groups"][cid]:
        db["groups"][cid]["warns"][uid] = 0
        save_db(db)


# === STATS ===

def get_total_groups():
    db = load_db()
    return len(db["groups"])


def get_total_users():
    db = load_db()
    return len(db.get("users", {}))


def register_user(user_id):
    db = load_db()
    uid = str(user_id)
    if uid not in db.get("users", {}):
        if "users" not in db:
            db["users"] = {}
        db["users"][uid] = {"joined": datetime.now().isoformat()}
        save_db(db)
