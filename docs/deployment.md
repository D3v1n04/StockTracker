# Neon and Render Deployment

StockTracker uses PostgreSQL in production. Render starts only the FastAPI web
process; database migrations are a separate release operation and must finish
before the corresponding application version is deployed.

## First-deployment checklist

1. Create a Neon project and database.
2. In Neon's **Connect** dialog, copy both connection strings:
   - the direct connection string for Alembic;
   - the pooled (`-pooler`) connection string for the running web service.
3. From a trusted machine or CI release job with the production dependencies
   installed, provision the schema with the direct connection string:

   ```bash
   DATABASE_URL="<Neon direct connection string>" APP_ENV=production alembic upgrade head
   ```

   Supply the value through a secret manager or temporary environment variable.
   Never save either connection string in this repository or a committed `.env`
   file.
4. Create a Render Blueprint from this repository's `render.yaml`.
5. When Render prompts for `DATABASE_URL`, securely provide the pooled Neon
   connection string. `APP_ENV=production` is already declared by the Blueprint.
6. Deploy the web service. Do not add Alembic to the build or Uvicorn start
   command.
7. Verify `/health`, `/ready`, the dashboard and its CSS/JavaScript assets, and
   a JSON API route. The included checker performs these requests:

   ```bash
   python scripts/deployment_smoke.py https://<your-render-service-hostname>
   ```

8. Review the Render logs for configuration errors, database timeouts, and
   query failures.

`/health` reports whether the API process is running and deliberately does not
connect to the database. `/ready` runs a lightweight database query and returns
HTTP 503 when the configured database cannot be reached.

## Future migrations and rollbacks

For every release containing a new migration, run `alembic upgrade head` once
with the Neon direct connection string before deploying the application version
that requires that schema. Free Render web services do not provide a pre-deploy
command, so the web process must not be responsible for applying migrations.

Plan schema changes to be backward compatible while old and new application
instances may overlap. Rolling back application code is safe only when the
database schema remains compatible with the older version. A code rollback may
therefore require a separately planned data/schema migration; do not blindly
downgrade a production database.

## Storage and connection notes

Render web-service filesystems are ephemeral. Files created at runtime can be
lost during deploys, restarts, or service replacement, so production must not
use the local SQLite database or rely on a persistent Render disk.

Neon's pooled endpoint uses PgBouncer transaction pooling and is appropriate for
the application's short SQLAlchemy transactions. Use the direct endpoint for
Alembic and other session-dependent administration. Preserve Neon's supplied
TLS query parameters (such as `sslmode=require`) when copying either URL.

## Provider references

- [Render Blueprint specification](https://render.com/docs/blueprint-spec)
- [Render Python version configuration](https://render.com/docs/python-version)
- [Render free service limitations](https://render.com/docs/free)
- [Neon connection pooling and migration guidance](https://neon.com/docs/connect/connection-pooling)
