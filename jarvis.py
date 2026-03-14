#!/usr/bin/env python3

# ── IMPORTS ──────────────────────────────────────────────

"""
JARVIS is a single-file voice assistant for macOS.

This script is intentionally verbose and heavily commented so a beginner can
read through it section by section and understand how each part works.
"""

import datetime
import json
import os
import re
import subprocess
import threading
import webbrowser
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
except ImportError:
    requests = None

try:
    import speech_recognition as sr
except ImportError:
    sr = None

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    import pyaudio  # noqa: F401  # Imported so SpeechRecognition has its microphone backend.
except ImportError:
    pyaudio = None

try:
    import anthropic
except ImportError:
    anthropic = None

try:
    import psycopg2
except ImportError:
    psycopg2 = None


# ── CONFIG LOADER ────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG = {
    "api_key": "",
    "wake_word": "jarvis",
    "voice_rate": 175,
    "history_limit": 10,
    "db_host": "localhost",
    "db_port": 5432,
    "db_name": "jarvis",
    "db_user": "postgres",
    "db_password": "",
    "db_sslmode": "prefer",
}

SYSTEM_PROMPT = (
    "You are JARVIS, a helpful, concise, and witty AI assistant inspired by Iron Man."
)


def load_config() -> Dict[str, Any]:
    """
    Load the assistant configuration from config.json.

    If the file does not exist, this function creates it with safe defaults.
    If the file exists but is invalid JSON, this function repairs it by writing
    a fresh default configuration back to disk.

    Parameters:
        None.

    Returns:
        Dict[str, Any]: A dictionary containing the active configuration values.
    """
    # Start with a copy of the defaults so we always have every required key.
    config = DEFAULT_CONFIG.copy()

    # Create config.json on first run so the user has somewhere to place the API key.
    if not os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as config_file:
                json.dump(config, config_file, indent=4)

            print(f"[CONFIG] Created default config file at: {CONFIG_PATH}")
            print("[CONFIG] Please add your Claude API key to config.json to enable AI replies.")
        except Exception as error:
            print(f"[CONFIG] Could not create config.json: {error}")

        return config

    # Read the existing file if it is present.
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
            loaded_config = json.load(config_file)

        # Only merge dictionaries so malformed JSON structures do not break the program.
        if isinstance(loaded_config, dict):
            config.update(loaded_config)
        else:
            print("[CONFIG] config.json did not contain a JSON object. Using defaults instead.")
    except Exception as error:
        print(f"[CONFIG] Could not read config.json cleanly: {error}")
        print("[CONFIG] Rebuilding config.json with default values.")

        # Write a repaired default config so the next startup is clean.
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as config_file:
                json.dump(config, config_file, indent=4)
        except Exception as write_error:
            print(f"[CONFIG] Could not repair config.json: {write_error}")

    # Make sure the numeric settings are always sensible integers.
    try:
        config["voice_rate"] = int(config.get("voice_rate", DEFAULT_CONFIG["voice_rate"]))
    except Exception:
        config["voice_rate"] = DEFAULT_CONFIG["voice_rate"]

    try:
        config["history_limit"] = int(config.get("history_limit", DEFAULT_CONFIG["history_limit"]))
    except Exception:
        config["history_limit"] = DEFAULT_CONFIG["history_limit"]

    # Keep the PostgreSQL port as an integer so database connections stay predictable.
    try:
        config["db_port"] = int(config.get("db_port", DEFAULT_CONFIG["db_port"]))
    except Exception:
        config["db_port"] = DEFAULT_CONFIG["db_port"]

    # Normalize the wake word so later string matching is simple and predictable.
    config["wake_word"] = str(config.get("wake_word", DEFAULT_CONFIG["wake_word"])).strip().lower()
    config["api_key"] = str(config.get("api_key", "")).strip()
    config["db_host"] = str(config.get("db_host", DEFAULT_CONFIG["db_host"])).strip()
    config["db_name"] = str(config.get("db_name", DEFAULT_CONFIG["db_name"])).strip()
    config["db_user"] = str(config.get("db_user", DEFAULT_CONFIG["db_user"])).strip()
    config["db_password"] = str(config.get("db_password", DEFAULT_CONFIG["db_password"]))
    config["db_sslmode"] = str(config.get("db_sslmode", DEFAULT_CONFIG["db_sslmode"])).strip()

    # Rewrite the config if any required keys were missing.
    missing_keys = [key for key in DEFAULT_CONFIG if key not in config]
    if missing_keys:
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as config_file:
                json.dump(config, config_file, indent=4)
        except Exception as error:
            print(f"[CONFIG] Could not update config.json with missing keys: {error}")

    return config


CONFIG = load_config()


# ── DATABASE / MEMORY SETUP ──────────────────────────────


def get_database_connection() -> Optional[Any]:
    """
    Open a PostgreSQL connection using values from config.json.

    Parameters:
        None.

    Returns:
        Optional[Any]: A live psycopg2 connection object, or None if the driver
        is missing or the database connection fails.
    """
    # Stop early if the PostgreSQL driver is not installed yet.
    if psycopg2 is None:
        print("[MEMORY] psycopg2 is not installed. PostgreSQL memory is unavailable.")
        return None

    try:
        # Read the database settings directly from the active config.
        return psycopg2.connect(
            host=CONFIG.get("db_host", "localhost"),
            port=CONFIG.get("db_port", 5432),
            dbname=CONFIG.get("db_name", "jarvis"),
            user=CONFIG.get("db_user", "postgres"),
            password=CONFIG.get("db_password", ""),
            sslmode=CONFIG.get("db_sslmode", "prefer"),
            connect_timeout=5,
        )
    except Exception as error:
        print(f"[MEMORY] PostgreSQL connection failed: {error}")
        return None


def initialize_database() -> None:
    """
    Create the PostgreSQL memory table if it does not already exist.

    The table stores short facts the user asks JARVIS to remember. Each row
    includes a key, a value, and a timestamp so the latest memory can be found.

    Parameters:
        None.

    Returns:
        None.
    """
    # Open a database connection using the PostgreSQL settings from config.json.
    connection = get_database_connection()

    if connection is None:
        return

    try:
        cursor = connection.cursor()

        # Create the memory table once and leave it in place for future runs.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS memory (
                id SERIAL PRIMARY KEY,
                "key" TEXT NOT NULL,
                "value" TEXT NOT NULL,
                timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        connection.commit()
    except Exception as error:
        print(f"[MEMORY] Database initialization failed: {error}")
    finally:
        # Always close the database connection so the file is not left locked.
        if connection is not None:
            connection.close()


def save_memory(key: str, value: str) -> bool:
    """
    Save a memory fact into PostgreSQL.

    Parameters:
        key (str): The short lookup phrase for the fact, such as "my wife's name".
        value (str): The stored fact body, such as "is Sarah".

    Returns:
        bool: True if the memory was saved successfully, otherwise False.
    """
    # Build a timestamp so we know when the memory was recorded.
    timestamp = datetime.datetime.now()
    connection = get_database_connection()

    if connection is None:
        return False

    try:
        cursor = connection.cursor()

        # Insert the new memory as a fresh row so older memories are preserved too.
        cursor.execute(
            'INSERT INTO memory ("key", "value", timestamp) VALUES (%s, %s, %s)',
            (key.strip().lower(), value.strip(), timestamp),
        )

        connection.commit()
        return True
    except Exception as error:
        print(f"[MEMORY] Could not save memory: {error}")
        return False
    finally:
        # Close the database connection whether the insert worked or not.
        if connection is not None:
            connection.close()


def recall_memory(key: str) -> Optional[Dict[str, str]]:
    """
    Retrieve the newest memory that matches a key or related phrase.

    Parameters:
        key (str): The phrase to look up, such as "my wife's name".

    Returns:
        Optional[Dict[str, str]]: A dictionary with key, value, and timestamp if
        a memory is found, otherwise None.
    """
    # Normalize the lookup phrase so searches are case-insensitive.
    cleaned_key = key.strip().lower()
    connection = get_database_connection()

    if connection is None:
        return None

    try:
        cursor = connection.cursor()

        # First try an exact match because it gives the cleanest result.
        cursor.execute(
            """
            SELECT "key", "value", timestamp
            FROM memory
            WHERE lower("key") = %s OR lower("value") = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (cleaned_key, cleaned_key),
        )
        row = cursor.fetchone()

        # If the exact search fails, fall back to a partial search.
        if row is None:
            like_pattern = f"%{cleaned_key}%"
            cursor.execute(
                """
                SELECT "key", "value", timestamp
                FROM memory
                WHERE lower("key") LIKE %s OR lower("value") LIKE %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (like_pattern, like_pattern),
            )
            row = cursor.fetchone()

        # Convert the PostgreSQL row into a friendlier dictionary.
        if row is not None:
            return {"key": row[0], "value": row[1], "timestamp": row[2]}

        return None
    except Exception as error:
        print(f"[MEMORY] Could not recall memory: {error}")
        return None
    finally:
        # Close the connection every time so repeated lookups stay reliable.
        if connection is not None:
            connection.close()


initialize_database()


# ── TEXT-TO-SPEECH ENGINE ────────────────────────────────

tts_lock = threading.Lock()
tts_engine = None


def choose_best_macos_voice(engine: Any) -> Optional[str]:
    """
    Pick a pleasant built-in macOS voice if one is available.

    Parameters:
        engine (Any): The pyttsx3 engine instance.

    Returns:
        Optional[str]: The selected voice ID, or None if no preferred voice
        could be identified.
    """
    # Ask pyttsx3 for every voice it can see on this Mac.
    try:
        available_voices = engine.getProperty("voices")
    except Exception as error:
        print(f"[TTS] Could not read voices: {error}")
        return None

    # Prefer well-known macOS voices in a simple highest-to-lowest order.
    preferred_names = [
        "alex",
        "samantha",
        "daniel",
        "victoria",
        "allison",
    ]

    # Search by human-readable name first because that is easiest to understand.
    for preferred_name in preferred_names:
        for voice in available_voices:
            voice_name = str(getattr(voice, "name", "")).lower()
            voice_id = str(getattr(voice, "id", "")).lower()

            if preferred_name in voice_name or preferred_name in voice_id:
                return getattr(voice, "id", None)

    # If none of the favorites are present, just use the first voice on the system.
    if available_voices:
        return getattr(available_voices[0], "id", None)

    return None


def initialize_tts_engine() -> Optional[Any]:
    """
    Initialize pyttsx3 for offline text-to-speech.

    Parameters:
        None.

    Returns:
        Optional[Any]: A ready pyttsx3 engine, or None if initialization fails.
    """
    # Gracefully continue if the text-to-speech package is missing.
    if pyttsx3 is None:
        print("[TTS] pyttsx3 is not installed. Spoken responses will be disabled.")
        return None

    try:
        engine = pyttsx3.init()

        # Apply the speaking rate from config so speech is a little slower and clearer.
        engine.setProperty("rate", CONFIG.get("voice_rate", 175))

        # Try to choose a strong built-in Mac voice for better sound quality.
        best_voice_id = choose_best_macos_voice(engine)
        if best_voice_id:
            engine.setProperty("voice", best_voice_id)

        return engine
    except Exception as error:
        print(f"[TTS] Engine initialization failed: {error}")
        return None


def speak(text: str) -> None:
    """
    Print and speak a line of JARVIS dialogue.

    Parameters:
        text (str): The message JARVIS should say out loud.

    Returns:
        None.
    """
    # Always print the response so the user can still read it in the terminal.
    print(f"JARVIS: {text}")

    # If text-to-speech is unavailable, printing is still better than failing.
    if tts_engine is None:
        return

    # Lock the engine so the main thread and timer threads do not speak at once.
    with tts_lock:
        try:
            tts_engine.say(text)
            tts_engine.runAndWait()
        except Exception as error:
            print(f"[TTS] Speaking failed: {error}")


tts_engine = initialize_tts_engine()


# ── SPEECH RECOGNITION ───────────────────────────────────


def initialize_speech_system() -> Tuple[Optional[Any], Optional[Any]]:
    """
    Prepare the speech recognizer and microphone for voice input.

    Parameters:
        None.

    Returns:
        Tuple[Optional[Any], Optional[Any]]: A tuple containing the recognizer
        and microphone objects, or (None, None) if setup fails.
    """
    # Make sure the microphone libraries are installed before trying to listen.
    if sr is None:
        print("[SPEECH] SpeechRecognition is not installed.")
        return None, None

    if pyaudio is None:
        print("[SPEECH] PyAudio is not installed, so microphone input is unavailable.")
        return None, None

    try:
        recognizer = sr.Recognizer()
        microphone = sr.Microphone()

        # Adjust the recognizer to the room noise level one time during startup.
        with microphone as source:
            print("[SPEECH] Calibrating microphone for ambient noise...")
            recognizer.adjust_for_ambient_noise(source, duration=1)

        # A slightly shorter pause threshold makes voice control feel more responsive.
        recognizer.pause_threshold = 0.8
        recognizer.dynamic_energy_threshold = True

        return recognizer, microphone
    except Exception as error:
        print(f"[SPEECH] Could not initialize microphone input: {error}")
        return None, None


def listen_for_speech(
    recognizer: Any,
    microphone: Any,
    active_listen: bool = False,
    timeout: Optional[int] = None,
    phrase_time_limit: Optional[int] = None,
) -> Optional[str]:
    """
    Capture audio from the microphone and convert it into text.

    Parameters:
        recognizer (Any): The SpeechRecognition recognizer instance.
        microphone (Any): The SpeechRecognition microphone instance.
        active_listen (bool): True when JARVIS is actively waiting for a command.
        timeout (Optional[int]): How many seconds to wait for speech to start.
        phrase_time_limit (Optional[int]): How many seconds a spoken phrase can last.

    Returns:
        Optional[str]: The recognized text in lowercase, or None if recognition fails.
    """
    # Stop early if microphone support is unavailable.
    if recognizer is None or microphone is None or sr is None:
        if active_listen:
            speak("Microphone support is unavailable right now, sir.")
        return None

    try:
        # Open the microphone stream only while we are actively listening.
        with microphone as source:
            if active_listen:
                print("[LISTENING] Awaiting your command...")
            else:
                print("[LISTENING] Waiting for wake word...")

            audio = recognizer.listen(
                source,
                timeout=timeout,
                phrase_time_limit=phrase_time_limit,
            )
    except sr.WaitTimeoutError:
        # Silence during active listening should produce a polite spoken fallback.
        if active_listen:
            speak("I didn't catch that, sir.")
        return None
    except Exception as error:
        print(f"[SPEECH] Audio capture failed: {error}")
        if active_listen:
            speak("I had trouble hearing you, sir.")
        return None

    try:
        # Google Speech Recognition returns plain text for the recorded audio.
        transcript = recognizer.recognize_google(audio)
        cleaned_transcript = transcript.strip().lower()
        print(f"YOU: {transcript}")
        return cleaned_transcript
    except sr.UnknownValueError:
        # This is the specific error we expect when speech is unclear.
        if active_listen:
            speak("I didn't catch that, sir.")
        return None
    except sr.RequestError as error:
        print(f"[SPEECH] Google recognition service failed: {error}")
        speak("Speech recognition is unavailable right now.")
        return None
    except Exception as error:
        print(f"[SPEECH] Unexpected speech recognition error: {error}")
        if active_listen:
            speak("I didn't catch that, sir.")
        return None


# ── AI BRAIN (CLAUDE API) ────────────────────────────────

conversation_history: List[Dict[str, str]] = []


def initialize_anthropic_client() -> Optional[Any]:
    """
    Create the Anthropic API client used for Claude conversations.

    Parameters:
        None.

    Returns:
        Optional[Any]: An Anthropic client if the API key and package are available,
        otherwise None.
    """
    # Do not create the client if the SDK package is missing.
    if anthropic is None:
        print("[AI] The anthropic package is not installed.")
        return None

    # Do not create the client if the user has not added an API key yet.
    if not CONFIG.get("api_key"):
        print("[AI] No Claude API key found in config.json. Local commands will still work.")
        return None

    try:
        return anthropic.Anthropic(api_key=CONFIG["api_key"])
    except Exception as error:
        print(f"[AI] Could not initialize Anthropic client: {error}")
        return None


def trim_history() -> None:
    """
    Keep only the newest messages in memory so the conversation stays efficient.

    Parameters:
        None.

    Returns:
        None.
    """
    global conversation_history

    # Read the configured history limit and protect against invalid values.
    history_limit = max(1, int(CONFIG.get("history_limit", 10)))

    # Slice the list so only the latest messages remain.
    conversation_history = conversation_history[-history_limit:]


def extract_text_from_claude_response(response: Any) -> str:
    """
    Convert an Anthropic response object into plain text.

    Parameters:
        response (Any): The object returned by client.messages.create(...).

    Returns:
        str: The assistant text extracted from the response.
    """
    # Collect all text blocks because Claude may return multiple content segments.
    text_parts: List[str] = []

    try:
        for block in getattr(response, "content", []):
            if getattr(block, "type", "") == "text":
                text_parts.append(getattr(block, "text", "").strip())
    except Exception as error:
        print(f"[AI] Could not parse Claude response blocks: {error}")

    # Join the parts into a single readable sentence or paragraph.
    combined_text = " ".join(part for part in text_parts if part).strip()

    return combined_text or "I seem to be momentarily speechless, sir."


def ask_claude(client: Any, user_text: str) -> str:
    """
    Send the user's request to Claude and return the assistant's reply.

    Parameters:
        client (Any): The initialized Anthropic client.
        user_text (str): The user's spoken request.

    Returns:
        str: Claude's reply text, or a friendly fallback message if the API fails.
    """
    global conversation_history

    # If the client is unavailable, explain how to enable AI mode.
    if client is None:
        return "My Claude API key is missing or unavailable. Please add it to config.json."

    try:
        # Build the conversation to send, including the newest user message.
        history_limit = max(1, int(CONFIG.get("history_limit", 10)))
        request_messages = (conversation_history + [{"role": "user", "content": user_text}])[-history_limit:]

        # Call the Anthropic Messages API with the requested Claude model.
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            system=SYSTEM_PROMPT,
            max_tokens=500,
            messages=request_messages,
        )

        # Convert Claude's structured response into a plain string.
        assistant_text = extract_text_from_claude_response(response)

        # Save both sides of the exchange so the session remembers context.
        conversation_history = request_messages + [{"role": "assistant", "content": assistant_text}]
        trim_history()

        return assistant_text
    except Exception as error:
        print(f"[AI] Claude API call failed: {error}")
        return "I'm having trouble connecting to my brain right now."


anthropic_client = initialize_anthropic_client()


# ── BUILT-IN SKILLS ──────────────────────────────────────

active_timers: List[threading.Timer] = []


def parse_memory_fact(fact_text: str) -> Tuple[str, str, str]:
    """
    Turn a raw remembered sentence into a key/value pair for PostgreSQL.

    Parameters:
        fact_text (str): The spoken fact after the words "remember that".

    Returns:
        Tuple[str, str, str]: A tuple containing the lookup key, the stored value,
        and the original cleaned sentence.
    """
    # Remove extra punctuation so the saved memory stays neat.
    cleaned_fact = fact_text.strip().rstrip(".!?")

    # Try to split simple facts like "my dog's name is Bruno" into key and value.
    match = re.match(r"(.+?)\s+(is|are|am|was|were)\s+(.+)", cleaned_fact, flags=re.IGNORECASE)

    if match:
        subject = match.group(1).strip().lower()
        verb = match.group(2).strip().lower()
        predicate = match.group(3).strip()
        stored_value = f"{verb} {predicate}"
        return subject, stored_value, cleaned_fact

    # If the sentence does not fit the pattern, store the whole sentence as both key and value.
    return cleaned_fact.lower(), cleaned_fact, cleaned_fact


def build_memory_sentence(memory: Dict[str, str]) -> str:
    """
    Turn a stored memory row back into a natural sentence for speech.

    Parameters:
        memory (Dict[str, str]): The memory dictionary returned by recall_memory().

    Returns:
        str: A human-friendly sentence that JARVIS can read aloud.
    """
    # Rebuild the sentence depending on how the memory was originally stored.
    key = memory["key"].strip()
    value = memory["value"].strip()

    if value.lower().startswith(("is ", "are ", "am ", "was ", "were ")):
        return f"{key} {value}"

    if key.lower() == value.lower():
        return value

    return f"{key}: {value}"


def open_application(app_name: str) -> bool:
    """
    Open a macOS application by name using the built-in `open` command.

    Parameters:
        app_name (str): The name of the application, such as "Music" or "Terminal".

    Returns:
        bool: True if the launch command was sent successfully, otherwise False.
    """
    try:
        subprocess.Popen(["open", "-a", app_name])
        return True
    except Exception as error:
        print(f"[SKILL] Could not open {app_name}: {error}")
        return False


def take_screenshot() -> str:
    """
    Capture a screenshot using macOS's built-in screencapture command.

    Parameters:
        None.

    Returns:
        str: A spoken response describing where the screenshot was saved.
    """
    # Prefer the Desktop for saved screenshots because it is easy for most users to find.
    desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
    target_folder = desktop_path if os.path.isdir(desktop_path) else BASE_DIR

    # Use a timestamped file name so each screenshot is unique.
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    screenshot_path = os.path.join(target_folder, f"jarvis_screenshot_{timestamp}.png")

    try:
        subprocess.run(["screencapture", screenshot_path], check=True)
        return f"Screenshot taken, sir. I saved it to {screenshot_path}."
    except Exception as error:
        print(f"[SKILL] Screenshot failed: {error}")
        return "I couldn't take the screenshot, sir."


def timer_finished(minutes: float) -> None:
    """
    Speak a reminder when a timer reaches zero.

    Parameters:
        minutes (float): The timer length in minutes, used in the spoken alert.

    Returns:
        None.
    """
    # Announce the finished timer out loud and in the terminal.
    speak(f"Sir, your {minutes:g}-minute timer is complete.")


def set_timer(minutes: float) -> str:
    """
    Create a background timer that announces itself when finished.

    Parameters:
        minutes (float): The requested timer duration in minutes.

    Returns:
        str: A spoken confirmation or error message.
    """
    # Reject empty, negative, or zero-length timers before creating anything.
    if minutes <= 0:
        return "That timer needs to be longer than zero minutes, sir."

    try:
        # Convert minutes to seconds because threading.Timer works in seconds.
        timer = threading.Timer(minutes * 60, timer_finished, args=[minutes])
        timer.daemon = True  # Make sure timers do not block the program from closing.
        timer.start()
        active_timers.append(timer)
        return f"Timer set for {minutes:g} minutes, sir."
    except Exception as error:
        print(f"[SKILL] Timer creation failed: {error}")
        return "I couldn't set that timer, sir."


def handle_builtin_command(command: str) -> Tuple[bool, str, bool]:
    """
    Check whether a command matches a built-in local skill.

    Parameters:
        command (str): The user's recognized speech in lowercase text.

    Returns:
        Tuple[bool, str, bool]: A tuple of:
            - handled (bool): True if a local skill matched
            - response (str): The response JARVIS should speak
            - should_exit (bool): True if the main loop should shut down
    """
    # Normalize the command once so every skill check uses the same text.
    command = command.strip()
    command_lower = command.lower()

    # Stop commands should exit gracefully without calling the AI.
    if command_lower in {"stop", "exit", "goodbye", "shut down"}:
        return True, "Goodbye, sir. Shutting down.", True

    # Time queries are answered locally because no internet or AI is required.
    if "what time is it" in command_lower or "current time" in command_lower:
        current_time = datetime.datetime.now().strftime("%I:%M %p")
        return True, f"The time is {current_time}, sir.", False

    # Date queries are also simple local lookups.
    if (
        "what's the date" in command_lower
        or "what is the date" in command_lower
        or "today's date" in command_lower
    ):
        today = datetime.datetime.now().strftime("%A, %B %d, %Y")
        return True, f"Today's date is {today}.", False

    # Open the default browser for a generic browser request.
    if "open browser" in command_lower:
        try:
            webbrowser.open("https://www.google.com")
            return True, "Opening your browser, sir.", False
        except Exception as error:
            print(f"[SKILL] Browser launch failed: {error}")
            return True, "I couldn't open the browser, sir.", False

    # Open Google Chrome directly when requested, then fall back to the default browser.
    if "open chrome" in command_lower:
        if open_application("Google Chrome"):
            return True, "Opening Google Chrome, sir.", False

        try:
            webbrowser.open("https://www.google.com")
            return True, "Chrome was unavailable, so I opened your default browser instead.", False
        except Exception:
            return True, "I couldn't open Chrome or your browser, sir.", False

    # Open Safari directly when requested, then fall back to the default browser.
    if "open safari" in command_lower:
        if open_application("Safari"):
            return True, "Opening Safari, sir.", False

        try:
            webbrowser.open("https://www.google.com")
            return True, "Safari was unavailable, so I opened your default browser instead.", False
        except Exception:
            return True, "I couldn't open Safari or your browser, sir.", False

    # Launch the macOS Music app for music-related commands.
    if "open music" in command_lower or "play music" in command_lower:
        if open_application("Music"):
            return True, "Opening Music, sir.", False
        return True, "I couldn't open the Music app, sir.", False

    # Launch the Terminal app with macOS's built-in application launcher.
    if "open terminal" in command_lower:
        if open_application("Terminal"):
            return True, "Opening Terminal, sir.", False
        return True, "I couldn't open Terminal, sir.", False

    # Run macOS's screenshot tool when asked.
    if "take a screenshot" in command_lower:
        return True, take_screenshot(), False

    # Parse memory storage requests like "remember that my dog's name is Bruno".
    if command_lower.startswith("remember that "):
        fact_text = command[14:].strip()
        if not fact_text:
            return True, "Tell me what you would like me to remember, sir.", False

        key, value, cleaned_fact = parse_memory_fact(fact_text)
        if save_memory(key, value):
            return True, f"I'll remember that {cleaned_fact}.", False

        return True, "I couldn't store that memory, sir.", False

    # Parse memory recall requests in two natural phrasings.
    if command_lower.startswith("do you remember "):
        lookup_key = command[16:].strip().rstrip("?")
        memory = recall_memory(lookup_key)

        if memory is not None:
            return True, f"Yes, sir. I remember that {build_memory_sentence(memory)}.", False

        return True, f"I don't remember anything about {lookup_key}, sir.", False

    if command_lower.startswith("what do you know about "):
        lookup_key = command[23:].strip().rstrip("?")
        memory = recall_memory(lookup_key)

        if memory is not None:
            return True, f"I remember that {build_memory_sentence(memory)}.", False

        return True, f"I don't know anything about {lookup_key} yet, sir.", False

    # Detect timer requests and extract the number of minutes.
    timer_match = re.search(
        r"set a timer for\s+(\d+(?:\.\d+)?)\s+minutes?",
        command_lower,
    )
    if timer_match:
        minutes = float(timer_match.group(1))
        return True, set_timer(minutes), False

    # Search the web by opening a Google results page in the browser.
    if command_lower.startswith("search for ") or command_lower.startswith("google "):
        if command_lower.startswith("search for "):
            search_query = command[11:].strip()
        else:
            search_query = command[7:].strip()

        if not search_query:
            return True, "Tell me what you want me to search for, sir.", False

        try:
            # Use requests' quote_plus helper if available, otherwise fall back to raw text.
            encoded_query = (
                requests.compat.quote_plus(search_query) if requests is not None else search_query
            )
            search_url = f"https://www.google.com/search?q={encoded_query}"
            webbrowser.open(search_url)
            return True, f"Searching Google for {search_query}, sir.", False
        except Exception as error:
            print(f"[SKILL] Web search failed: {error}")
            return True, "I couldn't open that search, sir.", False

    # No local skill matched, so the command should be handled by Claude instead.
    return False, "", False


# ── COMMAND ROUTER ───────────────────────────────────────


def route_command(command: str) -> bool:
    """
    Send a recognized command to either a local skill or the Claude API.

    Parameters:
        command (str): The user's command text.

    Returns:
        bool: True if JARVIS should exit after handling the command, otherwise False.
    """
    # Ignore empty commands so a failed recognition does not trigger extra work.
    if not command or not command.strip():
        return False

    try:
        # Check fast built-in skills before spending time and money on an API call.
        handled, response, should_exit = handle_builtin_command(command)

        if handled:
            speak(response)
            return should_exit

        # If no skill matched, send the full request to Claude.
        ai_reply = ask_claude(anthropic_client, command)
        speak(ai_reply)
        return False
    except Exception as error:
        print(f"[ROUTER] Command routing failed: {error}")
        speak("Something went wrong while handling that request, sir.")
        return False


# ── WAKE WORD LISTENER ───────────────────────────────────


def listen_for_wake_word(recognizer: Any, microphone: Any) -> Optional[str]:
    """
    Listen for the wake word and optionally capture an inline command.

    For example:
        - "Jarvis" returns an empty string, which means JARVIS should ask for the command.
        - "Jarvis open terminal" returns "open terminal".

    Parameters:
        recognizer (Any): The SpeechRecognition recognizer.
        microphone (Any): The SpeechRecognition microphone.

    Returns:
        Optional[str]: An empty string or command if the wake word is heard,
        otherwise None.
    """
    # Listen in short bursts so the program can keep looping smoothly.
    heard_text = listen_for_speech(
        recognizer,
        microphone,
        active_listen=False,
        timeout=5,
        phrase_time_limit=5,
    )

    # If nothing was recognized, simply continue waiting.
    if heard_text is None:
        return None

    wake_word = CONFIG.get("wake_word", "jarvis").strip().lower()

    # Use simple string matching for the wake word, as requested.
    if wake_word not in heard_text:
        return None

    # Split on the first wake word so extra words become the immediate command.
    remaining_text = heard_text.split(wake_word, 1)[1].strip(" ,.!?")
    return remaining_text


# ── MAIN LOOP ────────────────────────────────────────────

BANNER = r"""
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
         Just A Rather Very Intelligent System
"""


def startup_sequence() -> None:
    """
    Show the JARVIS banner and speak the startup announcement.

    Parameters:
        None.

    Returns:
        None.
    """
    # Print the banner exactly once so the terminal has a clear startup moment.
    print(BANNER)
    print("[SYSTEM] JARVIS is starting up...")

    # Let the user know if AI mode is disabled because the key is missing.
    if not CONFIG.get("api_key"):
        print("[SYSTEM] Add your Claude API key to config.json to enable AI conversations.")

    # Let the user know which PostgreSQL database JARVIS will try to use for memory.
    print(
        "[SYSTEM] PostgreSQL memory target: "
        f"{CONFIG.get('db_user')}@{CONFIG.get('db_host')}:{CONFIG.get('db_port')}/{CONFIG.get('db_name')}"
    )

    # Warn early if the PostgreSQL driver is not installed.
    if psycopg2 is None:
        print("[SYSTEM] Install psycopg2-binary to enable PostgreSQL memory storage.")

    # Announce that the assistant is ready for voice commands.
    speak("JARVIS online. All systems operational. How can I assist you?")


def main() -> None:
    """
    Run the full JARVIS assistant loop.

    Parameters:
        None.

    Returns:
        None.
    """
    # Wrap the whole application so any unexpected error is handled gracefully.
    try:
        startup_sequence()

        # Initialize the microphone system after startup speech is complete.
        recognizer, microphone = initialize_speech_system()

        if recognizer is None or microphone is None:
            speak("Microphone initialization failed. Please check your permissions and dependencies, sir.")
            return

        # Keep listening until the user explicitly tells JARVIS to stop.
        while True:
            try:
                # First wait passively for the configured wake word.
                wake_result = listen_for_wake_word(recognizer, microphone)

                if wake_result is None:
                    continue

                # If the user only said the wake word, ask what they need next.
                if wake_result == "":
                    speak("Yes, sir?")
                    command = listen_for_speech(
                        recognizer,
                        microphone,
                        active_listen=True,
                        timeout=10,
                        phrase_time_limit=12,
                    )
                else:
                    command = wake_result

                # Skip the router when no valid command text was captured.
                if not command:
                    continue

                # Route the command and break out of the loop if shutdown was requested.
                if route_command(command):
                    break
            except KeyboardInterrupt:
                # Allow Ctrl+C to shut the assistant down cleanly.
                speak("Keyboard interrupt received. Shutting down, sir.")
                break
            except Exception as loop_error:
                print(f"[MAIN LOOP] Unexpected loop error: {loop_error}")
                speak("I ran into a problem, but I'm still online, sir.")
    except KeyboardInterrupt:
        # Catch keyboard interrupts that happen outside the inner loop as well.
        speak("Shutting down, sir.")
    except Exception as error:
        print(f"[FATAL] Unhandled startup error: {error}")
        speak("A critical error occurred, but I am shutting down safely, sir.")


if __name__ == "__main__":
    main()
