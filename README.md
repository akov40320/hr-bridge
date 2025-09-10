# hr-bridge

[![CI](https://github.com/OWNER/hr-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/hr-bridge/actions/workflows/ci.yml)

Project description.

## Configuration

The application requires the `ADMIN_TOKEN` environment variable to be set.
This token protects administrative endpoints and must be provided in the
environment or in a `.env` file before running the service.

## Services

- `worker` – processes asynchronous tasks from RabbitMQ.
- `scheduler` – periodically refreshes integration tokens, cleans dedup tables and requeues overdue tasks.
