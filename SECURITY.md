# Security and privacy notes

- Run the MCP server only for trusted local AI clients.
- Treat `matlab_execute` as a code-execution boundary: it is designed to execute MATLAB work inside a caller-supplied project directory.
- Do not expose the MCP stdio process through an unauthenticated network bridge.
- Do not commit `.env` files, tokens, account configuration, MATLAB license files, local databases, logs, or runtime caches.
- Review generated MATLAB scripts before using them with real hardware or production data.
