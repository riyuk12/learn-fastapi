"""Temporary in-memory 'database'.

A module-level global dict keyed by manga id (as a string), so:
  - fetch one by id  -> MANGA_DB.get(str(manga_id))      (O(1) lookup)
  - list / filter    -> iterate MANGA_DB.values()

This will be replaced by PostgreSQL + SQLAlchemy in a later chapter.
status is stored as the plain string value (matches MangaStatus enum values),
and created_at as an ISO-8601 string (Pydantic will coerce it to datetime later).
"""

MANGA_DB: dict[str, dict] = {
    "11111111-1111-1111-1111-111111111111": {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "One Piece",
        "description": "A boy sets sail to become King of the Pirates.",
        "status": "ongoing",
        "genres": ["action", "adventure", "fantasy"],
        "created_at": "2024-01-05T10:00:00Z",
    },
    "22222222-2222-2222-2222-222222222222": {
        "id": "22222222-2222-2222-2222-222222222222",
        "title": "Naruto",
        "description": "A young ninja seeks recognition and dreams of becoming Hokage.",
        "status": "completed",
        "genres": ["action", "adventure"],
        "created_at": "2024-01-06T10:00:00Z",
    },
    "33333333-3333-3333-3333-333333333333": {
        "id": "33333333-3333-3333-3333-333333333333",
        "title": "Berserk",
        "description": "A lone mercenary's brutal struggle against fate.",
        "status": "hiatus",
        "genres": ["action", "dark fantasy", "seinen"],
        "created_at": "2024-01-07T10:00:00Z",
    },
    "44444444-4444-4444-4444-444444444444": {
        "id": "44444444-4444-4444-4444-444444444444",
        "title": "Death Note",
        "description": "A student finds a notebook that kills anyone whose name is written in it.",
        "status": "completed",
        "genres": ["thriller", "mystery", "supernatural"],
        "created_at": "2024-01-08T10:00:00Z",
    },
    "55555555-5555-5555-5555-555555555555": {
        "id": "55555555-5555-5555-5555-555555555555",
        "title": "Attack on Titan",
        "description": "Humanity fights for survival against man-eating giants.",
        "status": "completed",
        "genres": ["action", "drama", "fantasy"],
        "created_at": "2024-01-09T10:00:00Z",
    },
    "66666666-6666-6666-6666-666666666666": {
        "id": "66666666-6666-6666-6666-666666666666",
        "title": "Vinland Saga",
        "description": "A young Viking seeks revenge and, later, peace.",
        "status": "ongoing",
        "genres": ["action", "adventure", "historical"],
        "created_at": "2024-01-10T10:00:00Z",
    },
    "77777777-7777-7777-7777-777777777777": {
        "id": "77777777-7777-7777-7777-777777777777",
        "title": "Vagabond",
        "description": "A fictionalized account of swordsman Miyamoto Musashi.",
        "status": "hiatus",
        "genres": ["action", "historical", "seinen"],
        "created_at": "2024-01-11T10:00:00Z",
    },
    "88888888-8888-8888-8888-888888888888": {
        "id": "88888888-8888-8888-8888-888888888888",
        "title": "Chainsaw Man",
        "description": "A devil hunter merges with his chainsaw devil dog.",
        "status": "ongoing",
        "genres": ["action", "horror", "supernatural"],
        "created_at": "2024-01-12T10:00:00Z",
    },
    "99999999-9999-9999-9999-999999999999": {
        "id": "99999999-9999-9999-9999-999999999999",
        "title": "Fullmetal Alchemist",
        "description": "Two brothers use alchemy to try to restore their bodies.",
        "status": "completed",
        "genres": ["action", "adventure", "fantasy"],
        "created_at": "2024-01-13T10:00:00Z",
    },
    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa": {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "title": "Hunter x Hunter",
        "description": "A boy searches the world for his absent father.",
        "status": "hiatus",
        "genres": ["action", "adventure"],
        "created_at": "2024-01-14T10:00:00Z",
    },
}
