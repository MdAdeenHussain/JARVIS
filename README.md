<div align="center">
```
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
         Just A Rather Very Intelligent System
```

# JARVIS AI Assistant

**A fully voice-activated, offline-capable AI assistant for macOS — built in Python, powered by Claude AI.**

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue?style=flat-square&logo=python)](https://www.python.org/)
[![Claude AI](https://img.shields.io/badge/AI-Claude%20API-blueviolet?style=flat-square)](https://console.anthropic.com/)
[![Platform](https://img.shields.io/badge/Platform-macOS-lightgrey?style=flat-square&logo=apple)](https://www.apple.com/macos/)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active-brightgreen?style=flat-square)]()

*"JARVIS online. All systems operational. How can I assist you?"*

</div>

---

## What is this?

JARVIS is a personal AI assistant you run locally on your Mac from the terminal. You talk to it, it talks back. It understands natural language, remembers things you tell it, controls your Mac, and connects to Claude AI for anything it can't handle on its own — all triggered by saying the wake word **"JARVIS"**.

Built as a single Python file with beginner-friendly comments throughout, it's designed to be easy to understand, easy to modify, and genuinely useful out of the box.

---

## Features

| Feature | Description |
|---|---|
| 🎙️ Wake word detection | Say "JARVIS" to activate — no button pressing needed |
| 🧠 Claude AI brain | Powered by Anthropic's Claude API for natural conversation |
| 🔊 Offline voice output | Uses macOS built-in voices via `pyttsx3` — no internet needed to speak |
| 💾 Persistent memory | SQLite database remembers facts across sessions |
| ⚡ Built-in skills | Time, date, timers, screenshots, app launching and more — no API call needed |
| 🌐 Web search | Opens Google searches directly from voice commands |
| 📝 Conversation history | Remembers context within a session (last 10 messages) |
| 🛡️ Fully error-handled | Every failure is caught and spoken aloud — it never crashes silently |
| ⚙️ Config file | Easy `config.json` setup — change wake word, voice speed, and more |

---

## Demo
```
> python jarvis.py

     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ...
         Just A Rather Very Intelligent System

[JARVIS] Online. Listening for wake word: "jarvis"

You: Jarvis, what time is it?
JARVIS: It's 3:42 PM, sir.

You: Jarvis, remember that my wife's name is Sarah.
JARVIS: Got it. I'll remember that Sarah is your wife.

You: Jarvis, do you remember my wife's name?
JARVIS: Of course. Your wife's name is Sarah.

You: Jarvis, set a timer for 5 minutes.
JARVIS: Timer set for 5 minutes. I'll let you know when it's up.

You: Jarvis, search for Python tutorials.
JARVIS: Opening Google search for Python tutorials.

You: Jarvis, explain how black holes work.
JARVIS: Certainly. A black hole is a region of spacetime where gravity...
```

---

## Requirements

- macOS (any version — tested on macOS Ventura and Sonoma)
- Python 3.9 or higher
- A free Claude API key from [console.anthropic.com](https://console.anthropic.com)
- A working microphone
- Internet connection (for speech recognition and Claude API calls only)

> Works on MacBook Air 2017 (Intel, 8GB RAM) and any newer Mac including M1/M2/M3.

---

## Installation

### Step 1 — Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/JARVIS-AI-Assistant.git
cd JARVIS-AI-Assistant
```

### Step 2 — Install PortAudio (required for microphone access on Mac)
```bash
brew install portaudio
```
> Don't have Homebrew? Install it first:
> ```bash
> /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
> ```

### Step 3 — Install Python dependencies
```bash
pip install SpeechRecognition pyttsx3 pyaudio anthropic requests
```

### Step 4 — Run JARVIS for the first time
```bash
python jarvis.py
```
On first launch, a `config.json` file is automatically created. The program will pause and ask you to add your API key.

### Step 5 — Add your Claude API key
Open `config.json` in any text editor:
```json
{
  "api_key": "YOUR_CLAUDE_API_KEY_HERE",
  "wake_word": "jarvis",
  "voice_rate": 175,
  "history_limit": 10
}
```
Get your free API key at [console.anthropic.com](https://console.anthropic.com), paste it in, save the file, and run `python jarvis.py` again.

---

## Voice Commands

### Built-in commands (instant, no API call)
| Say this | What happens |
|---|---|
| `"Jarvis, what time is it?"` | Speaks the current time |
| `"Jarvis, what's the date?"` | Speaks today's date |
| `"Jarvis, open browser"` | Opens your default browser |
| `"Jarvis, open terminal"` | Opens a new Terminal window |
| `"Jarvis, play music"` | Opens the macOS Music app |
| `"Jarvis, take a screenshot"` | Saves a screenshot to your desktop |
| `"Jarvis, set a timer for 10 minutes"` | Sets a spoken countdown timer |
| `"Jarvis, search for [anything]"` | Opens a Google search |
| `"Jarvis, remember that [fact]"` | Saves a fact to memory |
| `"Jarvis, do you remember [topic]?"` | Recalls a saved memory |
| `"Jarvis, goodbye"` | Shuts down gracefully |

### AI-powered commands (anything else)
Anything that doesn't match a built-in command is sent to Claude AI automatically. Ask it anything:
- *"Jarvis, explain quantum computing in simple terms."*
- *"Jarvis, write me a Python function that sorts a list."*
- *"Jarvis, what should I make for dinner with chicken and rice?"*
- *"Jarvis, translate 'hello' into Japanese."*

---

## Project Structure
```
JARVIS-AI-Assistant/
│
├── jarvis.py          # The entire program — single file, heavily commented
├── config.json        # Auto-generated on first run — add your API key here
├── jarvis_memory.db   # Auto-generated SQLite database for persistent memory
├── requirements.txt   # All pip dependencies
├── LICENSE            # MIT License
└── README.md          # This file
```

---

## Configuration

Edit `config.json` to customise JARVIS:
```json
{
  "api_key": "sk-ant-...",
  "wake_word": "jarvis",
  "voice_rate": 175,
  "history_limit": 10
}
```

| Key | Default | Description |
|---|---|---|
| `api_key` | `""` | Your Claude API key from Anthropic |
| `wake_word` | `"jarvis"` | The word that activates JARVIS (change to anything you like) |
| `voice_rate` | `175` | Speech speed in words per minute (150–200 recommended) |
| `history_limit` | `10` | How many messages of conversation history to keep per session |

---

## How it works
```
You speak
    ↓
Microphone captures audio (PyAudio)
    ↓
Google Speech Recognition converts audio → text
    ↓
Wake word check: does the text contain "jarvis"?
    ↓ yes
Command router checks for built-in skill match
    ↓ no match
Claude API processes the input + conversation history
    ↓
Response text sent to pyttsx3
    ↓
macOS voice speaks the response aloud
    ↓
Response + your message saved to conversation history
    ↓
Loop — back to listening
```

---

## Extending JARVIS

Adding a new skill is straightforward. Inside `jarvis.py`, find the `# ── BUILT-IN SKILLS ──` section and add a new block:
```python
# Check if the user wants to know the weather
elif "weather" in command or "forecast" in command:
    # Call a weather API here and return the result
    return get_weather()  # implement this function above
```

Because every section is clearly commented, you'll know exactly where each piece of the code lives.

---

## Troubleshooting

**`PyAudio` installation fails**
```bash
brew install portaudio
pip install --global-option='build_ext' --global-option='-I/usr/local/include' --global-option='-L/usr/local/lib' pyaudio
```

**JARVIS can't hear me / microphone not working**
Go to System Settings → Privacy & Security → Microphone and make sure Terminal (or your IDE) has microphone access enabled.

**Speech recognition returns errors**
Make sure you have an active internet connection — Google's free speech recognition requires it.

**Claude API returns an auth error**
Double-check your API key in `config.json`. Make sure there are no extra spaces. Generate a new key at [console.anthropic.com](https://console.anthropic.com) if needed.

---

## Roadmap

- [ ] GUI dashboard using `tkinter`
- [ ] Spotify / Apple Music playback control
- [ ] Email reading via Gmail API
- [ ] Weather skill via OpenWeatherMap API
- [ ] Calendar integration via macOS Calendar
- [ ] Custom wake word training
- [ ] Home Assistant / smart home integration
- [ ] Whisper API for better offline speech recognition

---

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you'd like to add. Make sure any new skills are commented in the same style as the existing code.

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## Acknowledgements

- [Anthropic](https://anthropic.com) for the Claude API
- [SpeechRecognition](https://github.com/Mybridge/recognize-speech) library
- [pyttsx3](https://github.com/nateshmbhat/pyttsx3) for offline TTS
- Inspired by the fictional JARVIS from the Iron Man / MCU universe

---

<div align="center">

**Built with Python · Powered by Claude AI · Made for macOS**

*"Sometimes you gotta run before you can walk." — Tony Stark*

</div>
