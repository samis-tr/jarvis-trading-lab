"""Ordered, append-only schema migrations. Never edit an applied migration; add a new one.

Each migration is a list of single SQL statements (no fragile SQL splitting).
"""

MIGRATIONS: list[tuple[int, list[str]]] = [
    (
        1,
        [
            """CREATE TABLE events (
            seq INTEGER PRIMARY KEY,
            ts TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            prev_hash TEXT NOT NULL,
            hash TEXT NOT NULL UNIQUE
        )""",
            """CREATE TRIGGER events_no_update BEFORE UPDATE ON events
            BEGIN SELECT RAISE(ABORT, 'journal is immutable'); END""",
            """CREATE TRIGGER events_no_delete BEFORE DELETE ON events
            BEGIN SELECT RAISE(ABORT, 'journal is immutable'); END""",
            "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            "CREATE TABLE account (id INTEGER PRIMARY KEY CHECK (id = 1), cash TEXT NOT NULL)",
            """CREATE TABLE positions (
            symbol TEXT PRIMARY KEY, qty TEXT NOT NULL, avg_cost TEXT NOT NULL, stop_price TEXT
        )""",
            """CREATE TABLE orders (
            client_order_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL CHECK (side IN ('buy','sell')),
            qty TEXT NOT NULL,
            status TEXT NOT NULL,
            created_session TEXT NOT NULL,
            protective INTEGER NOT NULL DEFAULT 0,
            intent TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT ''
        )""",
            "CREATE UNIQUE INDEX one_pending_order_per_symbol ON orders(symbol) WHERE status = 'pending'",
            """CREATE TABLE fills (
            client_order_id TEXT PRIMARY KEY REFERENCES orders(client_order_id),
            symbol TEXT NOT NULL, side TEXT NOT NULL, qty TEXT NOT NULL, price TEXT NOT NULL,
            reference_price TEXT NOT NULL, fees TEXT NOT NULL, session TEXT NOT NULL,
            ts TEXT NOT NULL, kind TEXT NOT NULL
        )""",
            """CREATE TABLE breakers (
            name TEXT PRIMARY KEY,
            latched INTEGER NOT NULL,
            reason TEXT NOT NULL,
            tripped_session TEXT NOT NULL,
            until_session TEXT
        )""",
            """CREATE TABLE equity (
            session TEXT PRIMARY KEY, equity TEXT NOT NULL, cash TEXT NOT NULL,
            position_value TEXT NOT NULL
        )""",
        ],
    ),
]
