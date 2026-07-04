const express = require('express');
const Task = require('../models/Task');
const { OPERATIONS } = require('../models/Task');
const { pushTask } = require('../config/redis');
const requireAuth = require('../middleware/auth');

const router = express.Router();
router.use(requireAuth);

// Create a task (status = PENDING, not yet queued).
router.post('/', async (req, res) => {
  try {
    const { title, inputText, operation } = req.body;
    if (!title || !inputText || !operation) {
      return res.status(400).json({ message: 'title, inputText and operation are required' });
    }
    if (!OPERATIONS.includes(operation)) {
      return res.status(400).json({ message: `operation must be one of: ${OPERATIONS.join(', ')}` });
    }

    const task = await Task.create({
      user: req.userId,
      title,
      inputText,
      operation,
      status: 'PENDING',
      logs: [{ message: 'Task created' }],
    });

    return res.status(201).json(task);
  } catch (err) {
    console.error('[tasks/create]', err);
    return res.status(500).json({ message: 'Internal server error' });
  }
});

// Execute a task: push its id onto the Redis queue. The Python worker
// consumes it, flips status to RUNNING, then SUCCESS/FAILED.
router.post('/:id/run', async (req, res) => {
  try {
    const task = await Task.findOne({ _id: req.params.id, user: req.userId });
    if (!task) return res.status(404).json({ message: 'Task not found' });

    if (task.status === 'RUNNING') {
      return res.status(409).json({ message: 'Task is already running' });
    }

    task.status = 'PENDING';
    task.errorMessage = null;
    task.logs.push({ message: 'Task queued for execution' });
    await task.save();

    await pushTask(task._id.toString());

    return res.json({ message: 'Task queued', task });
  } catch (err) {
    console.error('[tasks/run]', err);
    return res.status(500).json({ message: 'Internal server error' });
  }
});

// List current user's tasks, newest first, optional status filter.
router.get('/', async (req, res) => {
  try {
    const filter = { user: req.userId };
    if (req.query.status) filter.status = req.query.status;

    const tasks = await Task.find(filter).sort({ createdAt: -1 }).limit(200);
    return res.json(tasks);
  } catch (err) {
    console.error('[tasks/list]', err);
    return res.status(500).json({ message: 'Internal server error' });
  }
});

// Get a single task: status, logs, result.
router.get('/:id', async (req, res) => {
  try {
    const task = await Task.findOne({ _id: req.params.id, user: req.userId });
    if (!task) return res.status(404).json({ message: 'Task not found' });
    return res.json(task);
  } catch (err) {
    console.error('[tasks/get]', err);
    return res.status(500).json({ message: 'Internal server error' });
  }
});

module.exports = router;
