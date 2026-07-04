import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../api.js';
import { useAuth } from '../context/AuthContext.jsx';

const OPERATIONS = [
  { value: 'UPPERCASE', label: 'Uppercase' },
  { value: 'LOWERCASE', label: 'Lowercase' },
  { value: 'REVERSE_STRING', label: 'Reverse String' },
  { value: 'WORD_COUNT', label: 'Word Count' },
];

const STATUS_COLORS = {
  PENDING: '#999',
  RUNNING: '#0077cc',
  SUCCESS: '#2e9e44',
  FAILED: '#c0392b',
};

export default function Dashboard() {
  const { token, user, logout } = useAuth();
  const [tasks, setTasks] = useState([]);
  const [title, setTitle] = useState('');
  const [inputText, setInputText] = useState('');
  const [operation, setOperation] = useState(OPERATIONS[0].value);
  const [error, setError] = useState('');

  const loadTasks = useCallback(async () => {
    try {
      const data = await api.listTasks(token);
      setTasks(data);
    } catch (err) {
      setError(err.message);
    }
  }, [token]);

  useEffect(() => {
    loadTasks();
    // Poll every 3s so PENDING/RUNNING tasks update once the worker finishes.
    const interval = setInterval(loadTasks, 3000);
    return () => clearInterval(interval);
  }, [loadTasks]);

  async function handleCreate(e) {
    e.preventDefault();
    setError('');
    try {
      await api.createTask(token, { title, inputText, operation });
      setTitle('');
      setInputText('');
      loadTasks();
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleRun(id) {
    try {
      await api.runTask(token, id);
      loadTasks();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="dashboard">
      <header>
        <h1>AI Task Processing Platform</h1>
        <div>
          <span>{user?.name}</span>
          <button onClick={logout}>Log out</button>
        </div>
      </header>

      {error && <p className="error">{error}</p>}

      <form onSubmit={handleCreate} className="task-form">
        <input placeholder="Task title" value={title} onChange={(e) => setTitle(e.target.value)} required />
        <textarea placeholder="Input text" value={inputText} onChange={(e) => setInputText(e.target.value)} required />
        <select value={operation} onChange={(e) => setOperation(e.target.value)}>
          {OPERATIONS.map((op) => (
            <option key={op.value} value={op.value}>{op.label}</option>
          ))}
        </select>
        <button type="submit">Create Task</button>
      </form>

      <table className="task-table">
        <thead>
          <tr>
            <th>Title</th>
            <th>Operation</th>
            <th>Status</th>
            <th>Result</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task._id}>
              <td>{task.title}</td>
              <td>{task.operation}</td>
              <td style={{ color: STATUS_COLORS[task.status] }}>{task.status}</td>
              <td>{task.result ?? '—'}</td>
              <td>
                <button
                  onClick={() => handleRun(task._id)}
                  disabled={task.status === 'RUNNING'}
                >
                  Run Task
                </button>
              </td>
            </tr>
          ))}
          {tasks.length === 0 && (
            <tr><td colSpan={5}>No tasks yet. Create one above.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
