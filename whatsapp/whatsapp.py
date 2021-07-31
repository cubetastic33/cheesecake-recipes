from datetime import datetime
from pathlib import Path
import html
import re
import glob
import os
import shutil
import ntpath
import json
import sqlite3
import shortuuid

INPUT_PATH = Path("whatsapp_exports")
OUTPUT_PATH = Path("wa_backup")


def mkdir(path):
    # Delete the directory if it already exists
    if path.exists():
        shutil.rmtree(path)
    os.mkdir(path)


def validate_color(color):
    return not not re.search(r"^#(?:[0-9a-fA-F]{3}){1,2}$", color)


def parse_markdown(text, test):
    # HTML escaping is handled by cheesecake for the unformatted content field
    # We only need to handle it if we're handling additional formatting
    # So if we're testing if any additional formatting is present, we don't need to escape HTML
    if not test:
        # Escape HTML
        text = html.escape(text, quote=False)
    # Italics
    text = re.sub(
        r"```(.+?)```|\b_(.+?)_",
        lambda m: f"<em>{m.group(2)}</em>" if m.group(2) else m.group(0),
        text
    )
    # Bold
    text = re.sub(
        r"(```(.+?)```|(\W|^)\*([^*]+)\*(?=\W|$))",
        lambda m: f"{m.group(3)}<strong>{m.group(4)}</strong>" if m.group(4) else m.group(0),
        text
    )
    # Strikethrough
    text = re.sub(
        r"(```(.+?)```|(\W|^)~([^~]+)~(?=\W|$))",
        lambda m: f"{m.group(3)}<del>{m.group(4)}</del>" if m.group(4) else m.group(0),
        text
    )
    # Monospace
    text = re.sub(r"```(.+?)```", r"<pre>\1</pre>", text, flags=re.DOTALL)
    # Newlines are normally handled by cheesecake for the unformatted content field
    if not test:
        # Newlines
        text = text.replace("\n", "<br>")
    return text


def backup_users(filepath, existing_users, existing_ids):
    with open(filepath, "r", encoding="UTF-8") as f:
        lines = f.readlines()

    info = {}
    if (INPUT_PATH / "info.json").exists():
        with open(INPUT_PATH / "info.json", "r", encoding="UTF-8") as f:
            info = json.load(f)

    user_regex = re.compile(r"^\d\d/\d\d/\d\d, \d\d:\d\d - ([^:]+): .+")
    # The names only have to be unique within this group, not necessarily through the whole backup
    # The names are unique because WhatsApp's export format doesn't give us unique IDs and we only
    # have their names, so we can't differentiate two people with the same name
    names = set()
    for line in lines:
        if match := user_regex.match(line):
            names.add(match.group(1))

    # For new users to be added to the database (not covered in previous chats)
    new_users = {}
    # For all users in this chat, indexed using their name
    group_users = {}

    # Iterate over all the names we've found
    for name in names:
        user_id = ""
        avatar = ""
        color = ""
        skip = False

        # User ID - preferably their phone number
        while len(user_id) == 0:
            if "users" in info and name in info["users"]:
                print(f"Found {name} in info.json")
                skip = True
                if name not in existing_users:
                    if info["users"][name]["avatar"] is None:
                        shutil.copyfile("default.svg", OUTPUT_PATH / "avatars/default.svg")
                        info["users"][name]["avatar"] = "default.svg"
                    else:
                        target = shortuuid.uuid() + os.path.splitext(info["users"][name]["avatar"])[1]
                        shutil.copyfile(INPUT_PATH / info["users"][name]["avatar"], OUTPUT_PATH / "avatars" / target)
                        info["users"][name]["avatar"] = target
                    new_users[info["users"][name]["user_id"]] = {
                        "name": name,
                        "avatar": info["users"][name]["avatar"],
                        "color": info["users"][name]["color"],
                    }
                else:
                    info["users"][name]["avatar"] = existing_users[name]["avatar"]
                group_users[name] = info["users"][name]
                existing_ids.add(info["users"][name]["user_id"])
                break
            if name in existing_users:
                # Add a space so that empty inputs don't falsify the while condition
                while response := input(f"User {name} already exists in a previously converted chat. Skip? (y/n): ").strip().lower() + " ":
                    if response == "y ":
                        # They want to skip, so we don't need to add this user to the `new_users` dictionary
                        skip = True
                        group_users[name] = existing_users[name]
                        print()
                        break
                    elif response == "n ":
                        # They want to add this as a new user
                        break
            if skip:
                # Don't ask for the phone number
                break

            user_id = input(f"Enter {name}'s phone number (Eg: 919246462754): ").strip()
            if user_id in existing_ids:
                # This phone number already belongs to someone else
                print("Error: Already exists")
                user_id = ""
        if skip:
            # Skip the rest of this iteration
            # We don't need to set skip to False here because it's reset in the next iteration
            continue
        existing_ids.add(user_id)

        # The user's avatar
        while len(avatar) == 0 or not Path(avatar).exists():
            if len(avatar) != 0:
                print(f"Error: file `{avatar}` not found")
            avatar = input(f"Enter the path to {name}'s avatar: ").strip()

        target = shortuuid.uuid() + os.path.splitext(avatar)[1]
        shutil.copyfile(avatar, OUTPUT_PATH / "avatars" / target)
        avatar = target

        # The color their name should show up in
        # Leave empty to use the default color
        color = ""
        while not validate_color(color):
            if len(color) != 0:
                print("The color must be a valid hex code (Eg: #48FF63)")
            color = input(f"Enter {name}'s name color [default]: ").strip().lower()
            if len(color) == 0:
                color = None
                break

        print()

        new_users[user_id] = {
            "name": name,
            "avatar": avatar,
            "color": color,
        }

        group_users[name] = {
            "user_id": user_id,
            "avatar": avatar,
            "color": color,
        }

    return new_users, group_users


def backup_messages(filepath, chat_id, group_users):
    messages = []
    with open(filepath, "r", encoding="UTF-8") as f:
        lines = f.readlines()

    pattern = re.compile(r"(\d\d)/(\d\d)/(\d\d), (\d\d):(\d\d) - ([^:]+): (.+)")
    # If a message doesn't match `pattern` but matches `skip_pattern` it's a system message
    skip_pattern = re.compile(r"(\d\d)/(\d\d)/(\d\d), (\d\d):(\d\d) - .+")

    skip = False

    for i, line in enumerate(lines):
        if skip:
            # If we've already handled this line in the previous iteration
            skip = False
            continue

        if match := pattern.match(line):
            # Modify this based on what date format your WhatsApp exports use
            year = int("20" + match.group(3))
            month = int(match.group(2))
            day = int(match.group(1))
            hour = int(match.group(4))
            minute = int(match.group(5))
            name = match.group(6)

            if match.group(7) == "This message was deleted" or match.group(7) == "You deleted this message":
                message_type = "redacted"
                content = ""
            else:
                message_type = "default"
                content = match.group(7)

            attachment = None
            # Image
            if match := re.match(r"(.*)(IMG-.+.jpg) \(file attached\)", content):
                attachment = Path(os.path.dirname(filepath)) / match.group(2)
                content = match.group(1)
                if len(lines) > i + 1:
                    if not pattern.match(lines[i + 1]) and not skip_pattern.match(lines[i + 1]):
                        content += lines[i + 1]
                        skip = True
            elif content[-16:] == " (file attached)":
                attachment = Path(os.path.dirname(filepath)) / content[:-16]
                if len(lines) > i + 1:
                    if lines[i + 1].strip() == content[:-16].strip():
                        skip = True
                content = ""
            # Copy the attachment
            if attachment:
                if not (OUTPUT_PATH / "attachments" / chat_id).exists():
                    mkdir(OUTPUT_PATH / "attachments" / chat_id)
                shutil.copyfile(attachment, OUTPUT_PATH / "attachments" / chat_id / ntpath.basename(attachment))
                attachment = chat_id + "/" + ntpath.basename(attachment)

            message_format = None
            formatted_content = None
            if len(content.strip()):
                if content.strip() != parse_markdown(content.strip(), True):
                    message_format = "whatsapp_markdown"
                    formatted_content = parse_markdown(content.strip(), False)

            messages.append({
                "id": shortuuid.uuid(),
                "user_id": group_users[name]["user_id"],
                "name": name,
                "avatar": group_users[name]["avatar"],
                "color": group_users[name]["color"],
                "created_timestamp": datetime(year, month, day, hour, minute).astimezone(),
                "message_type": message_type,
                "content": content.strip() if len(content.strip()) else None,
                "format": message_format,
                "formatted_content": formatted_content,
                "attachments": json.dumps([attachment]) if attachment else None,
            })
        elif len(messages) > 0:
            # This line is either a system message or a continuation of the previous message
            if messages[-1]["content"] and not skip_pattern.match(line):
                new_content = messages[-1]["content"] + "\n" + line.strip()
                if new_content != parse_markdown(new_content, True):
                    # The new content has formatting
                    messages[-1]["format"] = "whatsapp_markdown"
                    messages[-1]["formatted_content"] = parse_markdown(new_content, False)
                messages[-1]["content"] = new_content
            elif not skip_pattern.match(line):
                new_content = line.strip()
                if new_content != parse_markdown(new_content, True):
                    messages[-1]["format"] = "whatsapp_markdown"
                    messages[-1]["formatted_content"] = parse_markdown(new_content, False)
                messages[-1]["content"] = new_content

    return messages


def initialize_backup():
    mkdir(OUTPUT_PATH)

    with open(OUTPUT_PATH / "info.json", "w") as f:
        json.dump({
            "type": "generic",
            "version": "0.1.0",
            "id": "whatsapp",
            "name": "WhatsApp chats",
            "icon": "whatsapp.png"
        }, f)
        shutil.copyfile("whatsapp.png", OUTPUT_PATH / "whatsapp.png")

    conn = sqlite3.connect(OUTPUT_PATH / "backup.db")
    cur = conn.cursor()
    # Create chats table
    cur.execute("DROP TABLE IF EXISTS chats")
    cur.execute("""CREATE TABLE chats (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            topic TEXT,
            avatar TEXT
        )""")
    # Create messages table
    cur.execute("DROP TABLE IF EXISTS messages")
    cur.execute("CREATE TABLE messages ("
            + "id TEXT PRIMARY KEY,"
            + "chat TEXT NOT NULL,"  # Room ID
            + "user_id TEXT NOT NULL,"  # User ID of the sender
            + "name TEXT NOT NULL,"  # Name of sender
            + "avatar TEXT NOT NULL,"  # Avatar of sender
            + "color TEXT,"  # Color of sender's name
            + "created_timestamp INT NOT NULL,"  # Timestamp when created
            + "edited_timestamp INT,"  # JSON list of edits (timestamp, message_type, content, format, formatted_content), optional
            + "reference INT,"  # Message this refers to, optional (for replies)
            + "message_type TEXT NOT NULL,"  # Message type, like text or image
            + "content TEXT,"  # Raw unformatted content, optional
            + "format TEXT,"  # How the content is formatted, optional
            + "formatted_content TEXT," # Formatted content, optional
            + "attachments TEXT" # JSON list of attachments, optional
            + ")")
    # Create users table
    cur.execute("DROP TABLE IF EXISTS users")
    cur.execute("""CREATE TABLE users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            avatar TEXT NOT NULL,
            color TEXT
        )""")

    mkdir(OUTPUT_PATH / "avatars")
    mkdir(OUTPUT_PATH / "attachments")

    users = {}
    user_ids = set()
    info = {}
    if (INPUT_PATH / "info.json").exists():
        with open(INPUT_PATH / "info.json", "r", encoding="UTF-8") as f:
            info = json.load(f)

    for filepath in glob.iglob(str(INPUT_PATH / "*/*.txt")):
        if match := re.match(r".*[/\\]WhatsApp Chat with (.+).txt", filepath):
            chat_id = shortuuid.uuid()

            name = match.group(1)
            print("Converting", filepath, "\n")

            # Avatar
            avatar = ""
            if "chats" in info and name in info["chats"]:
                print(f"Found chat \"{name}\" in info.json")
                avatar = str(INPUT_PATH / info["chats"][name]["avatar"])
            while len(avatar) == 0 or not Path(avatar).exists():
                if len(avatar) != 0:
                    print(f"Error: file `{avatar}` not found")
                avatar = input(f"Enter the path to the \"{name}\" chat's avatar (optional): ")
                if len(avatar) == 0:
                    avatar = None
                    break

            # Copy avatar if it's specified
            if avatar:
                target = shortuuid.uuid() + os.path.splitext(avatar)[1]
                shutil.copyfile(avatar, OUTPUT_PATH / "avatars" / target)
                avatar = target

            # Topic
            if "chats" in info and name in info["chats"]:
                topic = info["chats"][name]["topic"]
            else:
                topic = input(f"Enter the \"{name}\" chat's description (optional): ")
                if len(topic) == 0:
                    topic = None
            # Save the chat details to the database
            cur.execute(
                "INSERT INTO chats VALUES (?, ?, ?, ?)",
                (chat_id, name, topic, avatar),
            )
            print("\nUsers:")

            new_users, group_users = backup_users(filepath, users, user_ids)
            # Iterate over the new users in this group (who aren't part of any previous groups)
            for user in new_users:
                cur.execute(
                    "INSERT INTO users VALUES (?, ?, ?, ?)",
                    (user, new_users[user]["name"], new_users[user]["avatar"], new_users[user]["color"]),
                )

            # Add these users to the existing users dictionary
            user_ids.update(new_users.keys())
            users.update(group_users)

            # Backup messages
            for message in backup_messages(filepath, chat_id, group_users):
                cur.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        message["id"],
                        chat_id,
                        message["user_id"],
                        message["name"],
                        message["avatar"],
                        message["color"],
                        message["created_timestamp"],
                        None,
                        None,
                        message["message_type"],
                        message["content"],
                        message["format"],
                        message["formatted_content"],
                        message["attachments"],
                    ),
                )

    print("Converted files saved to", OUTPUT_PATH)

    conn.commit()
    conn.close()


def index_messages():
    conn = sqlite3.connect(OUTPUT_PATH / "backup.db")
    cur = conn.cursor()
    # (Re)create table
    cur.execute("DROP TABLE IF EXISTS message_search")
    cur.execute("CREATE VIRTUAL TABLE message_search USING FTS5(id, content)")
    cur.execute("INSERT INTO message_search SELECT id, content FROM messages")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    initialize_backup()
    index_messages()
