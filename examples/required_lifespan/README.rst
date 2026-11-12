Required lifespan verification
==============================

These assets demonstrate the ``lifespan = "required"`` mode.

* ``failing_app.py`` raises while loading its revocation list during
  lifespan startup. Its HTTP handler increments ``request_count`` for every
  request it processes.
* ``working_app.py`` participates in the lifespan protocol correctly,
  sending ``lifespan.startup.complete`` and ``lifespan.shutdown.complete``.
* ``verify.py`` starts Hypercorn as a subprocess for both apps and asserts
  that the failing app makes the worker exit non-zero without ever opening
  the serving socket, while the working app starts, serves one request and
  shuts down cleanly.

Run from the repository root with the project environment active::

    python examples/required_lifespan/verify.py          # asyncio worker
    python examples/required_lifespan/verify.py trio     # trio worker

Equivalent manual checks::

    # Failing app: process exits non-zero, "Running on ..." is never logged
    hypercorn --lifespan required --bind 127.0.0.1:8000 \
        examples/required_lifespan/failing_app.py:app

    # Working app: starts, serves requests, exits 0 on Ctrl-C / SIGTERM
    hypercorn --lifespan required --bind 127.0.0.1:8000 \
        examples/required_lifespan/working_app.py:app
