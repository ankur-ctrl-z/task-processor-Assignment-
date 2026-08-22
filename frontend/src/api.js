const BASE_URL = "https://task-processor-assignment.onrender.com"

async function request(path, { method = 'GET', body, token } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.message || `Request failed with status ${res.status}`);
  }
  return data;
}

export const api = {
  register: (payload) => request('/auth/register', { method: 'POST', body: payload }),
  login: (payload) => request('/auth/login', { method: 'POST', body: payload }),
  listTasks: (token, status) =>
    request(`/tasks${status ? `?status=${status}` : ''}`, { token }),
  createTask: (token, payload) => request('/tasks', { method: 'POST', body: payload, token }),
  runTask: (token, id) => request(`/tasks/${id}/run`, { method: 'POST', token }),
  getTask: (token, id) => request(`/tasks/${id}`, { token }),
};
