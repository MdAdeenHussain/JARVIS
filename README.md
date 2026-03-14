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

JARVIS is a voice-first macOS assistant built around one Python entrypoint: [jarvis.py](/Users/mohammadadeenhussain/Desktop/JARVIS/jarvis.py). It keeps local skills fast, stores memory and reminders in PostgreSQL, uses Gemini first with Groq fallback, and now drives both the terminal animation and an optional PyQt6 floating overlay from the same state machine.

## What This Upgrade Adds

- Voice-controlled file and folder management with search, disambiguation, and Trash-safe deletion
- A much larger local skill set for system control, clipboard, notes, networking, calculations, window actions, and fun commands
- A PyQt6 floating overlay for macOS with listening, thinking, speaking, idle, and error states
- `UI_MODE=both|terminal|overlay` so the terminal animation and overlay can run together or independently
- Startup accessibility checks for keyboard automation skills
- `.env.example` for onboarding and updated setup docs

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
- Python 3.10 or newer
- Homebrew
- PostgreSQL
- A working microphone
- Terminal microphone permission
- Accessibility permission if you want typing, copy/paste, app switching, or other keyboard automation

## 1. Install System Dependencies

Install the audio backend required by `PyAudio`:

```bash
brew install portaudio
```

Install PostgreSQL if needed:

```bash
brew install postgresql
brew services start postgresql
```

If you want brightness controls, install the `brightness` CLI too:

```bash
brew install brightness
```

## 2. Create a PostgreSQL Database and User

Example setup:

```bash
createuser -P jarvis_user
createdb -O jarvis_user jarvis_db
```

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

```bash
cp .env.example .env
```

Then fill in every value:

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
UI_MODE=both
```

`UI_MODE` values:

- `both`: terminal animation plus PyQt6 overlay
- `terminal`: terminal animation only
- `overlay`: overlay only, while regular console output still prints

## 6. Accessibility Permissions

`pyautogui`-powered commands need Accessibility access.

1. Open `System Settings`
2. Go to `Privacy & Security`
3. Open `Accessibility`
4. Allow your terminal app or Python interpreter

If JARVIS cannot use automation, it will disable those commands gracefully and tell you.

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
5. Start the terminal UI and optional overlay
6. Start the reminder checker
7. Print the status panel
8. Speak the startup message
9. Begin always-on wake listening

## Overlay UI

The floating PyQt6 overlay is a dark frosted pill that appears near the bottom center of the screen. It has:

- an indigo listening pulse with a drawn microphone icon
- a rotating thinking arc with the current provider badge
- animated equalizer bars while speaking
- a low-opacity idle dot when JARVIS is quiet
- shared state with the terminal animation, so both views stay in sync

If `PyQt6` is not installed or the overlay cannot start, JARVIS falls back cleanly to terminal mode.

## Voice Commands

### File and folder management

- `Jarvis, rename report to final report`
- `Jarvis, change the name of notes folder to archive`
- `Jarvis, move report to desktop`
- `Jarvis, put invoices in documents`
- `Jarvis, send budget.xlsx to downloads`
- `Jarvis, copy report to documents`
- `Jarvis, duplicate photos to desktop`
- `Jarvis, make a copy of taxes in downloads`
- `Jarvis, delete report`
- `Jarvis, trash old screenshots`
- `Jarvis, create a folder called Projects`
- `Jarvis, make a new folder named Receipts in documents`
- `Jarvis, find budget`
- `Jarvis, where is passport scan`
- `Jarvis, what's in desktop`
- `Jarvis, open downloads in finder`
- `Jarvis, open report.pdf`
- `Jarvis, tell me about report.pdf`
- `Jarvis, file info budget.xlsx`
- `Jarvis, organize my desktop`

### System control

- `Jarvis, increase volume`
- `Jarvis, decrease volume`
- `Jarvis, set volume to 40`
- `Jarvis, mute`
- `Jarvis, unmute`
- `Jarvis, increase brightness`
- `Jarvis, decrease brightness`
- `Jarvis, lock screen`
- `Jarvis, sleep computer`
- `Jarvis, empty trash`
- `Jarvis, what's my IP address`
- `Jarvis, what's my battery`
- `Jarvis, how much storage do I have`
- `Jarvis, how much RAM am I using`
- `Jarvis, CPU usage`
- `Jarvis, what processes are running`

### Clipboard and writing

- `Jarvis, what's in my clipboard`
- `Jarvis, clear clipboard`
- `Jarvis, copy that`
- `Jarvis, type meeting starts at 3 PM`
- `Jarvis, press enter`
- `Jarvis, press escape`
- `Jarvis, select all`
- `Jarvis, copy`
- `Jarvis, paste`
- `Jarvis, undo`

### Window and network control

- `Jarvis, minimize window`
- `Jarvis, close window`
- `Jarvis, switch app`
- `Jarvis, show desktop`
- `Jarvis, full screen`
- `Jarvis, are we connected`
- `Jarvis, what wifi am I on`
- `Jarvis, open network settings`

### Calculations, notes, and weather

- `Jarvis, calculate 22 / 7`
- `Jarvis, what is 15 * (4 + 2)`
- `Jarvis, what's 18 percent of 240`
- `Jarvis, convert 5 km to miles`
- `Jarvis, convert 10 celsius to fahrenheit`
- `Jarvis, convert 100 usd to inr`
- `Jarvis, make a note buy almond milk`
- `Jarvis, read my notes`
- `Jarvis, clear my notes`
- `Jarvis, what's the weather`
- `Jarvis, will it rain`

### Memory, reminders, apps, and fun

- `Jarvis, remember that my dog's name is Bruno`
- `Jarvis, do you remember my dog's name`
- `Jarvis, what do you know about my dog's name`
- `Jarvis, set a timer for 5 minutes`
- `Jarvis, remind me to stretch in 10 minutes`
- `Jarvis, open browser`
- `Jarvis, search for best espresso near me`
- `Jarvis, open Terminal`
- `Jarvis, switch to groq`
- `Jarvis, switch to gemini`
- `Jarvis, tell me a joke`
- `Jarvis, flip a coin`
- `Jarvis, roll a dice`
- `Jarvis, what's 42 in binary`
- `Jarvis, motivate me`
- `Jarvis, what version are you`

## AI Routing Behavior

- Local skills are checked before any AI call
- Gemini is attempted first by default
- Groq takes over automatically if Gemini fails
- If both fail, JARVIS says: `Both AI systems are offline sir. Running on local skills only.`
- Manual provider switches are written to [jarvis.log](/Users/mohammadadeenhussain/Desktop/JARVIS/jarvis.log)

## PostgreSQL Schema

JARVIS creates these tables automatically:

- `memory`
- `conversation_log`
- `ai_usage`
- `reminders`

## Main Files

- Core assistant: [jarvis.py](/Users/mohammadadeenhussain/Desktop/JARVIS/jarvis.py)
- Package list: [requirements.txt](/Users/mohammadadeenhussain/Desktop/JARVIS/requirements.txt)
- Environment template: [.env.example](/Users/mohammadadeenhussain/Desktop/JARVIS/.env.example)
