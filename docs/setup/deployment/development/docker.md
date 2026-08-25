# Docker

Requires the most recent version of [Docker](https://www.docker.com/get-started) and Python's [Fabric](https://www.fabfile.org/)/[Invoke](https://www.pyinvoke.org/) (`pip install fabric`), used to drive the `fab` commands below.

!!! info
    This page describes the docker setup for this fork (`torchbox/wtsh-hypha`), which differs from upstream Hypha's own docker docs — it uses the root `docker-compose.yml` and the tasks in `fabfile.py`, not a separate `docker/compose.yaml`.

## Domains for local development

You will need a domain to run this app.

Add this to your `/etc/hosts` file.

```text
127.0.0.1 hypha.test
```

The "[test](https://en.wikipedia.org/wiki/.test)" TLD is safe to use, it's reserved for testing purposes.

!!! info
    All examples from now on will use the `hypha.test` domain.

## Get the code

```shell
git clone git@github.com:torchbox/wtsh-hypha.git

cd wtsh-hypha
```

There's no need to create a `media/` directory manually — Django creates it automatically on startup (`hypha/settings/base.py:662`).

### Local settings overrides

Copy the example local settings file (this is gitignored, so it's yours to customise and won't be committed):

```shell
mv hypha/settings/local.py.example hypha/settings/local.py
```

Then add these two settings to it — without them, logging in fails with `Forbidden (403) CSRF verification failed`, because Django doesn't trust `hypha.test:8000` as a POST origin by default (the same issue is documented for the Vagrant setup in `ansible/README.md`, under "Fixing CSRF errors on the admin login"):

```python
WAGTAILADMIN_BASE_URL = 'http://hypha.test:8000'
CSRF_TRUSTED_ORIGINS = ['http://hypha.test:8000']
```

## Docker

### Build the docker images

Run this first, and again any time `Dockerfile` or the Python/Node dependencies change:

```shell
fab build
```

This pulls up-to-date base images, removes any existing `web` container and its `node_modules` volume (so Node dependencies get reinitialised from the image), then builds the images.

### Start the docker environment

```shell
fab start
```

This runs `docker compose up --detach` — the containers start in the background rather than attaching to your terminal. The `web` container itself doesn't run a server by default; its `dev` build stage just idles (`Dockerfile:248`) so you can exec into it and run things interactively.

### Set up the database (first run only)

On a fresh database, apply migrations and create the DB-backed cache table (used by `CACHES["default"]` and `CACHES["django_file_form"]`, see `hypha/settings/base.py:338-352`) — `migrate` does not create this table, it needs Django's separate `createcachetable` command:

```shell
docker compose exec web ./manage.py migrate
docker compose exec web ./manage.py createcachetable
docker compose exec web ./manage.py sync_roles
```

Skipping `createcachetable` results in `django.db.utils.ProgrammingError: relation "database_cache" does not exist` the first time something reads or writes the cache. In production this step is handled automatically as part of every deploy (`ansible/roles/hypha/templates/deploy.sh.jinja2:42`) — there's currently no local equivalent, so it has to be run manually once per fresh database.

### Run the app

Get a shell in the `web` container:

```shell
fab sh
```

Then, inside that shell, start the actual dev processes:

```shell
make serve
```

This runs `runserver_plus`, the frontend watchers (`npm run watch:*`), and `mkdocs serve` together via `tandem` (`Makefile:26-31`).

### Access the docker environment

- The Wagtail/Django site: [http://hypha.test:8000/](http://hypha.test:8000/)
- These docs, served live: [http://localhost:8001/](http://localhost:8001/)

(`docker-compose.yml` maps host port `8000` to the app's internal port `9001`, and host port `8001` to the docs' internal port `8001`.)

### Stop the docker environment

Press `ctrl+c` in the `make serve` terminal to stop the dev processes, then `exit` the shell. To stop the containers themselves:

```shell
fab stop
```

### Run commands in the docker environment

To get a bash shell on the container that runs the Django app:

```shell
fab sh
```

or, targeting a different service (e.g. the database):

```shell
fab sh --service=db
```

Once in the `web` container, issue Django commands as normal:

```shell
./manage.py migrate
```

You can also run one-off commands directly from the host without an interactive shell:

```shell
docker compose exec web ./manage.py migrate
```

To get a shell on the container that runs Postgres:

```shell
fab sh --service=db
```

## Restore a database dump

`fabfile.py` has a dedicated task for this — it drops and recreates the local database, restores the dump, and (optionally) rewrites the default site's hostname so local links don't point at a staging/live site:

```shell
fab import-data path/to/dump.file
```

Pass an empty hostname to skip that last step:

```shell
fab import-data path/to/dump.file --new-default-site-hostname=""
```

After restoring, run migrations and sync roles as usual (see [Run commands in the docker environment](#run-commands-in-the-docker-environment) above):

```shell
docker compose exec web ./manage.py migrate
docker compose exec web ./manage.py sync_roles
```

Note that any superuser accounts you'd previously created locally will have been wiped and will need to be recreated.
