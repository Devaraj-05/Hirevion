// A stand-in for Caddy in the sign-in suite: one origin, with /api/* going to the API and
// everything else to the web app, so the session cookie is same-origin as in production.
import http from "node:http";

const port = Number(process.env.HV_GATEWAY_PORT ?? 3100);
const web = { host: "127.0.0.1", port: Number(process.env.HV_WEB_PORT ?? 3101) };
const apiUrl = new URL(process.env.HV_API_INTERNAL_URL ?? "http://127.0.0.1:8000");
const api = { host: apiUrl.hostname, port: Number(apiUrl.port || 80) };

http
  .createServer((request, response) => {
    const target = request.url?.startsWith("/api/") ? api : web;
    const upstream = http.request(
      { ...target, method: request.method, path: request.url, headers: request.headers },
      (reply) => {
        response.writeHead(reply.statusCode ?? 502, reply.headers);
        reply.pipe(response);
      },
    );
    upstream.on("error", () => {
      response.writeHead(502);
      response.end();
    });
    request.pipe(upstream);
  })
  .listen(port, "127.0.0.1");
