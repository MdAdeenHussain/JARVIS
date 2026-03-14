# JARVIS AI Assistant

```text
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
         Just A Rather Very Intelligent System
```

JARVIS is a single-file Python voice assistant for macOS. It listens for the wake word `jarvis`, handles common commands locally, uses Claude for open-ended questions, and now stores long-term memory in PostgreSQL instead of SQLite.

## Recent Updates

- Built the assistant as a single heavily commented file: `jarvis.py`
- Added wake-word listening, Google speech recognition, Claude chat fallback, timers, screenshots, browser/app launchers, and memory commands
- Switched memory storage from SQLite to PostgreSQL
- Expanded `config.json` with PostgreSQL connection settings
- Auto-creates the PostgreSQL `memory` table when the app starts and a database connection is available
- Installed the core audio and AI dependencies in the local `venv`
- Added Homebrew `portaudio` support for `PyAudio`

## Project Files

```text
JARVIS/
├── jarvis.py
├── config.json
├── jarvis_memory.db
├── README.md
├── LICENSE
└── venv/
```

Notes:

- `jarvis.py` is the main program.
- `config.json` stores the Claude API key and PostgreSQL settings.
- `jarvis_memory.db` is a leftover file from the earlier SQLite version and is no longer used by the app.

## Features

- Wake word detection with simple string matching
- Voice input through `SpeechRecognition` and `PyAudio`
- Offline speech output through `pyttsx3`
- Claude integration with `claude-sonnet-4-20250514`
- Session conversation history limited by config
- PostgreSQL-backed memory storage
- Built-in local skills for time, date, search, timers, screenshots, and app launching
- Graceful shutdown and broad error handling

## Requirements

- macOS
- Python 3.10 or newer recommended
- Homebrew
- PostgreSQL running locally or reachable over the network
- A Claude API key
- Microphone permission for Terminal

## Python Dependencies

Install these into your virtual environment:

```bash
pip install SpeechRecognition pyttsx3 pyaudio anthropic requests psycopg2-binary
```

## System Dependencies

Install the microphone backend dependency:

```bash
brew install portaudio
```

Install PostgreSQL if you do not already have it:

```bash
brew install postgresql
```

Then start PostgreSQL and create a database for JARVIS:

```bash
brew services start postgresql
createdb jarvis
```

If you prefer a different database name, user, host, or port, update `config.json` accordingly.

## Configuration

`config.json` now contains both assistant settings and PostgreSQL connection settings:

```json
{
    "api_key": "",
    "wake_word": "jarvis",
    "voice_rate": 175,
    "history_limit": 10,
    "db_host": "localhost",
    "db_port": 5432,
    "db_name": "jarvis",
    "db_user": "postgres",
    "db_password": "",
    "db_sslmode": "prefer"
}
```

Field guide:

- `api_key`: your Anthropic Claude API key
- `wake_word`: the activation word JARVIS listens for
- `voice_rate`: pyttsx3 speech speed
- `history_limit`: how many recent Claude messages stay in memory for the current session
- `db_host`: PostgreSQL host
- `db_port`: PostgreSQL port
- `db_name`: PostgreSQL database name
- `db_user`: PostgreSQL username
- `db_password`: PostgreSQL password
- `db_sslmode`: PostgreSQL SSL mode such as `prefer`, `require`, or `disable`

## Running JARVIS

If you want to use the local virtual environment already present in this repository:

```bash
source venv/bin/activate
python jarvis.py
```

On startup JARVIS will:

- print the banner
- load `config.json`
- connect to PostgreSQL and create the `memory` table if possible
- initialize speech and AI services
- start listening for the wake word

## PostgreSQL Memory Table

JARVIS creates this table automatically:

```sql
CREATE TABLE IF NOT EXISTS memory (
    id SERIAL PRIMARY KEY,
    "key" TEXT NOT NULL,
    "value" TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Memory commands:

- `Jarvis, remember that my dog's name is Bruno`
- `Jarvis, do you remember my dog's name?`
- `Jarvis, what do you know about Bruno?`

## Built-in Commands

- `what time is it`
- `current time`
- `what's the date`
- `today's date`
- `open browser`
- `open chrome`
- `open safari`
- `open music`
- `play music`
- `open terminal`
- `take a screenshot`
- `remember that ...`
- `do you remember ...`
- `what do you know about ...`
- `set a timer for N minutes`
- `search for ...`
- `google ...`
- `stop`
- `exit`
- `goodbye`
- `shut down`

Anything else is sent to Claude.

## Known Notes

- The code now uses PostgreSQL for memory. If PostgreSQL is unreachable or `psycopg2-binary` is missing, memory commands will fail gracefully instead of crashing the app.
- `pyttsx3` is installed, but on some macOS and Python combinations its NSSpeech driver can still be temperamental. The script already falls back to terminal output if TTS initialization fails.
- Speech recognition still depends on Google's online recognition service, so microphone transcription needs internet access.

## Verification Done In This Repo

- `jarvis.py` was updated to use PostgreSQL connection settings from `config.json`
- `config.json` was updated with PostgreSQL defaults
- The local `venv` has the voice and AI packages installed
- `portaudio` was installed with Homebrew so `PyAudio` could build
- The Python file has been syntax-checked successfully with `python3 -m py_compile jarvis.py`

## Next Good Step

Install `psycopg2-binary` into the same `venv` if it is not already present, start PostgreSQL, fill in your `config.json`, and then run:

```bash
source venv/bin/activate
python jarvis.py
```
