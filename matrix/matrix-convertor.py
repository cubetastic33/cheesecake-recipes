from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime
import posixpath
import os
import glob
import shutil
import re
import json
import sqlite3

load_dotenv()

INPUT_PATH = Path("input")
OUTPUT_PATH = Path("backup")
NAME_REGEX = re.compile(r"(.*) <@.*:.*>")
NAME_FROM_TAG_REGEX = re.compile(r"@(.*):.*")


def sanitize(value):
    """
    Make string safe for use as filename on NTFS filesystems
    This is recommended even if you're running on this a unix filesystem so that if you want to
    copy the backup to a windows system later you won't have problems, especially with the
    attachment filenames
    """
    value = str(value)
    # value.lower() is useful because on unix we might be fine with foo.bar and Foo.bar as
    # attachments but on windows one would get overwritten. This way it'll be recognized as a
    # duplicate and get saved as foo(1).bar by `choose_filename`
    return re.sub(r"[\"*/:<>?\\|]", "_", value.lower())


def mkdir(path):
    # Delete the directory if it already exists
    if path.exists():
        shutil.rmtree(path)
    os.mkdir(path)


def backup_messages():
    conn = sqlite3.connect(OUTPUT_PATH / "backup.db")
    cur = conn.cursor()

    for f_events in glob.iglob(str(INPUT_PATH / "*/events.json")):
        # Get saved avatars
        with open(Path(os.path.dirname(f_events)) / "info.json", "r") as f:
            info = json.load(f)
            avatars = info["user_avatars"]
        with open(f_events, "r") as f:
            events = json.load(f)
            for event in events:
                if (
                        "m.relates_to" in event["content"]
                        and "rel_type" in event["content"]["m.relates_to"]
                        and event["content"]["m.relates_to"]["rel_type"] == "m.replace"
                    ):
                    # This is an edit
                    original_id = event["content"]["m.relates_to"]["event_id"]
                    cur.execute(
                        "SELECT edits FROM messages WHERE id = ?",
                        (original_id,),
                    )
                    edits = cur.fetchone()[0]
                    if edits:
                        edits = json.loads(edits)
                    else:
                        edits = []

                    try:
                        message_format = event["content"]["m.new_content"]["format"]
                        formatted_content = event["content"]["m.new_content"]["formatted_body"]
                    except KeyError:
                        message_format = formatted_content = None

                    edits.append([
                        event["origin_server_ts"],
                        event["content"]["m.new_content"]["msgtype"],
                        event["content"]["m.new_content"]["body"],
                        message_format,
                        formatted_content,
                    ])
                    cur.execute("UPDATE messages SET edits = ? WHERE id = ?", (
                        json.dumps(edits), original_id
                    ))
                else:
                    # Save the user to the database
                    try:
                        avatar = avatars[event["sender"]]
                        if not (OUTPUT_PATH / "avatars" / avatar).exists():
                            shutil.copyfile(Path(os.path.dirname(f_events)) / "avatars" / avatar, OUTPUT_PATH / "avatars" / avatar)
                    except KeyError:
                        avatar = None
                    sender_name = ""
                    if "_sender_name" in event:
                        name = NAME_REGEX.match(event["_sender_name"]).group(1)
                    else:
                        # This user is no longer in the room
                        name = NAME_FROM_TAG_REGEX.match(event["sender"]).group((1))

                    cur.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?, ?)", (
                        event["sender"],
                        name,
                        avatar,
                        None,
                    ))

                    # Save the event to the database
                    if "redacted_because" in event:
                        msgtype = "m.room.redaction"
                        content = None
                    else:
                        msgtype = event["content"]["msgtype"]
                        content = event["content"]["body"]

                    try:
                        message_format = event["content"]["format"]
                        formatted_content = event["content"]["formatted_body"]
                    except KeyError:
                        message_format = formatted_content = None

                    # Reply
                    try:
                        reference = event["content"]["m.relates_to"]["m.in_reply_to"]["event_id"]
                    except KeyError:
                        reference = None
                    
                    # Attachment
                    if msgtype == "m.image" or msgtype == "m.file":
                        # Create a directory for this room's attachments if it doesn't exist yet
                        room_attachments = OUTPUT_PATH / "attachments" / sanitize(event["room_id"])
                        if not room_attachments.exists():
                            os.mkdir(room_attachments)
                        
                        # Create a directory for this attachment
                        # This is so that we don't have to worry about duplicate attachment names
                        os.mkdir(room_attachments / sanitize(event["event_id"]))
                        attachment_path = room_attachments / sanitize(event["event_id"]) / sanitize(event["content"]["body"])
                        # Remove OUTPUT_PATH/attachments and use forward slashes as separators
                        content = posixpath.join(*str(attachment_path).split(os.sep)[2:])
                        shutil.copyfile(
                            "/".join([str(INPUT_PATH)] + event["_file_path"].split("/")[1:]),
                            attachment_path,
                        )

                    cur.execute(
                        "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            event["event_id"],
                            event["room_id"],
                            event["sender"],
                            name,
                            avatar,
                            None,
                            datetime.utcfromtimestamp(event["origin_server_ts"] / 1000),
                            None,
                            reference,
                            msgtype,
                            content,
                            message_format,
                            formatted_content,
                        )
                    )
    conn.commit()
    conn.close()


def index_messages():
    conn = sqlite3.connect(OUTPUT_PATH / "backup.db")
    cur = conn.cursor()
    # (Re)create table
    cur.execute("DROP TABLE IF EXISTS message_search")
    cur.execute("CREATE VIRTUAL TABLE message_search USING FTS5(id, content, edits)")
    cur.execute("INSERT INTO message_search SELECT id, content, edits FROM messages")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    mkdir(OUTPUT_PATH)
    with open(OUTPUT_PATH / "info.json", "w") as f:
        json.dump({
            "type": "matrix",
            "version": "0.1.0",
            "id": "matrix",
            "name": "matrix chats",
            "icon": "matrix.png"
        }, f)
        shutil.copyfile("matrix.png", OUTPUT_PATH / "matrix.png")

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
            + "user_id TEXT NOT NULL,"  # Matrix ID of the sender
            + "name TEXT NOT NULL,"  # Name of sender
            + "avatar TEXT,"  # Avatar of sender, optional
            + "color TEXT,"  # Color of sender's name
            + "created_timestamp INT NOT NULL,"  # Timestamp when created
            + "edits TEXT,"  # JSON list of edits (timestamp, message_type, content, format, formatted_content), optional
            + "reference INT,"  # Message this refers to, optional (for replies)
            + "message_type TEXT NOT NULL,"  # Message type, like text or image
            + "content TEXT,"  # Raw unformatted content, optional
            + "format TEXT,"  # How the content is formatted, optional
            + "formatted_content TEXT" # Formatted content, optional
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

    for f_info in glob.iglob(str(INPUT_PATH / "*/info.json")):
        with open(f_info, "r") as f:
            info = json.load(f)
            # Save the room details to the database
            cur.execute(
                "INSERT INTO chats VALUES (?, ?, ?, ?)",
                (info["id"], info["name"], info["topic"], info["avatar"]),
            )
            # Copy avatar if it's specified
            if info["avatar"]:
                shutil.copyfile(Path(os.path.dirname(f_info)) / info["avatar"], OUTPUT_PATH / "avatars" / info["avatar"])
    conn.commit()
    conn.close()
    backup_messages()
    index_messages()
