const { createClient } = require('redis');

const REDIS_URL = process.env.REDIS_URL || 'redis://localhost:6379';
const TASK_QUEUE_KEY = process.env.TASK_QUEUE_KEY || 'ai_task_queue';

const redisClient = createClient({ url: REDIS_URL });

redisClient.on('error', (err) => console.error('[redis] Client error:', err.message));
redisClient.on('connect', () => console.log('[redis] Connected'));

async function connectRedis() {
  if (!redisClient.isOpen) {
    await redisClient.connect();
  }
}

// Push a task id onto the queue for the Python worker to consume.
async function pushTask(taskId) {
  await redisClient.lPush(TASK_QUEUE_KEY, taskId);
}

module.exports = { redisClient, connectRedis, pushTask, TASK_QUEUE_KEY };
