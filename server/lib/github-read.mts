// One bounded retry for transient GitHub metadata failures. Never replay a POST
// that could have already queued a collector. The caller's shared deadline holds.
export async function fetchGitHub(url: string, options: RequestInit, fetcher: typeof fetch = fetch) {
  let response = await fetcher(url, options);
  if (options.method === 'GET' && [502, 503, 504].includes(response.status) && !options.signal?.aborted) {
    await response.body?.cancel();
    await new Promise(resolve => setTimeout(resolve, 250));
    if (!options.signal?.aborted) response = await fetcher(url, options);
  }
  return response;
}
