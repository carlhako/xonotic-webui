"""Server settings: the panel's own store, the config it generates, and the cvar catalogue.

* :mod:`~xonotic_webui.serversettings.serialize` — validating names and values and writing
  them so the console takes them literally (design D4).
* :mod:`~xonotic_webui.serversettings.registry` — the static registries: curated settings,
  gametypes and the cvars the panel reserves (D1-D3, D7).
* :mod:`~xonotic_webui.serversettings.store` — ``settings.json`` and the generated config.
* :mod:`~xonotic_webui.serversettings.servercfg` — the best-effort ``server.cfg`` scan (D11).
* :mod:`~xonotic_webui.serversettings.catalogue` — the bundled cvar catalogue (D5).
* :mod:`~xonotic_webui.serversettings.service` — saving, applying live and live values.

Nothing here is imported by the package root, so the supervisor can use the registry
without pulling in the console or the supervisor itself.
"""
