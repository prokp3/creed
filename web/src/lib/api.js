export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { Accept: 'application/json', ...(options.headers || {}) },
    });
  } catch {
    throw new ApiError(0, "Can't reach Creed. Check your connection.");
  }
  if (!response.ok) {
    let detail = '';
    try {
      detail = (await response.json()).detail;
    } catch {
      // The status code below still says what happened.
    }
    throw new ApiError(response.status, detail || `Something went wrong (${response.status}).`);
  }
  return response.json();
}

export const get = (path) => request(path);

export const put = (path, body) =>
  request(path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
