export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

let whenSessionEnds = () => {};

/** Called when a request finds the session is over, such as after 30 days away. */
export function onSessionEnded(handler) {
  whenSessionEnds = handler;
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
    // A POST's 401 is usually a sign-in attempt that failed, which its own screen explains.
    if (response.status === 401 && options.method !== 'POST') whenSessionEnds();
    throw new ApiError(response.status, detail || `Something went wrong (${response.status}).`);
  }
  return response.json();
}

const jsonBody = (method, body) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body ?? {}),
});

export const get = (path) => request(path);
export const put = (path, body) => request(path, jsonBody('PUT', body));
export const post = (path, body) => request(path, jsonBody('POST', body));
export const del = (path) => request(path, { method: 'DELETE' });
