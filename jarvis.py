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
import math
import mimetypes
import operator
import os
import queue
import random
import re
import shutil
import socket
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

import ast

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

try:
    import psutil
except ImportError:
    psutil = None

try:
    import pyautogui

    pyautogui.FAILSAFE = True
except ImportError:
    pyautogui = None

try:
    import pyperclip
except ImportError:
    pyperclip = None

try:
    import requests
except ImportError:
    requests = None

try:
    from send2trash import send2trash
except ImportError:
    send2trash = None

try:
    from PyQt6.QtCore import (
        QEasingCurve,
        QObject,
        QPauseAnimation,
        QPropertyAnimation,
        QRectF,
        Qt,
        QTimer,
        pyqtProperty,
        pyqtSignal,
    )
    from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
    from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect, QWidget
except ImportError:
    QApplication = None
    QColor = None
    QFont = None
    QGraphicsOpacityEffect = None
    QGuiApplication = None
    QObject = object
    QPainter = None
    QPainterPath = None
    QPauseAnimation = None
    QPen = None
    QPropertyAnimation = None
    QRectF = None
    Qt = None
    QTimer = None
    QEasingCurve = None
    QWidget = object

    def pyqtProperty(*args: Any, **kwargs: Any) -> Any:
        def decorator(function: Any) -> Any:
            return function

        return decorator

    def pyqtSignal(*args: Any, **kwargs: Any) -> Any:
        return None


# ══════════════════════════════════════════════════════════
# ██  ENVIRONMENT & CONFIG LOADER
# ══════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
LOG_PATH = BASE_DIR / "jarvis.log"
JARVIS_VERSION = "2.0.0"
JARVIS_BUILD_DATE = "2026-03-15"
NOTES_PATH = Path("~/Desktop/jarvis_notes.txt").expanduser()

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
    ui_mode (str): Presentation mode such as `both`, `terminal`, or `overlay`.

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
    ui_mode: str


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

    # ── normalize the requested UI mode and fall back safely when invalid ──
    ui_mode = os.getenv("UI_MODE", "both").strip().lower()
    if ui_mode not in {"both", "terminal", "overlay"}:
        ui_mode = "both"

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
        ui_mode=ui_mode,
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


# ─═════════════════════════════════════════════════════════
# ██  OVERLAY UI — PYQT6
# ══════════════════════════════════════════════════════════


if QApplication is not None and QPropertyAnimation is not None:

    class UIBridge(QObject):
        """
        Connect the voice pipeline to the PyQt overlay using queued signals only.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This class does not raise exceptions directly.
        """

        state_signal = pyqtSignal(str)
        text_signal = pyqtSignal(str)
        provider_signal = pyqtSignal(str)
        stop_signal = pyqtSignal()

    class JarvisOverlay(QWidget):
        """
        Render the floating JARVIS overlay window on a dedicated Qt thread.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This class keeps UI failures local so the assistant can fall back safely.
        """

        def __init__(self) -> None:
            """
            Initialize the overlay window, drawing state, and animations.

            Parameters:
                None.

            Returns:
                None.

            Exceptions:
                This constructor does not raise exceptions intentionally.
            """
            super().__init__()
            self.current_state = "idle"
            self.display_text = ""
            self.provider_name = "gemini"
            self.pulse_phase_value = 0.0
            self.spin_angle_value = 0.0
            self.text_opacity_value = 0.0
            self.bar_values = [8.0, 12.0, 18.0, 10.0, 14.0]
            self.idle_minimum_opacity = 0.15
            self.active_opacity = 1.0
            self.error_color = QColor("#FF4D6A")
            self.accent_color = QColor("#6C63FF")
            self.text_color = QColor("#E8E8F0")
            self.idle_timer = QTimer(self)
            self.idle_timer.setSingleShot(True)
            self.idle_timer.timeout.connect(self.fade_to_idle)
            self.setup_window()
            self.setup_animations()
            self.setup_ui()
            self.apply_state("idle", "")

        def setup_window(self) -> None:
            """
            Configure the floating frameless window.

            Parameters:
                None.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            # ── NEW ── frameless floating overlay with a translucent background ──
            self.setWindowFlags(
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.WindowDoesNotAcceptFocus
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            self.setFixedSize(460, 110)
            self.opacity_effect = QGraphicsOpacityEffect(self)
            self.opacity_effect.setOpacity(self.idle_minimum_opacity)
            self.setGraphicsEffect(self.opacity_effect)
            self.reposition()

        def setup_animations(self) -> None:
            """
            Build the reusable state animations.

            Parameters:
                None.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            # ── NEW ── cross-fade the overlay between visible states and idle ──
            self.opacity_animation = QPropertyAnimation(self.opacity_effect, b"opacity", self)
            self.opacity_animation.setDuration(300)
            self.opacity_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

            self.text_opacity_animation = QPropertyAnimation(self, b"textOpacity", self)
            self.text_opacity_animation.setDuration(300)
            self.text_opacity_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

            self.pulse_animation = QPropertyAnimation(self, b"pulsePhase", self)
            self.pulse_animation.setStartValue(0.0)
            self.pulse_animation.setEndValue(1.0)
            self.pulse_animation.setDuration(800)
            self.pulse_animation.setLoopCount(-1)
            self.pulse_animation.setEasingCurve(QEasingCurve.Type.InOutSine)

            self.spin_animation = QPropertyAnimation(self, b"spinAngle", self)
            self.spin_animation.setStartValue(0.0)
            self.spin_animation.setEndValue(360.0)
            self.spin_animation.setDuration(1200)
            self.spin_animation.setLoopCount(-1)
            self.spin_animation.setEasingCurve(QEasingCurve.Type.Linear)

            self.bar_animations: List[QPropertyAnimation] = []
            for index in range(5):
                animation = QPropertyAnimation(self, f"barLevel{index}".encode("utf-8"), self)
                animation.setStartValue(4.0)
                animation.setEndValue(24.0)
                animation.setDuration(random.randint(200, 600))
                animation.setLoopCount(-1)
                animation.setEasingCurve(QEasingCurve.Type.InOutSine)
                self.bar_animations.append(animation)

            self.error_pulse_animation = QPropertyAnimation(self.opacity_effect, b"opacity", self)
            self.error_pulse_animation.setDuration(450)
            self.error_pulse_animation.setKeyValueAt(0.0, 1.0)
            self.error_pulse_animation.setKeyValueAt(0.5, 0.55)
            self.error_pulse_animation.setKeyValueAt(1.0, 1.0)

        def setup_ui(self) -> None:
            """
            Finalize the initial overlay state and show the widget.

            Parameters:
                None.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            self.show()

        def reposition(self) -> None:
            """
            Move the overlay to the bottom center of the active screen.

            Parameters:
                None.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            geometry = screen.availableGeometry()
            x_pos = geometry.x() + (geometry.width() - self.width()) // 2
            y_pos = geometry.y() + geometry.height() - self.height() - 40
            self.move(x_pos, y_pos)

        def stop_all_state_animations(self) -> None:
            """
            Stop every active state animation before switching visuals.

            Parameters:
                None.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            self.pulse_animation.stop()
            self.spin_animation.stop()
            for animation in self.bar_animations:
                animation.stop()

        def animate_opacity(self, target_opacity: float) -> None:
            """
            Animate the overlay opacity to the requested level.

            Parameters:
                target_opacity (float): Desired final opacity.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            self.opacity_animation.stop()
            self.opacity_animation.setStartValue(self.opacity_effect.opacity())
            self.opacity_animation.setEndValue(target_opacity)
            self.opacity_animation.start()

        def apply_state(self, state: str, text: str = "") -> None:
            """
            Update the active visual state and associated text.

            Parameters:
                state (str): One of `idle`, `listening`, `thinking`, `speaking`, or `error`.
                text (str): Optional display text.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            normalized_state = state if state in {"idle", "listening", "thinking", "speaking", "error"} else "idle"
            self.current_state = normalized_state
            if text:
                self.display_text = text[:40] + ("..." if len(text) > 40 else "")
            elif normalized_state in {"listening", "thinking"}:
                self.display_text = f"{normalized_state.title()}..."
            elif normalized_state == "idle":
                self.display_text = ""

            self.stop_all_state_animations()
            self.idle_timer.stop()

            if normalized_state == "idle":
                self.text_opacity_animation.stop()
                self.text_opacity_animation.setStartValue(self.text_opacity_value)
                self.text_opacity_animation.setEndValue(0.0)
                self.text_opacity_animation.start()
                self.idle_timer.start(4000)
            elif normalized_state == "listening":
                self.animate_opacity(self.active_opacity)
                self.text_opacity_animation.stop()
                self.text_opacity_animation.setStartValue(self.text_opacity_value)
                self.text_opacity_animation.setEndValue(1.0)
                self.text_opacity_animation.start()
                self.pulse_animation.start()
            elif normalized_state == "thinking":
                self.animate_opacity(self.active_opacity)
                self.text_opacity_animation.stop()
                self.text_opacity_animation.setStartValue(self.text_opacity_value)
                self.text_opacity_animation.setEndValue(1.0)
                self.text_opacity_animation.start()
                self.spin_animation.start()
            elif normalized_state == "speaking":
                self.animate_opacity(self.active_opacity)
                self.text_opacity_animation.stop()
                self.text_opacity_animation.setStartValue(self.text_opacity_value)
                self.text_opacity_animation.setEndValue(1.0)
                self.text_opacity_animation.start()
                for animation in self.bar_animations:
                    animation.start()
            elif normalized_state == "error":
                self.animate_opacity(self.active_opacity)
                self.text_opacity_animation.stop()
                self.text_opacity_animation.setStartValue(self.text_opacity_value)
                self.text_opacity_animation.setEndValue(1.0)
                self.text_opacity_animation.start()
                for animation in self.bar_animations:
                    animation.start()
                self.error_pulse_animation.start()
                QTimer.singleShot(2000, lambda: self.apply_state("idle", ""))

            self.update()

        def fade_to_idle(self) -> None:
            """
            Fade the overlay down to its low-opacity idle appearance.

            Parameters:
                None.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            if self.current_state == "idle":
                self.animate_opacity(self.idle_minimum_opacity)
                self.update()

        def on_state_changed(self, state: str) -> None:
            """
            Receive a queued state change from the voice pipeline.

            Parameters:
                state (str): New overlay state.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            self.apply_state(state, "")

        def on_text_changed(self, text: str) -> None:
            """
            Receive new display text from the voice pipeline.

            Parameters:
                text (str): Text to render in the overlay.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            self.display_text = text[:40] + ("..." if len(text) > 40 else "")
            self.text_opacity_animation.stop()
            self.text_opacity_animation.setStartValue(0.0)
            self.text_opacity_animation.setEndValue(1.0)
            self.text_opacity_animation.start()
            self.update()

        def on_provider_changed(self, provider: str) -> None:
            """
            Receive a provider-label update from the voice pipeline.

            Parameters:
                provider (str): Provider name such as `gemini` or `groq`.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            self.provider_name = provider.strip().lower() or "gemini"
            self.update()

        def on_stop_requested(self) -> None:
            """
            Close the overlay when the application is shutting down.

            Parameters:
                None.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            self.close()

        def draw_background(self, painter: QPainter) -> None:
            """
            Draw the rounded frosted-glass shell.

            Parameters:
                painter (QPainter): Active widget painter.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            outer_rect = self.rect().adjusted(4, 4, -4, -4)
            background_path = QPainterPath()
            background_path.addRoundedRect(QRectF(outer_rect), 34, 34)
            painter.fillPath(background_path, QColor(13, 13, 15, 224))

            border_pen = QPen(QColor(108, 99, 255, 70), 1.2)
            painter.setPen(border_pen)
            painter.drawPath(background_path)

        def draw_idle(self, painter: QPainter) -> None:
            """
            Draw the idle glowing dot.

            Parameters:
                painter (QPainter): Active widget painter.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            center_x = self.width() // 2
            center_y = self.height() // 2
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(108, 99, 255, 75))
            painter.drawEllipse(center_x - 12, center_y - 12, 24, 24)
            painter.setBrush(self.accent_color)
            painter.drawEllipse(center_x - 4, center_y - 4, 8, 8)

        def draw_microphone(self, painter: QPainter) -> None:
            """
            Draw a simple microphone icon for the listening state.

            Parameters:
                painter (QPainter): Active widget painter.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            painter.save()
            painter.setPen(QPen(self.text_color, 2))
            painter.drawRoundedRect(32, 30, 12, 24, 6, 6)
            painter.drawLine(38, 54, 38, 64)
            painter.drawArc(28, 44, 20, 20, 0, -180 * 16)
            painter.drawLine(30, 64, 46, 64)
            painter.restore()

        def draw_listening(self, painter: QPainter) -> None:
            """
            Draw the pulsing listening rings.

            Parameters:
                painter (QPainter): Active widget painter.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            center_x = self.width() // 2
            center_y = 42
            self.draw_microphone(painter)
            for offset in (0.0, 0.33, 0.66):
                progress = (self.pulse_phase_value + offset) % 1.0
                radius = 8 + (progress * 32)
                alpha = max(20, int(140 * (1.0 - progress)))
                pen = QPen(QColor(108, 99, 255, alpha), 2)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(
                    int(center_x - radius),
                    int(center_y - radius),
                    int(radius * 2),
                    int(radius * 2),
                )

        def draw_thinking(self, painter: QPainter) -> None:
            """
            Draw the rotating arc used while AI providers think.

            Parameters:
                painter (QPainter): Active widget painter.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            center_x = self.width() // 2
            center_y = 42
            painter.save()
            painter.translate(center_x, center_y)
            painter.rotate(self.spin_angle_value)
            pen = QPen(self.accent_color, 4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawArc(-20, -20, 40, 40, 20 * 16, 260 * 16)
            painter.restore()

        def draw_speaking(self, painter: QPainter, color: QColor) -> None:
            """
            Draw the animated equalizer bars for speaking and error states.

            Parameters:
                painter (QPainter): Active widget painter.
                color (QColor): Accent color for the bars.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            base_x = (self.width() // 2) - 36
            base_y = 54
            painter.setPen(Qt.PenStyle.NoPen)
            for index, value in enumerate(self.bar_values):
                x_pos = base_x + (index * 18)
                glow_color = QColor(color)
                glow_color.setAlpha(70)
                painter.setBrush(glow_color)
                painter.drawRoundedRect(x_pos - 2, int(base_y - value - 2), 12, int(value + 4), 6, 6)
                painter.setBrush(color)
                painter.drawRoundedRect(x_pos, int(base_y - value), 8, int(value), 4, 4)

        def draw_provider_badge(self, painter: QPainter) -> None:
            """
            Draw the provider pill in the thinking state.

            Parameters:
                painter (QPainter): Active widget painter.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            badge_rect = QRectF(self.width() - 84, 30, 56, 22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 22))
            painter.drawRoundedRect(badge_rect, 11, 11)
            painter.setPen(self.text_color)
            painter.setFont(QFont("Helvetica Neue", 9))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, self.provider_name)

        def draw_text(self, painter: QPainter) -> None:
            """
            Draw the current overlay caption with animated opacity.

            Parameters:
                painter (QPainter): Active widget painter.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            if not self.display_text:
                return
            painter.save()
            color = QColor(self.text_color)
            color.setAlphaF(max(0.0, min(1.0, self.text_opacity_value)))
            painter.setPen(color)
            painter.setFont(QFont("Helvetica Neue", 13))
            painter.drawText(
                QRectF(24, 68, self.width() - 48, 26),
                Qt.AlignmentFlag.AlignCenter,
                self.display_text,
            )
            painter.restore()

        def paintEvent(self, event: Any) -> None:
            """
            Paint the overlay background and active-state graphics.

            Parameters:
                event (Any): Qt paint event.

            Returns:
                None.

            Exceptions:
                This method does not raise exceptions.
            """
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self.draw_background(painter)

            if self.current_state == "idle":
                self.draw_idle(painter)
            elif self.current_state == "listening":
                self.draw_listening(painter)
            elif self.current_state == "thinking":
                self.draw_thinking(painter)
                self.draw_provider_badge(painter)
            elif self.current_state == "speaking":
                self.draw_speaking(painter, self.accent_color)
            elif self.current_state == "error":
                self.draw_speaking(painter, self.error_color)

            self.draw_text(painter)

        def get_pulse_phase(self) -> float:
            return self.pulse_phase_value

        def set_pulse_phase(self, value: float) -> None:
            self.pulse_phase_value = float(value)
            self.update()

        pulsePhase = pyqtProperty(float, fget=get_pulse_phase, fset=set_pulse_phase)

        def get_spin_angle(self) -> float:
            return self.spin_angle_value

        def set_spin_angle(self, value: float) -> None:
            self.spin_angle_value = float(value)
            self.update()

        spinAngle = pyqtProperty(float, fget=get_spin_angle, fset=set_spin_angle)

        def get_text_opacity(self) -> float:
            return self.text_opacity_value

        def set_text_opacity(self, value: float) -> None:
            self.text_opacity_value = float(value)
            self.update()

        textOpacity = pyqtProperty(float, fget=get_text_opacity, fset=set_text_opacity)

        def _get_bar_value(self, index: int) -> float:
            return self.bar_values[index]

        def _set_bar_value(self, index: int, value: float) -> None:
            self.bar_values[index] = float(value)
            self.update()

        def get_bar_level_0(self) -> float:
            return self._get_bar_value(0)

        def set_bar_level_0(self, value: float) -> None:
            self._set_bar_value(0, value)

        barLevel0 = pyqtProperty(float, fget=get_bar_level_0, fset=set_bar_level_0)

        def get_bar_level_1(self) -> float:
            return self._get_bar_value(1)

        def set_bar_level_1(self, value: float) -> None:
            self._set_bar_value(1, value)

        barLevel1 = pyqtProperty(float, fget=get_bar_level_1, fset=set_bar_level_1)

        def get_bar_level_2(self) -> float:
            return self._get_bar_value(2)

        def set_bar_level_2(self, value: float) -> None:
            self._set_bar_value(2, value)

        barLevel2 = pyqtProperty(float, fget=get_bar_level_2, fset=set_bar_level_2)

        def get_bar_level_3(self) -> float:
            return self._get_bar_value(3)

        def set_bar_level_3(self, value: float) -> None:
            self._set_bar_value(3, value)

        barLevel3 = pyqtProperty(float, fget=get_bar_level_3, fset=set_bar_level_3)

        def get_bar_level_4(self) -> float:
            return self._get_bar_value(4)

        def set_bar_level_4(self, value: float) -> None:
            self._set_bar_value(4, value)

        barLevel4 = pyqtProperty(float, fget=get_bar_level_4, fset=set_bar_level_4)

    class JarvisOverlayThread(threading.Thread):
        """
        Host the PyQt overlay in a dedicated thread.

        Parameters:
            bridge (UIBridge): Signal bridge used by the voice pipeline.
            logger (logging.Logger): Logger for UI lifecycle events.

        Returns:
            None.

        Exceptions:
            This thread reports failures to the logger and exits cleanly.
        """

        def __init__(self, bridge: UIBridge, logger: logging.Logger) -> None:
            super().__init__(daemon=True, name="jarvis-overlay-ui")
            self.bridge = bridge
            self.logger = logger
            self.ready_event = threading.Event()
            self.failed = False

        def run(self) -> None:
            """
            Start the Qt event loop and wire the bridge to the overlay.

            Parameters:
                None.

            Returns:
                None.

            Exceptions:
                This method catches and logs UI failures.
            """
            try:
                app = QApplication.instance() or QApplication([])
                app.setQuitOnLastWindowClosed(False)
                overlay = JarvisOverlay()
                self.bridge.state_signal.connect(overlay.on_state_changed)
                self.bridge.text_signal.connect(overlay.on_text_changed)
                self.bridge.provider_signal.connect(overlay.on_provider_changed)
                self.bridge.stop_signal.connect(overlay.on_stop_requested)
                self.bridge.stop_signal.connect(app.quit)
                self.ready_event.set()
                app.exec()
            except Exception as error:
                self.failed = True
                self.logger.error("Overlay UI failed to start: %s", error)
                self.ready_event.set()

else:

    class UIBridge:
        def __init__(self) -> None:
            self.state_signal = None
            self.text_signal = None
            self.provider_signal = None
            self.stop_signal = None

    class JarvisOverlayThread(threading.Thread):
        def __init__(self, bridge: UIBridge, logger: logging.Logger) -> None:
            super().__init__(daemon=True, name="jarvis-overlay-ui-disabled")
            self.ready_event = threading.Event()
            self.failed = True

        def run(self) -> None:
            self.ready_event.set()


class JarvisPresentationController:
    """
    Drive the terminal animator and optional PyQt overlay from one shared state machine.

    Parameters:
        ui_mode (str): Requested UI mode such as `both`, `terminal`, or `overlay`.
        logger (logging.Logger): Logger for UI diagnostics and fallback events.

    Returns:
        None.

    Exceptions:
        Public methods catch their own UI errors so presentation never crashes JARVIS.
    """

    def __init__(self, ui_mode: str, logger: logging.Logger) -> None:
        """
        Initialize the presentation controller and requested backends.

        Parameters:
            ui_mode (str): Requested UI mode from configuration.
            logger (logging.Logger): Logger for UI diagnostics.

        Returns:
            None.

        Exceptions:
            This constructor does not raise exceptions.
        """
        # ── NEW ── keep terminal output and overlay state aligned from one controller ──
        self.ui_mode = ui_mode
        self.logger = logger
        self.terminal_enabled = ui_mode in {"both", "terminal"}
        self.overlay_requested = ui_mode in {"both", "overlay"}
        self.terminal_animator = JarvisAnimator() if self.terminal_enabled else None
        self.bridge = UIBridge() if self.overlay_requested else None
        self.overlay_thread = JarvisOverlayThread(self.bridge, logger) if self.overlay_requested else None
        self.output_lock = threading.Lock()
        self.state = "idle"
        self.provider = "gemini"
        self.last_text = ""
        self.overlay_enabled = False

    def start(self) -> None:
        """
        Start the requested presentation backends.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method catches backend startup issues and logs fallbacks.
        """
        if self.terminal_animator is not None:
            self.terminal_animator.start()

        if self.overlay_thread is not None:
            if QApplication is None:
                self.logger.warning("PyQt6 is unavailable. Falling back to terminal-only mode.")
                return
            self.overlay_thread.start()
            self.overlay_thread.ready_event.wait(timeout=3.0)
            if self.overlay_thread.failed:
                self.logger.warning("Overlay UI is unavailable. Falling back to terminal-only mode.")
                return
            self.overlay_enabled = True
            self.set_provider(self.provider)
            self.set_state(self.state, self.last_text)

    def stop(self) -> None:
        """
        Stop the overlay and terminal animation cleanly.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method catches shutdown issues so application cleanup continues.
        """
        try:
            if self.overlay_enabled and self.bridge is not None and getattr(self.bridge, "stop_signal", None):
                self.bridge.stop_signal.emit()
                if self.overlay_thread and self.overlay_thread.is_alive():
                    self.overlay_thread.join(timeout=1.5)
        except Exception as error:
            self.logger.error("Overlay shutdown failed: %s", error)

        if self.terminal_animator is not None:
            self.terminal_animator.stop()

    def safe_print(self, message: str) -> None:
        """
        Print text safely above the terminal animation when enabled.

        Parameters:
            message (str): Message to print.

        Returns:
            None.

        Exceptions:
            This method catches terminal output issues.
        """
        if self.terminal_animator is not None:
            self.terminal_animator.safe_print(message)
            return

        with self.output_lock:
            try:
                print(message)
            except Exception:
                pass

    def clear_line(self) -> None:
        """
        Clear the terminal animation line when enabled.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        if self.terminal_animator is not None:
            self.terminal_animator.clear_line()

    def set_provider(self, provider: str) -> None:
        """
        Update the provider label across all active UIs.

        Parameters:
            provider (str): Provider name such as `gemini` or `groq`.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        self.provider = provider.strip().lower() or "gemini"
        if self.terminal_animator is not None:
            self.terminal_animator.set_provider(self.provider)
        if self.overlay_enabled and self.bridge is not None and getattr(self.bridge, "provider_signal", None):
            self.bridge.provider_signal.emit(self.provider)

    def set_text(self, text: str) -> None:
        """
        Update the overlay text without changing the active state.

        Parameters:
            text (str): Text to display.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        self.last_text = text.strip()
        if self.overlay_enabled and self.bridge is not None and getattr(self.bridge, "text_signal", None):
            self.bridge.text_signal.emit(self.last_text)

    def set_state(self, state: str, text: str = "") -> None:
        """
        Update the shared state machine and fan it out to every UI backend.

        Parameters:
            state (str): Shared state such as `idle`, `listening`, `thinking`, `speaking`, or `error`.
            text (str): Optional state-associated text.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        self.state = state
        if text:
            self.last_text = text.strip()

        if self.terminal_animator is not None:
            self.terminal_animator.set_state(state)

        if self.overlay_enabled and self.bridge is not None:
            if getattr(self.bridge, "state_signal", None):
                self.bridge.state_signal.emit(state)
            if getattr(self.bridge, "text_signal", None):
                overlay_text = self.last_text
                if state == "listening" and not overlay_text:
                    overlay_text = "Listening..."
                elif state == "thinking" and not overlay_text:
                    overlay_text = "Thinking..."
                self.bridge.text_signal.emit(overlay_text)

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

    def __init__(self, voice_rate: int, animator: JarvisPresentationController, logger: logging.Logger) -> None:
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
        self.animator.set_state("speaking", text)
        self.animator.set_text(text)

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
        animator: JarvisPresentationController,
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
            self.animator.set_state("listening", "Listening...")

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
        animator: JarvisPresentationController,
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
            self.animator.set_state("thinking", "Thinking...")

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


# ─═════════════════════════════════════════════════════════
# ██  LOCAL SKILL HELPERS
# ══════════════════════════════════════════════════════════


def clean_spoken_entity(entity: str) -> str:
    """
    Strip filler words from a spoken file, folder, or destination phrase.

    Parameters:
        entity (str): Raw spoken entity text.

    Returns:
        str: Cleaned entity text.

    Exceptions:
        This function does not raise exceptions.
    """
    cleaned = entity.strip().strip(" .!?")
    cleaned = re.sub(
        r"^(please\s+|the\s+|my\s+|this\s+|that\s+|a\s+|an\s+)+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(file|folder|directory|folder called|folder named|file called|file named)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^(called|named)\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip().strip("\"'")


def format_bytes(size_in_bytes: int) -> str:
    """
    Convert a byte count into a compact human-readable string.

    Parameters:
        size_in_bytes (int): Raw size in bytes.

    Returns:
        str: Human-readable size such as `2.3 GB`.

    Exceptions:
        This function does not raise exceptions.
    """
    value = float(size_in_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def parse_spoken_number(text: str) -> Optional[int]:
    """
    Convert simple spoken ordinal choices into an integer index.

    Parameters:
        text (str): Spoken number text.

    Returns:
        Optional[int]: Parsed 1-based number, or None when unclear.

    Exceptions:
        This function does not raise exceptions.
    """
    cleaned_text = text.strip().lower()
    if cleaned_text.isdigit():
        return int(cleaned_text)

    mapping = {
        "one": 1,
        "first": 1,
        "two": 2,
        "second": 2,
        "three": 3,
        "third": 3,
        "four": 4,
        "fourth": 4,
        "five": 5,
        "fifth": 5,
    }
    return mapping.get(cleaned_text)


def safe_calculate(expression: str) -> float:
    """
    Evaluate a restricted arithmetic expression safely.

    Parameters:
        expression (str): Expression using numbers and basic operators.

    Returns:
        float: Calculated numeric result.

    Exceptions:
        Raises:
            ValueError: When the expression contains unsupported syntax.
    """
    allowed_binary_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    allowed_unary_ops = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    def evaluate(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Num):
            return float(node.n)
        if isinstance(node, ast.BinOp) and type(node.op) in allowed_binary_ops:
            return allowed_binary_ops[type(node.op)](evaluate(node.left), evaluate(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed_unary_ops:
            return allowed_unary_ops[type(node.op)](evaluate(node.operand))
        raise ValueError("Unsupported expression")

    if not re.fullmatch(r"[\d\s\.\+\-\*\/%\(\)]+", expression):
        raise ValueError("Unsupported expression")

    parsed = ast.parse(expression, mode="eval")
    return evaluate(parsed)


def format_result_number(value: float) -> str:
    """
    Format a float so whole numbers are spoken cleanly.

    Parameters:
        value (float): Numeric value to format.

    Returns:
        str: Spoken-friendly numeric string.

    Exceptions:
        This function does not raise exceptions.
    """
    if math.isclose(value, round(value), abs_tol=1e-9):
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


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

        # ── UPGRADED ── keep the terminal animation and optional overlay behind one controller ──
        self.animator = JarvisPresentationController(config.ui_mode, self.logger)
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
        self.last_response_text = ""
        self.automation_available = pyautogui is not None
        self.home_path = Path.home()
        self.desktop_path = self.home_path / "Desktop"
        self.documents_path = self.home_path / "Documents"
        self.downloads_path = self.home_path / "Downloads"
        self.common_search_roots = [
            self.desktop_path,
            self.documents_path,
            self.downloads_path,
            self.home_path,
        ]
        self.skill_routes: List[Tuple[List[str], Any]] = [
            (["goodbye", "shut down", "exit", "that's all"], self.handle_exit_commands),
            (
                [
                    "what time",
                    "current time",
                    "what's the time",
                    "what's the date",
                    "today's date",
                    "what day is it",
                    "take a screenshot",
                    "screenshot",
                    "volume",
                    "mute",
                    "unmute",
                    "brightness",
                    "lock screen",
                    "sleep computer",
                    "what's my ip",
                    "ip address",
                    "battery",
                    "storage",
                    "ram",
                    "cpu",
                    "processes",
                    "system status",
                    "jarvis status",
                    "empty trash",
                ],
                self.handle_system_control_commands,
            ),
            (
                [
                    "rename ",
                    "change the name",
                    "move ",
                    "put ",
                    "send ",
                    "delete ",
                    "remove ",
                    "trash ",
                    "copy ",
                    "duplicate ",
                    "make a copy",
                    "create a folder",
                    "make a new folder",
                    "new folder",
                    "find ",
                    "where is ",
                    "locate ",
                    "search for file",
                    "what's in ",
                    "list contents",
                    "show me what's in",
                    "in finder",
                    "open ",
                    "launch ",
                    "open the file",
                    "tell me about",
                    "file info",
                    "what is ",
                    "organize my desktop",
                    "clean up desktop",
                    "sort my desktop",
                ],
                self.handle_file_management_commands,
            ),
            (
                ["clipboard", "copy that", "clear clipboard", "read clipboard"],
                self.handle_clipboard_commands,
            ),
            (
                [
                    "type ",
                    "write ",
                    "press enter",
                    "press escape",
                    "select all",
                    "copy",
                    "paste",
                    "undo",
                ],
                self.handle_text_input_commands,
            ),
            (
                [
                    "minimize window",
                    "close window",
                    "switch app",
                    "next app",
                    "show desktop",
                    "full screen",
                ],
                self.handle_window_management_commands,
            ),
            (
                ["are we connected", "check internet", "wifi", "network settings"],
                self.handle_network_commands,
            ),
            (
                ["calculate ", "convert ", "percent of", " in binary", "what is "],
                self.handle_calculation_commands,
            ),
            (
                ["make a note", "note this down", "read my notes", "what are my notes", "clear my notes"],
                self.handle_notes_commands,
            ),
            (
                ["weather", "will it rain"],
                self.handle_weather_commands,
            ),
            (
                ["remember that", "do you remember", "what do you know about", "what do you remember", "list your memories"],
                self.handle_memory_commands,
            ),
            (
                ["set a timer", "remind me to"],
                self.handle_timer_and_reminder_commands,
            ),
            (
                ["open browser", "open chrome", "open safari", "launch browser", "search for ", "google ", "open ", "launch "],
                self.handle_app_launch_commands,
            ),
            (
                ["tell me a joke", "flip a coin", "roll a dice", "motivate me", "what version are you", " in binary"],
                self.handle_fun_commands,
            ),
        ]
        self.jokes = [
            "Why do programmers prefer dark mode? Because light attracts bugs.",
            "Why did the computer go to therapy? It had too many unresolved issues.",
            "I would tell you a UDP joke, sir, but you might not get it.",
            "Why was the Mac so calm? It had excellent Finder control.",
            "Parallel lines have so much in common. It is a shame they will never meet.",
            "Why do Java developers wear glasses? Because they do not C sharp.",
            "Why was the keyboard so honest? It always had the right keys.",
            "Why did the scarecrow become a developer? He was outstanding in his field.",
            "What do you call eight hobbits? A hobbyte.",
            "Why did the server break up with the client? Too many bad requests.",
            "Why was the battery optimistic? It still had some charge left.",
            "How do trees get online? They log in.",
            "Why did the notebook blush? It saw the desktop get organized.",
            "What did the RAM say after a workout? I feel refreshed.",
            "Why do calendars seem so confident? Their days are numbered.",
            "Why did the phone wear glasses? It lost its contacts.",
            "Why did the folder look proud? It had everything in order.",
            "What is a computer's favorite snack? Microchips.",
            "Why was the browser exhausted? Too many tabs open.",
            "Why did the developer stay calm? They had excellent exception handling.",
        ]
        self.motivational_quotes = [
            "Small steps still move the mission forward.",
            "Momentum beats perfection, sir.",
            "You do not need a perfect day to make meaningful progress.",
            "Consistency turns difficult work into normal work.",
            "The next attempt might be the one that clicks.",
            "You have handled hard things before. This is another one.",
            "Progress hides inside repetition.",
            "A calm mind makes sharper decisions.",
            "Finish the next clear step, then the next one after that.",
            "Discipline is just confidence built in public.",
        ]

    def queue_response(self, text: str, provider: Optional[str] = None) -> None:
        """
        Persist and speak one assistant response.

        Parameters:
            text (str): Assistant text to log and speak.
            provider (Optional[str]): AI provider name when the response came from AI.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        self.last_response_text = text
        self.db_manager.log_conversation(self.session_id, "assistant", text, provider)
        self.tts_engine.speak(text)

    def speak_and_wait(self, text: str) -> None:
        """
        Speak text and block until the queued speech finishes.

        Parameters:
            text (str): Text to speak.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        self.last_response_text = text
        done_event = self.tts_engine.speak(text)
        done_event.wait()

    def listen_for_followup(self, timeout: int = 6, phrase_time_limit: int = 6) -> Optional[str]:
        """
        Listen for a short follow-up answer during confirmations or disambiguation.

        Parameters:
            timeout (int): Seconds to wait for speech to start.
            phrase_time_limit (int): Maximum phrase duration in seconds.

        Returns:
            Optional[str]: Recognized text, or None when nothing clear was heard.

        Exceptions:
            This method does not raise exceptions.
        """
        return self.speech_manager.listen_for_text(
            timeout=timeout,
            phrase_time_limit=phrase_time_limit,
            mode="command",
            prompt_on_failure=False,
        )

    def ask_confirmation(self, prompt: str) -> bool:
        """
        Ask for a yes or no confirmation and default to cancel on ambiguity.

        Parameters:
            prompt (str): Prompt to speak before listening.

        Returns:
            bool: True only when the user confirms clearly.

        Exceptions:
            This method does not raise exceptions.
        """
        self.speak_and_wait(prompt)
        confirmation = self.listen_for_followup()
        if not confirmation:
            return False
        lowered_confirmation = confirmation.strip().lower()
        if any(word in lowered_confirmation for word in ["yes", "confirm", "do it", "go ahead"]):
            return True
        return False

    def run_subprocess(self, command: List[str]) -> bool:
        """
        Run a subprocess command and log failures centrally.

        Parameters:
            command (List[str]): Command tokens to execute.

        Returns:
            bool: True when the command exits successfully.

        Exceptions:
            This method catches subprocess failures and returns False.
        """
        try:
            subprocess.run(command, check=True)
            return True
        except Exception as error:
            self.logger.error("Command failed (%s): %s", " ".join(command), error)
            return False

    def run_applescript(self, script: str) -> bool:
        """
        Execute a small AppleScript command safely.

        Parameters:
            script (str): AppleScript source.

        Returns:
            bool: True when the script succeeds.

        Exceptions:
            This method catches subprocess failures and returns False.
        """
        return self.run_subprocess(["osascript", "-e", script])

    def check_automation_permissions(self) -> bool:
        """
        Check whether pyautogui automation appears available on this Mac.

        Parameters:
            None.

        Returns:
            bool: True when keyboard automation should work, otherwise False.

        Exceptions:
            This method catches automation-check failures and disables the feature gracefully.
        """
        if pyautogui is None:
            self.automation_available = False
            return False

        try:
            pyautogui.position()
            pyautogui.size()
            self.automation_available = True
        except Exception as error:
            self.automation_available = False
            self.logger.warning("Accessibility automation is unavailable: %s", error)
        return self.automation_available

    def ensure_automation_available(self) -> Tuple[bool, str]:
        """
        Verify keyboard automation can be used before running pyautogui actions.

        Parameters:
            None.

        Returns:
            Tuple[bool, str]: Availability flag and the appropriate spoken response on failure.

        Exceptions:
            This method does not raise exceptions.
        """
        if pyautogui is None:
            return False, "pyautogui is not installed, so automation skills are unavailable, sir."
        if self.automation_available:
            return True, ""
        return False, (
            "I need accessibility permissions sir. Please enable them in System Preferences."
        )

    def perform_automation_action(self, action: Any, success_message: str) -> Tuple[bool, str, bool]:
        """
        Run a pyautogui action with graceful accessibility failure handling.

        Parameters:
            action (Any): Callable that performs the automation step.
            success_message (str): Spoken success response.

        Returns:
            Tuple[bool, str, bool]: Standard local-skill result tuple.

        Exceptions:
            This method catches automation failures and disables automation gracefully.
        """
        available, failure_message = self.ensure_automation_available()
        if not available:
            return True, failure_message, False

        try:
            action()
            return True, success_message, False
        except Exception as error:
            self.logger.warning("Automation command failed: %s", error)
            self.automation_available = False
            return True, (
                "I need accessibility permissions sir. Please enable them in System Preferences."
            ), False

    def resolve_special_folder(self, location_text: str) -> Optional[Path]:
        """
        Resolve spoken folder aliases like Desktop or Downloads.

        Parameters:
            location_text (str): Spoken destination text.

        Returns:
            Optional[Path]: Resolved folder path, or None when no alias matches.

        Exceptions:
            This method does not raise exceptions.
        """
        cleaned_location = clean_spoken_entity(location_text).lower()
        aliases = {
            "desktop": self.desktop_path,
            "documents": self.documents_path,
            "document": self.documents_path,
            "downloads": self.downloads_path,
            "download": self.downloads_path,
            "home": self.home_path,
            "house": self.home_path,
        }
        return aliases.get(cleaned_location)

    def iter_search_matches(
        self,
        query: str,
        include_files: bool = True,
        include_dirs: bool = True,
        roots: Optional[List[Path]] = None,
        max_depth: int = 3,
    ) -> List[Path]:
        """
        Search common roots recursively with a controlled depth limit.

        Parameters:
            query (str): Filename or folder phrase to look for.
            include_files (bool): Whether files should be matched.
            include_dirs (bool): Whether directories should be matched.
            roots (Optional[List[Path]]): Custom search roots.
            max_depth (int): Maximum recursive depth beneath each root.

        Returns:
            List[Path]: Ranked filesystem matches.

        Exceptions:
            This method catches filesystem access errors and continues searching.
        """
        search_query = clean_spoken_entity(query).lower()
        if not search_query:
            return []

        search_roots = roots or self.common_search_roots
        seen_paths: set[str] = set()
        candidates: List[Tuple[int, Path]] = []

        for root in search_roots:
            if not root.exists():
                continue

            for current_root, dirs, files in os.walk(root):
                current_path = Path(current_root)
                try:
                    relative_depth = len(current_path.relative_to(root).parts)
                except Exception:
                    relative_depth = 0

                if relative_depth >= max_depth:
                    dirs[:] = []

                names: List[str] = []
                if include_dirs:
                    names.extend(dirs)
                if include_files:
                    names.extend(files)

                for name in names:
                    candidate_path = current_path / name
                    normalized_name = name.lower()
                    stem_name = candidate_path.stem.lower()
                    if search_query not in normalized_name and search_query not in stem_name:
                        continue
                    resolved_string = str(candidate_path.resolve())
                    if resolved_string in seen_paths:
                        continue
                    seen_paths.add(resolved_string)
                    score = 0
                    if normalized_name == search_query or stem_name == search_query:
                        score -= 30
                    elif normalized_name.startswith(search_query):
                        score -= 20
                    else:
                        score -= 10
                    score += relative_depth
                    candidates.append((score, candidate_path))

        return [candidate for _, candidate in sorted(candidates, key=lambda item: (item[0], str(item[1]).lower()))]

    def choose_match(self, matches: List[Path], spoken_name: str) -> Optional[Path]:
        """
        Resolve multiple filesystem matches by asking the user which one they mean.

        Parameters:
            matches (List[Path]): Candidate paths.
            spoken_name (str): Original spoken target name.

        Returns:
            Optional[Path]: Chosen path, or None when the choice is unclear.

        Exceptions:
            This method does not raise exceptions.
        """
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]

        numbered_items = []
        for index, path in enumerate(matches[:5], start=1):
            parent_name = path.parent.name or "home"
            numbered_items.append(f"{index}, {path.name} in {parent_name}")
        prompt = (
            f"I found multiple matches for {clean_spoken_entity(spoken_name)}. "
            + " ".join(numbered_items)
            + ". Say the number you want."
        )
        self.speak_and_wait(prompt)
        answer = self.listen_for_followup()
        if not answer:
            return None

        number = parse_spoken_number(answer)
        if number is not None and 1 <= number <= min(len(matches), 5):
            return matches[number - 1]

        lowered_answer = answer.lower()
        for path in matches[:5]:
            if path.name.lower() in lowered_answer:
                return path
        return None

    def resolve_existing_target(
        self,
        target_text: str,
        include_files: bool = True,
        include_dirs: bool = True,
    ) -> Optional[Path]:
        """
        Find an existing filesystem target using common locations and voice disambiguation.

        Parameters:
            target_text (str): Spoken target phrase.
            include_files (bool): Whether file matches are allowed.
            include_dirs (bool): Whether folder matches are allowed.

        Returns:
            Optional[Path]: Resolved path, or None when not found or not clarified.

        Exceptions:
            This method does not raise exceptions.
        """
        direct_alias = self.resolve_special_folder(target_text)
        if direct_alias is not None and direct_alias.exists():
            return direct_alias

        matches = self.iter_search_matches(
            target_text,
            include_files=include_files,
            include_dirs=include_dirs,
            roots=self.common_search_roots,
            max_depth=3,
        )
        return self.choose_match(matches, target_text)

    def resolve_destination_path(self, destination_text: str) -> Optional[Path]:
        """
        Resolve a spoken destination to a usable folder path.

        Parameters:
            destination_text (str): Spoken destination phrase.

        Returns:
            Optional[Path]: Resolved folder path, or None when resolution fails.

        Exceptions:
            This method does not raise exceptions.
        """
        special_folder = self.resolve_special_folder(destination_text)
        if special_folder is not None:
            return special_folder

        direct_path = Path(destination_text).expanduser()
        if direct_path.exists() and direct_path.is_dir():
            return direct_path

        return self.resolve_existing_target(destination_text, include_files=False, include_dirs=True)

    def trash_path(self, target_path: Path) -> bool:
        """
        Move a path to Trash without permanently deleting it.

        Parameters:
            target_path (Path): File or folder to trash.

        Returns:
            bool: True when the item reaches Trash successfully.

        Exceptions:
            This method catches Trash failures and returns False.
        """
        try:
            if send2trash is not None:
                send2trash(str(target_path))
                return True
        except Exception as error:
            self.logger.error("send2trash failed for %s: %s", target_path, error)

        applescript = (
            f'tell application "Finder" to delete POSIX file "{str(target_path).replace(chr(34), chr(92) + chr(34))}"'
        )
        return self.run_applescript(applescript)

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

        # ── UPGRADED ── start the shared presentation controller before printing status ──
        self.animator.start()

        # ── check keyboard automation support once at startup and disable it cleanly on failure ──
        self.check_automation_permissions()

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

        if pyautogui is not None and not self.automation_available:
            self.tts_engine.speak_sync(
                "I need accessibility permissions sir. Please enable them in System Preferences."
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
        ui_mode = self.config.ui_mode.title()

        # ── build the requested terminal status panel ──
        panel = (
            "┌─────────────────────────────────────────┐\n"
            "│           JARVIS  SYSTEM STATUS          │\n"
            "├─────────────────────────────────────────┤\n"
            f"│  Primary AI   : Gemini 1.5 Flash   {gemini_mark}   │\n"
            f"│  Fallback AI  : Groq LLaMA3        {groq_mark}   │\n"
            f"│  Database     : PostgreSQL         {db_mark}   │\n"
            f"│  Microphone   : Ready              {mic_mark}   │\n"
            f"│  UI Mode      : {ui_mode}{' ' * max(0, 19 - len(ui_mode))}│\n"
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

    def handle_builtin_skill_legacy(self, command: str) -> Tuple[bool, str, bool]:
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
        if lowered_command in {"goodbye", "shut down", "exit", "that's all","bye bye"}:
            return True, "Shutting down all systems. Goodbye sir.", True

        # ── answer local time requests instantly ──
        if any(pattern in lowered_command for pattern in ["what time", "current time", "what's the time","time"]):
            current_time = datetime.datetime.now().strftime("%I:%M %p")
            return True, f"The time is {current_time}, sir.", False

        # ── answer local date requests instantly ──
        if any(
            pattern in lowered_command
            for pattern in ["what's the date", "today's date", "what day is it","date","day"]
        ):
            current_date = datetime.datetime.now().strftime("%A, %B %d, %Y")
            return True, f"Today is {current_date}, sir.", False

        # ── open a browser when browser phrases are spoken ──
        if any(
            pattern in lowered_command
            for pattern in ["open browser", "open chrome", "launch browser", "chrome", "browser"]
        ):
            try:
                webbrowser.open("https://www.google.com")
                return True, "Opening your browser, sir.", False
            except Exception as error:
                self.logger.error("Browser launch failed: %s", error)
                return True, "I could not open the browser, sir.", False

        # ── open a safari when safari phrases are spoken ──
        if any(
            pattern in lowered_command
            for pattern in ["open safari", "launch safari","safari"]
        ):
            try:
                webbrowser.open("https://www.safari.com")
                return True, "Opening your safari, sir.", False
            except Exception as error:
                self.logger.error("Safari launch failed: %s", error)
                return True, "I could not open the safari, sir.", False

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

    def handle_exit_commands(self, cleaned_command: str, lowered_command: str) -> Tuple[bool, str, bool]:
        """
        Handle explicit shutdown phrases.

        Parameters:
            cleaned_command (str): Original command text.
            lowered_command (str): Lowercased command text.

        Returns:
            Tuple[bool, str, bool]: Standard skill result tuple.

        Exceptions:
            This method does not raise exceptions.
        """
        if lowered_command in {"goodbye", "shut down", "exit", "that's all", "bye bye"}:
            return True, "Shutting down all systems. Goodbye sir.", True
        return False, "", False

    def handle_system_control_commands(self, cleaned_command: str, lowered_command: str) -> Tuple[bool, str, bool]:
        """
        Handle system control, diagnostics, and screenshot commands.

        Parameters:
            cleaned_command (str): Original command text.
            lowered_command (str): Lowercased command text.

        Returns:
            Tuple[bool, str, bool]: Standard skill result tuple.

        Exceptions:
            This method catches local command failures and returns friendly responses.
        """
        if any(pattern in lowered_command for pattern in ["what time", "current time", "what's the time"]):
            return True, f"The time is {datetime.datetime.now().strftime('%I:%M %p')}, sir.", False

        if any(pattern in lowered_command for pattern in ["what's the date", "today's date", "what day is it"]):
            return True, f"Today is {datetime.datetime.now().strftime('%A, %B %d, %Y')}, sir.", False

        if lowered_command in {"system status", "jarvis status"}:
            return True, self.build_status_report(), False

        if lowered_command in {"take a screenshot", "screenshot"} or "take a screenshot" in lowered_command:
            _, response_text = self.take_screenshot()
            return True, response_text, False

        if lowered_command in {"increase volume", "volume up"}:
            success = self.run_applescript(
                "set volume output volume ((output volume of (get volume settings)) + 10)"
            )
            return True, "Volume increased, sir." if success else "I could not adjust the volume, sir.", False

        if lowered_command in {"decrease volume", "volume down"}:
            success = self.run_applescript(
                "set volume output volume ((output volume of (get volume settings)) - 10)"
            )
            return True, "Volume decreased, sir." if success else "I could not adjust the volume, sir.", False

        volume_match = re.search(r"set volume to\s+(\d{1,3})", lowered_command)
        if volume_match:
            volume = max(0, min(100, int(volume_match.group(1))))
            success = self.run_applescript(f"set volume output volume {volume}")
            return True, (
                f"Volume set to {volume} percent, sir." if success else "I could not set the volume, sir."
            ), False

        if lowered_command in {"mute", "mute volume"}:
            success = self.run_applescript("set volume output muted true")
            return True, "Volume muted, sir." if success else "I could not mute the volume, sir.", False

        if lowered_command == "unmute":
            success = self.run_applescript("set volume output muted false")
            return True, "Volume restored, sir." if success else "I could not unmute the volume, sir.", False

        if lowered_command in {"increase brightness", "brightness up", "decrease brightness", "brightness down"}:
            brightness_cli = shutil.which("brightness")
            if not brightness_cli:
                return True, "The brightness command line tool is not installed, sir.", False
            try:
                current = subprocess.run(
                    [brightness_cli, "-l"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                match = re.search(r"brightness\s+([0-9.]+)", current.stdout)
                current_value = float(match.group(1)) if match else 0.5
                delta = 0.1 if "increase" in lowered_command or "up" in lowered_command else -0.1
                target = min(1.0, max(0.0, current_value + delta))
                subprocess.run([brightness_cli, str(target)], check=True)
                response = "Brightness increased, sir." if delta > 0 else "Brightness decreased, sir."
                return True, response, False
            except Exception as error:
                self.logger.error("Brightness command failed: %s", error)
                return True, "I could not adjust the brightness, sir.", False

        if lowered_command == "lock screen":
            success = self.run_subprocess(["pmset", "displaysleepnow"])
            return True, "Locking the screen, sir." if success else "I could not lock the screen, sir.", False

        if lowered_command in {"sleep", "sleep computer"}:
            success = self.run_applescript('tell app "System Events" to sleep')
            return True, "Putting the computer to sleep, sir." if success else "I could not put the computer to sleep, sir.", False

        if lowered_command == "empty trash":
            if not self.ask_confirmation("Are you sure you want to empty the Trash? Say yes to confirm."):
                return True, "Trash emptying cancelled sir.", False
            success = self.run_applescript('tell app "Finder" to empty trash')
            return True, "Trash emptied, sir." if success else "I could not empty the Trash, sir.", False

        if "ip address" in lowered_command:
            try:
                ip_address = socket.gethostbyname(socket.gethostname())
                if ip_address.startswith("127."):
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                        sock.connect(("8.8.8.8", 80))
                        ip_address = sock.getsockname()[0]
                return True, f"Your IP address is {ip_address}, sir.", False
            except Exception as error:
                self.logger.error("IP address lookup failed: %s", error)
                return True, "I could not determine your IP address, sir.", False

        if "battery" in lowered_command:
            try:
                result = subprocess.run(
                    ["pmset", "-g", "batt"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                match = re.search(r"(\d+)%", result.stdout)
                if match:
                    return True, f"Battery is at {match.group(1)} percent, sir.", False
            except Exception as error:
                self.logger.error("Battery lookup failed: %s", error)
            return True, "I could not read the battery status, sir.", False

        if "storage" in lowered_command:
            total, used, free = shutil.disk_usage("/")
            return True, f"You have {format_bytes(free)} free out of {format_bytes(total)} total storage, sir.", False

        if "ram" in lowered_command:
            if psutil is None:
                return True, "psutil is not installed, so I cannot read memory usage, sir.", False
            memory = psutil.virtual_memory()
            return True, f"You are using {format_bytes(memory.used)} of {format_bytes(memory.total)} RAM, sir.", False

        if lowered_command == "cpu usage":
            if psutil is None:
                return True, "psutil is not installed, so I cannot read CPU usage, sir.", False
            return True, f"CPU usage is {psutil.cpu_percent(interval=1):.0f} percent, sir.", False

        if "what processes are running" in lowered_command:
            if psutil is None:
                return True, "psutil is not installed, so I cannot inspect processes, sir.", False
            processes = []
            for process in psutil.process_iter(["name"]):
                try:
                    process.cpu_percent(interval=None)
                    processes.append(process)
                except Exception:
                    continue
            time.sleep(0.2)
            ranked = []
            for process in processes:
                try:
                    ranked.append((process.cpu_percent(interval=None), process.info.get("name") or "Unknown"))
                except Exception:
                    continue
            top_processes = sorted(ranked, key=lambda item: item[0], reverse=True)[:5]
            if not top_processes:
                return True, "I could not determine the active processes, sir.", False
            spoken = ", ".join(f"{name} at {cpu:.0f} percent" for cpu, name in top_processes)
            return True, f"Top processes right now are {spoken}.", False

        return False, "", False

    def handle_file_management_commands(self, cleaned_command: str, lowered_command: str) -> Tuple[bool, str, bool]:
        """
        Handle file and folder operations using natural language patterns.

        Parameters:
            cleaned_command (str): Original command text.
            lowered_command (str): Lowercased command text.

        Returns:
            Tuple[bool, str, bool]: Standard skill result tuple.

        Exceptions:
            This method catches filesystem failures and returns friendly responses.
        """
        rename_match = re.search(r"(?:rename|change the name of)\s+(.+?)\s+to\s+(.+)", cleaned_command, flags=re.IGNORECASE)
        if rename_match:
            old_name = clean_spoken_entity(rename_match.group(1))
            new_name = clean_spoken_entity(rename_match.group(2))
            source_path = self.resolve_existing_target(old_name, include_files=True, include_dirs=True)
            if source_path is None:
                return True, f"I could not find {old_name}, sir.", False
            try:
                target_path = source_path.with_name(new_name)
                os.rename(source_path, target_path)
                return True, f"Done sir. {source_path.name} has been renamed to {new_name}.", False
            except Exception as error:
                self.logger.error("Rename failed: %s", error)
                return True, "I could not rename that item, sir.", False

        move_match = re.search(r"(?:move|put|send)\s+(.+?)\s+(?:to|in)\s+(.+)", cleaned_command, flags=re.IGNORECASE)
        if move_match:
            item_name = clean_spoken_entity(move_match.group(1))
            destination_name = clean_spoken_entity(move_match.group(2))
            source_path = self.resolve_existing_target(item_name, include_files=True, include_dirs=True)
            destination_path = self.resolve_destination_path(destination_name)
            if source_path is None:
                return True, f"I could not find {item_name}, sir.", False
            if destination_path is None:
                return True, f"I could not resolve the destination {destination_name}, sir.", False
            try:
                shutil.move(str(source_path), str(destination_path))
                return True, f"Moved. {source_path.name} is now in {destination_path}.", False
            except Exception as error:
                self.logger.error("Move failed: %s", error)
                return True, "I could not move that item, sir.", False

        copy_match = re.search(
            r"(?:copy|duplicate)\s+(.+?)\s+to\s+(.+)|make a copy of\s+(.+?)\s+in\s+(.+)",
            cleaned_command,
            flags=re.IGNORECASE,
        )
        if copy_match:
            item_name = clean_spoken_entity(copy_match.group(1) or copy_match.group(3) or "")
            destination_name = clean_spoken_entity(copy_match.group(2) or copy_match.group(4) or "")
            source_path = self.resolve_existing_target(item_name, include_files=True, include_dirs=True)
            destination_path = self.resolve_destination_path(destination_name)
            if source_path is None:
                return True, f"I could not find {item_name}, sir.", False
            if destination_path is None:
                return True, f"I could not resolve the destination {destination_name}, sir.", False
            try:
                if source_path.is_dir():
                    shutil.copytree(source_path, destination_path / source_path.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(source_path, destination_path / source_path.name)
                return True, "Copy complete sir.", False
            except Exception as error:
                self.logger.error("Copy failed: %s", error)
                return True, "I could not copy that item, sir.", False

        delete_match = re.search(r"(?:delete|remove|trash)\s+(.+)", cleaned_command, flags=re.IGNORECASE)
        if delete_match:
            item_name = clean_spoken_entity(delete_match.group(1))
            target_path = self.resolve_existing_target(item_name, include_files=True, include_dirs=True)
            if target_path is None:
                return True, f"I could not find {item_name}, sir.", False
            if not self.ask_confirmation(
                f"Are you sure you want to delete {target_path.name}? Say yes to confirm."
            ):
                return True, "Deletion cancelled sir.", False
            if self.trash_path(target_path):
                return True, f"Done. {target_path.name} has been moved to the Trash.", False
            return True, "I could not move that item to the Trash, sir.", False

        folder_match = re.search(
            r"(?:create a folder called|create a folder named|make a new folder called|make a new folder named|new folder)\s+(.+)",
            cleaned_command,
            flags=re.IGNORECASE,
        )
        if folder_match:
            remainder = folder_match.group(1).strip()
            location_match = re.search(r"(.+?)\s+(?:on|in|at)\s+(.+)", remainder, flags=re.IGNORECASE)
            folder_name = clean_spoken_entity(location_match.group(1) if location_match else remainder)
            destination_root = self.desktop_path
            if location_match:
                resolved_destination = self.resolve_destination_path(location_match.group(2))
                if resolved_destination is None:
                    return True, "I could not resolve that folder location, sir.", False
                destination_root = resolved_destination
            try:
                target_folder = destination_root / folder_name
                os.makedirs(target_folder, exist_ok=True)
                if destination_root == self.desktop_path:
                    return True, f"Created. New folder {folder_name} is on your Desktop.", False
                return True, f"Created. New folder {folder_name} is in {destination_root}.", False
            except Exception as error:
                self.logger.error("Folder creation failed: %s", error)
                return True, "I could not create that folder, sir.", False

        find_match = re.search(r"(?:find|where is|locate|search for file)\s+(.+)", cleaned_command, flags=re.IGNORECASE)
        if find_match:
            item_name = clean_spoken_entity(find_match.group(1))
            target_path = self.resolve_existing_target(item_name, include_files=True, include_dirs=True)
            if target_path is None:
                return True, f"I couldn't find {item_name} sir.", False
            return True, f"Found it. {target_path.name} is located at {target_path}.", False

        folder_list_match = re.search(
            r"(?:what's in|list contents of|show me what's in)\s+(.+)",
            cleaned_command,
            flags=re.IGNORECASE,
        )
        finder_match = re.search(r"open\s+(.+?)\s+in finder", cleaned_command, flags=re.IGNORECASE)
        if folder_list_match or finder_match:
            folder_name = clean_spoken_entity(
                folder_list_match.group(1) if folder_list_match else finder_match.group(1)
            )
            folder_path = self.resolve_existing_target(folder_name, include_files=False, include_dirs=True)
            if folder_path is None:
                return True, f"I could not find the folder {folder_name}, sir.", False
            try:
                items = sorted(path.name for path in folder_path.iterdir())
                preview = ", ".join(items[:5]) if items else "nothing yet"
                subprocess.run(["open", str(folder_path)], check=True)
                if len(items) > 5:
                    return True, f"Your {folder_path.name} contains: {preview}, and {len(items) - 5} more items.", False
                return True, f"Your {folder_path.name} contains: {preview}.", False
            except Exception as error:
                self.logger.error("Folder listing failed: %s", error)
                return True, "I could not open that folder, sir.", False

        if lowered_command in {"organize my desktop", "clean up desktop", "sort my desktop"}:
            if not self.ask_confirmation("Are you sure you want me to organize your Desktop? Say yes to confirm."):
                return True, "Desktop organization cancelled sir.", False
            try:
                folders = {
                    "Images": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic"},
                    "Documents": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".ppt", ".pptx", ".xls", ".xlsx"},
                    "Videos": {".mp4", ".mov", ".mkv", ".avi", ".webm"},
                    "Others": set(),
                }
                for folder_name in folders:
                    (self.desktop_path / folder_name).mkdir(exist_ok=True)
                for item in self.desktop_path.iterdir():
                    if item.is_dir() or item.name in folders:
                        continue
                    target_folder = self.desktop_path / "Others"
                    for folder_name, extensions in folders.items():
                        if item.suffix.lower() in extensions:
                            target_folder = self.desktop_path / folder_name
                            break
                    shutil.move(str(item), str(target_folder / item.name))
                return True, "I've organized your Desktop into 4 folders sir.", False
            except Exception as error:
                self.logger.error("Desktop organization failed: %s", error)
                return True, "I could not organize your Desktop, sir.", False

        open_match = re.search(r"(?:open|launch)(?: the file)?\s+(.+)", cleaned_command, flags=re.IGNORECASE)
        if open_match and "browser" not in lowered_command and "finder" not in lowered_command:
            target_name = clean_spoken_entity(open_match.group(1))
            target_path = self.resolve_existing_target(target_name, include_files=True, include_dirs=True)
            if target_path is None:
                return False, "", False
            try:
                subprocess.run(["open", str(target_path)], check=True)
                return True, f"Opening {target_path.name}, sir.", False
            except Exception as error:
                self.logger.error("File open failed: %s", error)
                return True, "I could not open that item, sir.", False

        info_match = re.search(r"(?:tell me about|what is|file info)\s+(.+)", cleaned_command, flags=re.IGNORECASE)
        if info_match:
            target_name = clean_spoken_entity(info_match.group(1))
            target_path = self.resolve_existing_target(target_name, include_files=True, include_dirs=True)
            if target_path is None:
                return False, "", False
            try:
                stats = target_path.stat()
                created = datetime.datetime.fromtimestamp(stats.st_ctime).strftime("%B %d, %Y at %I:%M %p")
                modified = datetime.datetime.fromtimestamp(stats.st_mtime).strftime("%B %d, %Y at %I:%M %p")
                file_type = "folder" if target_path.is_dir() else (mimetypes.guess_type(target_path.name)[0] or target_path.suffix or "file")
                return True, (
                    f"{target_path.name} is a {file_type}. Size is {format_bytes(stats.st_size)}. "
                    f"It was created on {created} and modified on {modified}."
                ), False
            except Exception as error:
                self.logger.error("File info failed: %s", error)
                return True, "I could not inspect that item, sir.", False

        return False, "", False

    def handle_clipboard_commands(self, cleaned_command: str, lowered_command: str) -> Tuple[bool, str, bool]:
        """
        Handle clipboard actions before AI fallback.

        Parameters:
            cleaned_command (str): Original command text.
            lowered_command (str): Lowercased command text.

        Returns:
            Tuple[bool, str, bool]: Standard skill result tuple.

        Exceptions:
            This method catches clipboard failures and returns friendly responses.
        """
        if pyperclip is None:
            return True, "pyperclip is not installed, so clipboard skills are unavailable, sir.", False

        if lowered_command in {"what's in my clipboard", "read clipboard"}:
            try:
                clipboard_text = pyperclip.paste().strip()
                if not clipboard_text:
                    return True, "Your clipboard is empty, sir.", False
                return True, f"Your clipboard contains: {clipboard_text}", False
            except Exception as error:
                self.logger.error("Clipboard read failed: %s", error)
                return True, "I could not read the clipboard, sir.", False

        if lowered_command == "clear clipboard":
            try:
                pyperclip.copy("")
                return True, "Clipboard cleared, sir.", False
            except Exception as error:
                self.logger.error("Clipboard clear failed: %s", error)
                return True, "I could not clear the clipboard, sir.", False

        if lowered_command == "copy that":
            try:
                pyperclip.copy(self.last_response_text)
                return True, "Copied the last response to your clipboard, sir.", False
            except Exception as error:
                self.logger.error("Clipboard copy failed: %s", error)
                return True, "I could not copy that, sir.", False

        return False, "", False

    def handle_text_input_commands(self, cleaned_command: str, lowered_command: str) -> Tuple[bool, str, bool]:
        """
        Handle typing and keyboard shortcut commands.

        Parameters:
            cleaned_command (str): Original command text.
            lowered_command (str): Lowercased command text.

        Returns:
            Tuple[bool, str, bool]: Standard skill result tuple.

        Exceptions:
            This method returns graceful failures when accessibility permissions are missing.
        """
        if lowered_command.startswith("type ") or lowered_command.startswith("write "):
            text_to_type = cleaned_command.split(maxsplit=1)[1].strip() if " " in cleaned_command else ""
            if not text_to_type:
                return True, "Please tell me what you want typed, sir.", False
            return self.perform_automation_action(lambda: pyautogui.typewrite(text_to_type), "Typed it, sir.")

        shortcuts = {
            "press enter": (lambda: pyautogui.press("enter"), "Enter pressed, sir."),
            "press escape": (lambda: pyautogui.press("escape"), "Escape pressed, sir."),
            "select all": (lambda: pyautogui.hotkey("command", "a"), "Selected everything, sir."),
            "copy": (lambda: pyautogui.hotkey("command", "c"), "Copied, sir."),
            "paste": (lambda: pyautogui.hotkey("command", "v"), "Pasted, sir."),
            "undo": (lambda: pyautogui.hotkey("command", "z"), "Undone, sir."),
        }
        if lowered_command in shortcuts:
            action, message = shortcuts[lowered_command]
            return self.perform_automation_action(action, message)

        return False, "", False

    def handle_window_management_commands(self, cleaned_command: str, lowered_command: str) -> Tuple[bool, str, bool]:
        """
        Handle active-window and app-switch commands.

        Parameters:
            cleaned_command (str): Original command text.
            lowered_command (str): Lowercased command text.

        Returns:
            Tuple[bool, str, bool]: Standard skill result tuple.

        Exceptions:
            This method returns friendly failures when shortcuts cannot be executed.
        """
        if lowered_command == "minimize window":
            success = self.run_applescript('tell app "System Events" to keystroke "m" using command down')
            return True, "Window minimized, sir." if success else "I could not minimize the window, sir.", False

        window_actions = {
            "close window": (lambda: pyautogui.hotkey("command", "w"), "Window closed, sir."),
            "switch app": (lambda: pyautogui.hotkey("command", "tab"), "Switching applications, sir."),
            "next app": (lambda: pyautogui.hotkey("command", "tab"), "Switching applications, sir."),
            "show desktop": (lambda: pyautogui.hotkey("fn", "f11"), "Showing the desktop, sir."),
            "full screen": (lambda: pyautogui.hotkey("command", "ctrl", "f"), "Toggling full screen, sir."),
        }
        if lowered_command in window_actions:
            action, message = window_actions[lowered_command]
            return self.perform_automation_action(action, message)

        return False, "", False

    def handle_network_commands(self, cleaned_command: str, lowered_command: str) -> Tuple[bool, str, bool]:
        """
        Handle internet checks, Wi-Fi details, and network settings.

        Parameters:
            cleaned_command (str): Original command text.
            lowered_command (str): Lowercased command text.

        Returns:
            Tuple[bool, str, bool]: Standard skill result tuple.

        Exceptions:
            This method catches network helper failures and returns friendly responses.
        """
        if lowered_command in {"are we connected", "check internet"}:
            if requests is None:
                return True, "The requests package is not installed, so I cannot check the internet, sir.", False
            try:
                requests.get("https://8.8.8.8", timeout=3, verify=False)
                return True, "Yes sir. The internet connection looks good.", False
            except Exception:
                return True, "No sir. I could not reach the internet.", False

        if "wifi" in lowered_command:
            try:
                result = subprocess.run(
                    [
                        "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport",
                        "-I",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                match = re.search(r"\sSSID: (.+)", result.stdout)
                if match:
                    return True, f"You are connected to {match.group(1).strip()}, sir.", False
            except Exception as error:
                self.logger.error("Wi-Fi lookup failed: %s", error)
            return True, "I could not determine the current Wi-Fi network, sir.", False

        if "network settings" in lowered_command:
            success = self.run_subprocess(["open", "x-apple.systempreferences:com.apple.preference.network"])
            return True, "Opening Network Settings, sir." if success else "I could not open Network Settings, sir.", False

        return False, "", False

    def handle_calculation_commands(self, cleaned_command: str, lowered_command: str) -> Tuple[bool, str, bool]:
        """
        Handle safe calculations, conversions, percentages, and binary output.

        Parameters:
            cleaned_command (str): Original command text.
            lowered_command (str): Lowercased command text.

        Returns:
            Tuple[bool, str, bool]: Standard skill result tuple.

        Exceptions:
            This method catches math parsing issues and falls back cleanly when needed.
        """
        binary_match = re.search(r"what'?s\s+(\d+)\s+in binary", lowered_command)
        if binary_match:
            number = int(binary_match.group(1))
            return True, f"{number} in binary is {bin(number)}.", False

        percent_match = re.search(r"what'?s\s+(\d+(?:\.\d+)?)\s+percent of\s+(\d+(?:\.\d+)?)", lowered_command)
        if percent_match:
            part = float(percent_match.group(1))
            whole = float(percent_match.group(2))
            result = (part / 100.0) * whole
            return True, f"{format_result_number(part)} percent of {format_result_number(whole)} is {format_result_number(result)}.", False

        convert_match = re.search(r"convert\s+(\d+(?:\.\d+)?)\s+([a-z]+)\s+to\s+([a-z]+)", lowered_command)
        if convert_match:
            value = float(convert_match.group(1))
            from_unit = convert_match.group(2)
            to_unit = convert_match.group(3)
            conversions = {
                ("km", "miles"): value * 0.621371,
                ("kilometers", "miles"): value * 0.621371,
                ("miles", "km"): value / 0.621371,
                ("miles", "kilometers"): value / 0.621371,
                ("kg", "lbs"): value * 2.20462,
                ("kilograms", "lbs"): value * 2.20462,
                ("lbs", "kg"): value / 2.20462,
                ("pounds", "kg"): value / 2.20462,
                ("celsius", "fahrenheit"): (value * 9 / 5) + 32,
                ("fahrenheit", "celsius"): (value - 32) * 5 / 9,
                ("usd", "inr"): value * 83.0,
                ("inr", "usd"): value / 83.0,
            }
            converted = conversions.get((from_unit, to_unit))
            if converted is None:
                return True, "I can convert kilometers and miles, kilograms and pounds, Celsius and Fahrenheit, and USD and INR, sir.", False
            return True, f"{format_result_number(value)} {from_unit} is {format_result_number(converted)} {to_unit}, sir.", False

        expression = ""
        if lowered_command.startswith("calculate "):
            expression = cleaned_command[len("calculate ") :].strip()
        elif lowered_command.startswith("what is "):
            expression = cleaned_command[len("what is ") :].strip().rstrip("?")
            if not re.fullmatch(r"[\d\s\.\+\-\*\/%\(\)]+", expression):
                return False, "", False

        if expression:
            try:
                result = safe_calculate(expression)
                return True, f"The answer is {format_result_number(result)}, sir.", False
            except Exception:
                return True, "I could not calculate that safely, sir.", False

        return False, "", False

    def handle_notes_commands(self, cleaned_command: str, lowered_command: str) -> Tuple[bool, str, bool]:
        """
        Handle quick local note-taking commands.

        Parameters:
            cleaned_command (str): Original command text.
            lowered_command (str): Lowercased command text.

        Returns:
            Tuple[bool, str, bool]: Standard skill result tuple.

        Exceptions:
            This method catches filesystem failures and returns friendly responses.
        """
        if lowered_command.startswith("make a note "):
            content = cleaned_command[len("make a note ") :].strip()
        elif lowered_command.startswith("note this down "):
            content = cleaned_command[len("note this down ") :].strip()
        else:
            content = ""

        if content:
            try:
                NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with NOTES_PATH.open("a", encoding="utf-8") as handle:
                    handle.write(f"[{timestamp}] {content}\n")
                return True, "Noted, sir.", False
            except Exception as error:
                self.logger.error("Note write failed: %s", error)
                return True, "I could not save that note, sir.", False

        if lowered_command in {"read my notes", "what are my notes"}:
            try:
                if not NOTES_PATH.exists():
                    return True, "You do not have any notes yet, sir.", False
                lines = [line.strip() for line in NOTES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
                if not lines:
                    return True, "You do not have any notes yet, sir.", False
                return True, f"Here are your latest notes, sir. {' '.join(lines[-5:])}", False
            except Exception as error:
                self.logger.error("Note read failed: %s", error)
                return True, "I could not read your notes, sir.", False

        if lowered_command == "clear my notes":
            if not self.ask_confirmation("Are you sure you want to clear your notes? Say yes to confirm."):
                return True, "Note clearing cancelled sir.", False
            try:
                NOTES_PATH.write_text("", encoding="utf-8")
                return True, "Your notes are cleared, sir.", False
            except Exception as error:
                self.logger.error("Note clear failed: %s", error)
                return True, "I could not clear your notes, sir.", False

        return False, "", False

    def handle_weather_commands(self, cleaned_command: str, lowered_command: str) -> Tuple[bool, str, bool]:
        """
        Handle simple weather requests through wttr.in.

        Parameters:
            cleaned_command (str): Original command text.
            lowered_command (str): Lowercased command text.

        Returns:
            Tuple[bool, str, bool]: Standard skill result tuple.

        Exceptions:
            This method catches network failures and returns friendly responses.
        """
        if requests is None:
            return True, "The requests package is not installed, so weather lookup is unavailable, sir.", False
        try:
            response = requests.get("https://wttr.in/Kolkata?format=3", timeout=5)
            if response.ok:
                return True, response.text.strip(), False
        except Exception as error:
            self.logger.error("Weather lookup failed: %s", error)
        return True, "I could not fetch the weather right now, sir.", False

    def handle_memory_commands(self, cleaned_command: str, lowered_command: str) -> Tuple[bool, str, bool]:
        """
        Handle PostgreSQL-backed memory skills and provider switches.

        Parameters:
            cleaned_command (str): Original command text.
            lowered_command (str): Lowercased command text.

        Returns:
            Tuple[bool, str, bool]: Standard skill result tuple.

        Exceptions:
            This method catches local failures and returns friendly responses.
        """
        if lowered_command.startswith("remember that "):
            fact_text = cleaned_command[len("remember that ") :].strip()
            if not fact_text:
                return True, "Please tell me what you would like me to remember, sir.", False
            memory_key, memory_value, category = parse_memory_statement(fact_text)
            if self.db_manager.save_memory(memory_key, memory_value, category):
                return True, f"I will remember that {fact_text}, sir.", False
            return True, "I could not store that memory, sir.", False

        if lowered_command.startswith("do you remember "):
            lookup_key = cleaned_command[len("do you remember ") :].strip().rstrip("?")
            memory = self.db_manager.recall_memory(lookup_key)
            if memory:
                return True, f"Yes, sir. I remember that {format_memory_sentence(memory)}.", False
            return True, f"I do not remember anything about {lookup_key}, sir.", False

        if lowered_command.startswith("what do you know about "):
            lookup_key = cleaned_command[len("what do you know about ") :].strip().rstrip("?")
            memory = self.db_manager.recall_memory(lookup_key)
            if memory:
                return True, f"I remember that {format_memory_sentence(memory)}.", False
            return True, f"I do not know anything about {lookup_key} yet, sir.", False

        if lowered_command in {"what do you remember", "list your memories"}:
            return True, self.db_manager.recall_all_memories(), False

        if any(pattern in lowered_command for pattern in ["switch to groq", "use groq"]):
            _, response_text = self.ai_router.switch_ai("groq")
            return True, response_text, False

        if any(pattern in lowered_command for pattern in ["switch to gemini", "use gemini"]):
            _, response_text = self.ai_router.switch_ai("gemini")
            return True, response_text, False

        return False, "", False

    def handle_timer_and_reminder_commands(self, cleaned_command: str, lowered_command: str) -> Tuple[bool, str, bool]:
        """
        Handle timers and reminders.

        Parameters:
            cleaned_command (str): Original command text.
            lowered_command (str): Lowercased command text.

        Returns:
            Tuple[bool, str, bool]: Standard skill result tuple.

        Exceptions:
            This method catches local failures and returns friendly responses.
        """
        timer_match = re.search(r"set a timer for\s+(\d+)\s+(minute|minutes|second|seconds)", lowered_command)
        if timer_match:
            amount = int(timer_match.group(1))
            unit = timer_match.group(2)
            seconds = amount * 60 if "minute" in unit else amount
            trigger_at = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
            timer_message = f"Sir, your {format_duration(seconds)} timer is complete."
            reminder_id = self.db_manager.save_reminder(timer_message, trigger_at)
            self.schedule_timer_alert(seconds, reminder_id, timer_message)
            return True, f"Timer set for {format_duration(seconds)}, sir.", False

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

        return False, "", False

    def handle_app_launch_commands(self, cleaned_command: str, lowered_command: str) -> Tuple[bool, str, bool]:
        """
        Handle browser launches, Google searches, and app launches.

        Parameters:
            cleaned_command (str): Original command text.
            lowered_command (str): Lowercased command text.

        Returns:
            Tuple[bool, str, bool]: Standard skill result tuple.

        Exceptions:
            This method catches launch failures and returns friendly responses.
        """
        if any(pattern in lowered_command for pattern in ["open browser", "open chrome", "open safari", "launch browser"]):
            try:
                webbrowser.open("https://www.google.com")
                return True, "Opening your browser, sir.", False
            except Exception as error:
                self.logger.error("Browser launch failed: %s", error)
                return True, "I could not open the browser, sir.", False

        if lowered_command.startswith("search for ") or lowered_command.startswith("google "):
            query = cleaned_command[11:].strip() if lowered_command.startswith("search for ") else cleaned_command[7:].strip()
            if not query:
                return True, "Tell me what you would like to search for, sir.", False
            try:
                webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
                return True, f"Searching Google for {query}, sir.", False
            except Exception as error:
                self.logger.error("Google search failed: %s", error)
                return True, "I could not open the search, sir.", False

        app_match = re.match(r"^(open|launch)\s+(.+)$", lowered_command)
        if app_match and all(keyword not in lowered_command for keyword in ["browser", "chrome", "safari"]):
            app_name = cleaned_command.split(maxsplit=1)[1].strip()
            if self.open_app(app_name):
                return True, f"Opening {app_name}, sir.", False
            return True, f"I could not open {app_name}, sir.", False

        return False, "", False

    def handle_fun_commands(self, cleaned_command: str, lowered_command: str) -> Tuple[bool, str, bool]:
        """
        Handle jokes, coin flips, dice rolls, motivation, and version checks.

        Parameters:
            cleaned_command (str): Original command text.
            lowered_command (str): Lowercased command text.

        Returns:
            Tuple[bool, str, bool]: Standard skill result tuple.

        Exceptions:
            This method does not raise exceptions.
        """
        if lowered_command == "tell me a joke":
            return True, random.choice(self.jokes), False

        if lowered_command == "flip a coin":
            return True, f"It is {random.choice(['heads', 'tails'])}, sir.", False

        if lowered_command == "roll a dice":
            return True, f"You rolled a {random.randint(1, 6)}, sir.", False

        if lowered_command == "motivate me":
            return True, random.choice(self.motivational_quotes), False

        if lowered_command == "what version are you":
            return True, f"I am JARVIS version {JARVIS_VERSION}, build date {JARVIS_BUILD_DATE}.", False

        return False, "", False

    def handle_builtin_skill(self, command: str) -> Tuple[bool, str, bool]:
        """
        Route local skills by ordered handler groups before falling back to AI.

        Parameters:
            command (str): The recognized user command.

        Returns:
            Tuple[bool, str, bool]: Handled flag, response text, and shutdown flag.

        Exceptions:
            This method catches local skill failures and returns a safe response.
        """
        cleaned_command = command.strip()
        lowered_command = cleaned_command.lower()

        for patterns, handler in self.skill_routes:
            if any(pattern in lowered_command for pattern in patterns):
                try:
                    handled, response_text, should_shutdown = handler(cleaned_command, lowered_command)
                    if handled:
                        return handled, response_text, should_shutdown
                except Exception as error:
                    self.logger.error("Local skill failed in %s: %s", handler.__name__, error)
                    self.logger.error(traceback.format_exc())
                    return True, "I encountered a local skill error, sir.", False

        return False, "", False

    def route_command(self, command: str) -> None:
        """
        Route one recognized command through ordered local skills or the AI stack.

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

            # ── UPGRADED ── route by the requested local-skill priority before AI fallback ──
            handled, response_text, should_shutdown = self.handle_builtin_skill(command)
            if handled:
                if should_shutdown:
                    self.request_shutdown("voice shutdown command")
                    return
                self.queue_response(response_text)
                return

            # ── call the AI router when no local skill matches the request ──
            reply_text, provider_used = self.ai_router.ask(command)

            # ── handle the case where both AI providers fail ──
            if reply_text is None:
                offline_message = "Both AI systems are offline sir. Running on local skills only."
                self.queue_response(offline_message)
                return

            # ── persist the AI reply and queue it for speech ──
            self.queue_response(reply_text, provider_used)
        except Exception as error:
            # ── catch all command-routing failures so the assistant never crashes ──
            self.logger.error("Command routing failed: %s", error)
            self.logger.error(traceback.format_exc())
            self.animator.set_state("error", "Internal error")
            self.queue_response("I encountered an internal error, sir.")

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
