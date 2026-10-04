"""The local product (``make product``, ADR-013's two processes on the dev stack) and the tool
that fills and checks it, ``cw-product``.

``make product`` runs ``cw-mvp serve`` and ``cw-mvp worker`` with Kafka and Temporal on and the
notification sink in place of the real channels. ``cw-product seed`` then creates two synthetic
tenants (``tenants``), publishes the seed rules the golden world cites as synthetic analysts
(``analysts``, ``publish``) and asks the engine for their decisions (``evaluate``); the worker
carries each decision to obligations and a change card. ``cw-product check`` proves that chain,
one named step after another (``check``).

Honest by construction: the tool refuses to run unless ``CW_ENV`` is local or test and
``CW_AUTH_MODE`` header or dual; only the four seed rules the golden world cites from recorded
quotes can be published, every published version still reads needs_review, and every name it
writes says it is synthetic.
"""
