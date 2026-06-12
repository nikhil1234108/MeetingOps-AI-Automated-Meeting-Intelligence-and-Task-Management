import os
import json
import logging
import hashlib
import asyncpg
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("WorkflowAutomation")

# Read PostgreSQL connection parameters from environment variables
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres123")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "Origin_Medical")

# Global PostgreSQL connection pool
_pool: Optional[asyncpg.Pool] = None

class Database:
    """
    Handles asynchronous PostgreSQL database operations for run caching,
    Jira ticket association, audit trails, and long-term memory summaries.
    """

    @staticmethod
    async def initialize() -> None:
        """Initializes PostgreSQL connection pool and creates tables if they do not exist."""
        global _pool
        if _pool is None or _pool._closed or (_pool._loop and _pool._loop.is_closed()):
            logger.info(f"Connecting to PostgreSQL database '{POSTGRES_DB}' on {POSTGRES_HOST}:{POSTGRES_PORT} as user '{POSTGRES_USER}'...")
            _pool = await asyncpg.create_pool(
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                database=POSTGRES_DB
            )
            
        async with _pool.acquire() as conn:
            # Table to store single AI operations and fingerprints
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    uuid TEXT PRIMARY KEY,
                    fingerprint TEXT UNIQUE,
                    timestamp TEXT NOT NULL,
                    title TEXT NOT NULL,
                    date TEXT,
                    summary TEXT NOT NULL,
                    decisions_json TEXT NOT NULL,
                    action_items_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_hash TEXT NOT NULL
                )
            """)
            
            # Ensure the date column exists (handles upgrades of pre-existing tables if any)
            try:
                await conn.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS date TEXT")
            except Exception as e:
                logger.debug(f"ALTER TABLE runs date column check: {e}")
            
            # Table to store created Jira tickets
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS jira_tickets (
                    id SERIAL PRIMARY KEY,
                    run_uuid TEXT,
                    ticket_key TEXT NOT NULL,
                    ticket_url TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    issue_type TEXT NOT NULL,
                    FOREIGN KEY(run_uuid) REFERENCES runs(uuid)
                )
            """)
            
            # Table for long-term historical memory summaries
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS long_term_memory (
                    id SERIAL PRIMARY KEY,
                    project_key TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    summary TEXT NOT NULL
                )
            """)
            
            logger.info("PostgreSQL Database initialized successfully.")

    @staticmethod
    async def get_pool() -> asyncpg.Pool:
        """Retrieves or initializes the global connection pool."""
        global _pool
        if _pool is None or _pool._closed or (_pool._loop and _pool._loop.is_closed()):
            await Database.initialize()
        return _pool

    @staticmethod
    async def close() -> None:
        """Gracefully closes the global PostgreSQL connection pool."""
        global _pool
        if _pool is not None:
            try:
                if not _pool._closed and _pool._loop and not _pool._loop.is_closed():
                    await _pool.close()
            except Exception as e:
                logger.warning(f"Error closing PostgreSQL pool: {e}")
            finally:
                _pool = None
                logger.info("PostgreSQL database pool closed.")

    @staticmethod
    async def get_cached_run(fingerprint: str) -> Optional[Dict[str, Any]]:
        """Queries the runs table for a matching SHA-256 fingerprint."""
        pool = await Database.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM runs WHERE fingerprint = $1", fingerprint)
            if row:
                logger.info(f"Cache hit in database for fingerprint: {fingerprint[:10]}...")
                return {
                    "uuid": row["uuid"],
                    "fingerprint": row["fingerprint"],
                    "timestamp": row["timestamp"],
                    "title": row["title"],
                    "date": row["date"] if row["date"] else "UNKNOWN",
                    "summary": row["summary"],
                    "decisions": json.loads(row["decisions_json"]),
                    "action_items": json.loads(row["action_items_json"]),
                    "status": row["status"]
                }
        return None

    @staticmethod
    async def get_run_by_uuid(uuid: str) -> Optional[Dict[str, Any]]:
        """Retrieves execution state using its unique UUID."""
        pool = await Database.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM runs WHERE uuid = $1", uuid)
            if row:
                return {
                    "uuid": row["uuid"],
                    "fingerprint": row["fingerprint"],
                    "timestamp": row["timestamp"],
                    "title": row["title"],
                    "date": row["date"] if row["date"] else "UNKNOWN",
                    "summary": row["summary"],
                    "decisions": json.loads(row["decisions_json"]),
                    "action_items": json.loads(row["action_items_json"]),
                    "status": row["status"]
                }
        return None

    @staticmethod
    async def save_run(uuid_val: str, fingerprint: str, title: str, summary: str, 
                       decisions: List[str], action_items: List[Dict[str, Any]], 
                       status: str = "PENDING_REVIEW", date: str = "UNKNOWN") -> None:
        """Stores a run in the database to enable subsequent cache lookups."""
        decisions_json = json.dumps(decisions)
        action_items_json = json.dumps(action_items)
        timestamp = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
        
        # Calculate text hash to track payload updates
        payload_hash = hashlib.sha256(f"{title}||{summary}".encode('utf-8')).hexdigest()

        pool = await Database.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO runs 
                (uuid, fingerprint, timestamp, title, date, summary, decisions_json, action_items_json, status, payload_hash)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (uuid) DO UPDATE SET
                    fingerprint = EXCLUDED.fingerprint,
                    timestamp = EXCLUDED.timestamp,
                    title = EXCLUDED.title,
                    date = EXCLUDED.date,
                    summary = EXCLUDED.summary,
                    decisions_json = EXCLUDED.decisions_json,
                    action_items_json = EXCLUDED.action_items_json,
                    status = EXCLUDED.status,
                    payload_hash = EXCLUDED.payload_hash
            """, uuid_val, fingerprint, timestamp, title, date, summary, decisions_json, action_items_json, status, payload_hash)
            logger.info(f"Saved run {uuid_val} in database. Status: {status}")

    @staticmethod
    async def update_run_status(uuid_val: str, status: str) -> None:
        """Updates status of a run (e.g. from PENDING_REVIEW to COMPLETED)."""
        pool = await Database.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE runs SET status = $1 WHERE uuid = $2", status, uuid_val)
            logger.info(f"Updated status for run {uuid_val} to: {status}")

    @staticmethod
    async def save_jira_ticket(run_uuid: str, ticket_key: str, ticket_url: str, 
                               summary: str, issue_type: str) -> None:
        """Registers a successfully synced Jira ticket in the database."""
        pool = await Database.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO jira_tickets (run_uuid, ticket_key, ticket_url, summary, issue_type)
                VALUES ($1, $2, $3, $4, $5)
            """, run_uuid, ticket_key, ticket_url, summary, issue_type)

    @staticmethod
    async def get_jira_tickets(run_uuid: str) -> List[Dict[str, Any]]:
        """Retrieves all Jira tickets associated with a run."""
        pool = await Database.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM jira_tickets WHERE run_uuid = $1", run_uuid)
            return [
                {
                    "key": row["ticket_key"],
                    "url": row["ticket_url"],
                    "summary": row["summary"],
                    "issue_type": row["issue_type"],
                    "success": True
                }
                for row in rows
            ]

    @staticmethod
    async def save_long_term_memory(project_key: str, summary: str) -> None:
        """Saves a meeting summary to long-term memory."""
        timestamp = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
        pool = await Database.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO long_term_memory (project_key, timestamp, summary)
                VALUES ($1, $2, $3)
            """, project_key, timestamp, summary)
            logger.info(f"Recorded meeting summary in long-term memory for project: {project_key}")

    @staticmethod
    async def get_long_term_memory(project_key: str, limit: int = 3) -> List[str]:
        """Retrieves the last N summaries for the project to provide historical context."""
        pool = await Database.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT summary FROM long_term_memory 
                WHERE project_key = $1 
                ORDER BY timestamp DESC LIMIT $2
            """, project_key, limit)
            # Reverse to keep chronological order
            return [row["summary"] for row in reversed(rows)]
