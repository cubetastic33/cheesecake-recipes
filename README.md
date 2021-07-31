# cheesecake-recipes
Programs to create chat backups for use with [cheesecake](https://github.com/cubetastic33/cheesecake)

Cheesecake currently supports backups of three types - `discord`, `matrix`, and `generic`.
`generic` is intended to be a general format you can use for most chat platforms. This repo
includes an example of using `generic` to backup WhatsApp chats.

## Discord
The script lets you backup whole servers, but it doesn't handle DMs. The backup includes a lot of
stuff, including custom emoji and attachments. The resulting backup files can  easily get very large
on big servers, so don't include attachments if you're backing up an enormous server.

### Environment variables
+ `GUILD`: The server ID of the server you want to backup.
+ `TOKEN`: The token of the bot account you're using to backup.

### How to use
+ Clone and open a terminal in the repo
+ Optionally create and activate a [virtual environment](https://docs.python.org/3/library/venv.html)
+ `cd discord`
+ `pip install -r requirements.txt`
+ Create `.env` file or specify environment variables in shell
+ `python discord-archive.py`

## Matrix
Backing up matrix involves running two scripts - the first one downloads the messages from the
server, and the second one runs locally to convert the downloaded messages into a format compatible
with cheesecake. The first script depends on `python-olm`, which can be
[difficult](https://github.com/matrix-org/olm/issues/25) to install on
windows. The second script, however, should work just fine on windows. So if you're on windows and
you're unable to get the dependencies installed, you can run the first script on a unix-based
system and copy the output files to windows, or you could run the second script on that system too.
If you're running only the second script on windows, do `pip install python-dotenv`

The first script, `matrix-archive.py`, is from [russelldavies/matrix-archive](https://github.com/russelldavies/matrix-archive)
with some modifications. The output format is modified a bit and the output files should also be
compatible with windows now (recommended even if you're on unix, so that you can share the backup).

### How to use
+ Clone and open a terminal in the repo
+ Optionally create and activate a [virtual environment](https://docs.python.org/3/library/venv.html)
+ `cd matrix`
+ `pip install -r requirements.txt` (this might fail on windows, read above for workaround)
+ `python matrix-archive.py`
+ `python matrix-convertor.py`


## WhatsApp
WhatsApp's export format lacks a lot of information, like user avatars, phone numbers, and replies.
Because of this, the backup script will ask you for a lot of this information, but replies will
only be saved like normal messages (you won't be able to see what message it is a reply to). You
can easily add that information by editing the database, but that is obviously tedious and
impractical when there are lots of replies.

By default the script asks for the data through stdin, but you can also create an `info.json` file
inside the input directory so the script can run without requiring any interaction.

There are two global variables in the script, `INPUT_PATH` and `OUTPUT_PATH`. `INPUT_PATH` should
have subdirectories for each of the chats you want to backup. Each subdirectory should have at
least the exported txt file, and they can also have the attachments. The optional `info.json`
should also be present directly inside `INPUT_PATH`.

`OUTPUT_PATH` is where the converted files will be saved. This directory can be renamed later, and
must be copied to the refrigerator for cheesecake to use. It can also be shared with other people.

### How to use
+ Clone and open a terminal in the repo
+ Optionally create and activate a [virtual environment](https://docs.python.org/3/library/venv.html)
+ `cd whatsapp`
+ `pip install -r requirements.txt`
+ Copy the exported files to `INPUT_PATH` (`whatsapp_exports` by default)
+ Optionally create an `info.json` file (details below)
+ `python whatsapp.py`

### `info.json` format
If you want to specify the chat metadata (avatar and description), create a `chats` key.
If you want to specify the user metadata (phone no., avatar, and name color) create a `users` key.
Data for the chats and users that are not present in the `info.json` file can be given through
stdin.

Create a key with the name of the chat/user, and the value is an object with `avatar` and `topic`
(description) for chats, and `user_id` (phone no.), `avatar`, and `color` (the color their name
will be shown in) for users. All the values must be present, but you can use `null` if you want it
empty. The avatar path is relative to `INPUT_PATH` (or you can use an absolute path).

### Example `info.json`
```json
{
    "chats": {
        "John Doe": {
            "avatar": "John Doe.jpg",
            "topic": null
        },
        "Class Reunion": {
            "avatar": "Class Reunion.jpg",
            "topic": "Discuss the upcoming class reunion."
        }
    },
    "users": {
        "John Doe": {
            "user_id": "14748183636",
            "avatar": "John Doe.jpg",
            "color": null
        },
        "Jane Doe": {
            "user_id": "16365459292",
            "avatar": "../default.svg",
            "color": "#ff0000"
        }
    }
}
```
