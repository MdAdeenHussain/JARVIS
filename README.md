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

JARVIS is a single-file, voice-activated AI assistant for macOS. It listens for the wake word `jarvis`, handles local Mac skills instantly, stores memory and reminders in PostgreSQL, and routes AI requests through Gemini first with Groq as a fallback.

## What This Upgrade Adds

- `.env`-only secret management with `python-dotenv`
- `.env.example` for safe onboarding
- Gemini `gemini-1.5-flash` as the default AI path
- Groq `llama3-8b-8192` as fallback when Gemini fails
- PostgreSQL connection pooling with persistent memory, reminders, conversation logs, and AI usage tracking
- Always-on wake listener thread
- Reminder polling thread
- Terminal animation system with idle, listening, thinking, speaking, and error states
- Rotating `jarvis.log` file with provider switches and runtime diagnostics

## Project Files

```text
JARVIS/
├── jarvis.py
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── LICENSE
```

## macOS Requirements

- macOS on Intel or Apple Silicon
- Python 3.10 or newer recommended
- Homebrew
- PostgreSQL
- A working microphone
- Terminal microphone permission

## 1. Install System Dependencies

Install the audio backend required by `PyAudio`:

```bash
brew install portaudio
```

Install PostgreSQL if it is not already installed:

```bash
brew install postgresql
```

Start PostgreSQL:

```bash
brew services start postgresql
```

## 2. Create a PostgreSQL Database and User

Example setup:

```bash
createuser -P jarvis_user
createdb -O jarvis_user jarvis_db
```

If you prefer to use your existing `postgres` user, that is fine too. Just make sure the values in `.env` match the database you actually created.

## 3. Create and Activate a Virtual Environment

```bash
cd /Users/mohammadadeenhussain/Desktop/JARVIS
python3 -m venv venv
source venv/bin/activate
```

## 4. Install Python Packages

```bash
pip install -r requirements.txt
```

## 5. Create Your `.env` File

Copy the example file:

```bash
cp .env.example .env
```

Then edit `.env` and fill in every value:

```env
# AI Providers
GEMINI_API_KEY=your_gemini_key_here
GROQ_API_KEY=your_groq_key_here

# PostgreSQL
DB_HOST=localhost
DB_NAME=jarvis_db
DB_USER=jarvis_user
DB_PASSWORD=your_db_password_here
DB_PORT=5432

# JARVIS settings
WAKE_WORD=jarvis
VOICE_RATE=175
HISTORY_LIMIT=10
PRIMARY_AI=gemini
```

Important:

- Do not commit `.env`.
- JARVIS exits at startup if any required `.env` value is missing.
- The app never prints or logs your secret values.

## 6. Get Free AI API Keys

### Gemini

1. Go to https://aistudio.google.com/
2. Sign in with your Google account
3. Create an API key
4. Paste it into `GEMINI_API_KEY`

### Groq

1. Go to https://console.groq.com/
2. Sign up or sign in
3. Create an API key
4. Paste it into `GROQ_API_KEY`

## 7. Run JARVIS

```bash
source venv/bin/activate
python jarvis.py
```

On startup JARVIS will:

1. Print the banner
2. Load and validate `.env`
3. Connect to PostgreSQL
4. Initialize Gemini and Groq
5. Start the terminal animation
6. Start the reminder checker
7. Print the system status panel
8. Speak the startup message
9. Begin always-on wake listening

## Voice Commands

### Time and date

- `Jarvis, what time is it`
- `Jarvis, current time`
- `Jarvis, what's the date`
- `Jarvis, what day is it`

### Browser and apps

- `Jarvis, open browser`
- `Jarvis, open chrome`
- `Jarvis, open safari`
- `Jarvis, open Terminal`
- `Jarvis, launch Music`

### Screenshots

- `Jarvis, take a screenshot`
- `Jarvis, screenshot`

### Timers and reminders

- `Jarvis, set a timer for 5 minutes`
- `Jarvis, set a timer for 30 seconds`
- `Jarvis, remind me to stretch in 10 minutes`
- `Jarvis, remind me to check the oven in 45 seconds`

### Memory

- `Jarvis, remember that my dog's name is Bruno`
- `Jarvis, do you remember my dog's name`
- `Jarvis, what do you know about my dog's name`
- `Jarvis, what do you remember`
- `Jarvis, list your memories`

### AI provider control

- `Jarvis, switch to groq`
- `Jarvis, switch to gemini`
- `Jarvis, use groq`
- `Jarvis, use gemini`

### System and shutdown

- `Jarvis, system status`
- `Jarvis, jarvis status`
- `Jarvis, goodbye`
- `Jarvis, shut down`
- `Jarvis, that's all`

### Everything else

Any command that does not match a built-in skill is sent to AI:

- `Jarvis, explain quantum entanglement`
- `Jarvis, summarize the differences between Flask and FastAPI`
- `Jarvis, write a Python function to merge two sorted lists`

## AI Routing Behavior

- JARVIS keeps separate histories for Gemini and Groq
- Gemini is attempted first by default
- If Gemini fails, JARVIS automatically falls back to Groq
- If both fail, JARVIS says: `Both AI systems are offline sir. Running on local skills only.`
- You can manually override the preferred provider with a voice command
- Every provider switch is written to `jarvis.log`

## PostgreSQL Schema

JARVIS creates these tables automatically on startup:

- `memory`
- `conversation_log`
- `ai_usage`
- `reminders`

This means:

- memories persist across runs
- conversations are stored per session
- AI performance is tracked
- reminders survive restarts

## Logging

JARVIS writes logs to `jarvis.log` with rotation at 5 MB.

Logged events include:

- AI provider switches
- PostgreSQL errors
- failed AI calls
- reminder firings
- session start and end

JARVIS does not log:

- API keys
- `.env` secrets
- user speech content to the log file
- personal memory values to the log file

## Troubleshooting

### `PyAudio` fails to install

Make sure `portaudio` is installed first:

```bash
brew install portaudio
```

Then reinstall:

```bash
pip install PyAudio==0.2.14
```

### PostgreSQL connection fails

Check:

- PostgreSQL is running: `brew services start postgresql`
- your `.env` values match the real host, user, password, port, and database
- your database user has permission to access `jarvis_db`

### JARVIS cannot hear you

Enable microphone access for Terminal:

- `System Settings -> Privacy & Security -> Microphone`

### Gemini or Groq requests fail

Check:

- your API keys are valid
- your internet connection is working
- the provider is not rate-limited or temporarily unavailable

If Gemini fails, JARVIS automatically falls back to Groq.

## Security Notes

- All secrets are loaded only from `.env`
- `.env` is ignored by Git
- `.env.example` is safe to commit
- No API key is hardcoded anywhere in `jarvis.py`

## Run Summary for Your MacBook Air 2017

Once everything is configured, your normal test flow is:

```bash
cd /Users/mohammadadeenhussain/Desktop/JARVIS
source venv/bin/activate
python jarvis.py
```

Then say:

```text
Jarvis
```

And follow with:

```text
what time is it
```

or:

```text
system status
```
