"""
Background worker: blocks on a Redis list (BRPOP), pulls task IDs pushed by
the Node backend, loads the task from MongoDB, runs the requested text
operation, and writes status/result/logs back to MongoDB.

Multiple replicas of this process can run concurrently (see k8s HPA) because
BRPOP is atomic across consumers — no two workers will get the same task id.
"""

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [worker] %(levelname)s %(message)s",
)
log = logging.getLogger("worker")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
TASK_QUEUE_KEY = os.environ.get("TASK_QUEUE_KEY", "ai_task_queue")
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/ai_task_platform")
BRPOP_TIMEOUT_SECONDS = int(os.environ.get("BRPOP_TIMEOUT_SECONDS", "5"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))

running = True


def handle_shutdown(signum, frame):
    global running
    log.info("Shutdown signal received (%s), finishing current task then exiting", signum)
    running = False


signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT, handle_shutdown)


def connect_redis():
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = redis.from_url(REDIS_URL, decode_responses=True)
            client.ping()
            log.info("Connected to Redis")
            return client
        except redis.exceptions.RedisError as exc:
            log.warning("Redis connection attempt %s/%s failed: %s", attempt, MAX_RETRIES, exc)
            time.sleep(2 ** attempt)
    log.error("Could not connect to Redis after %s attempts, exiting", MAX_RETRIES)
    sys.exit(1)


def connect_mongo():
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            client.admin.command("ping")
            log.info("Connected to MongoDB")
            return client
        except Exception as exc:  # noqa: BLE001
            log.warning("Mongo connection attempt %s/%s failed: %s", attempt, MAX_RETRIES, exc)
            time.sleep(2 ** attempt)
    log.error("Could not connect to MongoDB after %s attempts, exiting", MAX_RETRIES)
    sys.exit(1)


def push_log(tasks_col, task_id, message):
    tasks_col.update_one(
        {"_id": task_id},
        {"$push": {"logs": {"message": message, "timestamp": datetime.now(timezone.utc)}}},
    )


def process_task(tasks_col, task_id_str):
    try:
        task_id = ObjectId(task_id_str)
    except Exception:  # noqa: BLE001
        log.error("Invalid task id on queue: %s", task_id_str)
        return

    task = tasks_col.find_one({"_id": task_id})
    if not task:
        log.warning("Task %s not found in DB (may have been deleted)", task_id_str)
        return

    log.info("Picked up task %s (operation=%s)", task_id_str, task.get("operation"))

    tasks_col.update_one(
        {"_id": task_id},
        {"$set": {"status": "RUNNING", "startedAt": datetime.now(timezone.utc)}},
    )
    push_log(tasks_col, task_id, "Worker started processing task")

    try:
        result = run_operation(task["operation"], task["inputText"])
        tasks_col.update_one(
            {"_id": task_id},
            {
                "$set": {
                    "status": "SUCCESS",
                    "result": result,
                    "completedAt": datetime.now(timezone.utc),
                }
            },
        )
        push_log(tasks_col, task_id, "Task completed successfully")
        log.info("Task %s completed successfully", task_id_str)
    except Exception as exc:  # noqa: BLE001
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
        push_log(tasks_col, task_id, f"Task failed: {exc}")
        log.error("Task %s failed: %s", task_id_str, exc)


def main():
    redis_client = connect_redis()
    mongo_client = connect_mongo()
    db = mongo_client.get_default_database()
    tasks_col = db["tasks"]

    log.info("Worker started, listening on queue '%s'", TASK_QUEUE_KEY)

    while running:
        try:
            item = redis_client.brpop(TASK_QUEUE_KEY, timeout=BRPOP_TIMEOUT_SECONDS)
        except redis.exceptions.RedisError as exc:
            # Redis unreachable mid-run: back off and retry rather than crash.
            # See docs/architecture.md "Redis failure handling" for the full strategy.
            log.error("Redis error during BRPOP: %s. Retrying in 3s", exc)
            time.sleep(3)
            continue

        if item is None:
            continue  # timeout, loop again (lets us check `running` for graceful shutdown)

        _, task_id_str = item
        process_task(tasks_col, task_id_str)

    log.info("Worker exiting cleanly")


if __name__ == "__main__":
    main()
