from dotenv import load_dotenv

load_dotenv()

import os
import sys
import time
import logging
import signal
from datetime import datetime, timezone

import redis
from pymongo import MongoClient
from bson import ObjectId

from operations import run_operation


# --------------------------------------------------
# Logging
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [worker] %(levelname)s %(message)s",
)

log = logging.getLogger("worker")


# --------------------------------------------------
# Environment Variables
# --------------------------------------------------

REDIS_URL = os.getenv("REDIS_URL")
TASK_QUEUE_KEY = os.getenv("TASK_QUEUE_KEY", "ai_task_queue")
MONGO_URI = os.getenv("MONGO_URI")

BRPOP_TIMEOUT_SECONDS = int(
    os.getenv("BRPOP_TIMEOUT_SECONDS", "5")
)

MAX_RETRIES = int(
    os.getenv("MAX_RETRIES", "3")
)


# --------------------------------------------------
# Validate Environment
# --------------------------------------------------

if not REDIS_URL:
    log.error("REDIS_URL environment variable is missing.")
    sys.exit(1)

if not MONGO_URI:
    log.error("MONGO_URI environment variable is missing.")
    sys.exit(1)


log.info(
    "Using Redis URL: %s",
    REDIS_URL.split("@")[-1],
)

log.info(
    "Using Mongo URI: %s",
    MONGO_URI.split("@")[-1],
)


# --------------------------------------------------
# Graceful Shutdown
# --------------------------------------------------

running = True


def handle_shutdown(signum, frame):
    global running

    log.info(
        "Shutdown signal received (%s), finishing current task then exiting",
        signum,
    )

    running = False


signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)


# --------------------------------------------------
# Redis Connection
# --------------------------------------------------

def connect_redis():
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=10,
                socket_timeout=10,
            )

            client.ping()

            log.info("Connected to Redis successfully")

            return client

        except Exception as exc:
            log.warning(
                "Redis connection attempt %s/%s failed: %s",
                attempt,
                MAX_RETRIES,
                exc,
            )

            time.sleep(2 ** attempt)

    log.error(
        "Could not connect to Redis after %s attempts.",
        MAX_RETRIES,
    )

    sys.exit(1)


# --------------------------------------------------
# MongoDB Connection
# --------------------------------------------------

def connect_mongo():
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = MongoClient(
                MONGO_URI,
                serverSelectionTimeoutMS=5000,
            )

            client.admin.command("ping")

            log.info("Connected to MongoDB")

            return client

        except Exception as exc:
            log.warning(
                "Mongo connection attempt %s/%s failed: %s",
                attempt,
                MAX_RETRIES,
                exc,
            )

            time.sleep(2 ** attempt)

    log.error(
        "Could not connect to MongoDB after %s attempts, exiting",
        MAX_RETRIES,
    )

    sys.exit(1)


# --------------------------------------------------
# Add Log To Task
# --------------------------------------------------

def push_log(tasks_col, task_id, message):
    tasks_col.update_one(
        {"_id": task_id},
        {
            "$push": {
                "logs": {
                    "message": message,
                    "timestamp": datetime.now(timezone.utc),
                }
            }
        },
    )


# --------------------------------------------------
# Process Task
# --------------------------------------------------

def process_task(tasks_col, task_id_str):

    # Validate ObjectId
    try:
        task_id = ObjectId(task_id_str)

    except Exception:
        log.error(
            "Invalid task id on queue: %s",
            task_id_str,
        )

        return

    # Find task
    task = tasks_col.find_one(
        {"_id": task_id}
    )

    if not task:
        log.warning(
            "Task %s not found in DB",
            task_id_str,
        )

        return

    log.info(
        "Picked up task %s (operation=%s)",
        task_id_str,
        task.get("operation"),
    )

    # --------------------------------------------------
    # RUNNING
    # --------------------------------------------------

    tasks_col.update_one(
        {"_id": task_id},
        {
            "$set": {
                "status": "RUNNING",
                "startedAt": datetime.now(timezone.utc),
                "errorMessage": None,
            }
        },
    )

    push_log(
        tasks_col,
        task_id,
        "Worker started processing task",
    )

    log.info(
        "Task %s status changed to RUNNING",
        task_id_str,
    )

    # --------------------------------------------------
    # Execute Operation
    # --------------------------------------------------

    try:

        operation = task.get("operation")
        input_text = task.get("inputText", "")

        log.info(
            "Executing %s for task %s",
            operation,
            task_id_str,
        )

        result = run_operation(
            operation,
            input_text,
        )

        # --------------------------------------------------
        # SUCCESS
        # --------------------------------------------------

        tasks_col.update_one(
            {"_id": task_id},
            {
                "$set": {
                    "status": "SUCCESS",
                    "result": result,
                    "completedAt": datetime.now(timezone.utc),
                    "errorMessage": None,
                }
            },
        )

        push_log(
            tasks_col,
            task_id,
            "Task completed successfully",
        )

        log.info(
            "Task %s completed successfully. Result: %s",
            task_id_str,
            result,
        )

    except Exception as exc:

        # --------------------------------------------------
        # FAILED
        # --------------------------------------------------

        tasks_col.update_one(
            {"_id": task_id},
            {
                "$set": {
                    "status": "FAILED",
                    "errorMessage": str(exc),
                    "completedAt": datetime.now(timezone.utc),
                }
            },
        )

        push_log(
            tasks_col,
            task_id,
            f"Task failed: {exc}",
        )

        log.exception(
            "Task %s failed",
            task_id_str,
        )


# --------------------------------------------------
# Main Worker
# --------------------------------------------------

def main():

    log.info("Starting task worker...")

    # Connect Redis
    redis_client = connect_redis()

    # Connect MongoDB
    mongo_client = connect_mongo()

    # IMPORTANT:
    # Explicitly select the database.
    # This avoids:
    # pymongo.errors.ConfigurationError:
    # No default database name defined or provided.
    db = mongo_client["taskhandler"]

    tasks_col = db["tasks"]

    log.info(
        "Using MongoDB database: taskhandler"
    )

    log.info(
        "Worker started, listening on queue '%s'",
        TASK_QUEUE_KEY,
    )

    # --------------------------------------------------
    # Worker Loop
    # --------------------------------------------------

    while running:

        try:

            item = redis_client.brpop(
                TASK_QUEUE_KEY,
                timeout=BRPOP_TIMEOUT_SECONDS,
            )

        except redis.exceptions.RedisError as exc:

            log.error(
                "Redis error during BRPOP: %s. Retrying in 3s",
                exc,
            )

            time.sleep(3)

            continue

        # No task received
        if item is None:
            continue

        # Redis BRPOP returns:
        #
        # ("ai_task_queue", "task_id")
        #
        _, task_id_str = item

        log.info(
            "Received task from Redis: %s",
            task_id_str,
        )

        process_task(
            tasks_col,
            task_id_str,
        )

    # --------------------------------------------------
    # Shutdown
    # --------------------------------------------------

    log.info("Worker exiting cleanly")

    try:
        redis_client.close()
    except Exception:
        pass

    try:
        mongo_client.close()
    except Exception:
        pass


# --------------------------------------------------
# Entry Point
# --------------------------------------------------

if __name__ == "__main__":
    main()