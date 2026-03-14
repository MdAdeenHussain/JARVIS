#!/usr/bin/env python3
from __future__ import annotations

# ══════════════════════════════════════════════════════════
# ██  IMPORTS
# ══════════════════════════════════════════════════════════

"""
JARVIS is a production-oriented, single-file voice assistant for macOS.

This version is designed around five core ideas:
1. Secrets come only from `.env`.
2. PostgreSQL stores memory, conversation logs, AI usage, and reminders.
3. Gemini is the preferred AI path, with Groq as a fast fallback.
4. Background threads handle wake listening, reminders, and animation.
5. pyttsx3 text-to-speech is kept on the main thread for stability.
"""

import datetime
import itertools
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    import speech_recognition as sr
except ImportError:
    sr = None

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    import pyaudio  # noqa: F401  # Imported so microphone backends can initialize correctly.
except ImportError:
    pyaudio = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    import psycopg2
    from psycopg2.pool import SimpleConnectionPool
except ImportError:
    psycopg2 = None
    SimpleConnectionPool = None


# ══════════════════════════════════════════════════════════
# ██  ENVIRONMENT & CONFIG LOADER
# ══════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
LOG_PATH = BASE_DIR / "jarvis.log"

SYSTEM_PROMPT = (
    "You are JARVIS, a highly intelligent, concise, and witty AI assistant inspired by Iron Man. "
    "You are running on a Mac. Keep responses under 3 sentences unless the user asks for detail. "
    "Never break character."
)

BANNER = r"""
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
         Just A Rather Very Intelligent System
"""

REQUIRED_ENV_KEYS = [
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "DB_HOST",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DB_PORT",
    "WAKE_WORD",
    "VOICE_RATE",
    "HISTORY_LIMIT",
    "PRIMARY_AI",
]


@dataclass
class AppConfig:
    """
    Hold validated runtime configuration loaded from `.env`.

    Parameters:
        gemini_api_key (str): API key for Gemini.
        groq_api_key (str): API key for Groq.
        db_host (str): PostgreSQL host name.
        db_name (str): PostgreSQL database name.
        db_user (str): PostgreSQL username.
        db_password (str): PostgreSQL password.
        db_port (int): PostgreSQL port number.
        wake_word (str): Wake word JARVIS listens for.
        voice_rate (int): Text-to-speech speaking rate.
        history_limit (int): Maximum number of provider-specific history messages to retain.
        primary_ai (str): Preferred AI provider at startup.

    Returns:
        None.
    """

    gemini_api_key: str
    groq_api_key: str
    db_host: str
    db_name: str
    db_user: str
    db_password: str
    db_port: int
    wake_word: str
    voice_rate: int
    history_limit: int
    primary_ai: str


def parse_int_env(key: str, fallback: int) -> int:
    """
    Parse an integer environment variable safely.

    Parameters:
        key (str): The environment variable name to parse.
        fallback (int): The fallback integer value if parsing fails.

    Returns:
        int: A valid integer value.

    Exceptions:
        This function does not raise exceptions; invalid values fall back safely.
    """
    # ── read the raw environment variable text ──
    raw_value = os.getenv(key, "").strip()

    # ── convert the text to an integer when possible ──
    try:
        return int(raw_value)
    except Exception:
        return fallback


def load_and_validate_environment() -> Optional[AppConfig]:
    """
    Load `.env`, validate required keys, and build the application config.

    Parameters:
        None.

    Returns:
        Optional[AppConfig]: A validated config object, or None when validation fails.

    Exceptions:
        This function does not raise exceptions; it prints helpful guidance and returns None.
    """
    # ── ensure python-dotenv is available before trying to load secrets ──
    if load_dotenv is None:
        print("Missing dependency: python-dotenv")
        print("Install dependencies and then check your .env file before starting JARVIS.")
        return None

    # ── load environment variables from the project-local .env file ──
    load_dotenv(ENV_PATH)

    # ── collect any required keys that are unset or blank ──
    missing_keys = [key for key in REQUIRED_ENV_KEYS if not os.getenv(key, "").strip()]
    if missing_keys:
        for missing_key in missing_keys:
            print(f"Missing required environment variable: {missing_key}")
        print("Please check your .env file and add the missing values before starting JARVIS.")
        return None

    # ── normalize the configured primary provider to a supported value ──
    primary_ai = os.getenv("PRIMARY_AI", "gemini").strip().lower()
    if primary_ai not in {"gemini", "groq"}:
        primary_ai = "gemini"

    # ── build the validated runtime configuration object ──
    return AppConfig(
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        db_host=os.getenv("DB_HOST", "").strip(),
        db_name=os.getenv("DB_NAME", "").strip(),
        db_user=os.getenv("DB_USER", "").strip(),
        db_password=os.getenv("DB_PASSWORD", ""),
        db_port=parse_int_env("DB_PORT", 5432),
        wake_word=os.getenv("WAKE_WORD", "jarvis").strip().lower(),
        voice_rate=parse_int_env("VOICE_RATE", 175),
        history_limit=max(1, parse_int_env("HISTORY_LIMIT", 10)),
        primary_ai=primary_ai,
    )


# ══════════════════════════════════════════════════════════
# ██  LOGGING SYSTEM
# ══════════════════════════════════════════════════════════


def setup_logging() -> logging.Logger:
    """
    Configure rotating file logging for JARVIS.

    Parameters:
        None.

    Returns:
        logging.Logger: The configured application logger.

    Exceptions:
        This function does not raise exceptions; it falls back to a basic logger if needed.
    """
    # ── create a dedicated application logger that only writes to file ──
    logger = logging.getLogger("jarvis")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # ── avoid duplicate handlers when the module is re-imported ──
    if logger.handlers:
        return logger

    # ── configure log rotation so the file never grows without bound ──
    try:
        handler = RotatingFileHandler(
            LOG_PATH,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    except Exception:
        logging.basicConfig(
            level=logging.INFO,
            format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    return logger


LOGGER = setup_logging()


# ══════════════════════════════════════════════════════════
# ██  DATABASE — POSTGRESQL
# ══════════════════════════════════════════════════════════


class DatabaseManager:
    """
    Manage pooled PostgreSQL access for JARVIS.

    Parameters:
        config (AppConfig): Validated application configuration.
        logger (logging.Logger): File logger for database errors and lifecycle events.

    Returns:
        None.

    Exceptions:
        Methods in this class catch and log their own exceptions instead of raising them.
    """

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        """
        Initialize the database manager with configuration and logger.

        Parameters:
            config (AppConfig): Validated runtime configuration.
            logger (logging.Logger): Logger used for database diagnostics.

        Returns:
            None.

        Exceptions:
            This constructor does not raise exceptions.
        """
        self.config = config
        self.logger = logger
        self.pool: Optional[SimpleConnectionPool] = None
        self.lock = threading.Lock()

    def initialize_pool(self) -> bool:
        """
        Create the PostgreSQL connection pool.

        Parameters:
            None.

        Returns:
            bool: True when the pool was created successfully, otherwise False.

        Exceptions:
            This method catches and logs connection errors.
        """
        # ── verify that the PostgreSQL driver is installed ──
        if psycopg2 is None or SimpleConnectionPool is None:
            self.logger.error("PostgreSQL driver is not installed.")
            return False

        # ── build a small connection pool suitable for a terminal assistant ──
        try:
            self.pool = SimpleConnectionPool(
                1,
                5,
                host=self.config.db_host,
                dbname=self.config.db_name,
                user=self.config.db_user,
                password=self.config.db_password,
                port=self.config.db_port,
                connect_timeout=5,
            )
            return True
        except Exception as error:
            self.logger.error("Failed to initialize PostgreSQL pool: %s", error)
            return False

    def _get_connection(self) -> Optional[Any]:
        """
        Borrow a connection from the pool.

        Parameters:
            None.

        Returns:
            Optional[Any]: A psycopg2 connection object, or None when unavailable.

        Exceptions:
            This method catches and logs pooling errors.
        """
        # ── make sure the pool exists before trying to borrow a connection ──
        if self.pool is None:
            self.logger.error("Connection pool is not initialized.")
            return None

        # ── borrow a connection for the current database operation ──
        try:
            return self.pool.getconn()
        except Exception as error:
            self.logger.error("Failed to get pooled connection: %s", error)
            return None

    def _put_connection(self, connection: Optional[Any]) -> None:
        """
        Return a connection to the pool.

        Parameters:
            connection (Optional[Any]): The connection to return.

        Returns:
            None.

        Exceptions:
            This method catches and logs pooling errors.
        """
        # ── skip empty connection objects safely ──
        if self.pool is None or connection is None:
            return

        # ── return the borrowed connection to the shared pool ──
        try:
            self.pool.putconn(connection)
        except Exception as error:
            self.logger.error("Failed to return pooled connection: %s", error)

    def test_connection(self) -> bool:
        """
        Run a simple health check against PostgreSQL.

        Parameters:
            None.

        Returns:
            bool: True when PostgreSQL responds successfully, otherwise False.

        Exceptions:
            This method catches and logs query errors.
        """
        # ── borrow a connection and run a trivial query ──
        connection = self._get_connection()
        if connection is None:
            return False

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return True
        except Exception as error:
            self.logger.error("Database health check failed: %s", error)
            return False
        finally:
            self._put_connection(connection)

    def setup_database(self) -> bool:
        """
        Create all required PostgreSQL tables if they do not already exist.

        Parameters:
            None.

        Returns:
            bool: True when schema creation succeeds, otherwise False.

        Exceptions:
            This method catches and logs schema errors.
        """
        # ── borrow a connection for schema setup ──
        connection = self._get_connection()
        if connection is None:
            return False

        try:
            with connection.cursor() as cursor:
                # ── create the persistent key-value memory store ──
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory (
                        id SERIAL PRIMARY KEY,
                        key VARCHAR(255) UNIQUE NOT NULL,
                        value TEXT NOT NULL,
                        category VARCHAR(100) DEFAULT 'general',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )

                # ── create the full conversation log for all sessions ──
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS conversation_log (
                        id SERIAL PRIMARY KEY,
                        session_id VARCHAR(100) NOT NULL,
                        role VARCHAR(50) NOT NULL,
                        content TEXT NOT NULL,
                        ai_provider VARCHAR(50),
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )

                # ── create the AI usage and performance tracking table ──
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ai_usage (
                        id SERIAL PRIMARY KEY,
                        provider VARCHAR(50) NOT NULL,
                        success BOOLEAN NOT NULL,
                        response_time_ms INTEGER,
                        tokens_used INTEGER,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )

                # ── create the reminder storage table ──
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS reminders (
                        id SERIAL PRIMARY KEY,
                        message TEXT NOT NULL,
                        trigger_at TIMESTAMP NOT NULL,
                        completed BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )

            # ── commit all schema changes as one setup unit ──
            connection.commit()
            return True
        except Exception as error:
            connection.rollback()
            self.logger.error("Failed to set up database schema: %s", error)
            return False
        finally:
            self._put_connection(connection)

    def save_memory(self, key: str, value: str, category: str = "general") -> bool:
        """
        Upsert a memory record into PostgreSQL.

        Parameters:
            key (str): The memory lookup key.
            value (str): The memory value to store.
            category (str): Optional memory category.

        Returns:
            bool: True when the memory is stored successfully, otherwise False.

        Exceptions:
            This method catches and logs database errors.
        """
        # ── borrow a connection for the memory upsert ──
        connection = self._get_connection()
        if connection is None:
            return False

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO memory (key, value, category, created_at, updated_at)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT (key)
                    DO UPDATE SET
                        value = EXCLUDED.value,
                        category = EXCLUDED.category,
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    (key, value, category),
                )
            connection.commit()
            return True
        except Exception as error:
            connection.rollback()
            self.logger.error("Failed to save memory: %s", error)
            return False
        finally:
            self._put_connection(connection)

    def recall_memory(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Fuzzy-search memory keys using PostgreSQL `ILIKE`.

        Parameters:
            key (str): The lookup phrase supplied by the user.

        Returns:
            Optional[Dict[str, Any]]: The best matching memory row, or None if nothing matches.

        Exceptions:
            This method catches and logs database errors.
        """
        # ── borrow a connection for the fuzzy memory search ──
        connection = self._get_connection()
        if connection is None:
            return None

        try:
            with connection.cursor() as cursor:
                search_pattern = f"%{key.strip()}%"
                cursor.execute(
                    """
                    SELECT key, value, category, created_at, updated_at
                    FROM memory
                    WHERE key ILIKE %s
                    ORDER BY updated_at DESC
                    LIMIT 1;
                    """,
                    (search_pattern,),
                )
                row = cursor.fetchone()
            if row is None:
                return None
            return {
                "key": row[0],
                "value": row[1],
                "category": row[2],
                "created_at": row[3],
                "updated_at": row[4],
            }
        except Exception as error:
            self.logger.error("Failed to recall memory: %s", error)
            return None
        finally:
            self._put_connection(connection)

    def recall_all_memories(self) -> str:
        """
        Return all stored memories as a human-friendly string.

        Parameters:
            None.

        Returns:
            str: A formatted memory summary.

        Exceptions:
            This method catches and logs database errors.
        """
        # ── borrow a connection for the memory listing query ──
        connection = self._get_connection()
        if connection is None:
            return "My memory system is unavailable right now, sir."

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT key, value, category
                    FROM memory
                    ORDER BY updated_at DESC;
                    """
                )
                rows = cursor.fetchall()
            if not rows:
                return "I do not have any stored memories yet, sir."
            formatted_rows = [
                f"{index}. {row[0]} -> {row[1]} ({row[2]})"
                for index, row in enumerate(rows, start=1)
            ]
            return "Here is what I remember, sir. " + " ".join(formatted_rows)
        except Exception as error:
            self.logger.error("Failed to list memories: %s", error)
            return "I could not retrieve my memories right now, sir."
        finally:
            self._put_connection(connection)

    def log_conversation(
        self,
        session_id: str,
        role: str,
        content: str,
        provider: Optional[str],
    ) -> None:
        """
        Persist one conversation message for the current session.

        Parameters:
            session_id (str): The session identifier.
            role (str): The message role such as `user`, `assistant`, or `system`.
            content (str): The message content to store.
            provider (Optional[str]): The AI provider used for the reply, if any.

        Returns:
            None.

        Exceptions:
            This method catches and logs database errors.
        """
        # ── borrow a connection for the conversation insert ──
        connection = self._get_connection()
        if connection is None:
            return

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversation_log (session_id, role, content, ai_provider)
                    VALUES (%s, %s, %s, %s);
                    """,
                    (session_id, role, content, provider),
                )
            connection.commit()
        except Exception as error:
            connection.rollback()
            self.logger.error("Failed to log conversation: %s", error)
        finally:
            self._put_connection(connection)

    def log_ai_usage(
        self,
        provider: str,
        success: bool,
        response_time_ms: Optional[int],
        tokens_used: Optional[int],
    ) -> None:
        """
        Record one AI provider usage entry.

        Parameters:
            provider (str): Provider name such as `gemini` or `groq`.
            success (bool): Whether the request succeeded.
            response_time_ms (Optional[int]): Request latency in milliseconds.
            tokens_used (Optional[int]): Tokens used when available.

        Returns:
            None.

        Exceptions:
            This method catches and logs database errors.
        """
        # ── borrow a connection for the usage insert ──
        connection = self._get_connection()
        if connection is None:
            return

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO ai_usage (provider, success, response_time_ms, tokens_used)
                    VALUES (%s, %s, %s, %s);
                    """,
                    (provider, success, response_time_ms, tokens_used),
                )
            connection.commit()
        except Exception as error:
            connection.rollback()
            self.logger.error("Failed to log AI usage: %s", error)
        finally:
            self._put_connection(connection)

    def save_reminder(self, message: str, trigger_at: datetime.datetime) -> Optional[int]:
        """
        Save a future reminder into PostgreSQL.

        Parameters:
            message (str): Reminder text to speak later.
            trigger_at (datetime.datetime): When the reminder should fire.

        Returns:
            Optional[int]: The reminder ID on success, otherwise None.

        Exceptions:
            This method catches and logs database errors.
        """
        # ── borrow a connection for the reminder insert ──
        connection = self._get_connection()
        if connection is None:
            return None

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO reminders (message, trigger_at)
                    VALUES (%s, %s)
                    RETURNING id;
                    """,
                    (message, trigger_at),
                )
                reminder_id = cursor.fetchone()[0]
            connection.commit()
            return int(reminder_id)
        except Exception as error:
            connection.rollback()
            self.logger.error("Failed to save reminder: %s", error)
            return None
        finally:
            self._put_connection(connection)

    def mark_reminder_completed(self, reminder_id: int) -> None:
        """
        Mark a reminder as completed.

        Parameters:
            reminder_id (int): The reminder row ID.

        Returns:
            None.

        Exceptions:
            This method catches and logs database errors.
        """
        # ── borrow a connection for the reminder completion update ──
        connection = self._get_connection()
        if connection is None:
            return

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE reminders
                    SET completed = TRUE
                    WHERE id = %s;
                    """,
                    (reminder_id,),
                )
            connection.commit()
        except Exception as error:
            connection.rollback()
            self.logger.error("Failed to complete reminder: %s", error)
        finally:
            self._put_connection(connection)

    def check_due_reminders(self) -> List[Dict[str, Any]]:
        """
        Fetch due reminders, mark them complete, and return them.

        Parameters:
            None.

        Returns:
            List[Dict[str, Any]]: Reminder rows that should fire now.

        Exceptions:
            This method catches and logs database errors.
        """
        # ── borrow a connection for the due reminder scan ──
        connection = self._get_connection()
        if connection is None:
            return []

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, message, trigger_at
                    FROM reminders
                    WHERE trigger_at <= CURRENT_TIMESTAMP
                      AND completed = FALSE
                    ORDER BY trigger_at ASC;
                    """
                )
                rows = cursor.fetchall()
                reminder_ids = [row[0] for row in rows]

                if reminder_ids:
                    cursor.execute(
                        """
                        UPDATE reminders
                        SET completed = TRUE
                        WHERE id = ANY(%s);
                        """,
                        (reminder_ids,),
                    )
            connection.commit()

            return [
                {"id": row[0], "message": row[1], "trigger_at": row[2]}
                for row in rows
            ]
        except Exception as error:
            connection.rollback()
            self.logger.error("Failed to check due reminders: %s", error)
            return []
        finally:
            self._put_connection(connection)

    def get_memory_count(self) -> int:
        """
        Count how many memories are stored.

        Parameters:
            None.

        Returns:
            int: The number of memory rows, or 0 on failure.

        Exceptions:
            This method catches and logs database errors.
        """
        # ── borrow a connection for the count query ──
        connection = self._get_connection()
        if connection is None:
            return 0

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM memory;")
                count = cursor.fetchone()[0]
            return int(count)
        except Exception as error:
            self.logger.error("Failed to count memories: %s", error)
            return 0
        finally:
            self._put_connection(connection)

    def close(self) -> None:
        """
        Close all pooled PostgreSQL connections.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method catches and logs pool shutdown errors.
        """
        # ── close every pooled connection during shutdown ──
        if self.pool is None:
            return
        try:
            self.pool.closeall()
        except Exception as error:
            self.logger.error("Failed to close PostgreSQL pool: %s", error)


# ══════════════════════════════════════════════════════════
# ██  ANIMATION SYSTEM
# ══════════════════════════════════════════════════════════


class JarvisAnimator:
    """
    Render a non-blocking terminal animation for JARVIS state changes.

    Parameters:
        None.

    Returns:
        None.

    Exceptions:
        Methods catch their own terminal I/O issues so animation never crashes the app.
    """

    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    RED = "\033[91m"
    RESET = "\033[0m"

    def __init__(self) -> None:
        """
        Initialize animation state and prepare reusable frame cycles.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This constructor does not raise exceptions.
        """
        self.state = "idle"
        self.provider = "gemini"
        self.stop_event = threading.Event()
        self.state_lock = threading.Lock()
        self.output_lock = threading.Lock()
        self.error_until = 0.0
        self.thread = threading.Thread(
            target=self._run_animation_loop,
            daemon=True,
            name="jarvis-animator",
        )
        self.frame_cycles = {
            "idle": itertools.cycle(
                [
                    "◉  JARVIS  [{provider}]  · · ·",
                    "◉  JARVIS  [{provider}]  ● · ·",
                    "◉  JARVIS  [{provider}]  ● ● ·",
                    "◉  JARVIS  [{provider}]  ● ● ●",
                ]
            ),
            "listening": itertools.cycle(
                [
                    "🎙  LISTENING  ▁▂▃▄▅▆▇█▇▆▅▄▃▂▁",
                    "🎙  LISTENING  ▂▄▆█▆▄▂▁▂▄▆█▆▄▂",
                ]
            ),
            "thinking": itertools.cycle(
                [
                    "🧠  THINKING  [{provider}]  ⠋",
                    "🧠  THINKING  [{provider}]  ⠙",
                    "🧠  THINKING  [{provider}]  ⠹",
                    "🧠  THINKING  [{provider}]  ⠸",
                    "🧠  THINKING  [{provider}]  ⠼",
                    "🧠  THINKING  [{provider}]  ⠴",
                ]
            ),
            "speaking": itertools.cycle(
                [
                    "🔊  SPEAKING  ≋ ═ ═ ≋ ═ ═ ≋",
                    "🔊  SPEAKING  ═ ≋ ═ ═ ≋ ═ ═",
                    "🔊  SPEAKING  ═ ═ ≋ ═ ═ ≋ ═",
                ]
            ),
            "error": itertools.cycle(
                [
                    "⚠  ERROR  ████████████████",
                    "⚠  ERROR  ░░░░░░░░░░░░░░░░",
                ]
            ),
        }

    def start(self) -> None:
        """
        Start the daemon animation thread.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method catches start errors silently to keep startup resilient.
        """
        # ── start the renderer exactly once ──
        try:
            if not self.thread.is_alive():
                self.thread.start()
        except Exception:
            pass

    def stop(self) -> None:
        """
        Stop the animation thread and clear the terminal line.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method catches terminal cleanup issues.
        """
        # ── signal the animation loop to stop and wait briefly ──
        self.stop_event.set()
        try:
            if self.thread.is_alive():
                self.thread.join(timeout=1.0)
        except Exception:
            pass

        # ── clear the animated line after shutdown ──
        self.clear_line()

    def set_state(self, state: str) -> None:
        """
        Change the active animation state safely.

        Parameters:
            state (str): One of `idle`, `listening`, `thinking`, `speaking`, or `error`.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── guard the shared state so all threads see consistent changes ──
        with self.state_lock:
            self.state = state
            if state == "error":
                self.error_until = time.time() + 2.0

    def set_provider(self, provider: str) -> None:
        """
        Update the provider label shown in animations.

        Parameters:
            provider (str): Provider name such as `gemini` or `groq`.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── update the visible provider tag used in idle and thinking frames ──
        with self.state_lock:
            self.provider = provider

    def clear_line(self) -> None:
        """
        Clear the active animation line from the terminal.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method catches terminal output errors.
        """
        # ── erase the line so future prints do not overlap the animation ──
        with self.output_lock:
            try:
                sys.stdout.write("\033[2K\r")
                sys.stdout.flush()
            except Exception:
                pass

    def safe_print(self, message: str) -> None:
        """
        Print text above the animation line without corrupting the terminal.

        Parameters:
            message (str): The message to print.

        Returns:
            None.

        Exceptions:
            This method catches terminal output errors.
        """
        # ── clear the line, print the message, then allow animation to redraw ──
        with self.output_lock:
            try:
                sys.stdout.write("\033[2K\r")
                sys.stdout.write(f"{message}\n")
                sys.stdout.flush()
            except Exception:
                pass

    def _render_line(self, state: str, provider: str) -> str:
        """
        Build one formatted animation frame.

        Parameters:
            state (str): Current animation state.
            provider (str): Current provider label.

        Returns:
            str: A colorized animation line ready to print.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── pull the next frame from the cycle for the active state ──
        raw_frame = next(self.frame_cycles[state]).format(provider=provider)

        # ── choose a color based on the active state ──
        if state == "idle":
            color = self.BLUE
        elif state == "listening":
            color = self.GREEN
        elif state == "thinking":
            color = self.YELLOW
        elif state == "speaking":
            color = self.CYAN
        else:
            color = self.RED

        return f"{color}{raw_frame}{self.RESET}"

    def _run_animation_loop(self) -> None:
        """
        Run the animation renderer in a daemon thread.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method catches its own errors so animation never kills the app.
        """
        # ── render frames continuously until shutdown is requested ──
        while not self.stop_event.is_set():
            try:
                with self.state_lock:
                    if self.state == "error" and time.time() >= self.error_until:
                        self.state = "idle"
                    current_state = self.state
                    current_provider = self.provider

                # ── build the next colorized frame ──
                line = self._render_line(current_state, current_provider)

                # ── write the frame in place without blocking other output ──
                with self.output_lock:
                    sys.stdout.write(f"\033[2K\r{line}")
                    sys.stdout.flush()
            except Exception:
                pass

            # ── sleep 100 ms so the animation stays smooth but lightweight ──
            time.sleep(0.1)


# ══════════════════════════════════════════════════════════
# ██  TEXT-TO-SPEECH ENGINE
# ══════════════════════════════════════════════════════════


@dataclass
class SpeechTask:
    """
    Represent one queued speech request.

    Parameters:
        text (str): Text to speak aloud.
        done_event (threading.Event): Event set after the speech request completes.

    Returns:
        None.
    """

    text: str
    done_event: threading.Event = field(default_factory=threading.Event)


class TextToSpeechEngine:
    """
    Queue and process JARVIS speech while keeping pyttsx3 on the main thread.

    Parameters:
        voice_rate (int): Desired pyttsx3 speaking rate.
        animator (JarvisAnimator): Animator used to reflect speaking state.
        logger (logging.Logger): Logger for TTS errors.

    Returns:
        None.

    Exceptions:
        Methods catch and log TTS errors instead of raising them.
    """

    def __init__(self, voice_rate: int, animator: JarvisAnimator, logger: logging.Logger) -> None:
        """
        Initialize the TTS queue, state flags, and pyttsx3 engine reference.

        Parameters:
            voice_rate (int): Speech rate in words per minute.
            animator (JarvisAnimator): Shared terminal animator.
            logger (logging.Logger): Logger for TTS diagnostics.

        Returns:
            None.

        Exceptions:
            This constructor does not raise exceptions.
        """
        self.voice_rate = voice_rate
        self.animator = animator
        self.logger = logger
        self.queue: "queue.Queue[SpeechTask]" = queue.Queue()
        self.engine: Optional[Any] = None
        self.speaking_event = threading.Event()

    def initialize_engine(self) -> bool:
        """
        Initialize pyttsx3 and choose the best macOS voice available.

        Parameters:
            None.

        Returns:
            bool: True when TTS is ready, otherwise False.

        Exceptions:
            This method catches and logs pyttsx3 initialization errors.
        """
        # ── verify that pyttsx3 is available in the current environment ──
        if pyttsx3 is None:
            self.logger.error("pyttsx3 is not installed.")
            return False

        # ── create the engine and apply rate and voice selection ──
        try:
            self.engine = pyttsx3.init()
            self.engine.setProperty("rate", self.voice_rate)
            best_voice = self._choose_best_voice()
            if best_voice:
                self.engine.setProperty("voice", best_voice)
            return True
        except Exception as error:
            self.logger.error("Failed to initialize TTS engine: %s", error)
            self.engine = None
            return False

    def _choose_best_voice(self) -> Optional[str]:
        """
        Select the preferred macOS voice by priority.

        Parameters:
            None.

        Returns:
            Optional[str]: The chosen voice ID, or None if no suitable voice exists.

        Exceptions:
            This method catches and logs voice lookup errors.
        """
        # ── stop early if the engine is not initialized yet ──
        if self.engine is None:
            return None

        # ── fetch all available system voices from pyttsx3 ──
        try:
            voices = self.engine.getProperty("voices")
        except Exception as error:
            self.logger.error("Failed to query TTS voices: %s", error)
            return None

        # ── search preferred names in the requested order ──
        preferred_order = ["samantha", "alex", "karen"]
        for preferred_name in preferred_order:
            for voice in voices:
                voice_name = str(getattr(voice, "name", "")).lower()
                voice_id = str(getattr(voice, "id", "")).lower()
                if preferred_name in voice_name or preferred_name in voice_id:
                    return getattr(voice, "id", None)

        # ── fall back to the first English voice if a preferred voice is missing ──
        for voice in voices:
            voice_name = str(getattr(voice, "name", "")).lower()
            voice_id = str(getattr(voice, "id", "")).lower()
            if "english" in voice_name or "en_" in voice_id or "en-" in voice_id:
                return getattr(voice, "id", None)

        # ── use the first available voice as a last resort ──
        if voices:
            return getattr(voices[0], "id", None)
        return None

    def split_sentences(self, text: str) -> List[str]:
        """
        Split text into natural sentence-sized chunks for smoother speech.

        Parameters:
            text (str): Full text to speak.

        Returns:
            List[str]: Ordered chunks ready for pyttsx3.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── normalize whitespace before chunking ──
        normalized_text = re.sub(r"\s+", " ", text).strip()
        if not normalized_text:
            return []

        # ── split on common sentence boundaries first ──
        chunks = re.split(r"(?<=[.!?])\s+", normalized_text)
        refined_chunks: List[str] = []

        # ── further split oversized chunks at punctuation for more natural pacing ──
        for chunk in chunks:
            if len(chunk) <= 220:
                refined_chunks.append(chunk)
                continue
            refined_chunks.extend(
                [part.strip() for part in re.split(r"(?<=[,;:])\s+", chunk) if part.strip()]
            )

        return refined_chunks

    def speak(self, text: str) -> threading.Event:
        """
        Queue text to be spoken by the main thread.

        Parameters:
            text (str): Text JARVIS should say.

        Returns:
            threading.Event: Event set when the queued speech finishes.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── create a speech task and put it on the shared queue ──
        task = SpeechTask(text=text)
        self.queue.put(task)
        return task.done_event

    def _perform_speech(self, text: str) -> None:
        """
        Speak text immediately on the main thread and update animation state.

        Parameters:
            text (str): Text to speak immediately.

        Returns:
            None.

        Exceptions:
            This method catches and logs TTS engine errors.
        """
        # ── always print the spoken response above the animation line ──
        self.animator.safe_print(f"JARVIS: {text}")

        # ── skip audio output when the engine is unavailable ──
        if self.engine is None:
            return

        # ── mark the speaking state so listeners can pause microphone capture ──
        self.speaking_event.set()
        self.animator.set_state("speaking")

        try:
            # ── speak one sentence chunk at a time so pacing sounds more natural ──
            for chunk in self.split_sentences(text):
                self.engine.say(chunk)
                self.engine.runAndWait()
        except Exception as error:
            self.logger.error("TTS playback failed: %s", error)
            self.animator.set_state("error")
        finally:
            # ── restore idle state after speech has finished ──
            self.speaking_event.clear()
            self.animator.set_state("idle")

    def speak_sync(self, text: str) -> None:
        """
        Speak text immediately on the main thread.

        Parameters:
            text (str): Text to speak synchronously.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── perform the speech directly on the main thread ──
        self._perform_speech(text)

    def process_one_task(self, timeout: float = 0.1) -> None:
        """
        Process one queued speech task on the main thread.

        Parameters:
            timeout (float): Queue wait timeout in seconds.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── wait briefly for queued speech so the main loop stays responsive ──
        try:
            task = self.queue.get(timeout=timeout)
        except queue.Empty:
            return

        # ── speak the queued text and release any waiting thread ──
        try:
            self._perform_speech(task.text)
        finally:
            task.done_event.set()
            self.queue.task_done()


# ══════════════════════════════════════════════════════════
# ██  SPEECH RECOGNITION
# ══════════════════════════════════════════════════════════


class SpeechRecognizerManager:
    """
    Handle microphone setup and safe speech recognition calls.

    Parameters:
        animator (JarvisAnimator): Animator used for printing and listening state.
        tts_engine (TextToSpeechEngine): Shared TTS manager so listening can pause during speech.
        logger (logging.Logger): Logger for microphone and STT errors.

    Returns:
        None.

    Exceptions:
        Methods catch and log their own speech-recognition errors.
    """

    def __init__(
        self,
        animator: JarvisAnimator,
        tts_engine: TextToSpeechEngine,
        logger: logging.Logger,
    ) -> None:
        """
        Initialize microphone coordination state.

        Parameters:
            animator (JarvisAnimator): Shared terminal animator.
            tts_engine (TextToSpeechEngine): Shared TTS coordinator.
            logger (logging.Logger): Logger for speech diagnostics.

        Returns:
            None.

        Exceptions:
            This constructor does not raise exceptions.
        """
        self.animator = animator
        self.tts_engine = tts_engine
        self.logger = logger
        self.microphone: Optional[Any] = None
        self.microphone_lock = threading.Lock()

    def initialize_microphone(self) -> bool:
        """
        Initialize and calibrate the system microphone.

        Parameters:
            None.

        Returns:
            bool: True when the microphone is ready, otherwise False.

        Exceptions:
            This method catches and logs microphone errors.
        """
        # ── verify core microphone dependencies are installed ──
        if sr is None or pyaudio is None:
            self.logger.error("SpeechRecognition or PyAudio is missing.")
            return False

        # ── create the microphone object and calibrate ambient noise ──
        try:
            recognizer = sr.Recognizer()
            self.microphone = sr.Microphone()
            with self.microphone as source:
                recognizer.adjust_for_ambient_noise(source, duration=1)
            return True
        except Exception as error:
            self.logger.error("Failed to initialize microphone: %s", error)
            return False

    def listen_for_text(
        self,
        timeout: int,
        phrase_time_limit: int,
        mode: str = "command",
        prompt_on_failure: bool = False,
    ) -> Optional[str]:
        """
        Listen to the microphone and convert audio to lowercase text.

        Parameters:
            timeout (int): Seconds to wait for speech to begin.
            phrase_time_limit (int): Maximum length of the spoken phrase.
            mode (str): Listener mode such as `wake` or `command`.
            prompt_on_failure (bool): Whether to speak a polite failure message when speech is unclear.

        Returns:
            Optional[str]: Recognized lowercase text, or None when recognition fails.

        Exceptions:
            This method catches microphone and recognizer exceptions internally.
        """
        # ── ensure the microphone exists before listening ──
        if self.microphone is None or sr is None:
            return None

        # ── avoid microphone capture while JARVIS is speaking ──
        while self.tts_engine.speaking_event.is_set():
            time.sleep(0.05)

        # ── create a fresh recognizer instance for this capture session ──
        recognizer = sr.Recognizer()
        recognizer.pause_threshold = 0.8
        recognizer.dynamic_energy_threshold = True

        # ── switch the animation to listening while the mic is hot ──
        if mode == "command":
            self.animator.set_state("listening")

        try:
            # ── serialize microphone access so wake and command listeners never collide ──
            with self.microphone_lock:
                with self.microphone as source:
                    audio = recognizer.listen(
                        source,
                        timeout=timeout,
                        phrase_time_limit=phrase_time_limit,
                    )
        except sr.WaitTimeoutError:
            if mode == "command" and prompt_on_failure:
                self.tts_engine.speak("I didn't catch that, sir.")
            return None
        except Exception as error:
            self.logger.error("Microphone capture failed: %s", error)
            time.sleep(2)
            return None
        finally:
            if mode == "command":
                self.animator.set_state("idle")

        try:
            # ── send the recorded audio to Google's free speech-to-text endpoint ──
            transcript = recognizer.recognize_google(audio)
            cleaned_transcript = transcript.strip().lower()
            self.animator.safe_print(f"YOU: {transcript}")
            return cleaned_transcript
        except sr.UnknownValueError:
            if mode == "command" and prompt_on_failure:
                self.tts_engine.speak("I didn't catch that, sir.")
            return None
        except sr.RequestError as error:
            self.logger.error("Speech recognition service failed: %s", error)
            if mode == "command" and prompt_on_failure:
                self.tts_engine.speak("I didn't catch that, sir.")
            return None
        except Exception as error:
            self.logger.error("Unexpected speech recognition error: %s", error)
            if mode == "command" and prompt_on_failure:
                self.tts_engine.speak("I didn't catch that, sir.")
            return None


# ══════════════════════════════════════════════════════════
# ██  AI BRAIN — GEMINI (PRIMARY)
# ══════════════════════════════════════════════════════════


class GeminiBrain:
    """
    Manage Gemini requests and provider-specific conversation history.

    Parameters:
        api_key (str): Gemini API key.
        history_limit (int): Maximum stored history messages for Gemini.
        logger (logging.Logger): Logger for provider failures.

    Returns:
        None.

    Exceptions:
        Methods catch and raise provider errors only to the AI router.
    """

    def __init__(self, api_key: str, history_limit: int, logger: logging.Logger) -> None:
        """
        Initialize Gemini configuration and provider-local history.

        Parameters:
            api_key (str): Gemini API key.
            history_limit (int): Number of message turns to keep.
            logger (logging.Logger): Logger for Gemini diagnostics.

        Returns:
            None.

        Exceptions:
            This constructor does not raise exceptions.
        """
        self.api_key = api_key
        self.history_limit = history_limit
        self.logger = logger
        self.available = False
        self.model: Optional[Any] = None
        self.history: List[Dict[str, Any]] = []

    def initialize(self) -> bool:
        """
        Configure the Gemini client and model object.

        Parameters:
            None.

        Returns:
            bool: True when Gemini appears ready, otherwise False.

        Exceptions:
            This method catches and logs provider setup errors.
        """
        # ── verify the Gemini SDK is available ──
        if genai is None:
            self.logger.warning("Gemini SDK is not installed.")
            return False

        # ── configure the SDK and create the chat model with a system instruction ──
        try:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction=SYSTEM_PROMPT,
            )
            self.available = True
            return True
        except Exception as error:
            self.logger.error("Failed to initialize Gemini: %s", error)
            self.available = False
            return False

    def _trim_history(self) -> None:
        """
        Trim provider-local history to the configured limit.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── keep only the newest messages for this provider ──
        self.history = self.history[-self.history_limit :]

    def send_message(self, user_text: str) -> Tuple[str, Optional[int]]:
        """
        Send a message to Gemini and update provider-local history.

        Parameters:
            user_text (str): The user's request.

        Returns:
            Tuple[str, Optional[int]]: The reply text and token count when available.

        Exceptions:
            Raises:
                RuntimeError: When Gemini is unavailable or returns no text.
                Exception: Any provider-level exception is allowed to bubble to the router.
        """
        # ── ensure the provider is initialized before sending a request ──
        if not self.available or self.model is None:
            raise RuntimeError("Gemini is unavailable.")

        # ── create an ephemeral chat using only Gemini-formatted history ──
        chat = self.model.start_chat(history=self.history)

        # ── send the user message to Gemini; the API returns a structured response object ──
        response = chat.send_message(user_text)

        # ── extract plain text from Gemini's response object ──
        reply_text = getattr(response, "text", "").strip()
        if not reply_text:
            raise RuntimeError("Gemini returned an empty response.")

        # ── update Gemini-specific history using the SDK's expected message structure ──
        self.history.append({"role": "user", "parts": [user_text]})
        self.history.append({"role": "model", "parts": [reply_text]})
        self._trim_history()

        # ── read token usage when the response exposes it ──
        usage = getattr(response, "usage_metadata", None)
        total_tokens = getattr(usage, "total_token_count", None) if usage else None
        return reply_text, total_tokens


# ══════════════════════════════════════════════════════════
# ██  AI BRAIN — GROQ (FALLBACK)
# ══════════════════════════════════════════════════════════


class GroqBrain:
    """
    Manage Groq requests and provider-specific conversation history.

    Parameters:
        api_key (str): Groq API key.
        history_limit (int): Maximum stored history messages for Groq.
        logger (logging.Logger): Logger for provider failures.

    Returns:
        None.

    Exceptions:
        Methods catch and raise provider errors only to the AI router.
    """

    def __init__(self, api_key: str, history_limit: int, logger: logging.Logger) -> None:
        """
        Initialize Groq configuration and provider-local history.

        Parameters:
            api_key (str): Groq API key.
            history_limit (int): Number of message turns to keep.
            logger (logging.Logger): Logger for Groq diagnostics.

        Returns:
            None.

        Exceptions:
            This constructor does not raise exceptions.
        """
        self.api_key = api_key
        self.history_limit = history_limit
        self.logger = logger
        self.available = False
        self.client: Optional[Any] = None
        self.history: List[Dict[str, str]] = []

    def initialize(self) -> bool:
        """
        Create the Groq client.

        Parameters:
            None.

        Returns:
            bool: True when Groq appears ready, otherwise False.

        Exceptions:
            This method catches and logs provider setup errors.
        """
        # ── verify the Groq SDK is available ──
        if Groq is None:
            self.logger.warning("Groq SDK is not installed.")
            return False

        # ── create the OpenAI-compatible Groq client ──
        try:
            self.client = Groq(api_key=self.api_key)
            self.available = True
            return True
        except Exception as error:
            self.logger.error("Failed to initialize Groq: %s", error)
            self.available = False
            return False

    def _trim_history(self) -> None:
        """
        Trim provider-local history to the configured limit.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── keep only the newest messages for this provider ──
        self.history = self.history[-self.history_limit :]

    def send_message(self, user_text: str) -> Tuple[str, Optional[int]]:
        """
        Send a message to Groq and update provider-local history.

        Parameters:
            user_text (str): The user's request.

        Returns:
            Tuple[str, Optional[int]]: The reply text and token count when available.

        Exceptions:
            Raises:
                RuntimeError: When Groq is unavailable or returns no text.
                Exception: Any provider-level exception is allowed to bubble to the router.
        """
        # ── ensure the provider is initialized before sending a request ──
        if not self.available or self.client is None:
            raise RuntimeError("Groq is unavailable.")

        # ── format the current request using Groq's OpenAI-style messages format ──
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self.history + [
            {"role": "user", "content": user_text}
        ]

        # ── send the chat completion request to Groq and receive a structured response ──
        response = self.client.chat.completions.create(
            model="llama3-8b-8192",
            messages=messages,
            temperature=0.4,
            max_tokens=300,
        )

        # ── extract the assistant text from the first returned choice ──
        reply_text = response.choices[0].message.content.strip()
        if not reply_text:
            raise RuntimeError("Groq returned an empty response.")

        # ── update Groq-specific history using its own OpenAI-compatible schema ──
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": reply_text})
        self._trim_history()

        # ── collect token usage when the response exposes it ──
        usage = getattr(response, "usage", None)
        total_tokens = getattr(usage, "total_tokens", None) if usage else None
        return reply_text, total_tokens


# ══════════════════════════════════════════════════════════
# ██  AI ROUTER — SMART FALLBACK LOGIC
# ══════════════════════════════════════════════════════════


class AIRouter:
    """
    Route AI requests across Gemini and Groq with automatic fallback.

    Parameters:
        config (AppConfig): Validated runtime configuration.
        logger (logging.Logger): Logger for provider switches and failures.
        db_manager (DatabaseManager): Database manager for AI usage tracking.
        animator (JarvisAnimator): Animator used to display the active provider.

    Returns:
        None.

    Exceptions:
        Methods catch provider failures and only return clean result tuples.
    """

    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        db_manager: DatabaseManager,
        animator: JarvisAnimator,
    ) -> None:
        """
        Initialize both provider managers and routing state.

        Parameters:
            config (AppConfig): Validated runtime configuration.
            logger (logging.Logger): Logger for AI diagnostics.
            db_manager (DatabaseManager): Database manager for usage metrics.
            animator (JarvisAnimator): Shared terminal animator.

        Returns:
            None.

        Exceptions:
            This constructor does not raise exceptions.
        """
        self.config = config
        self.logger = logger
        self.db_manager = db_manager
        self.animator = animator
        self.gemini = GeminiBrain(config.gemini_api_key, config.history_limit, logger)
        self.groq = GroqBrain(config.groq_api_key, config.history_limit, logger)
        self.manual_override: Optional[str] = None
        self.active_provider = config.primary_ai
        self.animator.set_provider(self.active_provider)

    def initialize_providers(self) -> Dict[str, bool]:
        """
        Initialize both AI providers and return readiness flags.

        Parameters:
            None.

        Returns:
            Dict[str, bool]: Readiness flags keyed by provider name.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── initialize both providers independently so one can survive without the other ──
        gemini_ready = self.gemini.initialize()
        groq_ready = self.groq.initialize()
        return {"gemini": gemini_ready, "groq": groq_ready}

    def provider_display_name(self, provider: str) -> str:
        """
        Convert an internal provider ID to a friendly display name.

        Parameters:
            provider (str): Provider key such as `gemini` or `groq`.

        Returns:
            str: Human-readable provider label.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── map short provider keys to terminal-friendly names ──
        return {"gemini": "Gemini", "groq": "Groq"}.get(provider, provider.title())

    def is_provider_available(self, provider: str) -> bool:
        """
        Check whether the selected provider is initialized and ready.

        Parameters:
            provider (str): Provider key to test.

        Returns:
            bool: True if the provider is available, otherwise False.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── inspect provider availability without making any network calls ──
        if provider == "gemini":
            return self.gemini.available
        if provider == "groq":
            return self.groq.available
        return False

    def _other_provider(self, provider: str) -> str:
        """
        Return the alternate AI provider name.

        Parameters:
            provider (str): Current provider key.

        Returns:
            str: The alternate provider key.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── toggle between the two supported providers ──
        return "groq" if provider == "gemini" else "gemini"

    def _log_switch(self, old_provider: str, new_provider: str, reason: str) -> None:
        """
        Log an AI switch event to `jarvis.log`.

        Parameters:
            old_provider (str): Previous provider.
            new_provider (str): New provider.
            reason (str): Why the switch happened.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── record provider switch events without logging user content or secrets ──
        self.logger.info(
            "AI provider switched from %s to %s. Reason: %s",
            old_provider,
            new_provider,
            reason,
        )

    def switch_ai(self, provider: str) -> Tuple[bool, str]:
        """
        Manually switch the preferred AI provider.

        Parameters:
            provider (str): Requested provider key.

        Returns:
            Tuple[bool, str]: Success flag and a spoken response.

        Exceptions:
            This method catches provider availability issues and returns clean feedback.
        """
        # ── normalize the requested provider name ──
        normalized_provider = provider.strip().lower()
        if normalized_provider not in {"gemini", "groq"}:
            return False, "That is not a supported AI provider, sir."

        # ── ensure the requested provider is actually initialized ──
        if not self.is_provider_available(normalized_provider):
            return False, f"{self.provider_display_name(normalized_provider)} is unavailable right now, sir."

        # ── update routing preference and visible provider state ──
        old_provider = self.active_provider
        self.manual_override = normalized_provider
        self.active_provider = normalized_provider
        self.animator.set_provider(normalized_provider)

        # ── write a provider switch event to the log file ──
        self._log_switch(old_provider, normalized_provider, "manual override")
        return True, f"Switching to {self.provider_display_name(normalized_provider)}, sir."

    def get_provider_order(self) -> List[str]:
        """
        Compute the provider routing order for the next AI request.

        Parameters:
            None.

        Returns:
            List[str]: Ordered provider names to try.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── honor a manual override first; otherwise default to Gemini-first routing ──
        first_provider = self.manual_override or "gemini"
        return [first_provider, self._other_provider(first_provider)]

    def ask(self, user_text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Ask the active AI stack for a response, falling back automatically on failure.

        Parameters:
            user_text (str): The user's request text.

        Returns:
            Tuple[Optional[str], Optional[str]]: The reply text and successful provider, or (None, None).

        Exceptions:
            This method catches provider failures and returns clean fallback results.
        """
        # ── compute the order of providers to try for this request ──
        provider_order = self.get_provider_order()

        # ── try each provider until one succeeds ──
        for provider_name in provider_order:
            provider = self.gemini if provider_name == "gemini" else self.groq
            if not provider.available:
                continue

            # ── show the current provider in the thinking animation before the API call ──
            self.animator.set_provider(provider_name)
            self.animator.set_state("thinking")

            # ── record timing so the database can track provider performance ──
            start_time = time.perf_counter()
            try:
                reply_text, token_count = provider.send_message(user_text)
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                self.db_manager.log_ai_usage(provider_name, True, elapsed_ms, token_count)

                # ── log a switch event when the active provider changes ──
                if self.active_provider != provider_name:
                    self._log_switch(self.active_provider, provider_name, "automatic fallback success")

                # ── update the active provider for terminal display ──
                self.active_provider = provider_name
                self.animator.set_provider(provider_name)
                return reply_text, provider_name
            except Exception as error:
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                self.db_manager.log_ai_usage(provider_name, False, elapsed_ms, None)
                self.logger.error("AI request failed for %s: %s", provider_name, error)

                # ── log the fallback handoff if another provider remains to try ──
                alternate_provider = self._other_provider(provider_name)
                if provider_name != alternate_provider and self.is_provider_available(alternate_provider):
                    self._log_switch(provider_name, alternate_provider, "provider failure")
                continue

        # ── signal that both providers were unavailable for this request ──
        self.animator.set_state("error")
        return None, None


# ══════════════════════════════════════════════════════════
# ██  BUILT-IN SKILLS
# ══════════════════════════════════════════════════════════


def format_memory_sentence(memory: Dict[str, Any]) -> str:
    """
    Convert a stored memory row into a natural spoken sentence.

    Parameters:
        memory (Dict[str, Any]): Memory row returned from PostgreSQL.

    Returns:
        str: A human-friendly memory sentence.

    Exceptions:
        This function does not raise exceptions.
    """
    # ── rebuild a natural sentence from the stored key and value ──
    key = str(memory.get("key", "")).strip()
    value = str(memory.get("value", "")).strip()
    if value.lower().startswith(("is ", "are ", "am ", "was ", "were ")):
        return f"{key} {value}"
    return f"{key}: {value}"


def parse_memory_statement(fact_text: str) -> Tuple[str, str, str]:
    """
    Parse a raw memory statement into key, value, and category.

    Parameters:
        fact_text (str): The spoken text following `remember that`.

    Returns:
        Tuple[str, str, str]: Parsed key, parsed value, and category.

    Exceptions:
        This function does not raise exceptions.
    """
    # ── clean whitespace and trailing punctuation from the memory statement ──
    cleaned_fact = fact_text.strip().rstrip(".!?")

    # ── split simple identity statements into a natural key/value pair ──
    match = re.match(r"(.+?)\s+(is|are|am|was|were)\s+(.+)", cleaned_fact, flags=re.IGNORECASE)
    if match:
        key = match.group(1).strip().lower()
        value = f"{match.group(2).strip().lower()} {match.group(3).strip()}"
        return key, value, "general"

    # ── use the full statement as both key and value when structure is unclear ──
    return cleaned_fact.lower(), cleaned_fact, "general"


def format_duration(seconds: int) -> str:
    """
    Convert seconds into a friendly duration string.

    Parameters:
        seconds (int): Duration in seconds.

    Returns:
        str: Human-readable duration such as `5 minutes` or `30 seconds`.

    Exceptions:
        This function does not raise exceptions.
    """
    # ── convert pure minute values to a cleaner phrase ──
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{seconds} second{'s' if seconds != 1 else ''}"


# ══════════════════════════════════════════════════════════
# ██  COMMAND ROUTER
# ══════════════════════════════════════════════════════════


class JarvisApp:
    """
    Coordinate the full JARVIS runtime, threads, AI routing, and local skills.

    Parameters:
        config (AppConfig): Validated application configuration.

    Returns:
        None.

    Exceptions:
        Public methods catch and handle exceptions so the assistant stays alive.
    """

    def __init__(self, config: AppConfig) -> None:
        """
        Initialize shared managers, runtime state, and threading primitives.

        Parameters:
            config (AppConfig): Validated runtime configuration.

        Returns:
            None.

        Exceptions:
            This constructor does not raise exceptions.
        """
        self.config = config
        self.logger = LOGGER
        self.session_id = uuid.uuid4().hex[:9]
        self.started_at = time.time()

        self.shutdown_requested = threading.Event()
        self.stop_background_threads = threading.Event()
        self.command_active = threading.Event()
        self.shutdown_lock = threading.Lock()

        self.animator = JarvisAnimator()
        self.tts_engine = TextToSpeechEngine(config.voice_rate, self.animator, self.logger)
        self.speech_manager = SpeechRecognizerManager(self.animator, self.tts_engine, self.logger)
        self.db_manager = DatabaseManager(config, self.logger)
        self.ai_router = AIRouter(config, self.logger, self.db_manager, self.animator)

        self.wake_thread: Optional[threading.Thread] = None
        self.reminder_thread: Optional[threading.Thread] = None
        self.active_timers: List[threading.Timer] = []
        self.timers_lock = threading.Lock()

        self.microphone_ready = False
        self.provider_status = {"gemini": False, "groq": False}

    def current_uptime(self) -> str:
        """
        Return the process uptime as a friendly string.

        Parameters:
            None.

        Returns:
            str: Human-readable uptime.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── convert raw uptime seconds into minutes and seconds ──
        elapsed = int(time.time() - self.started_at)
        minutes, seconds = divmod(elapsed, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours} hour{'s' if hours != 1 else ''}, {minutes} minute{'s' if minutes != 1 else ''}"
        if minutes:
            return f"{minutes} minute{'s' if minutes != 1 else ''}, {seconds} second{'s' if seconds != 1 else ''}"
        return f"{seconds} second{'s' if seconds != 1 else ''}"

    def request_shutdown(self, reason: str) -> None:
        """
        Signal the main loop to begin graceful shutdown.

        Parameters:
            reason (str): Why shutdown was requested.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── record the shutdown request once and only once ──
        with self.shutdown_lock:
            if not self.shutdown_requested.is_set():
                self.logger.info("Shutdown requested. Reason: %s", reason)
                self.shutdown_requested.set()

    def startup_sequence(self) -> bool:
        """
        Run the full startup sequence required by the assistant.

        Parameters:
            None.

        Returns:
            bool: True when startup succeeds, otherwise False.

        Exceptions:
            This method catches and reports startup failures without crashing.
        """
        # ── initialize the PostgreSQL pool and fail fast if the database is unavailable ──
        if not self.db_manager.initialize_pool() or not self.db_manager.test_connection():
            print("PostgreSQL connection failed. Please check your database settings in .env and try again.")
            return False

        # ── create required tables before any assistant work begins ──
        if not self.db_manager.setup_database():
            print("PostgreSQL schema setup failed. Please check jarvis.log for details.")
            return False

        # ── initialize both AI providers; failures are warnings, not fatal ──
        self.provider_status = self.ai_router.initialize_providers()

        # ── initialize the microphone and fail clearly if the assistant cannot listen ──
        self.microphone_ready = self.speech_manager.initialize_microphone()
        if not self.microphone_ready:
            print("Microphone initialization failed. Please check permissions and audio dependencies.")
            return False

        # ── initialize text-to-speech; failure is non-fatal because terminal output still works ──
        self.tts_engine.initialize_engine()

        # ── start the animation thread before printing the status panel ──
        self.animator.start()

        # ── start the background reminder checker thread ──
        self.start_reminder_checker_thread()

        # ── log the session start to both the log file and PostgreSQL ──
        self.logger.info("Session started. Session ID: %s", self.session_id)
        self.db_manager.log_conversation(self.session_id, "system", "Session started", None)

        # ── print the system status panel above the animation line ──
        self.print_status_panel()

        # ── speak the startup message on the main thread before wake listening begins ──
        self.tts_engine.speak_sync(
            "JARVIS online. Gemini and Groq systems active. All systems operational. How can I assist you sir?"
        )

        # ── begin the always-on wake-word loop in the background ──
        self.start_wake_listener_thread()
        return True

    def print_status_panel(self) -> None:
        """
        Print the startup status panel.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── map provider readiness into neat checkmark symbols ──
        gemini_mark = "✓" if self.provider_status.get("gemini") else "✗"
        groq_mark = "✓" if self.provider_status.get("groq") else "✗"
        db_mark = "✓"
        mic_mark = "✓" if self.microphone_ready else "✗"

        # ── build the requested terminal status panel ──
        panel = (
            "┌─────────────────────────────────────────┐\n"
            "│           JARVIS  SYSTEM STATUS          │\n"
            "├─────────────────────────────────────────┤\n"
            f"│  Primary AI   : Gemini 1.5 Flash   {gemini_mark}   │\n"
            f"│  Fallback AI  : Groq LLaMA3        {groq_mark}   │\n"
            f"│  Database     : PostgreSQL         {db_mark}   │\n"
            f"│  Microphone   : Ready              {mic_mark}   │\n"
            f"│  Wake Word    : \"{self.config.wake_word}\"{' ' * max(0, 14 - len(self.config.wake_word))}│\n"
            f"│  Session ID   : {self.session_id}{' ' * max(0, 23 - len(self.session_id))}│\n"
            "└─────────────────────────────────────────┘"
        )
        self.animator.safe_print(panel)

    def start_wake_listener_thread(self) -> None:
        """
        Start the permanent background wake-word listener thread.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── create the always-on listener thread that runs until shutdown ──
        self.wake_thread = threading.Thread(
            target=self.wake_listener_loop,
            daemon=True,
            name="jarvis-wake-listener",
        )
        self.wake_thread.start()

    def start_reminder_checker_thread(self) -> None:
        """
        Start the background reminder polling thread.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── create the daemon reminder checker that polls PostgreSQL every 30 seconds ──
        self.reminder_thread = threading.Thread(
            target=self.reminder_checker_loop,
            daemon=True,
            name="jarvis-reminder-checker",
        )
        self.reminder_thread.start()

    def schedule_timer_alert(self, seconds: int, reminder_id: Optional[int], message: str) -> None:
        """
        Schedule a local timer alert using `threading.Timer`.

        Parameters:
            seconds (int): Delay until the timer fires.
            reminder_id (Optional[int]): Associated reminder row ID.
            message (str): Message to speak when the timer finishes.

        Returns:
            None.

        Exceptions:
            This method catches and logs timer creation errors.
        """
        # ── define the callback that fires when the timer expires ──
        def timer_callback() -> None:
            # ── skip firing if shutdown is already in progress ──
            if self.shutdown_requested.is_set():
                return

            # ── mark the persisted reminder completed so the checker does not repeat it ──
            if reminder_id is not None:
                self.db_manager.mark_reminder_completed(reminder_id)

            # ── log the reminder firing and queue the spoken alert ──
            self.logger.info("Reminder fired. Reminder ID: %s", reminder_id)
            self.tts_engine.speak(message)

        # ── create and start the timer in daemon mode ──
        try:
            timer = threading.Timer(seconds, timer_callback)
            timer.daemon = True
            timer.start()
            with self.timers_lock:
                self.active_timers.append(timer)
        except Exception as error:
            self.logger.error("Failed to schedule timer alert: %s", error)

    def open_app(self, app_name: str) -> bool:
        """
        Open a macOS application by name.

        Parameters:
            app_name (str): Application name such as `Safari` or `Music`.

        Returns:
            bool: True when the app launch succeeds, otherwise False.

        Exceptions:
            This method catches and logs subprocess errors.
        """
        # ── launch the macOS application using the built-in `open` tool ──
        try:
            subprocess.run(["open", "-a", app_name], check=True)
            return True
        except Exception as error:
            self.logger.error("Failed to open app '%s': %s", app_name, error)
            return False

    def take_screenshot(self) -> Tuple[bool, str]:
        """
        Capture a silent screenshot to the Desktop.

        Parameters:
            None.

        Returns:
            Tuple[bool, str]: Success flag and spoken response.

        Exceptions:
            This method catches and logs subprocess errors.
        """
        # ── build the screenshot target path on the user's Desktop ──
        desktop_path = Path("~/Desktop").expanduser()
        screenshot_path = desktop_path / "jarvis_screenshot.png"

        # ── run macOS screencapture without the shutter sound ──
        try:
            subprocess.run(
                ["screencapture", "-x", str(screenshot_path)],
                check=True,
            )
            return True, f"Screenshot captured, sir. I saved it to {screenshot_path}."
        except Exception as error:
            self.logger.error("Screenshot command failed: %s", error)
            return False, "I could not take the screenshot, sir."

    def build_status_report(self) -> str:
        """
        Build a spoken system status summary.

        Parameters:
            None.

        Returns:
            str: Spoken status report.

        Exceptions:
            This method catches and hides database access issues gracefully.
        """
        # ── collect live runtime status details ──
        current_provider = self.ai_router.provider_display_name(self.ai_router.active_provider)
        memory_count = self.db_manager.get_memory_count()
        db_status = "connected"
        uptime = self.current_uptime()

        # ── turn the raw status values into a short spoken summary ──
        return (
            f"System status, sir. Active AI provider is {current_provider}. "
            f"PostgreSQL is {db_status}. "
            f"I currently hold {memory_count} stored memories. "
            f"Uptime is {uptime}."
        )

    def handle_builtin_skill(self, command: str) -> Tuple[bool, str, bool]:
        """
        Handle local skills before any AI call is made.

        Parameters:
            command (str): The recognized user command.

        Returns:
            Tuple[bool, str, bool]: Handled flag, response text, and shutdown flag.

        Exceptions:
            This method catches and handles its own errors where needed.
        """
        # ── normalize command text once for all local pattern checks ──
        cleaned_command = command.strip()
        lowered_command = cleaned_command.lower()

        # ── handle explicit shutdown phrases first ──
        if lowered_command in {"goodbye", "shut down", "exit", "that's all"}:
            return True, "Shutting down all systems. Goodbye sir.", True

        # ── answer local time requests instantly ──
        if any(pattern in lowered_command for pattern in ["what time", "current time", "what's the time"]):
            current_time = datetime.datetime.now().strftime("%I:%M %p")
            return True, f"The time is {current_time}, sir.", False

        # ── answer local date requests instantly ──
        if any(
            pattern in lowered_command
            for pattern in ["what's the date", "today's date", "what day is it"]
        ):
            current_date = datetime.datetime.now().strftime("%A, %B %d, %Y")
            return True, f"Today is {current_date}, sir.", False

        # ── open a browser when browser phrases are spoken ──
        if any(
            pattern in lowered_command
            for pattern in ["open browser", "open chrome", "open safari", "launch browser"]
        ):
            try:
                webbrowser.open("https://www.google.com")
                return True, "Opening your browser, sir.", False
            except Exception as error:
                self.logger.error("Browser launch failed: %s", error)
                return True, "I could not open the browser, sir.", False

        # ── open an arbitrary macOS application by name ──
        app_match = re.match(r"^(open|launch)\s+(.+)$", lowered_command)
        if app_match and all(keyword not in lowered_command for keyword in ["browser", "chrome", "safari"]):
            app_name = cleaned_command.split(maxsplit=1)[1].strip()
            if self.open_app(app_name):
                return True, f"Opening {app_name}, sir.", False
            return True, f"I could not open {app_name}, sir.", False

        # ── capture a screenshot locally using macOS tooling ──
        if lowered_command in {"take a screenshot", "screenshot"} or "take a screenshot" in lowered_command:
            _, response_text = self.take_screenshot()
            return True, response_text, False

        # ── create a timer and persist it as a reminder ──
        timer_match = re.search(
            r"set a timer for\s+(\d+)\s+(minute|minutes|second|seconds)",
            lowered_command,
        )
        if timer_match:
            amount = int(timer_match.group(1))
            unit = timer_match.group(2)
            seconds = amount * 60 if "minute" in unit else amount
            trigger_at = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
            timer_message = f"Sir, your {format_duration(seconds)} timer is complete."
            reminder_id = self.db_manager.save_reminder(timer_message, trigger_at)
            self.schedule_timer_alert(seconds, reminder_id, timer_message)
            return True, f"Timer set for {format_duration(seconds)}, sir.", False

        # ── save a natural-language reminder into PostgreSQL ──
        reminder_match = re.search(
            r"remind me to\s+(.+?)\s+in\s+(\d+)\s+(minute|minutes|second|seconds)",
            lowered_command,
        )
        if reminder_match:
            reminder_action = reminder_match.group(1).strip()
            amount = int(reminder_match.group(2))
            unit = reminder_match.group(3)
            seconds = amount * 60 if "minute" in unit else amount
            trigger_at = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
            reminder_text = f"Reminder, sir. {reminder_action}."
            self.db_manager.save_reminder(reminder_text, trigger_at)
            return True, f"I will remind you to {reminder_action} in {format_duration(seconds)}, sir.", False

        # ── open a Google search in the default browser ──
        if lowered_command.startswith("search for ") or lowered_command.startswith("google "):
            query = cleaned_command[11:].strip() if lowered_command.startswith("search for ") else cleaned_command[7:].strip()
            if not query:
                return True, "Tell me what you would like to search for, sir.", False
            try:
                search_url = f"https://www.google.com/search?q={quote_plus(query)}"
                webbrowser.open(search_url)
                return True, f"Searching Google for {query}, sir.", False
            except Exception as error:
                self.logger.error("Google search failed: %s", error)
                return True, "I could not open the search, sir.", False

        # ── save memory statements in PostgreSQL ──
        if lowered_command.startswith("remember that "):
            fact_text = cleaned_command[len("remember that ") :].strip()
            if not fact_text:
                return True, "Please tell me what you would like me to remember, sir.", False
            memory_key, memory_value, category = parse_memory_statement(fact_text)
            if self.db_manager.save_memory(memory_key, memory_value, category):
                return True, f"I will remember that {fact_text}, sir.", False
            return True, "I could not store that memory, sir.", False

        # ── recall one memory using fuzzy key matching ──
        if lowered_command.startswith("do you remember "):
            lookup_key = cleaned_command[len("do you remember ") :].strip().rstrip("?")
            memory = self.db_manager.recall_memory(lookup_key)
            if memory:
                return True, f"Yes, sir. I remember that {format_memory_sentence(memory)}.", False
            return True, f"I do not remember anything about {lookup_key}, sir.", False

        # ── answer open-ended memory recall queries ──
        if lowered_command.startswith("what do you know about "):
            lookup_key = cleaned_command[len("what do you know about ") :].strip().rstrip("?")
            memory = self.db_manager.recall_memory(lookup_key)
            if memory:
                return True, f"I remember that {format_memory_sentence(memory)}.", False
            return True, f"I do not know anything about {lookup_key} yet, sir.", False

        # ── list every stored memory in one spoken summary ──
        if lowered_command in {"what do you remember", "list your memories"}:
            return True, self.db_manager.recall_all_memories(), False

        # ── manually switch AI providers on spoken request ──
        if any(pattern in lowered_command for pattern in ["switch to groq", "use groq"]):
            success, response_text = self.ai_router.switch_ai("groq")
            return True, response_text, False

        if any(pattern in lowered_command for pattern in ["switch to gemini", "use gemini"]):
            success, response_text = self.ai_router.switch_ai("gemini")
            return True, response_text, False

        # ── return a short live health summary on demand ──
        if lowered_command in {"system status", "jarvis status"}:
            return True, self.build_status_report(), False

        # ── hand off anything unmatched to the AI router ──
        return False, "", False

    def route_command(self, command: str) -> None:
        """
        Route one recognized command through local skills or the AI stack.

        Parameters:
            command (str): The recognized command text.

        Returns:
            None.

        Exceptions:
            This method catches and handles all command-routing exceptions.
        """
        # ── skip empty commands quietly ──
        if not command.strip():
            return

        try:
            # ── log the user's message to PostgreSQL for session history ──
            self.db_manager.log_conversation(self.session_id, "user", command, None)

            # ── check fast local skills before any AI provider is contacted ──
            handled, response_text, should_shutdown = self.handle_builtin_skill(command)
            if handled:
                if should_shutdown:
                    self.request_shutdown("voice shutdown command")
                    return
                self.db_manager.log_conversation(self.session_id, "assistant", response_text, None)
                self.tts_engine.speak(response_text)
                return

            # ── call the AI router when no local skill matches the request ──
            reply_text, provider_used = self.ai_router.ask(command)

            # ── handle the case where both AI providers fail ──
            if reply_text is None:
                offline_message = "Both AI systems are offline sir. Running on local skills only."
                self.db_manager.log_conversation(self.session_id, "assistant", offline_message, None)
                self.tts_engine.speak(offline_message)
                return

            # ── persist the AI reply and queue it for speech ──
            self.db_manager.log_conversation(self.session_id, "assistant", reply_text, provider_used)
            self.tts_engine.speak(reply_text)
        except Exception as error:
            # ── catch all command-routing failures so the assistant never crashes ──
            self.logger.error("Command routing failed: %s", error)
            self.logger.error(traceback.format_exc())
            self.animator.set_state("error")
            self.tts_engine.speak("I encountered an internal error, sir.")

    def process_command_thread(self, inline_command: Optional[str] = None) -> None:
        """
        Handle one wake-triggered command session in a background thread.

        Parameters:
            inline_command (Optional[str]): Command text spoken in the same phrase as the wake word.

        Returns:
            None.

        Exceptions:
            This method catches and handles all command-session exceptions.
        """
        # ── mark that an active command session is underway ──
        self.command_active.set()

        try:
            command_text = inline_command

            # ── if only the wake word was spoken, prompt for the actual command ──
            if not command_text:
                prompt_done = self.tts_engine.speak("Yes, sir?")
                prompt_done.wait()
                command_text = self.speech_manager.listen_for_text(
                    timeout=8,
                    phrase_time_limit=15,
                    mode="command",
                    prompt_on_failure=True,
                )

            # ── ignore empty command sessions and return to passive listening ──
            if not command_text:
                return

            # ── route the recognized command through local skills or AI ──
            self.route_command(command_text)
        except Exception as error:
            # ── catch all command-thread failures so wake listening can recover ──
            self.logger.error("Command thread failed: %s", error)
            self.logger.error(traceback.format_exc())
            self.animator.set_state("error")
            self.tts_engine.speak("I ran into a command processing problem, sir.")
        finally:
            # ── release the active-command flag so the wake listener can resume ──
            self.command_active.clear()

    # ══════════════════════════════════════════════════════════
    # ██  ALWAYS-ON LISTENER
    # ══════════════════════════════════════════════════════════

    def wake_listener_loop(self) -> None:
        """
        Run the permanent background wake-word listener.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method catches and logs all wake-listener failures internally.
        """
        # ── loop forever until the main application requests shutdown ──
        while not self.stop_background_threads.is_set():
            try:
                # ── pause wake detection while speaking or handling a command ──
                if self.command_active.is_set() or self.tts_engine.speaking_event.is_set():
                    time.sleep(0.1)
                    continue

                # ── keep the idle animation visible while listening passively ──
                self.animator.set_state("idle")

                # ── capture a short wake-word phrase using a lightweight microphone window ──
                heard_text = self.speech_manager.listen_for_text(
                    timeout=3,
                    phrase_time_limit=3,
                    mode="wake",
                    prompt_on_failure=False,
                )
                if not heard_text:
                    continue

                # ── wake the assistant only when the configured wake word appears in the transcript ──
                if self.config.wake_word not in heard_text:
                    continue

                # ── extract any inline command that followed the wake word ──
                inline_command = heard_text.split(self.config.wake_word, 1)[1].strip(" ,.!?")

                # ── create a fresh command thread only after the wake word is confirmed ──
                command_thread = threading.Thread(
                    target=self.process_command_thread,
                    args=(inline_command or None,),
                    daemon=True,
                    name="jarvis-command-handler",
                )
                command_thread.start()
            except Exception as error:
                # ── recover from any wake-listener failure without crashing the assistant ──
                self.logger.error("Wake listener error: %s", error)
                self.logger.error(traceback.format_exc())
                time.sleep(2)

    # ══════════════════════════════════════════════════════════
    # ██  REMINDER CHECKER
    # ══════════════════════════════════════════════════════════

    def reminder_checker_loop(self) -> None:
        """
        Poll PostgreSQL every 30 seconds for due reminders.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method catches and logs reminder-checker errors internally.
        """
        # ── keep polling until shutdown is requested ──
        while not self.stop_background_threads.is_set():
            try:
                # ── fetch due reminders and mark them completed inside PostgreSQL ──
                due_reminders = self.db_manager.check_due_reminders()

                # ── announce each due reminder through the main-thread speech queue ──
                for reminder in due_reminders:
                    self.logger.info("Reminder fired. Reminder ID: %s", reminder["id"])
                    self.tts_engine.speak(reminder["message"])

                # ── sleep in an interruptible way so shutdown remains responsive ──
                if self.stop_background_threads.wait(timeout=30):
                    break
            except Exception as error:
                # ── recover from reminder checker failures and continue polling ──
                self.logger.error("Reminder checker error: %s", error)
                self.logger.error(traceback.format_exc())
                if self.stop_background_threads.wait(timeout=30):
                    break

    # ══════════════════════════════════════════════════════════
    # ██  STARTUP SEQUENCE
    # ══════════════════════════════════════════════════════════

    def graceful_shutdown(self) -> None:
        """
        Run the full graceful shutdown sequence.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method catches shutdown errors so cleanup continues as far as possible.
        """
        # ── restore idle animation before the shutdown announcement ──
        self.animator.set_state("idle")

        # ── speak the shutdown line on the main thread as required ──
        self.tts_engine.speak_sync("Shutting down all systems. Goodbye sir.")

        # ── persist the session end event before closing the database ──
        self.logger.info("Session ended. Session ID: %s", self.session_id)
        self.db_manager.log_conversation(self.session_id, "system", "Session ended", None)

        # ── signal all background threads to stop their loops ──
        self.stop_background_threads.set()

        # ── cancel any outstanding local timers so shutdown is clean ──
        with self.timers_lock:
            for timer in self.active_timers:
                try:
                    timer.cancel()
                except Exception:
                    pass
            self.active_timers.clear()

        # ── wait briefly for listener and reminder threads to finish ──
        for background_thread in [self.wake_thread, self.reminder_thread]:
            try:
                if background_thread and background_thread.is_alive():
                    background_thread.join(timeout=1.0)
            except Exception:
                pass

        # ── close pooled database connections after thread activity has stopped ──
        self.db_manager.close()

        # ── stop animation, clear the line, and print the final offline message ──
        self.animator.stop()
        print("JARVIS offline.")

    def run(self) -> int:
        """
        Run the main-thread event loop that processes speech and handles shutdown.

        Parameters:
            None.

        Returns:
            int: Process exit code.

        Exceptions:
            This method catches KeyboardInterrupt and internal loop errors.
        """
        try:
            # ── keep the main thread alive for queued TTS and shutdown monitoring ──
            while not self.shutdown_requested.is_set():
                self.tts_engine.process_one_task(timeout=0.1)
        except KeyboardInterrupt:
            # ── convert Ctrl+C into the standard graceful shutdown path ──
            self.request_shutdown("keyboard interrupt")
        except Exception as error:
            # ── log unexpected main-loop failures and still shut down cleanly ──
            self.logger.error("Main loop error: %s", error)
            self.logger.error(traceback.format_exc())
            self.request_shutdown("main loop error")
        finally:
            # ── drain any already-queued speech before final cleanup, then exit ──
            while not self.tts_engine.queue.empty():
                self.tts_engine.process_one_task(timeout=0.0)
            self.graceful_shutdown()

        return 0


# ══════════════════════════════════════════════════════════
# ██  MAIN LOOP
# ══════════════════════════════════════════════════════════


def main() -> int:
    """
    Load environment settings, start JARVIS, and run the main loop.

    Parameters:
        None.

    Returns:
        int: Process exit code.

    Exceptions:
        This function catches startup failures and exits gracefully.
    """
    # ── print the banner before loading `.env`, matching the requested startup order ──
    print(BANNER)

    # ── load `.env` and validate required keys before any runtime work begins ──
    config = load_and_validate_environment()
    if config is None:
        return 1

    # ── build the application object and run startup ──
    app = JarvisApp(config)
    if not app.startup_sequence():
        print("JARVIS could not start. Please review the messages above and check jarvis.log.")
        return 1

    # ── enter the main-thread event loop for queued speech and shutdown control ──
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
