# Production database requirement

`ENVIRONMENT=production` requires a persistent PostgreSQL database.

Set `DATABASE_URL` in Render to a PostgreSQL connection string, for example
`postgresql://user:password@host/database`. The application converts it to the
async SQLAlchemy URL automatically.

An empty `DATABASE_URL` selects local SQLite. That is allowed only for local
tests with `ALLOW_EPHEMERAL_DATABASE=true`; production startup and health checks
reject it so requests cannot silently disappear after a Render restart.

After setting the database variable, redeploy and verify that
`/api/v1/health` returns:

```json
{"status":"ok","data_persistent":true,"database_backend":"postgresql"}
```
