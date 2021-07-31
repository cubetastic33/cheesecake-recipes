from dotenv import load_dotenv
from pathlib import Path
import os
import shutil
import re
import json
import sys
import sqlite3
import discord
import requests

load_dotenv()

intents = discord.Intents.default()
intents.members = True

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    if input("\nHit enter to backup or type something to cancel: ") == "":
        await initialize_backup()
        await backup_messages()
        await index_messages()
        print("\nBackup complete")
    sys.exit()


async def initialize_backup():
    # The guild we wanna backup
    guild = client.get_guild(int(os.environ["GUILD"]))

    # Create the backup directory
    backup_path = Path(str(guild.id))
    if backup_path.exists():
        shutil.rmtree(backup_path)
    os.mkdir(backup_path)

    # Save the guild icon
    icon = str(guild.icon_url).split("/")[-1].split("?")[0]
    await guild.icon_url.save(backup_path / icon)

    # Save guild info
    guild_info = {
        "type": "discord",
        "version": "0.1.0",
        "id": guild.id,
        "name": guild.name,
        "icon": icon,
    }
    with open(backup_path / "info.json", "w") as f:
        json.dump(guild_info, f)

    conn = sqlite3.connect(backup_path / "backup.db")
    cur = conn.cursor()
    # Create roles table
    cur.execute("DROP TABLE IF EXISTS roles")
    cur.execute("""CREATE TABLE roles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            color TEXT
        )""")
    for role in guild.roles:
        # If the name color is the default color, save it as None
        color = str(role.color)
        if role.color == discord.colour.Colour.default():
            color = None
        # Save the role to the database
        cur.execute("INSERT INTO roles VALUES (?, ?, ?)", (role.id, role.name, color))
    conn.commit()
    conn.close()


async def backup_messages():
    # The guild we wanna backup
    guild = client.get_guild(int(os.environ["GUILD"]))

    backup_path = Path(str(guild.id))
    # Create directories to store assets
    for asset in ["avatars", "emoji", "attachments"]:
        if (backup_path / asset).exists():
            shutil.rmtree(backup_path / asset)
        os.mkdir(backup_path / asset)

    # Create a database connection
    conn = sqlite3.connect(backup_path / "backup.db")
    cur = conn.cursor()
    # (Re)create tables
    cur.execute("DROP TABLE IF EXISTS messages")
    cur.execute("""CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            chat TEXT NOT NULL,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            avatar TEXT NOT NULL,
            color TEXT,
            bot INTEGER NOT NULL,
            created_timestamp INTEGER NOT NULL,
            edited_timestamp INT,
            reference INT,
            message_type TEXT NOT NULL,
            content TEXT,
            attachments TEXT,
            embeds TEXT,
            reactions TEXT
        )""")
    cur.execute("DROP TABLE IF EXISTS chats")
    cur.execute("""CREATE TABLE chats (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            topic TEXT
        )""")
    cur.execute("DROP TABLE IF EXISTS users")
    cur.execute("""CREATE TABLE users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            avatar TEXT NOT NULL,
            bot INTEGER NOT NULL
        )""")

    # This does not mimic discord's parsing 100% accurately, but comes close enough.
    # It differs from discord in some special cases like escaped backslashes and backticks that
    # don't constitute a code block - discord's parsing itself seems weird in this case and was
    # hard to reproduce. For example, in discord ``foo` counts as a code block but `foo`` doesn't.
    triple_backtick = re.compile(r"(?<!\\)(```[^`]*```)*")
    double_backtick = re.compile(r"(?<!\\)(``[^`]*``)*")
    single_backtick = re.compile(r"(?<!\\)(`[^`]*`)*")
    static_emoji_regex = re.compile(r"(?<!\\)<:\w+:(\d+)>")
    gif_emoji_regex = re.compile(r"(?<!\\)<a:\w+:(\d+)>")

    # Iterate over all the text channels
    for channel in guild.channels:
        if channel.type == discord.ChannelType(0):
            print(f"\nStarting backup of channel {channel.name}")
            # Save the channel to the database
            cur.execute("INSERT INTO chats VALUES (?, ?, ?)", (
                channel.id, channel.name, channel.topic
            ))

            async for message in channel.history(limit=None, oldest_first=True):
                # Download avatars
                directory_path = backup_path / "avatars" / str(message.author.avatar_url_as(format="webp")).split("/")[-2]
                directory_path.mkdir(exist_ok=True)
                if not (directory_path / str(message.author.avatar_url_as(format="webp")).split("/")[-1].split("?")[0]).exists():
                    await message.author.avatar_url_as(format="webp").save(directory_path / str(message.author.avatar_url_as(format="webp")).split("/")[-1].split("?")[0])

                # Download emoji
                for pattern, extension in [(static_emoji_regex, "png"), (gif_emoji_regex, "gif")]:
                    for match in pattern.finditer(single_backtick.sub("", double_backtick.sub("", triple_backtick.sub("", message.content)))):
                        if not (backup_path / "emoji" / f"{match.group(1)}.{extension}").exists():
                            r = requests.get(f"https://cdn.discordapp.com/emojis/{match.group(1)}.{extension}")
                            with open(backup_path / "emoji" / f"{match.group(1)}.{extension}", "wb") as f:
                                f.write(r.content)

                # Reactions
                reactions = []
                for reaction in message.reactions:
                    # `emoji` holds info about the actual emoji
                    emoji = ""
                    if reaction.custom_emoji:
                        extension = "png"
                        if reaction.emoji.animated:
                            emoji += "a"
                            extension = "gif"
                        # Download the emoji if it doesn't already exist
                        if not (backup_path / "emoji" / f"{reaction.emoji.id}.{extension}").exists():
                            r = requests.get(f"https://cdn.discordapp.com/emojis/{reaction.emoji.id}.{extension}")
                            with open(backup_path / "emoji" / f"{reaction.emoji.id}.{extension}", "wb") as f:
                                f.write(r.content)
                        emoji += f":{reaction.emoji.name}:{reaction.emoji.id}"
                    else:
                        emoji += reaction.emoji
                    # `users` is the list of users who have reacted with this emoji
                    users = []
                    async for user in reaction.users():
                        # Download avatar
                        directory_path = backup_path / "avatars" / str(user.avatar_url_as(format="webp")).split("/")[-2]
                        directory_path.mkdir(exist_ok=True)
                        if not (directory_path / str(user.avatar_url_as(format="webp")).split("/")[-1].split("?")[0]).exists():
                            await user.avatar_url_as(format="webp").save(directory_path / str(user.avatar_url_as(format="webp")).split("/")[-1].split("?")[0])
                        # Save the user to the database
                        cur.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?, ?)", (
                            user.id,
                            user.display_name,
                            "/".join(str(user.avatar_url_as(format="webp")).split("/")[-2:]).split("?")[0],
                            int(user.bot),
                        ))
                        users.append(str(user.id))
                    # The final string we add to the list of reactions has both `emoji` and `users`
                    reactions.append(emoji + "-" + ",".join(users))

                # Download attachments
                attachments = []
                for attachment in message.attachments:
                    segments = str(attachment).split("/")
                    directory_path = backup_path / "attachments" / segments[-3] / segments[-2]
                    directory_path.mkdir(parents=True, exist_ok=True)
                    r = requests.get(attachment)
                    with open(directory_path / segments[-1], "wb") as f:
                        f.write(r.content)
                    attachments.append(str(attachment)[39:])

                # If the name color is the default color, save it as None
                color = str(message.author.color)
                if message.author.color == discord.colour.Colour.default():
                    color = None
                # Avatar URL
                avatar = "/".join(str(message.author.avatar_url_as(format="webp")).split("/")[-2:]).split("?")[0]
                # 2 for webhooks, 1 for bots, 0 for normal users
                bot = 2 if message.webhook_id else int(message.author.bot)

                if not message.webhook_id:
                    # Save the user to the database
                    cur.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?, ?)", (
                        message.author.id,
                        message.author.display_name,
                        avatar,
                        bot,
                    ))

                if message.embeds:
                    embeds = json.dumps([embed.to_dict() for embed in message.embeds])
                else:
                    embeds = None

                # Save the message to the database
                cur.execute(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        message.id,
                        message.channel.id,
                        message.author.id,
                        message.author.display_name,
                        avatar,
                        color,
                        bot,
                        message.created_at,
                        message.edited_at,
                        message.reference.message_id if message.reference else None,
                        str(message.type).split(".")[1],
                        message.system_content if len(message.system_content) else None,
                        " ".join(attachments) if len(attachments) else None,
                        embeds,
                        " ".join(reactions) if len(reactions) else None,
                    ),
                )
            print(f"Backup of channel {channel.name} complete")
    conn.commit()
    conn.close()


async def index_messages():
    # The guild we wanna backup
    guild = client.get_guild(int(os.environ["GUILD"]))

    backup_path = Path(str(guild.id))

    # Create a database connection
    conn = sqlite3.connect(backup_path / "backup.db")
    cur = conn.cursor()
    # (Re)create table
    cur.execute("DROP TABLE IF EXISTS message_search")
    cur.execute("CREATE VIRTUAL TABLE message_search USING FTS5(id, content, embeds)")
    cur.execute("INSERT INTO message_search SELECT id, content, embeds FROM messages")
    conn.commit()
    conn.close()

client.run(os.environ["TOKEN"])
