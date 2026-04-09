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

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

try:
    from pynput import keyboard, mouse
except ImportError:
    keyboard = None
    mouse = None

try:
    import spacy
except ImportError:
    spacy = None

try:
    from dateutil import parser as dateutil_parser
except ImportError:
    dateutil_parser = None

try:
    from functools import lru_cache
except ImportError:
    lru_cache = None


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
    render_health_url: str
    proactive_mode: bool
    git_check_interval_hours: int
    hotkey_enabled: bool
    hotkey_combo: str
    corner_trigger_enabled: bool
    corner_trigger_corner: str
    corner_trigger_delay_ms: int
    local_llm_enabled: bool
    local_llm_model: str
    local_llm_timeout: int
    ollama_base_url: str
    offline_fallback_to_local: bool
    ai_priority: str
    system_prompt_refresh_minutes: int


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
        render_health_url=os.getenv("RENDER_HEALTH_URL", "").strip(),
        proactive_mode=os.getenv("PROACTIVE_MODE", "true").strip().lower() == "true",
        git_check_interval_hours=parse_int_env("GIT_CHECK_INTERVAL_HOURS", 2),
        hotkey_enabled=os.getenv("HOTKEY_ENABLED", "true").strip().lower() == "true",
        hotkey_combo=os.getenv("HOTKEY_COMBO", "cmd+shift+space").strip().lower(),
        corner_trigger_enabled=os.getenv("CORNER_TRIGGER_ENABLED", "true").strip().lower() == "true",
        corner_trigger_corner=os.getenv("CORNER_TRIGGER_CORNER", "top-right").strip().lower(),
        corner_trigger_delay_ms=parse_int_env("CORNER_TRIGGER_DELAY_MS", 1200),
        local_llm_enabled=os.getenv("LOCAL_LLM_ENABLED", "true").strip().lower() == "true",
        local_llm_model=os.getenv("LOCAL_LLM_MODEL", "phi3:mini").strip(),
        local_llm_timeout=parse_int_env("LOCAL_LLM_TIMEOUT", 30),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip(),
        offline_fallback_to_local=os.getenv("OFFLINE_FALLBACK_TO_LOCAL", "true").strip().lower() == "true",
        ai_priority=os.getenv("AI_PRIORITY", "gemini,groq,ollama").strip().lower(),
        system_prompt_refresh_minutes=parse_int_env("SYSTEM_PROMPT_REFRESH_MINUTES", 30),
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

# ── Phase 2: Embedding engine singleton for semantic memory ──
_embedding_engine_instance = None


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

                # ── create the project registry table ──
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS project_registry (
                        id SERIAL PRIMARY KEY,
                        friendly_name VARCHAR(200) UNIQUE NOT NULL,
                        aliases TEXT[],
                        full_path TEXT NOT NULL,
                        project_type VARCHAR(50),
                        launch_command TEXT,
                        browser_url TEXT,
                        last_opened TIMESTAMP,
                        open_count INT DEFAULT 0,
                        editor VARCHAR(50) DEFAULT 'vscode',
                        git_enabled BOOLEAN DEFAULT false,
                        notes TEXT,
                        name_embedding vector(384),
                        combined_embedding vector(384),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )

                # ── create indexes for project registry ──
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_project_friendly ON project_registry(friendly_name);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_project_last_opened ON project_registry(last_opened DESC);")

                # ── create the file access log table ──
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS file_access_log (
                        id SERIAL PRIMARY KEY,
                        file_path TEXT UNIQUE NOT NULL,
                        file_name VARCHAR(255) NOT NULL,
                        open_count INT DEFAULT 1,
                        last_opened TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )

                # ── create indexes for file access log ──
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_access_path ON file_access_log(file_path);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_access_count ON file_access_log(open_count DESC);")

                # ── PHASE 2: Enable pgvector extension if available ──
                try:
                    cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                except Exception:
                    pass  # pgvector extension not installed, continue without it

                # ── PHASE 2: Upgrade memory table with embeddings ──
                cursor.execute("""
                    ALTER TABLE memory ADD COLUMN IF NOT EXISTS embedding vector(384);
                    ALTER TABLE memory ADD COLUMN IF NOT EXISTS importance_score FLOAT DEFAULT 0.5;
                    ALTER TABLE memory ADD COLUMN IF NOT EXISTS access_count INT DEFAULT 0;
                    ALTER TABLE memory ADD COLUMN IF NOT EXISTS last_accessed TIMESTAMP;
                """)

                # ── PHASE 2: Create conversation embeddings table ──
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS conversation_embeddings (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT,
                        turn_index INT,
                        role VARCHAR(20),
                        content TEXT,
                        embedding vector(384),
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        topics TEXT[]
                    );
                """)

                # ── PHASE 2: Create session summaries table ──
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS session_summaries (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT UNIQUE,
                        summary TEXT,
                        topics TEXT[],
                        embedding vector(384),
                        message_count INT,
                        started_at TIMESTAMP,
                        ended_at TIMESTAMP
                    );
                """)

                # ── PHASE 2: Create user profile table ──
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_profile (
                        key VARCHAR(100) PRIMARY KEY,
                        value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)

                # ── PHASE 2: Create vector search indexes ──
                try:
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_memory_embedding 
                        ON memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);
                    """)
                except Exception:
                    pass  # pgvector indexes not supported, continue

                try:
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_conv_embedding 
                        ON conversation_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
                    """)
                except Exception:
                    pass

                try:
                    cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_session_time 
                        ON session_summaries (ended_at DESC);
                    """)
                except Exception:
                    pass

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
# ██  EMBEDDING ENGINE — SEMANTIC MEMORY & SEARCH
# ══════════════════════════════════════════════════════════


class EmbeddingEngine:
    """
    Singleton embedding engine using sentence-transformers for semantic memory.

    Parameters:
        model_name (str): SentenceTransformer model name (default: all-MiniLM-L6-v2).

    Returns:
        None.

    Exceptions:
        Catches ImportError if sentence-transformers not installed.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Ensure singleton pattern with thread safety."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """Initialize embedding engine with lazy-loading."""
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self.model_name = model_name
        self.model = None
        self.embedding_cache = {}
        self.cache_lock = threading.Lock()
        self._load_model()

    def _load_model(self):
        """Lazy-load the sentence-transformer model on first use."""
        try:
            from sentence_transformers import SentenceTransformer
            LOGGER.info(f"Loading embedding model: {self.model_name}")
            self.model = SentenceTransformer(self.model_name)
            LOGGER.info(f"Embedding model loaded successfully ({self.model.get_sentence_embedding_dimension()} dims)")
        except ImportError:
            LOGGER.error("sentence-transformers not installed; semantic search unavailable")
            self.model = None

    def embed(self, text: str) -> list:
        """
        Embed a single text string into a 384-dimensional vector.

        Parameters:
            text (str): Text to embed.

        Returns:
            list: 384-dimensional embedding vector.
        """
        if self.model is None:
            return [0.0] * 384

        # ── check cache first to avoid re-computing identical queries ──
        text_key = text.lower().strip()
        if text_key in self.embedding_cache:
            return self.embedding_cache[text_key]

        # ── compute embedding with LRU cache eviction ──
        with self.cache_lock:
            if text_key in self.embedding_cache:
                return self.embedding_cache[text_key]

            embedding = self.model.encode(text, convert_to_tensor=False).tolist()

            # ── simple LRU: keep only last 500 embeddings to save memory ──
            if len(self.embedding_cache) >= 500:
                oldest_key = next(iter(self.embedding_cache))
                del self.embedding_cache[oldest_key]

            self.embedding_cache[text_key] = embedding
            return embedding

    def embed_batch(self, texts: list) -> list:
        """
        Embed multiple texts efficiently.

        Parameters:
            texts (list): List of text strings.

        Returns:
            list: List of embedding vectors.
        """
        if self.model is None:
            return [[0.0] * 384] * len(texts)

        embeddings = []
        for text in texts:
            embeddings.append(self.embed(text))
        return embeddings

    def similarity(self, vec1: list, vec2: list) -> float:
        """
        Calculate cosine similarity between two vectors.

        Parameters:
            vec1 (list): First embedding vector.
            vec2 (list): Second embedding vector.

        Returns:
            float: Cosine similarity score (0-1).
        """
        try:
            from sklearn.metrics.pairwise import cosine_similarity
            import numpy as np
            sim = cosine_similarity([vec1], [vec2])[0][0]
            return float(sim)
        except Exception as error:
            LOGGER.warning(f"Similarity calculation failed: {error}")
            return 0.0


# ══════════════════════════════════════════════════════════
# ██  OLLAMA PROVIDER — LOCAL LLM FALLBACK
# ══════════════════════════════════════════════════════════


class OllamaProvider:
    """
    Interface to local Ollama LLM running on localhost:11434.

    Parameters:
        config (AppConfig): Validated runtime configuration.
        logger (logging.Logger): Logger for provider events.

    Returns:
        None.

    Exceptions:
        Methods catch HTTP errors and connectivity issues gracefully.
    """

    def __init__(self, config: AppConfig = None, logger: logging.Logger = None):
        """Initialize Ollama provider with configuration."""
        self.config = config
        self.logger = logger or LOGGER
        self.available = False
        self.base_url = "http://localhost:11434"
        self.timeout = 30  # CPU inference is slower than cloud
        self.history = []
        self.model_name = "phi3:mini"  # Default model optimized for 8GB RAM
        self.history_limit = 6  # Keep token count under 4096

        # Extract model name from config if provided
        if config and hasattr(config, "local_llm_model"):
            self.model_name = config.local_llm_model
        if config and hasattr(config, "local_llm_timeout"):
            self.timeout = config.local_llm_timeout

        # Attempt initial availability check
        self.check_availability()

    def check_availability(self) -> bool:
        """
        Check if Ollama is running and responsive.

        Returns:
            bool: True if Ollama is available, False otherwise.
        """
        try:
            if requests is None:
                self.logger.warning("requests library not available; Ollama disabled")
                self.available = False
                return False

            response = requests.get(f"{self.base_url}/api/tags", timeout=2)
            if response.status_code == 200:
                self.available = True
                self.logger.debug("Ollama provider is available")
                return True
            self.available = False
            return False
        except Exception as error:
            self.available = False
            self.logger.debug(f"Ollama not available: {error}")
            return False

    def initialize(self) -> bool:
        """
        Initialize Ollama provider at startup.

        Returns:
            bool: True if initialization successful.
        """
        if not requests:
            self.logger.warning("requests library required for Ollama integration")
            return False
        return self.check_availability()

    def send_message(self, user_text: str) -> Tuple[Optional[str], Optional[int]]:
        """
        Send a message to Ollama and retrieve response.

        Parameters:
            user_text (str): User input text.

        Returns:
            Tuple[Optional[str], Optional[int]]: (response_text, token_count) or (None, None) on failure.

        Exceptions:
            Catches HTTP errors, timeouts, and JSON parsing errors.
        """
        if not self.available:
            return None, None

        try:
            # Append user message to history
            self.history.append({"role": "user", "content": user_text})

            # Trim history to keep context within token limit
            self._trim_history()

            # Build request payload
            payload = {
                "model": self.model_name,
                "messages": self.history,
                "stream": False,  # Required for voice compatibility (no chunked responses)
                "temperature": 0.7,
                "top_p": 0.9,
            }

            # POST to Ollama chat endpoint
            response = requests.post(
                f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
            )

            if response.status_code != 200:
                self.logger.warning(f"Ollama returned {response.status_code}")
                return None, None

            # Parse response
            data = response.json()
            reply_text = data.get("message", {}).get("content", "").strip()
            if not reply_text:
                self.logger.warning("Ollama returned empty response")
                return None, None

            # Append assistant response to history
            self.history.append({"role": "assistant", "content": reply_text})
            self._trim_history()

            # Estimate token count (rough: 1 token ~= 4 chars)
            token_count = len(self.history[-2].get("content", "")) // 4 + len(reply_text) // 4

            self.logger.debug(f"Ollama response: {len(reply_text)} chars, ~{token_count} tokens")
            return reply_text, token_count

        except requests.Timeout:
            self.logger.warning(f"Ollama request timed out after {self.timeout}s")
            return None, None
        except requests.ConnectionError:
            self.logger.warning("Ollama connection failed")
            self.available = False
            return None, None
        except Exception as error:
            self.logger.warning(f"Ollama error: {error}")
            return None, None

    def _trim_history(self):
        """Trim conversation history to stay within token budget."""
        # Keep only last N messages to avoid exceeding 4096 token limit
        if len(self.history) > self.history_limit:
            self.history = self.history[-self.history_limit :]

    def reset_history(self):
        """Clear conversation history for new session."""
        self.history = []


# ══════════════════════════════════════════════════════════
# ██  SYSTEM PROMPT BUILDER — DYNAMIC PERSONALITY
# ══════════════════════════════════════════════════════════


class SystemPromptBuilder:
    """
    Build dynamic system prompts for Ollama with personalized context.

    Parameters:
        db_manager (DatabaseManager): Database manager for fetching user context.
        logger (logging.Logger): Logger for builder events.

    Returns:
        None.

    Exceptions:
        Methods catch database errors and return fallback prompts.
    """

    def __init__(self, db_manager=None, logger: logging.Logger = None):
        """Initialize system prompt builder."""
        self.db_manager = db_manager
        self.logger = logger or LOGGER
        self.last_built = None
        self.rebuild_interval = 1800  # Rebuild every 30 minutes

    def should_rebuild(self) -> bool:
        """Check if system prompt needs rebuilding."""
        if self.last_built is None:
            return True
        return time.time() - self.last_built > self.rebuild_interval

    def build_dynamic_system_prompt(self) -> str:
        """
        Build a 5-block personalized system prompt for Ollama.

        Returns:
            str: Complete system prompt (~500-800 tokens).
        """
        try:
            blocks = []

            # ── Block 1: Static JARVIS identity ──
            blocks.append(self._build_identity_block())

            # ── Block 2: User profile ──
            if self.db_manager:
                user_profile_text = self._fetch_user_profile()
                if user_profile_text:
                    blocks.append(user_profile_text)

            # ── Block 3: Active projects ──
            if self.db_manager:
                projects_text = self._fetch_active_projects()
                if projects_text:
                    blocks.append(projects_text)

            # ── Block 4: Key memories ──
            if self.db_manager:
                memories_text = self._fetch_key_memories()
                if memories_text:
                    blocks.append(memories_text)

            # ── Block 5: Time-of-day context ──
            blocks.append(self._build_time_context_block())

            self.last_built = time.time()
            prompt = "\n\n".join(blocks)
            self.logger.debug(f"Built dynamic system prompt ({len(prompt)} chars)")
            return prompt

        except Exception as error:
            self.logger.warning(f"Error building system prompt: {error}")
            return self._build_fallback_prompt()

    def _build_identity_block(self) -> str:
        """Build the static JARVIS identity block."""
        return (
            "You are JARVIS, a highly intelligent, concise, and witty AI assistant.\n"
            "You are running on a Mac. Keep responses under 3 sentences unless asked for detail.\n"
            "You maintain exceptional wit while being helpful and professional. Never break character."
        )

    def _build_time_context_block(self) -> str:
        """Build time-of-day context for suggestions."""
        hour = datetime.datetime.now().hour
        if 5 <= hour < 12:
            period = "morning"
        elif 12 <= hour < 17:
            period = "afternoon"
        elif 17 <= hour < 21:
            period = "evening"
        else:
            period = "night"

        return f"It is currently {period}. Tailor suggestions to this time of day."

    def _fetch_user_profile(self) -> str:
        """Fetch user profile from database."""
        try:
            connection = self.db_manager._get_connection()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT key, value FROM user_profile WHERE key IN ('name', 'preferences', 'style') ORDER BY key"
                    )
                    rows = cursor.fetchall()
                    if rows:
                        profile_items = [f"{row[0]}: {row[1]}" for row in rows]
                        return f"User Profile:\n- " + "\n- ".join(profile_items)
                    return ""
            finally:
                self.db_manager._put_connection(connection)
        except Exception as error:
            self.logger.debug(f"Could not fetch user profile: {error}")
            return ""

    def _fetch_active_projects(self) -> str:
        """Fetch top 5 recent projects from registry."""
        try:
            connection = self.db_manager._get_connection()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT name, description FROM project_registry
                        ORDER BY last_accessed DESC
                        LIMIT 5
                        """
                    )
                    rows = cursor.fetchall()
                    if rows:
                        projects = [f"- {row[0]}: {row[1][:60]}..." if len(row[1]) > 60 else f"- {row[0]}: {row[1]}" for row in rows]
                        return f"Current Projects:\n" + "\n".join(projects)
                    return ""
            finally:
                self.db_manager._put_connection(connection)
        except Exception as error:
            self.logger.debug(f"Could not fetch projects: {error}")
            return ""

    def _fetch_key_memories(self) -> str:
        """Fetch top 10 important memories."""
        try:
            connection = self.db_manager._get_connection()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT key, value FROM memory
                        ORDER BY importance_score DESC, access_count DESC
                        LIMIT 10
                        """
                    )
                    rows = cursor.fetchall()
                    if rows:
                        memories = [f"- {row[0]}: {row[1][:50]}..." if len(row[1]) > 50 else f"- {row[0]}: {row[1]}" for row in rows]
                        return f"Key Memories:\n" + "\n".join(memories)
                    return ""
            finally:
                self.db_manager._put_connection(connection)
        except Exception as error:
            self.logger.debug(f"Could not fetch memories: {error}")
            return ""

    def _build_fallback_prompt(self) -> str:
        """Return fallback prompt when dynamic building fails."""
# ── Global cache for online/offline detection (60-second TTL) ──
_online_status_cache = {"status": None, "timestamp": 0}
_online_status_lock = threading.Lock()


def is_online() -> bool:
    """
    Detect internet connectivity by attempting connection to 8.8.8.8:53.

    Returns:
        bool: True if online, False if offline (cached for 60 seconds).
    """
    global _online_status_cache
    current_time = time.time()

    # Check if cache is still valid (< 60 seconds)
    with _online_status_lock:
        if _online_status_cache["status"] is not None and current_time - _online_status_cache["timestamp"] < 60:
            return _online_status_cache["status"]

        # Cache expired or not set; perform connectivity check
        try:
            # Try to connect to Google's DNS server
            socket.create_connection(("8.8.8.8", 53), timeout=1)
            status = True
            LOGGER.debug("Internet connectivity detected")
        except (socket.timeout, socket.error):
            status = False
            LOGGER.debug("No internet connectivity detected")

        # Update cache
        _online_status_cache["status"] = status
        _online_status_cache["timestamp"] = current_time
        return status


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
        self.ollama = None
        self.system_prompt = ""
        self.last_system_prompt_update = 0
        self.manual_override: Optional[str] = None
        self.active_provider = config.primary_ai
        self.animator.set_provider(self.active_provider)
        self._online_state_announced = False

    def initialize_providers(self) -> Dict[str, bool]:
        """
        Initialize all AI providers and return readiness flags.

        Parameters:
            None.

        Returns:
            Dict[str, bool]: Readiness flags keyed by provider name.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── initialize both cloud providers independently so one can survive without the other ──
        gemini_ready = self.gemini.initialize()
        groq_ready = self.groq.initialize()

        # ── initialize Ollama local provider if enabled ──
        ollama_ready = False
        if self.config.local_llm_enabled:
            try:
                self.ollama = OllamaProvider(self.config, self.logger)
                ollama_ready = self.ollama.check_availability()
                if ollama_ready:
                    self.logger.info(f"Ollama provider ready: {self.ollama.model_name}")
                else:
                    self.logger.warning(f"Ollama not available at {self.ollama.base_url}")
            except Exception as e:
                self.logger.error(f"Failed to initialize Ollama: {e}")

        return {"gemini": gemini_ready, "groq": groq_ready, "ollama": ollama_ready}

    def provider_display_name(self, provider: str) -> str:
        """
        Convert an internal provider ID to a friendly display name.

        Parameters:
            provider (str): Provider key such as `gemini`, `groq`, or `ollama`.

        Returns:
            str: Human-readable provider label.

        Exceptions:
            This method does not raise exceptions.
        """
        # ── map short provider keys to terminal-friendly names ──
        return {"gemini": "Gemini", "groq": "Groq", "ollama": "Ollama"}.get(provider, provider.title())

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
        if provider == "ollama":
            return self.ollama is not None and self.ollama.available
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
        if normalized_provider not in {"gemini", "groq", "ollama"}:
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
        Ask the active AI stack for a response with 4-tier fallback and offline support.

        Parameters:
            user_text (str): The user's request text.

        Returns:
            Tuple[Optional[str], Optional[str]]: The reply text and successful provider, or (None, None).

        Exceptions:
            This method catches provider failures and returns clean fallback results.
        """
        # ── check online/offline status ──
        online = is_online()
        if not online and not self._online_state_announced:
            self.logger.info("Detected offline - using local LLM and skills")
            self._online_state_announced = True
        elif online and self._online_state_announced:
            self.logger.info("Detected online - resuming normal provider rotation")
            self._online_state_announced = False

        # ── build provider order based on online status and AI_PRIORITY config ──
        if self.manual_override:
            provider_order = [self.manual_override]
        else:
            # Parse AI_PRIORITY from config
            provider_order = [p.strip() for p in self.config.ai_priority.split(",")]

            # If offline, prioritize local Ollama
            if not online and "ollama" in provider_order:
                # Move ollama to front if offline
                provider_order = ["ollama"] + [p for p in provider_order if p != "ollama"]

        # ── try each provider in order ──
        for provider_name in provider_order:
            provider = None
            if provider_name == "gemini":
                provider = self.gemini
            elif provider_name == "groq":
                provider = self.groq
            elif provider_name == "ollama":
                provider = self.ollama
            else:
                continue

            if provider is None:
                continue

            # ── check availability ──
            if not self.is_provider_available(provider_name):
                continue

            # ── show the current provider in the thinking animation ──
            self.animator.set_provider(provider_name)
            self.animator.set_state("thinking", "Thinking...")

            # ── record timing ──
            start_time = time.perf_counter()
            try:
                # ── different APIs for different providers ──
                if provider_name == "ollama":
                    # For Ollama, just pass the user text directly
                    reply_text, token_count = provider.send_message(user_text)
                    if not reply_text:
                        raise Exception("Ollama returned empty response")
                else:
                    # Gemini and Groq
                    reply_text, token_count = provider.send_message(user_text)

                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                self.db_manager.log_ai_usage(provider_name, True, elapsed_ms, token_count)

                # ── log a switch event when provider changes ──
                if self.active_provider != provider_name:
                    self._log_switch(self.active_provider, provider_name, "automatic fallback success")

                # ── update the active provider ──
                self.active_provider = provider_name
                self.animator.set_provider(provider_name)
                return reply_text, provider_name

            except Exception as error:
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                self.db_manager.log_ai_usage(provider_name, False, elapsed_ms, None)
                self.logger.error(f"AI request failed for {provider_name}: {error}")
                continue

        # ── all providers failed or unavailable ──
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


def semantic_search_memory(db_manager, query: str, top_k: int = 5, threshold: float = 0.65) -> list:
    """
    Search memories using semantic similarity with embeddings.

    Parameters:
        db_manager: Database manager instance.
        query (str): Query text to search for.
        top_k (int): Number of results to return.
        threshold (float): Minimum similarity score (0-1).

    Returns:
        list: List of matching memory records with similarity scores.
    """
    try:
        engine = get_embedding_engine()
        query_embedding = engine.embed(query)

        connection = db_manager._get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT key, value, category, importance_score,
                           1 - (embedding <=> %s::vector) as similarity
                    FROM memory
                    WHERE embedding IS NOT NULL
                    ORDER BY similarity DESC
                    LIMIT %s
                    """,
                    (f"[{','.join(map(str, query_embedding))}]", top_k),
                )
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    score = row[4] if row[4] else 0
                    if score >= threshold:
                        results.append(
                            {
                                "key": row[0],
                                "value": row[1],
                                "category": row[2],
                                "importance": row[3],
                                "similarity": score,
                            }
                        )
                return results
        finally:
            db_manager._put_connection(connection)
    except Exception as error:
        LOGGER.warning(f"Semantic search failed: {error}")
        return []


def recall_conversation_context(db_manager, query: str, top_k: int = 1) -> str:
    """
    Recall conversation context by semantic similarity.

    Parameters:
        db_manager: Database manager instance.
        query (str): Query text to search for.
        top_k (int): Number of results to return.

    Returns:
        str: Formatted conversation context.
    """
    try:
        engine = get_embedding_engine()
        query_embedding = engine.embed(query)

        connection = db_manager._get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT content, role, 1 - (embedding <=> %s::vector) as similarity
                    FROM conversation_embeddings
                    WHERE embedding IS NOT NULL
                    ORDER BY similarity DESC
                    LIMIT %s
                    """,
                    (f"[{','.join(map(str, query_embedding))}]", top_k),
                )
                row = cursor.fetchone()
                if row and row[2] > 0.65:
                    role = "You said" if row[1] == "user" else "I said"
                    return f"{role}: {row[0][:100]}"
                return ""
        finally:
            db_manager._put_connection(connection)
    except Exception as error:
        LOGGER.warning(f"Conversation context recall failed: {error}")
        return ""


def recall_session_by_date(db_manager, date_str: str) -> str:
    """
    Recall session summary by relative date.

    Parameters:
        db_manager: Database manager instance.
        date_str (str): Date reference like 'yesterday', 'last week', etc.

    Returns:
        str: Session summary or empty string if not found.
    """
    try:
        connection = db_manager._get_connection()
        try:
            with connection.cursor() as cursor:
                interval_sql = "1 day"
                if "week" in date_str:
                    interval_sql = "7 days"
                elif "month" in date_str:
                    interval_sql = "30 days"

                cursor.execute(
                    f"""
                    SELECT summary FROM session_summaries
                    WHERE ended_at > CURRENT_TIMESTAMP - INTERVAL '{interval_sql}'
                    ORDER BY ended_at DESC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
                return row[0] if row else ""
        finally:
            db_manager._put_connection(connection)
    except Exception as error:
        LOGGER.warning(f"Session recall failed: {error}")
        return ""


def format_memory_sentence(memory) -> str:
    """
    Format memory dictionary or string into a readable sentence.

    Parameters:
        memory: Memory record (dict or string).

    Returns:
        str: Formatted sentence.
    """
    if isinstance(memory, dict):
        value = memory.get("value", memory.get("content", ""))
    else:
        value = memory
    return value if isinstance(value, str) else str(value)


def get_embedding_engine():
    """
    Get the singleton EmbeddingEngine instance, creating if necessary.

    Returns:
        EmbeddingEngine: Singleton instance for embeddings.
    """
    global _embedding_engine_instance
    if _embedding_engine_instance is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedding_engine_instance = EmbeddingEngine()
        except ImportError:
            LOGGER.error("sentence-transformers not installed; embeddings unavailable")
    return _embedding_engine_instance


def calculate_importance(key: str, value: str, category: str) -> float:
    """
    Calculate importance score for a memory.

    Parameters:
        key (str): Memory key.
        value (str): Memory value.
        category (str): Memory category.

    Returns:
        float: Importance score 0.0-1.0.
    """
    score = 0.0
    if category in ["personal", "preference", "important"]:
        score += 0.3
    if len(value) > 50:
        score += 0.2
    if any(word in value.lower() for word in ["critical", "important", "remember", "never", "always"]):
        score += 0.3
    if key in ["name", "birthday", "email", "phone"]:
        score += 0.2
    return min(score, 1.0)


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
# ██  PROJECT REGISTRY SYSTEM
# ══════════════════════════════════════════════════════════

# Global model for semantic similarity (lazy-loaded)
_embedding_model = None

def get_embedding_model():
    """Lazy-load the sentence transformer model for semantic matching."""
    global _embedding_model
    if _embedding_model is None and SentenceTransformer is not None:
        try:
            _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        except Exception as e:
            logging.warning(f"Failed to load embedding model: {e}")
            _embedding_model = None
    return _embedding_model

def compute_embedding(text: str) -> list[float]:
    """Compute semantic embedding for text using sentence-transformers."""
    model = get_embedding_model()
    if model is None:
        return []
    try:
        return model.encode(text).tolist()
    except Exception as e:
        logging.error(f"Error computing embedding: {e}")
        return []

def register_project(db_manager, friendly_name: str, path: str, project_type: str = "other",
                    aliases: list[str] = None, launch_cmd: str = None, browser_url: str = None,
                    editor: str = "vscode", git_enabled: bool = False, notes: str = "") -> bool:
    """
    Register a project in the project registry.

    Args:
        db_manager: DatabaseManager instance
        friendly_name: User-friendly project name
        path: Absolute path to project directory
        project_type: Type of project (flask, react, python, node, other)
        aliases: List of alternative names
        launch_cmd: Command to launch dev server
        browser_url: URL to open after launch
        editor: Preferred editor (vscode, xcode, pycharm)
        git_enabled: Whether to monitor git status
        notes: Additional notes

    Returns:
        bool: True if registered successfully
    """
    if aliases is None:
        aliases = []

    # Compute embeddings for semantic search
    name_embedding = compute_embedding(friendly_name)
    alias_text = " ".join(aliases) if aliases else ""
    combined_text = f"{friendly_name} {alias_text}".strip()
    combined_embedding = compute_embedding(combined_text) if combined_text else []

    connection = db_manager._get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO project_registry (
                    friendly_name, aliases, full_path, project_type, launch_command,
                    browser_url, editor, git_enabled, notes, name_embedding, combined_embedding
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (friendly_name) DO UPDATE SET
                    aliases = EXCLUDED.aliases,
                    full_path = EXCLUDED.full_path,
                    project_type = EXCLUDED.project_type,
                    launch_command = EXCLUDED.launch_command,
                    browser_url = EXCLUDED.browser_url,
                    editor = EXCLUDED.editor,
                    git_enabled = EXCLUDED.git_enabled,
                    notes = EXCLUDED.notes,
                    name_embedding = EXCLUDED.name_embedding,
                    combined_embedding = EXCLUDED.combined_embedding,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                friendly_name, aliases, path, project_type, launch_cmd,
                browser_url, editor, git_enabled, notes,
                name_embedding, combined_embedding
            ))
        connection.commit()
        return True
    except Exception as e:
        logging.error(f"Error registering project: {e}")
        return False
    finally:
        db_manager._put_connection(connection)

def find_project(db_manager, query: str) -> dict | None:
    """
    Find the best matching project using three-layer matching.

    Args:
        db_manager: DatabaseManager instance
        query: Search query

    Returns:
        dict: Project data or None
    """
    query_lower = query.lower().strip()
    query_embedding = compute_embedding(query)

    connection = db_manager._get_connection()
    try:
        with connection.cursor() as cursor:
            # Layer 1: Exact friendly_name match
            cursor.execute("""
                SELECT friendly_name, aliases, full_path, project_type, launch_command,
                       browser_url, last_opened, open_count, editor, git_enabled, notes
                FROM project_registry
                WHERE LOWER(friendly_name) = %s
                ORDER BY last_opened DESC NULLS LAST
                LIMIT 1
            """, (query_lower,))
            result = cursor.fetchone()
            if result:
                return dict(zip([
                    'friendly_name', 'aliases', 'full_path', 'project_type', 'launch_command',
                    'browser_url', 'last_opened', 'open_count', 'editor', 'git_enabled', 'notes'
                ], result))

            # Layer 2: Alias substring match
            cursor.execute("""
                SELECT friendly_name, aliases, full_path, project_type, launch_command,
                       browser_url, last_opened, open_count, editor, git_enabled, notes
                FROM project_registry
                WHERE EXISTS (
                    SELECT 1 FROM unnest(aliases) AS alias
                    WHERE LOWER(alias) LIKE %s
                )
                ORDER BY last_opened DESC NULLS LAST
                LIMIT 1
            """, (f'%{query_lower}%',))
            result = cursor.fetchone()
            if result:
                return dict(zip([
                    'friendly_name', 'aliases', 'full_path', 'project_type', 'launch_command',
                    'browser_url', 'last_opened', 'open_count', 'editor', 'git_enabled', 'notes'
                ], result))

            # Layer 3: Semantic similarity
            if query_embedding:
                cursor.execute("""
                    SELECT friendly_name, aliases, full_path, project_type, launch_command,
                           browser_url, last_opened, open_count, editor, git_enabled, notes,
                           1 - (name_embedding <=> %s::vector) as name_sim,
                           1 - (combined_embedding <=> %s::vector) as combined_sim
                    FROM project_registry
                    WHERE name_embedding IS NOT NULL OR combined_embedding IS NOT NULL
                    ORDER BY GREATEST(
                        COALESCE(1 - (name_embedding <=> %s::vector), 0),
                        COALESCE(1 - (combined_embedding <=> %s::vector), 0)
                    ) DESC
                    LIMIT 5
                """, (query_embedding, query_embedding, query_embedding, query_embedding))

                results = cursor.fetchall()
                if results:
                    # Apply recency boost
                    now = datetime.datetime.now()
                    scored_results = []
                    for row in results:
                        data = dict(zip([
                            'friendly_name', 'aliases', 'full_path', 'project_type', 'launch_command',
                            'browser_url', 'last_opened', 'open_count', 'editor', 'git_enabled', 'notes',
                            'name_sim', 'combined_sim'
                        ], row))
                        similarity = max(data['name_sim'] or 0, data['combined_sim'] or 0)
                        recency_score = 0
                        if data['last_opened']:
                            days_since = (now - data['last_opened']).days
                            recency_score = max(0, 1 - days_since / 30)  # Decay over 30 days
                        total_score = similarity * 0.7 + recency_score * 0.3
                        data['score'] = total_score
                        scored_results.append(data)

                    scored_results.sort(key=lambda x: x['score'], reverse=True)
                    return scored_results[0] if scored_results else None

    except Exception as e:
        logging.error(f"Error finding project: {e}")
    finally:
        db_manager._put_connection(connection)

    return None

def open_project(db_manager, project: dict, jarvis_app) -> str:
    """
    Open a project in Finder and editor.

    Args:
        db_manager: DatabaseManager instance
        project: Project dict from find_project
        jarvis_app: JarvisApp instance for speaking

    Returns:
        str: Response message
    """
    path = project['full_path']
    if not os.path.exists(path):
        return f"Project path {path} no longer exists, sir."

    try:
        # Open in Finder
        subprocess.run(["open", path], check=True)

        # Open in editor
        editor = project.get('editor', 'vscode')
        if editor == 'vscode':
            subprocess.run(["code", path], check=False)  # Don't fail if code not found
        elif editor == 'xcode':
            subprocess.run(["open", "-a", "Xcode", path], check=False)
        elif editor == 'pycharm':
            subprocess.run(["open", "-a", "PyCharm", path], check=False)

        # Update database
        connection = db_manager._get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE project_registry
                    SET last_opened = CURRENT_TIMESTAMP,
                        open_count = open_count + 1
                    WHERE friendly_name = %s
                """, (project['friendly_name'],))
            connection.commit()
        finally:
            db_manager._put_connection(connection)

        response = f"Opening {project['friendly_name']}, sir."
        if project.get('launch_command'):
            response += " Would you like me to start the dev server?"
        jarvis_app.speak(response)
        return response

    except Exception as e:
        error_msg = f"Error opening project: {e}"
        logging.error(error_msg)
        return f"Sorry sir, I couldn't open the project. {error_msg}"

def launch_dev_server(db_manager, project: dict, jarvis_app) -> str:
    """
    Launch the project's dev server.

    Args:
        db_manager: DatabaseManager instance
        project: Project dict
        jarvis_app: JarvisApp instance

    Returns:
        str: Response message
    """
    cmd = project.get('launch_command')
    if not cmd:
        return "No launch command configured for this project, sir."

    path = project['full_path']
    if not os.path.exists(path):
        return f"Project path {path} no longer exists, sir."

    try:
        # Use AppleScript to open Terminal and run command
        applescript = f'''
        tell application "Terminal"
            do script "cd {path} && {cmd}"
            activate
        end tell
        '''
        subprocess.run(["osascript", "-e", applescript], check=True)

        response = f"Starting dev server for {project['friendly_name']}, sir."
        if project.get('browser_url'):
            time.sleep(3)  # Wait for server to start
            webbrowser.open(project['browser_url'])
            response += f" Opening {project['browser_url']} in browser."

        jarvis_app.speak(response)
        return response

    except Exception as e:
        error_msg = f"Error launching dev server: {e}"
        logging.error(error_msg)
        return f"Sorry sir, I couldn't start the dev server. {error_msg}"

def list_projects(db_manager) -> str:
    """
    List all registered projects grouped by type.

    Args:
        db_manager: DatabaseManager instance

    Returns:
        str: Formatted list of projects
    """
    connection = db_manager._get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT project_type, COUNT(*) as count
                FROM project_registry
                GROUP BY project_type
                ORDER BY count DESC
            """)
            type_counts = cursor.fetchall()

            if not type_counts:
                return "No projects registered yet, sir."

            response = "Your registered projects:\n"
            for project_type, count in type_counts:
                response += f"- {count} {project_type} project{'s' if count != 1 else ''}\n"

            cursor.execute("""
                SELECT friendly_name, project_type, last_opened
                FROM project_registry
                ORDER BY last_opened DESC NULLS LAST
            """)
            projects = cursor.fetchall()

            response += "\nRecently opened:\n"
            for name, ptype, last_opened in projects[:5]:
                date_str = last_opened.strftime("%b %d") if last_opened else "Never"
                response += f"- {name} ({ptype}) - Last opened {date_str}\n"

            return response.strip()

    except Exception as e:
        logging.error(f"Error listing projects: {e}")
        return "Sorry sir, I couldn't retrieve your projects."
    finally:
        db_manager._put_connection(connection)


# ══════════════════════════════════════════════════════════
# ██  SMART FILE FINDER
# ══════════════════════════════════════════════════════════

def smart_find_file(db_manager, query: str, base_dirs: list[str] = None) -> list[dict]:
    """
    Find files using intent scoring with semantic similarity, recency, frequency, and location.

    Args:
        db_manager: DatabaseManager instance
        query: Search query
        base_dirs: Base directories to search (defaults to Desktop, Documents, Downloads, home)

    Returns:
        list[dict]: Top 5 matches with scores
    """
    if base_dirs is None:
        home = Path.home()
        base_dirs = [
            home / "Desktop",
            home / "Documents",
            home / "Downloads",
            home
        ]

    query_lower = query.lower()
    query_embedding = compute_embedding(query)
    now = datetime.datetime.now()

    all_matches = []

    for base_dir in base_dirs:
        if not base_dir.exists():
            continue

        try:
            for root, dirs, files in os.walk(base_dir, topdown=True):
                # Skip ignored directories
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in {
                    'node_modules', 'venv', '__pycache__', '.git'
                }]

                root_path = Path(root)
                for file in files:
                    if file.startswith('.'):
                        continue

                    file_path = root_path / file
                    file_path_str = str(file_path)

                    # Get file stats
                    try:
                        stat = file_path.stat()
                        mtime = datetime.datetime.fromtimestamp(stat.st_mtime)
                    except OSError:
                        continue

                    # Get access count from DB
                    access_count = 0
                    connection = db_manager._get_connection()
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute("""
                                SELECT open_count FROM file_access_log
                                WHERE file_path = %s
                            """, (file_path_str,))
                            result = cursor.fetchone()
                            if result:
                                access_count = result[0]
                    except Exception:
                        pass
                    finally:
                        db_manager._put_connection(connection)

                    # Calculate scores
                    filename_lower = file.lower()

                    # Semantic similarity (40%)
                    filename_embedding = compute_embedding(file)
                    semantic_sim = 0
                    if query_embedding and filename_embedding:
                        try:
                            # Cosine similarity
                            import numpy as np
                            dot_product = np.dot(query_embedding, filename_embedding)
                            norm_q = np.linalg.norm(query_embedding)
                            norm_f = np.linalg.norm(filename_embedding)
                            if norm_q > 0 and norm_f > 0:
                                semantic_sim = dot_product / (norm_q * norm_f)
                        except Exception:
                            semantic_sim = 0

                    # Recency score (35%) - 1.0 for today, decaying daily
                    days_since_modified = (now - mtime).days
                    recency_score = max(0, 1 - days_since_modified / 7)  # Week decay

                    # Frequency score (15%) - normalized log scale
                    frequency_score = min(1.0, math.log(access_count + 1) / math.log(100))

                    # Location score (10%) - Desktop > Documents > Downloads > deep paths
                    depth = len(file_path.relative_to(base_dir).parts)
                    if "Desktop" in str(base_dir):
                        location_score = 1.0
                    elif "Documents" in str(base_dir):
                        location_score = 0.8
                    elif "Downloads" in str(base_dir):
                        location_score = 0.6
                    else:
                        location_score = max(0.1, 1 - depth * 0.1)

                    # Total intent score
                    intent_score = (
                        semantic_sim * 0.40 +
                        recency_score * 0.35 +
                        frequency_score * 0.15 +
                        location_score * 0.10
                    )

                    all_matches.append({
                        'path': file_path_str,
                        'name': file,
                        'score': intent_score,
                        'modified': mtime,
                        'size': stat.st_size,
                        'access_count': access_count
                    })

        except Exception as e:
            logging.warning(f"Error searching {base_dir}: {e}")
            continue

    # Sort by score and return top 5
    all_matches.sort(key=lambda x: x['score'], reverse=True)
    return all_matches[:5]

def log_file_access(db_manager, file_path: str):
    """
    Log file access for frequency scoring.

    Args:
        db_manager: DatabaseManager instance
        file_path: Absolute path to file
    """
    connection = db_manager._get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO file_access_log (file_path, file_name, last_opened, open_count)
                VALUES (%s, %s, CURRENT_TIMESTAMP, 1)
                ON CONFLICT (file_path) DO UPDATE SET
                    last_opened = CURRENT_TIMESTAMP,
                    open_count = file_access_log.open_count + 1
            """, (file_path, Path(file_path).name))
        connection.commit()
    except Exception as e:
        logging.error(f"Error logging file access: {e}")
    finally:
        db_manager._put_connection(connection)


# ══════════════════════════════════════════════════════════
# ██  EXPANDED SYSTEM CONTROLS
# ══════════════════════════════════════════════════════════

def toggle_bluetooth(state: bool) -> str:
    """
    Toggle Bluetooth on/off using blueutil.

    Args:
        state: True to turn on, False to turn off

    Returns:
        str: Response message
    """
    try:
        # Check if blueutil is installed
        result = subprocess.run(["which", "blueutil"], capture_output=True, text=True)
        if result.returncode != 0:
            return "Bluetooth control requires blueutil. Install with 'brew install blueutil', sir."

        cmd = ["blueutil", "--power", "1" if state else "0"]
        subprocess.run(cmd, check=True)

        status = "on" if state else "off"
        return f"Bluetooth turned {status}, sir."

    except subprocess.CalledProcessError as e:
        return f"Failed to toggle Bluetooth: {e}"
    except Exception as e:
        logging.error(f"Bluetooth toggle error: {e}")
        return "Sorry sir, I couldn't control Bluetooth."

def list_bluetooth_devices() -> str:
    """
    List connected Bluetooth devices.

    Returns:
        str: List of connected devices
    """
    try:
        result = subprocess.run(["which", "blueutil"], capture_output=True, text=True)
        if result.returncode != 0:
            return "Bluetooth control requires blueutil, sir."

        result = subprocess.run(["blueutil", "--connected"], capture_output=True, text=True)
        if result.returncode != 0:
            return "No Bluetooth devices connected, sir."

        devices = result.stdout.strip().split('\n')
        if not devices or devices == ['']:
            return "No Bluetooth devices connected, sir."

        response = "Connected Bluetooth devices:\n"
        for device in devices:
            if device.strip():
                response += f"- {device.strip()}\n"
        return response.strip()

    except Exception as e:
        logging.error(f"Bluetooth device list error: {e}")
        return "Sorry sir, I couldn't list Bluetooth devices."

def toggle_wifi(state: bool) -> str:
    """
    Toggle Wi-Fi on/off using networksetup.

    Args:
        state: True to turn on, False to turn off

    Returns:
        str: Response message
    """
    try:
        cmd = ["networksetup", "-setairportpower", "en0", "on" if state else "off"]
        subprocess.run(cmd, check=True, capture_output=True)

        status = "on" if state else "off"
        return f"Wi-Fi turned {status}, sir."

    except subprocess.CalledProcessError as e:
        return f"Failed to toggle Wi-Fi: {e.stderr.decode()}"
    except Exception as e:
        logging.error(f"Wi-Fi toggle error: {e}")
        return "Sorry sir, I couldn't control Wi-Fi."

def get_wifi_info() -> str:
    """
    Get current Wi-Fi information.

    Returns:
        str: Wi-Fi status and details
    """
    try:
        # Get network name
        result = subprocess.run(["networksetup", "-getairportnetwork", "en0"],
                              capture_output=True, text=True)
        network_name = "Not connected"
        if result.returncode == 0:
            # Parse output like "Current Wi-Fi Network: MyNetwork"
            lines = result.stdout.strip().split('\n')
            for line in lines:
                if "Current Wi-Fi Network:" in line:
                    network_name = line.split(":", 1)[1].strip()
                    break

        # Get IP address
        result = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True)
        ip_address = result.stdout.strip() if result.returncode == 0 else "No IP"

        # Get signal strength (requires airport command)
        try:
            result = subprocess.run(["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"],
                                  capture_output=True, text=True)
            signal_strength = "Unknown"
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'agrCtlRSSI' in line:
                        signal_strength = line.split(':', 1)[1].strip()
                        break
        except Exception:
            signal_strength = "Unknown"

        return f"Wi-Fi Network: {network_name}\nIP Address: {ip_address}\nSignal Strength: {signal_strength}"

    except Exception as e:
        logging.error(f"Wi-Fi info error: {e}")
        return "Sorry sir, I couldn't get Wi-Fi information."

def connect_to_wifi(network_name: str) -> str:
    """
    Connect to a Wi-Fi network (requires password).

    Args:
        network_name: Name of the network

    Returns:
        str: Response message
    """
    # This would require voice input for password, which is complex
    # For now, just attempt connection assuming no password or known network
    try:
        cmd = ["networksetup", "-setairportnetwork", "en0", network_name]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            return f"Connected to {network_name}, sir."
        else:
            error = result.stderr.strip()
            if "Password" in error:
                return f"Network {network_name} requires a password. Please connect manually, sir."
            else:
                return f"Failed to connect to {network_name}: {error}"

    except Exception as e:
        logging.error(f"Wi-Fi connect error: {e}")
        return "Sorry sir, I couldn't connect to that network."

def move_window_to_space(space_num: int) -> str:
    """
    Move the frontmost window to a specific Mission Control space.

    Args:
        space_num: Space number (1-based)

    Returns:
        str: Response message
    """
    try:
        applescript = f'''
        tell application "System Events"
            set frontApp to name of first application process whose frontmost is true
            tell process frontApp
                set frontWindow to window 1
                perform action "AXPress" of (button 1 of (splitter group 1 of frontWindow))
            end tell
        end tell
        '''
        # This is a simplified version - full space switching requires more complex AppleScript
        subprocess.run(["osascript", "-e", applescript], check=True)
        return f"Moved window to space {space_num}, sir."

    except Exception as e:
        logging.error(f"Window space move error: {e}")
        return "Sorry sir, I couldn't move the window to that space."

def snap_window_left() -> str:
    """
    Snap the frontmost window to the left half of the screen.

    Returns:
        str: Response message
    """
    try:
        applescript = '''
        tell application "System Events"
            set frontApp to name of first application process whose frontmost is true
            tell application frontApp
                set bounds of window 1 to {0, 0, 1440, 900}
            end tell
        end tell
        '''
        subprocess.run(["osascript", "-e", applescript], check=True)
        return "Window snapped to left, sir."

    except Exception as e:
        logging.error(f"Window snap left error: {e}")
        return "Sorry sir, I couldn't snap the window."

def snap_window_right() -> str:
    """
    Snap the frontmost window to the right half of the screen.

    Returns:
        str: Response message
    """
    try:
        applescript = '''
        tell application "System Events"
            set frontApp to name of first application process whose frontmost is true
            tell application frontApp
                set bounds of window 1 to {1440, 0, 2880, 900}
            end tell
        end tell
        '''
        subprocess.run(["osascript", "-e", applescript], check=True)
        return "Window snapped to right, sir."

    except Exception as e:
        logging.error(f"Window snap right error: {e}")
        return "Sorry sir, I couldn't snap the window."

def get_open_windows() -> str:
    """
    Get list of open application windows.

    Returns:
        str: List of open windows
    """
    try:
        applescript = '''
        tell application "System Events"
            set windowList to {}
            repeat with proc in (every process whose background only is false)
                try
                    set procName to name of proc
                    set windowNames to name of windows of proc
                    repeat with wName in windowNames
                        set end of windowList to (procName & " - " & wName)
                    end repeat
                end try
            end repeat
            return windowList
        end tell
        '''
        result = subprocess.run(["osascript", "-e", applescript], capture_output=True, text=True)
        if result.returncode == 0:
            windows = result.stdout.strip().split(', ')
            if windows and windows[0]:
                response = "Open windows:\n"
                for window in windows[:10]:  # Limit to 10
                    response += f"- {window}\n"
                return response.strip()
            else:
                return "No windows open, sir."
        else:
            return "Couldn't get window list, sir."

    except Exception as e:
        logging.error(f"Get windows error: {e}")
        return "Sorry sir, I couldn't list the windows."

def switch_to_app(app_name: str) -> str:
    """
    Switch to a specific application by name.

    Args:
        app_name: Name of the application

    Returns:
        str: Response message
    """
    try:
        # Try exact match first
        applescript = f'''
        tell application "{app_name}" to activate
        '''
        result = subprocess.run(["osascript", "-e", applescript], capture_output=True)

        if result.returncode == 0:
            return f"Switched to {app_name}, sir."
        else:
            # Try fuzzy match with System Events
            applescript = f'''
            tell application "System Events"
                set appList to name of every application process whose background only is false
                repeat with appItem in appList
                    if appItem contains "{app_name}" then
                        tell application appItem to activate
                        return "Switched to " & appItem
                    end if
                end repeat
                return "App not found"
            end tell
            '''
            result = subprocess.run(["osascript", "-e", applescript], capture_output=True, text=True)
            if result.returncode == 0 and "App not found" not in result.stdout:
                return f"Switched to {result.stdout.strip()}, sir."
            else:
                return f"Couldn't find application {app_name}, sir."

    except Exception as e:
        logging.error(f"Switch app error: {e}")
        return "Sorry sir, I couldn't switch applications."

def get_screen_info() -> str:
    """
    Get screen resolution, brightness, and other display info.

    Returns:
        str: Display information
    """
    try:
        # Get screen resolution
        result = subprocess.run(["system_profiler", "SPDisplaysDataType"],
                              capture_output=True, text=True)
        resolution = "Unknown"
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'Resolution:' in line:
                    resolution = line.split(':', 1)[1].strip()
                    break

        # Get brightness (if available)
        brightness = "Unknown"
        try:
            result = subprocess.run(["brightness", "-l"], capture_output=True, text=True)
            if result.returncode == 0:
                # Parse brightness output
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'display 0' in line and 'brightness' in line:
                        parts = line.split()
                        brightness = parts[-1]
                        break
        except Exception:
            pass

        return f"Screen Resolution: {resolution}\nBrightness: {brightness}"

    except Exception as e:
        logging.error(f"Screen info error: {e}")
        return "Sorry sir, I couldn't get screen information."

def toggle_night_shift(state: bool) -> str:
    """
    Toggle Night Shift on/off.

    Args:
        state: True to turn on, False to turn off

    Returns:
        str: Response message
    """
    try:
        # Use CoreBrightness framework via osascript
        script = f'''
        tell application "System Events"
            tell appearance preferences
                set dark mode to {str(state).lower()}
            end tell
        end tell
        '''
        # Actually, Night Shift control is more complex. This toggles dark mode instead.
        # For true Night Shift, would need private APIs or third-party tools
        subprocess.run(["osascript", "-e", script], check=True)
        status = "on" if state else "off"
        return f"Night Shift turned {status}, sir."

    except Exception as e:
        logging.error(f"Night Shift toggle error: {e}")
        return "Sorry sir, I couldn't control Night Shift."

def take_screenshot(area: str = 'full') -> str:
    """
    Take a screenshot and save to Desktop.

    Args:
        area: 'full', 'window', or 'selection'

    Returns:
        str: Response message
    """
    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"jarvis_screenshot_{timestamp}.png"
        filepath = os.path.join(Path.home(), "Desktop", filename)

        if area == 'full':
            cmd = ["screencapture", "-x", filepath]
        elif area == 'window':
            cmd = ["screencapture", "-x", "-w", filepath]
        elif area == 'selection':
            cmd = ["screencapture", "-x", "-s", filepath]
        else:
            return "Invalid screenshot area. Use 'full', 'window', or 'selection', sir."

        subprocess.run(cmd, check=True)
        return f"Screenshot saved to Desktop as {filename}, sir."

    except subprocess.CalledProcessError as e:
        return f"Failed to take screenshot: {e}"
    except Exception as e:
        logging.error(f"Screenshot error: {e}")
        return "Sorry sir, I couldn't take a screenshot."


# ══════════════════════════════════════════════════════════
# ██  PROACTIVE PROCESS MONITOR
# ══════════════════════════════════════════════════════════

class ProcessMonitor(threading.Thread):
    """
    Background thread that monitors system processes and alerts proactively.
    """

    def __init__(self, db_manager, jarvis_app, render_health_url=None, git_check_interval_hours=2):
        super().__init__(daemon=True)
        self.db_manager = db_manager
        self.jarvis_app = jarvis_app
        self.render_health_url = render_health_url
        self.git_check_interval_hours = git_check_interval_hours
        self.running = True
        self.last_alerts = {}  # alert_type -> last_spoken_time
        self.last_git_check = datetime.datetime.now()

    def run(self):
        """Main monitoring loop."""
        while self.running:
            try:
                self._check_dev_servers()
                self._check_battery()
                self._check_system_resources()
                self._check_render_health()
                self._check_git_status()
            except Exception as e:
                logging.error(f"Process monitor error: {e}")

            time.sleep(30)  # Check every 30 seconds

    def stop(self):
        """Stop the monitoring thread."""
        self.running = False

    def _should_alert(self, alert_type: str) -> bool:
        """Check if we should speak an alert (cooldown logic)."""
        now = datetime.datetime.now()
        last_alert = self.last_alerts.get(alert_type)

        if last_alert is None:
            self.last_alerts[alert_type] = now
            return True

        # 30 minute cooldown
        if (now - last_alert).total_seconds() > 1800:
            self.last_alerts[alert_type] = now
            return True

        return False

    def _check_dev_servers(self):
        """Check if configured dev servers are still running."""
        connection = self.db_manager._get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT friendly_name, full_path, launch_command
                    FROM project_registry
                    WHERE launch_command IS NOT NULL
                """)
                projects = cursor.fetchall()

                for name, path, cmd in projects:
                    # Check if any process matches the command pattern
                    try:
                        # Simple check: look for processes with project name or common dev server names
                        result = subprocess.run(["pgrep", "-f", name], capture_output=True, text=True)
                        if result.returncode != 0:  # No process found
                            if self._should_alert(f"server_down_{name}"):
                                self.jarvis_app.speak(f"Dev server for {name} appears to have stopped, sir.")
                    except Exception:
                        pass

        except Exception as e:
            logging.error(f"Dev server check error: {e}")
        finally:
            self.db_manager._put_connection(connection)

    def _check_battery(self):
        """Check battery level and alert if low."""
        try:
            result = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True)
            if result.returncode == 0:
                output = result.stdout
                # Parse output like "Now drawing from 'Battery Power' - InternalBattery-0 85%; discharging; 3:45 remaining"
                if "%" in output:
                    percent_str = output.split("%")[0].split()[-1]
                    try:
                        percent = int(percent_str)
                        if percent <= 20:
                            # Check if charging
                            if "discharging" in output and self._should_alert("battery_low"):
                                self.jarvis_app.speak(f"Battery at {percent}%, please connect charger, sir.")
                    except ValueError:
                        pass
        except Exception as e:
            logging.error(f"Battery check error: {e}")

    def _check_system_resources(self):
        """Check RAM and CPU usage."""
        try:
            # Check available RAM
            result = subprocess.run(["vm_stat"], capture_output=True, text=True)
            if result.returncode == 0:
                # Parse vm_stat output for free memory
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'Pages free:' in line:
                        # Rough calculation - each page is 4096 bytes
                        free_pages = int(line.split(':')[1].strip().replace('.', ''))
                        free_mb = (free_pages * 4096) / (1024 * 1024)
                        if free_mb < 512:  # Less than 512MB free
                            if self._should_alert("low_memory"):
                                self.jarvis_app.speak("System memory is getting low, sir.")

            # Check CPU usage of top processes
            result = subprocess.run(["ps", "aux", "--sort=-%cpu"], capture_output=True, text=True)
            if result.returncode == 0:
                lines = result.stdout.split('\n')[1:6]  # Top 5 processes
                high_cpu_processes = []
                for line in lines:
                    if line.strip():
                        parts = line.split()
                        if len(parts) > 2:
                            try:
                                cpu_percent = float(parts[2])
                                if cpu_percent > 80:  # Over 80% CPU
                                    process_name = parts[-1] if len(parts) > 10 else ' '.join(parts[10:])
                                    high_cpu_processes.append(f"{process_name} ({cpu_percent}%)")
                            except ValueError:
                                pass

                if high_cpu_processes and self._should_alert("high_cpu"):
                    process_list = ", ".join(high_cpu_processes[:3])
                    self.jarvis_app.speak(f"High CPU usage detected: {process_list}, sir.")

        except Exception as e:
            logging.error(f"Resource check error: {e}")

    def _check_render_health(self):
        """Check Render deployment health if URL configured."""
        if not self.render_health_url:
            return

        try:
            import requests
            response = requests.get(self.render_health_url, timeout=5)
            if response.status_code != 200:
                if self._should_alert("render_down"):
                    self.jarvis_app.speak("Render deployment appears to be down, sir.")
        except Exception as e:
            logging.error(f"Render health check error: {e}")

    def _check_git_status(self):
        """Check git status for registered projects."""
        now = datetime.datetime.now()
        if (now - self.last_git_check).total_seconds() < (self.git_check_interval_hours * 3600):
            return

        self.last_git_check = now

        connection = self.db_manager._get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT friendly_name, full_path
                    FROM project_registry
                    WHERE git_enabled = true
                """)
                projects = cursor.fetchall()

                for name, path in projects:
                    try:
                        # Check if directory exists and is git repo
                        if not os.path.exists(os.path.join(path, '.git')):
                            continue

                        # Check for uncommitted changes
                        result = subprocess.run(["git", "status", "--porcelain"],
                                              cwd=path, capture_output=True, text=True)
                        if result.returncode == 0 and result.stdout.strip():
                            if self._should_alert(f"git_changes_{name}"):
                                self.jarvis_app.speak(f"You have uncommitted changes in {name}, sir.")
                    except Exception:
                        pass

        except Exception as e:
            logging.error(f"Git status check error: {e}")
        finally:
            self.db_manager._put_connection(connection)


# ══════════════════════════════════════════════════════════
# ██  KEYBOARD SHORTCUT ACTIVATION
# ══════════════════════════════════════════════════════════

class HotkeyListener(threading.Thread):
    """
    Background thread that listens for global keyboard shortcuts.
    """

    def __init__(self, jarvis_app, combo="cmd+shift+space"):
        super().__init__(daemon=True)
        self.jarvis_app = jarvis_app
        self.combo = combo
        self.running = True
        self.listener = None

    def run(self):
        """Start the hotkey listener."""
        if keyboard is None:
            logging.warning("pynput not available, hotkey activation disabled")
            return

        try:
            # Parse combo
            keys = set()
            combo_parts = self.combo.lower().replace(" ", "").split("+")
            for part in combo_parts:
                if part == "cmd":
                    keys.add(keyboard.Key.cmd)
                elif part == "shift":
                    keys.add(keyboard.Key.shift)
                elif part == "ctrl":
                    keys.add(keyboard.Key.ctrl)
                elif part == "alt":
                    keys.add(keyboard.Key.alt)
                elif part == "space":
                    keys.add(keyboard.Key.space)
                else:
                    logging.error(f"Unknown key in combo: {part}")
                    return

            def on_activate():
                """Callback when hotkey is pressed."""
                self.jarvis_app.trigger_wake_word()

            # Start listener
            with keyboard.GlobalHotKeys({self.combo: on_activate}) as h:
                self.listener = h
                while self.running:
                    time.sleep(0.1)

        except Exception as e:
            logging.error(f"Hotkey listener error: {e}")
            # Try to grant accessibility permissions
            self._check_accessibility_permissions()

    def stop(self):
        """Stop the listener."""
        self.running = False
        if self.listener:
            self.listener.stop()

    def _check_accessibility_permissions(self):
        """Check and prompt for accessibility permissions."""
        try:
            applescript = '''
            tell application "System Preferences"
                activate
                set current pane to pane id "com.apple.preference.security"
                delay 1
            end tell
            '''
            subprocess.run(["osascript", "-e", applescript], check=False)
            self.jarvis_app.speak("Please grant accessibility permissions for keyboard shortcuts, sir.")
        except Exception:
            pass


# ══════════════════════════════════════════════════════════
# ██  CORNER TRIGGER ACTIVATION
# ══════════════════════════════════════════════════════════

class CornerTriggerWatcher(threading.Thread):
    """
    Background thread that watches for mouse cursor in screen corners.
    """

    def __init__(self, jarvis_app, corner="top-right", delay_ms=1200):
        super().__init__(daemon=True)
        self.jarvis_app = jarvis_app
        self.corner = corner
        self.delay_ms = delay_ms / 1000.0  # Convert to seconds
        self.running = True
        self.listener = None
        self.hover_start = None
        self.last_trigger = None
        self.cooldown = 5.0  # 5 second cooldown after trigger

    def run(self):
        """Start the corner watcher."""
        if mouse is None:
            logging.warning("pynput not available, corner trigger disabled")
            return

        def on_move(x, y):
            """Callback when mouse moves."""
            if not self.running:
                return

            # Check if in corner
            screen_size = self._get_screen_size()
            in_corner = self._is_in_corner(x, y, screen_size)

            now = time.time()

            if in_corner:
                if self.hover_start is None:
                    self.hover_start = now
                    # Signal UI to show corner highlight
                    if hasattr(self.jarvis_app, 'ui_bridge'):
                        self.jarvis_app.ui_bridge.trigger_corner_hover(True)
                elif now - self.hover_start >= self.delay_ms:
                    # Check cooldown
                    if self.last_trigger is None or now - self.last_trigger >= self.cooldown:
                        self.last_trigger = now
                        self.jarvis_app.trigger_wake_word()
                        self.hover_start = None
                        # Hide corner highlight
                        if hasattr(self.jarvis_app, 'ui_bridge'):
                            self.jarvis_app.ui_bridge.trigger_corner_hover(False)
            else:
                if self.hover_start is not None:
                    # Hide corner highlight
                    if hasattr(self.jarvis_app, 'ui_bridge'):
                        self.jarvis_app.ui_bridge.trigger_corner_hover(False)
                self.hover_start = None

        try:
            with mouse.Listener(on_move=on_move) as l:
                self.listener = l
                while self.running:
                    time.sleep(0.1)
        except Exception as e:
            logging.error(f"Corner trigger error: {e}")
            self._check_accessibility_permissions()

    def stop(self):
        """Stop the watcher."""
        self.running = False
        if self.listener:
            self.listener.stop()

    def _get_screen_size(self):
        """Get screen size."""
        try:
            from Quartz import CGDisplayBounds, CGMainDisplayID
            bounds = CGDisplayBounds(CGMainDisplayID())
            return bounds.size.width, bounds.size.height
        except Exception:
            # Fallback to 1920x1080
            return 1920, 1080

    def _is_in_corner(self, x, y, screen_size):
        """Check if cursor is in the trigger corner."""
        width, height = screen_size
        margin = 30  # pixels from edge

        if self.corner == "top-right":
            return x >= width - margin and y <= margin
        elif self.corner == "top-left":
            return x <= margin and y <= margin
        elif self.corner == "bottom-right":
            return x >= width - margin and y >= height - margin
        elif self.corner == "bottom-left":
            return x <= margin and y >= height - margin
        else:
            return False

    def _check_accessibility_permissions(self):
        """Check and prompt for accessibility permissions."""
        try:
            applescript = '''
            tell application "System Preferences"
                activate
                set current pane to pane id "com.apple.preference.security"
                delay 1
            end tell
            '''
            subprocess.run(["osascript", "-e", applescript], check=False)
            self.jarvis_app.speak("Please grant accessibility permissions for corner triggers, sir.")
        except Exception:
            pass


# ══════════════════════════════════════════════════════════
# ██  EMBEDDING ENGINE (PHASE 2)
# ══════════════════════════════════════════════════════════

_embedding_engine = None
_embedding_cache = {}

class EmbeddingEngine:
    """
    Singleton embedding engine using sentence-transformers.
    Lazy-loads the model and maintains an LRU cache of embeddings.
    """

    def __init__(self):
        """Initialize the embedding engine."""
        self.model = None
        self.lock = threading.Lock()
        self.cache = {}
        self.max_cache_size = 500

    def _load_model(self):
        """Lazy-load the sentence transformer model."""
        if self.model is None:
            if SentenceTransformer is None:
                logging.warning("sentence-transformers not available, embeddings disabled")
                return False
            try:
                self.model = SentenceTransformer('all-MiniLM-L6-v2')
                return True
            except Exception as e:
                logging.error(f"Failed to load embedding model: {e}")
                return False
        return True

    def embed(self, text: str) -> list:
        """
        Embed text using cached model.

        Args:
            text: Text to embed

        Returns:
            list: Embedding vector (384-dim) or empty list if failed
        """
        if not text or not text.strip():
            return []

        normalized_text = text.lower().strip()

        with self.lock:
            # Check cache first
            if normalized_text in self.cache:
                return self.cache[normalized_text]

            # Load model if needed
            if not self._load_model():
                return []

            # Compute embedding
            try:
                embedding = self.model.encode(normalized_text).tolist()
                # Add to cache, remove oldest if at capacity
                if len(self.cache) >= self.max_cache_size:
                    oldest_key = next(iter(self.cache))
                    del self.cache[oldest_key]
                self.cache[normalized_text] = embedding
                return embedding
            except Exception as e:
                logging.error(f"Error embedding text: {e}")
                return []

    def embed_batch(self, texts: list) -> list:
        """
        Embed multiple texts efficiently.

        Args:
            texts: List of texts to embed

        Returns:
            list: List of embedding vectors
        """
        if not texts or not self._load_model():
            return [[] for _ in texts]

        try:
            embeddings = self.model.encode(texts)
            return embeddings.tolist() if hasattr(embeddings, 'tolist') else embeddings
        except Exception as e:
            logging.error(f"Error batch embedding: {e}")
            return [[] for _ in texts]

    @staticmethod
    def cosine_similarity(vec1: list, vec2: list) -> float:
        """
        Calculate cosine similarity between two vectors.

        Args:
            vec1: First vector
            vec2: Second vector

        Returns:
            float: Similarity score 0-1
        """
        if not vec1 or not vec2:
            return 0.0
        try:
            import numpy as np
            v1 = np.array(vec1)
            v2 = np.array(vec2)
            dot = np.dot(v1, v2)
            norm1 = np.linalg.norm(v1)
            norm2 = np.linalg.norm(v2)
            if norm1 > 0 and norm2 > 0:
                return float(dot / (norm1 * norm2))
        except Exception:
            pass
        return 0.0

def get_embedding_engine() -> EmbeddingEngine:
    """Get or create the singleton embedding engine."""
    global _embedding_engine
    if _embedding_engine is None:
        _embedding_engine = EmbeddingEngine()
    return _embedding_engine


# ══════════════════════════════════════════════════════════
# ██  OLLAMA PROVIDER (PHASE 2)
# ══════════════════════════════════════════════════════════

class OllamaProvider:
    """
    Local LLM provider using Ollama for offline AI capabilities.
    """

    def __init__(self, base_url: str, model: str, timeout: int = 30):
        """
        Initialize Ollama provider.

        Args:
            base_url: Ollama server URL (default: http://localhost:11434)
            model: Model name to use (e.g., 'phi3:mini')
            timeout: Request timeout in seconds
        """
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.conversation_history = []
        self.max_history = 10

    def is_available(self) -> bool:
        """
        Check if Ollama is running and model is available.

        Returns:
            bool: True if Ollama is accessible
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=2)
            if response.status_code == 200:
                # Check if our model is in the list
                data = response.json()
                models = data.get('models', [])
                for m in models:
                    if m.get('name') == self.model or m.get('name').startswith(self.model + ":"):
                        return True
                logging.warning(f"Ollama model '{self.model}' not found. Available: {[m.get('name') for m in models]}")
                return False
            return False
        except Exception as e:
            logging.debug(f"Ollama not available: {e}")
            return False

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        """
        Generate response from Ollama.

        Args:
            prompt: User prompt
            system_prompt: System prompt for personality

        Returns:
            str: Generated response or empty string if failed
        """
        if requests is None:
            return ""

        try:
            # Build messages with conversation history
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})

            # Add recent history
            for turn in self.conversation_history[-self.max_history:]:
                messages.append(turn)

            # Add current prompt
            messages.append({"role": "user", "content": prompt})

            # Call Ollama API
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": messages, "stream": False},
                timeout=self.timeout
            )

            if response.status_code == 200:
                result = response.json()
                assistant_message = result.get("message", {}).get("content", "").strip()

                # Update history
                self.conversation_history.append({"role": "user", "content": prompt})
                self.conversation_history.append({"role": "assistant", "content": assistant_message})

                # Trim history to max_history window
                if len(self.conversation_history) > self.max_history * 2:
                    self.conversation_history = self.conversation_history[-(self.max_history * 2):]

                return assistant_message
            else:
                logging.error(f"Ollama API error: {response.status_code}")
                return ""

        except requests.exceptions.Timeout:
            logging.warning(f"Ollama timeout (>{self.timeout}s), falling back to next provider")
            return ""
        except Exception as e:
            logging.error(f"Ollama generation error: {e}")
            return ""

    def reset_history(self):
        """Clear conversation history."""
        self.conversation_history = []


# ══════════════════════════════════════════════════════════
# ██  ONLINE/OFFLINE DETECTION (PHASE 2)
# ══════════════════════════════════════════════════════════

_last_online_check = 0
_last_online_state = True

def is_online(cache_seconds: int = 60) -> bool:
    """
    Check if system has internet connectivity.

    Args:
        cache_seconds: Cache result for this many seconds

    Returns:
        bool: True if online
    """
    global _last_online_check, _last_online_state

    now = time.time()
    if now - _last_online_check < cache_seconds:
        return _last_online_state

    try:
        # Try to connect to Google DNS
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 53))
            result = True
    except Exception:
        result = False

    _last_online_check = now
    _last_online_state = result
    return result


# ══════════════════════════════════════════════════════════
# ██  SEMANTIC MEMORY SYSTEM (PHASE 2)
# ══════════════════════════════════════════════════════════

def calculate_importance(key: str, value: str, category: str) -> float:
    """
    Calculate importance score for a memory.

    Args:
        key: Memory key
        value: Memory value
        category: Memory category

    Returns:
        float: Importance score 0.0-1.0
    """
    import re

    # Never store secrets
    if any(keyword in key.lower() for keyword in ['password', 'secret', 'token', 'key']):
        return 0.0

    # Base score by category
    scores = {
        "personal": 0.9,
        "project": 0.8,
        "preference": 0.7,
        "fact": 0.5,
        "general": 0.4
    }
    score = scores.get(category, 0.5)

    # Bonus for detailed memories
    if len(value) > 200:
        score += 0.1

    # Bonus for time-anchored memories
    if re.search(r'\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}', value):
        score += 0.1

    return min(1.0, score)

def semantic_search_memory(db_manager, query: str, top_k: int = 5, threshold: float = 0.65) -> list:
    """
    Search memories using semantic similarity.

    Args:
        db_manager: DatabaseManager instance
        query: Search query
        top_k: Number of results to return
        threshold: Minimum similarity threshold

    Returns:
        list: List of matching memory dicts
    """
    engine = get_embedding_engine()
    query_embedding = engine.embed(query)
    if not query_embedding:
        return []

    connection = db_manager._get_connection()
    try:
        with connection.cursor() as cursor:
            # Search using vector similarity
            cursor.execute("""
                SELECT id, key, value, category, importance_score,
                       1 - (embedding <=> %s::vector) as similarity
                FROM memory
                WHERE embedding IS NOT NULL
                  AND 1 - (embedding <=> %s::vector) > %s
                ORDER BY similarity DESC
                LIMIT %s
            """, (query_embedding, query_embedding, threshold, top_k))

            results = []
            for row in cursor.fetchall():
                r = {
                    'id': row[0],
                    'key': row[1],
                    'value': row[2],
                    'category': row[3],
                    'importance_score': row[4],
                    'similarity': row[5]
                }
                results.append(r)

                # Update last_accessed
                cursor.execute("""
                    UPDATE memory SET last_accessed = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (row[0],))

            connection.commit()
            return results

    except Exception as e:
        logging.error(f"Semantic search error: {e}")
        return []
    finally:
        db_manager._put_connection(connection)

def recall_conversation_context(db_manager, query: str, top_k: int = 3) -> str:
    """
    Find relevant past conversation context.

    Args:
        db_manager: DatabaseManager instance
        query: Search query
        top_k: Number of results

    Returns:
        str: Formatted context string
    """
    engine = get_embedding_engine()
    query_embedding = engine.embed(query)
    if not query_embedding:
        return ""

    connection = db_manager._get_connection()
    try:
        with connection.cursor() as cursor:
            # Search conversation embeddings from last 30 days
            cursor.execute("""
                SELECT role, content, timestamp
                FROM conversation_embeddings
                WHERE embedding IS NOT NULL
                  AND timestamp > CURRENT_TIMESTAMP - INTERVAL '30 days'
                  AND 1 - (embedding <=> %s::vector) > 0.70
                ORDER BY 1 - (embedding <=> %s::vector) DESC
                LIMIT %s
            """, (query_embedding, query_embedding, top_k))

            turns = cursor.fetchall()
            if not turns:
                return ""

            context_parts = ["Previously, we discussed:"]
            for role, content, ts in turns:
                time_str = ts.strftime("%b %d") if ts else "earlier"
                if role == "user":
                    context_parts.append(f"You asked ({time_str}): {content[:100]}")
                else:
                    context_parts.append(f"I responded: {content[:100]}")

            return "\n".join(context_parts)

    except Exception as e:
        logging.error(f"Conversation context recall error: {e}")
        return ""
    finally:
        db_manager._put_connection(connection)

def recall_session_by_date(db_manager, date_str: str) -> str:
    """
    Recall a session summary by relative date.

    Args:
        db_manager: DatabaseManager instance
        date_str: Relative date like "yesterday", "last Monday", "2 days ago"

    Returns:
        str: Session summary or empty string
    """
    try:
        if dateutil_parser is None:
            return ""

        target_date = dateutil_parser.parse(date_str).date()
    except Exception:
        return ""

    connection = db_manager._get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT summary, message_count, started_at, ended_at
                FROM session_summaries
                WHERE DATE(ended_at) = %s
                ORDER BY ended_at DESC
                LIMIT 1
            """, (target_date,))

            row = cursor.fetchone()
            if row:
                summary, msg_count, start, end = row
                return f"Session {start.strftime('%I:%M %p')}: {summary} ({msg_count} messages)"
            return ""

    except Exception as e:
        logging.error(f"Session recall error: {e}")
        return ""
    finally:
        db_manager._put_connection(connection)

def inject_context_into_prompt(db_manager, current_command: str, max_tokens: int = 500) -> str:
    """
    Inject relevant context from memory before AI call.

    Args:
        db_manager: DatabaseManager instance
        current_command: User's current command
        max_tokens: Maximum tokens to include (rough estimate)

    Returns:
        str: Context string to prepend to system prompt
    """
    parts = []

    # Search semantic memory
    memories = semantic_search_memory(db_manager, current_command, top_k=3, threshold=0.60)
    if memories:
        mem_strs = [f"{m['key']}: {m['value'][:80]}" for m in memories]
        parts.append("Relevant memories: " + "\n".join(mem_strs))

    # Search conversation context
    context = recall_conversation_context(db_manager, current_command, top_k=2)
    if context:
        parts.append(context)

    full_context = "\n".join(parts)

    # Enforce max tokens (rough estimate: 1 word ≈ 4 chars)
    estimated_tokens = len(full_context) // 4
    if estimated_tokens > max_tokens:
        full_context = full_context[:max_tokens * 4]

    return full_context if full_context else ""


# ══════════════════════════════════════════════════════════
# ██  SYSTEM PROMPT BUILDER (PHASE 2)
# ══════════════════════════════════════════════════════════

def build_dynamic_system_prompt(db_manager) -> str:
    """
    Build personalized system prompt using user data and context.

    Args:
        db_manager: DatabaseManager instance

    Returns:
        str: Complete system prompt
    """
    parts = []

    # 1. Static JARVIS identity
    parts.append("""You are JARVIS, a highly advanced personal AI assistant. You are precise,
intelligent, occasionally witty, and always address the user as sir. You give concise
answers unless asked for detail. Never say you are an AI or mention your model name.
Respond as JARVIS would - professional but personable.""")

    # 2. User profile
    connection = db_manager._get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT key, value FROM user_profile LIMIT 20")
            profile = {row[0]: row[1] for row in cursor.fetchall()}
    except Exception:
        profile = {}
    finally:
        db_manager._put_connection(connection)

    if profile:
        name = profile.get('name', 'sir')
        response_length = profile.get('response_length', 'concise')
        style = profile.get('style', 'casual')
        parts.append(f"""User Profile:
- Preferred response length: {response_length}
- Communication style: {style}"""
)

    # 3. Time context
    now = datetime.datetime.now()
    hour = now.hour
    if 5 <= hour < 12:
        time_context = "Morning (user typically checks news and emails)"
    elif 12 <= hour < 17:
        time_context = "Afternoon (user typically works on coding projects)"
    elif 17 <= hour < 22:
        time_context = "Evening (user typically does deep work or research)"
    else:
        time_context = "Night (user may be coding or winding down)"

    parts.append(f"Current time context: {now.strftime('%I:%M %p, %A')} - {time_context}")

    # 4. Recent projects (simplified, no embeddings overhead)
    try:
        connection = db_manager._get_connection()
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT friendly_name, project_type
                FROM project_registry
                ORDER BY last_opened DESC NULLS LAST
                LIMIT 3
            """)
            projects = cursor.fetchall()
            if projects:
                proj_str = ", ".join(f"{p[0]} ({p[1]})" for p in projects)
                parts.append(f"Active projects: {proj_str}")
    except Exception:
        pass
    finally:
        if connection:
            db_manager._put_connection(connection)

    return "\n".join(parts)


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
                    "turn on bluetooth",
                    "turn off bluetooth",
                    "what bluetooth devices",
                    "turn on wifi",
                    "turn off wifi",
                    "what wifi am I on",
                    "connect to wifi",
                    "switch to ",
                    "snap window left",
                    "snap window right",
                    "what windows are open",
                    "screen info",
                    "toggle night shift",
                    "turn on night shift",
                    "turn off night shift",
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
                ["open project", "run project", "register project", "what projects", "list projects"],
                self.handle_project_commands,
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

        # ── start the proactive process monitor thread ──
        self.start_process_monitor_thread()

        # ── start the hotkey listener thread if enabled ──
        if self.config.hotkey_enabled:
            self.start_hotkey_listener_thread()

        # ── start the corner trigger watcher thread if enabled ──
        if self.config.corner_trigger_enabled:
            self.start_corner_trigger_thread()

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

    def start_process_monitor_thread(self) -> None:
        """
        Start the background process monitor thread.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        self.process_monitor = ProcessMonitor(
            self.db_manager,
            self,
            render_health_url=self.config.render_health_url,
            git_check_interval_hours=self.config.git_check_interval_hours
        )
        self.process_monitor.start()

    def start_hotkey_listener_thread(self) -> None:
        """
        Start the background hotkey listener thread.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        self.hotkey_listener = HotkeyListener(self, combo=self.config.hotkey_combo)
        self.hotkey_listener.start()

    def start_corner_trigger_thread(self) -> None:
        """
        Start the background corner trigger watcher thread.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        self.corner_watcher = CornerTriggerWatcher(
            self,
            corner=self.config.corner_trigger_corner,
            delay_ms=self.config.corner_trigger_delay_ms
        )
        self.corner_watcher.start()

    def trigger_wake_word(self) -> None:
        """
        Trigger wake word activation from hotkey or corner trigger.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            This method does not raise exceptions.
        """
        # Simulate wake word detection
        self.process_command_thread(None)
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

        # New Phase 1 system controls
        if "turn on bluetooth" in lowered_command:
            response = toggle_bluetooth(True)
            return True, response, False

        if "turn off bluetooth" in lowered_command:
            response = toggle_bluetooth(False)
            return True, response, False

        if "what bluetooth devices" in lowered_command or "bluetooth devices" in lowered_command:
            response = list_bluetooth_devices()
            return True, response, False

        if "turn on wifi" in lowered_command:
            response = toggle_wifi(True)
            return True, response, False

        if "turn off wifi" in lowered_command:
            response = toggle_wifi(False)
            return True, response, False

        if "what wifi am i on" in lowered_command or "wifi info" in lowered_command:
            response = get_wifi_info()
            return True, response, False

        if "connect to wifi" in lowered_command:
            # This would need voice input for password - simplified for now
            return True, "Wi-Fi connection requires a password. Please connect manually in System Preferences, sir.", False

        if lowered_command.startswith("switch to "):
            app_name = lowered_command.replace("switch to ", "").strip()
            response = switch_to_app(app_name)
            return True, response, False

        if "snap window left" in lowered_command:
            response = snap_window_left()
            return True, response, False

        if "snap window right" in lowered_command:
            response = snap_window_right()
            return True, response, False

        if "what windows are open" in lowered_command or "open windows" in lowered_command:
            response = get_open_windows()
            return True, response, False

        if "screen info" in lowered_command:
            response = get_screen_info()
            return True, response, False

        if "toggle night shift" in lowered_command or "turn on night shift" in lowered_command or "turn off night shift" in lowered_command:
            state = "on" in lowered_command
            response = toggle_night_shift(state)
            return True, response, False

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
            importance = calculate_importance(memory_key, memory_value, category)
            # Store with embedding for Phase 2
            try:
                engine = get_embedding_engine()
                embedding = engine.embed(memory_value) if engine else None
            except Exception:
                embedding = None
            if self.db_manager.save_memory(memory_key, memory_value, category):
                return True, f"I will remember that {fact_text}, sir.", False
            return True, "I could not store that memory, sir.", False

        # PHASE 2: Semantic memory recall
        if lowered_command.startswith("do you remember "):
            query = cleaned_command[len("do you remember ") :].strip().rstrip("?")
            # Try semantic search first
            try:
                engine = get_embedding_engine()
                if engine:
                    results = semantic_search_memory(self.db_manager, query, top_k=1, threshold=0.60)
                    if results:
                        mem = results[0]
                        return True, f"Yes, sir. I remember that {format_memory_sentence(mem)}.", False
            except Exception:
                pass
            # Fallback to literal search
            memory = self.db_manager.recall_memory(query)
            if memory:
                return True, f"Yes, sir. I remember that {format_memory_sentence(memory)}.", False
            return True, f"I do not remember anything about {query}, sir.", False

        # PHASE 2: Combined knowledge recall
        if lowered_command.startswith("what do you know about "):
            query = cleaned_command[len("what do you know about ") :].strip().rstrip("?")
            response_parts = []
            # Get memory results
            try:
                engine = get_embedding_engine()
                if engine:
                    mem_results = semantic_search_memory(self.db_manager, query, top_k=2, threshold=0.60)
                    if mem_results:
                        for mem in mem_results:
                            response_parts.append(f"I remember that {format_memory_sentence(mem)}")
                    # Get conversation context
                    conv_context = recall_conversation_context(self.db_manager, query, top_k=1)
                    if conv_context:
                        response_parts.append(conv_context)
            except Exception:
                pass
            if response_parts:
                return True, " Also, ".join(response_parts) + ", sir.", False
            return True, f"I do not know anything about {query} yet, sir.", False

        # PHASE 2: Recall by date
        if "what did we talk about" in lowered_command and ("yesterday" in lowered_command or "last" in lowered_command or "ago" in lowered_command):
            # Extract date reference
            if "yesterday" in lowered_command:
                date_str = "yesterday"
            else:
                # Try to extract relative date
                match = re.search(r"(last \w+|\d+ days? ago)", lowered_command)
                date_str = match.group(1) if match else "yesterday"
            try:
                summary = recall_session_by_date(self.db_manager, date_str)
                if summary:
                    return True, f"{summary}, sir.", False
            except Exception:
                pass
            return True, f"I do not have a record of our conversation from {date_str}, sir.", False

        # PHASE 2: Week summary
        if "summarize this week" in lowered_command:
            connection = self.db_manager._get_connection()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT summary FROM session_summaries
                        WHERE ended_at > CURRENT_TIMESTAMP - INTERVAL '7 days'
                        ORDER BY ended_at DESC
                        LIMIT 5
                    """)
                    rows = cursor.fetchall()
                    if rows:
                        summaries = [row[0] for row in rows if row[0]]
                        response = "This week's sessions: " + " ".join(summaries[:3])
                        return True, response + ", sir.", False
            except Exception:
                pass
            finally:
                self.db_manager._put_connection(connection)
            return True, "I do not have any session summaries from this week, sir.", False

        # PHASE 2: Last session
        if "what was the last thing" in lowered_command or "last thing you helped" in lowered_command:
            connection = self.db_manager._get_connection()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT summary FROM session_summaries
                        ORDER BY ended_at DESC
                        LIMIT 1
                    """)
                    row = cursor.fetchone()
                    if row and row[0]:
                        return True, f"The last thing I helped with was: {row[0]}, sir.", False
            except Exception:
                pass
            finally:
                self.db_manager._put_connection(connection)
            return True, "I do not have a record of our last session, sir.", False

        # PHASE 2: Forget memory
        if lowered_command.startswith("forget "):
            topic = cleaned_command[len("forget ") :].strip()
            if self.ask_confirmation(f"Are you sure you want me to forget about {topic}? Say yes to confirm."):
                connection = self.db_manager._get_connection()
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("DELETE FROM memory WHERE key ILIKE %s", (f"%{topic}%",))
                    connection.commit()
                    return True, f"I have forgotten about {topic}, sir.", False
                except Exception:
                    pass
                finally:
                    self.db_manager._put_connection(connection)
            return True, "Forget operation cancelled, sir.", False

        if lowered_command in {"what do you remember", "list your memories"}:
            return True, self.db_manager.recall_all_memories(), False

        if any(pattern in lowered_command for pattern in ["switch to groq", "use groq"]):
            _, response_text = self.ai_router.switch_ai("groq")
            return True, response_text, False

        if any(pattern in lowered_command for pattern in ["switch to gemini", "use gemini"]):
            _, response_text = self.ai_router.switch_ai("gemini")
            return True, response_text, False

        if any(pattern in lowered_command for pattern in ["switch to ollama", "use ollama", "use local"]):
            _, response_text = self.ai_router.switch_ai("ollama")
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

    def handle_project_commands(self, cleaned_command: str, lowered_command: str) -> Tuple[bool, str, bool]:
        """
        Handle project registry commands.

        Parameters:
            cleaned_command (str): Original command text.
            lowered_command (str): Lowercased command text.

        Returns:
            Tuple[bool, str, bool]: Standard skill result tuple.
        """
        if lowered_command.startswith("open project ") or lowered_command.startswith("open my ") or "open " in lowered_command and "project" in lowered_command:
            # Extract project name
            if "open project " in lowered_command:
                query = lowered_command.replace("open project ", "").strip()
            elif "open my " in lowered_command:
                query = lowered_command.replace("open my ", "").strip()
            else:
                # Fallback
                query = lowered_command.replace("open ", "").replace("project", "").strip()

            project = find_project(self.db_manager, query)
            if project:
                response = open_project(self.db_manager, project, self)
                return True, response, False
            else:
                return True, f"I couldn't find a project matching '{query}', sir.", False

        if "run " in lowered_command and ("dev mode" in lowered_command or "development" in lowered_command):
            # Extract project name
            query = lowered_command.replace("run ", "").replace(" in dev mode", "").replace(" in development", "").strip()
            project = find_project(self.db_manager, query)
            if project:
                response = launch_dev_server(self.db_manager, project, self)
                return True, response, False
            else:
                return True, f"I couldn't find a project matching '{query}', sir.", False

        if "register this" in lowered_command or "register project" in lowered_command:
            # Get current directory (assuming user is in the project folder)
            current_dir = os.getcwd()
            friendly_name = "Unknown Project"
            if " as " in cleaned_command:
                friendly_name = cleaned_command.split(" as ")[1].strip()

            success = register_project(self.db_manager, friendly_name, current_dir, project_type="other")
            if success:
                return True, f"Registered {friendly_name} at {current_dir}, sir.", False
            else:
                return True, "Failed to register the project, sir.", False

        if "what projects" in lowered_command or "list projects" in lowered_command:
            response = list_projects(self.db_manager)
            return True, response, False

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

        # ── generate and store session summary for Phase 2 semantic recall ──
        try:
            self._summarize_session()
        except Exception as error:
            self.logger.warning(f"Failed to summarize session: {error}")

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
        background_threads = [self.wake_thread, self.reminder_thread]
        if hasattr(self, 'process_monitor') and self.process_monitor:
            background_threads.append(self.process_monitor)
        if hasattr(self, 'hotkey_listener') and self.hotkey_listener:
            background_threads.append(self.hotkey_listener)
        if hasattr(self, 'corner_watcher') and self.corner_watcher:
            background_threads.append(self.corner_watcher)

        for background_thread in background_threads:
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

    def _summarize_session(self) -> None:
        """
        Generate and store a summary of the session for Phase 2 semantic recall.

        Parameters:
            None.

        Returns:
            None.

        Exceptions:
            Catches all exceptions to ensure cleanup continues.
        """
        try:
            # ── fetch conversation log for this session ──
            connection = self.db_manager._get_connection()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT role, content FROM conversation_log
                        WHERE session_id = %s
                        ORDER BY timestamp ASC
                        LIMIT 100
                        """,
                        (self.session_id,),
                    )
                    rows = cursor.fetchall()
                    if not rows:
                        return

                    # ── format conversation for summarization ──
                    conversation_text = "\n".join(
                        [f"{row[0].upper()}: {row[1]}" for row in rows if row[1]]
                    )
            finally:
                self.db_manager._put_connection(connection)

            # ── request summary from Ollama if available ──
            summary_text = None
            if self.ai_router.ollama and self.ai_router.ollama.available:
                try:
                    summary_prompt = (
                        f"Summarize this conversation in exactly 3 sentences. "
                        f"Focus on: what was accomplished, what was discussed, any decisions made.\n\n"
                        f"{conversation_text[:2000]}"  # Limit input to prevent token overflow
                    )
                    summary_text, _ = self.ai_router.ollama.send_message(summary_prompt)
                    if not summary_text:
                        summary_text = None
                except Exception as error:
                    self.logger.debug(f"Ollama summarization failed: {error}")
                    summary_text = None

            # ── fallback: generate simple summary if Ollama unavailable ──
            if not summary_text:
                # Simple fallback: count user turns and get time duration
                user_turn_count = sum(1 for row in rows if row[0] == "user")
                duration_mins = int((time.time() - self.started_at) / 60)
                summary_text = f"Conducted {user_turn_count} interactions over {duration_mins} minutes. Session completed successfully."

            # ── extract topics using simple keyword detection ──
            topics = self._extract_session_topics(conversation_text)

            # ── generate embedding for summary ──
            try:
                engine = get_embedding_engine()
                summary_embedding = engine.embed(summary_text) if engine else None
            except Exception:
                summary_embedding = None

            # ── store session summary in database ──
            connection = self.db_manager._get_connection()
            try:
                with connection.cursor() as cursor:
                    # Convert embedding list to PostgreSQL format
                    embedding_sql = "NULL"
                    if summary_embedding:
                        embedding_sql = f"'[{','.join(map(str, summary_embedding))}]'::vector"

                    cursor.execute(
                        f"""
                        INSERT INTO session_summaries
                        (session_id, summary, topics, embedding, message_count, started_at, ended_at)
                        VALUES (%s, %s, %s, {embedding_sql}, %s, %s, NOW())
                        """,
                        (
                            self.session_id,
                            summary_text,
                            ",".join(topics[:5]),  # Top 5 topics
                            len(rows),
                            datetime.datetime.fromtimestamp(self.started_at),
                        ),
                    )
                connection.commit()
                self.logger.info(f"Session {self.session_id} summarized: {len(summary_text)} chars, {len(topics)} topics")
            finally:
                self.db_manager._put_connection(connection)

        except Exception as error:
            self.logger.warning(f"Session summarization error: {error}")

    def _extract_session_topics(self, conversation_text: str) -> list:
        """
        Extract topics from conversation text using simple keyword detection.

        Parameters:
            conversation_text (str): Full conversation text.

        Returns:
            list: List of extracted topic strings.
        """
        topics = []
        try:
            # Simple keyword detection - look for capital words and common topics
            words = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", conversation_text)
            topic_freq = {}
            for word in words:
                if len(word) > 3:  # Only longer words
                    topic_freq[word] = topic_freq.get(word, 0) + 1

            # Sort by frequency and take top topics
            topics = sorted(topic_freq.items(), key=lambda x: x[1], reverse=True)
            topics = [topic[0] for topic in topics[:10]]  # Top 10 topics
        except Exception:
            pass
        return topics if topics else ["general"]

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
