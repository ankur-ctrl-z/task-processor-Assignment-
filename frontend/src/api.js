const BASE_URL = "https://task-processor-assignment.onrender.com";

async function request(path, { method = "GET", body, token } = {}) {
  const headers = {
    "Content-Type": "application/json",
  };

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    throw new Error(
      data.message || `Request failed with status ${res.status}`
    );
  }

  return data;
}

export const api = {
  // =========================
  // AUTH
  // =========================

  register: (payload) =>
    request("/api/auth/register", {
      method: "POST",
      body: payload,
    }),

  login: (payload) =>
    request("/api/auth/login", {
      method: "POST",
      body: payload,
    }),

  // =========================
  // TASKS
  // =========================

  listTasks: (token, status) =>
    request(
      `/api/tasks${status ? `?status=${encodeURIComponent(status)}` : ""}`,
      {
        token,
      }
    ),

  createTask: (token, payload) =>
    request("/api/tasks", {
      method: "POST",
      body: payload,
      token,
    }),

  runTask: (token, id) =>
    request(`/api/tasks/${id}/run`, {
      method: "POST",
      token,
    }),

  getTask: (token, id) =>
    request(`/api/tasks/${id}`, {
      method: "GET",
      token,
    }),
};