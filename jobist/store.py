"""Archivio SQLite degli annunci, con sincronizzazione opzionale su Google Cloud Storage.

Su Cloud Run il filesystem è effimero: il file viene scaricato dal bucket all'avvio e
ricaricato alla fine. Il caricamento usa la *generation* letta al download come
precondizione, così due esecuzioni sovrapposte non si sovrascrivono a vicenda: la
seconda fallisce invece di perdere dati.
"""

import logging
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS annunci (
    id          INTEGER PRIMARY KEY,
    url         TEXT NOT NULL UNIQUE,
    titolo      TEXT NOT NULL,
    fonte       TEXT NOT NULL DEFAULT '',
    sommario    TEXT NOT NULL DEFAULT '',
    trovato_il  TEXT NOT NULL,
    inviato_il  TEXT
);
CREATE INDEX IF NOT EXISTS annunci_da_inviare ON annunci (inviato_il) WHERE inviato_il IS NULL;
"""


@dataclass(frozen=True, slots=True)
class Annuncio:
    url: str
    titolo: str
    fonte: str = ""
    sommario: str = ""
    id: int | None = None


def _adesso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Archivio:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)

    def aggiungi(self, annunci: Iterable[Annuncio]) -> int:
        """Inserisce gli annunci non ancora visti (per URL). Restituisce quanti sono nuovi."""
        with self.conn:
            cur = self.conn.executemany(
                "INSERT OR IGNORE INTO annunci (url, titolo, fonte, sommario, trovato_il) "
                "VALUES (?, ?, ?, ?, ?)",
                [(a.url, a.titolo, a.fonte, a.sommario, _adesso()) for a in annunci],
            )
        return cur.rowcount

    def da_inviare(self) -> list[Annuncio]:
        rows = self.conn.execute(
            "SELECT id, url, titolo, fonte, sommario FROM annunci "
            "WHERE inviato_il IS NULL ORDER BY trovato_il, id"
        )
        return [Annuncio(**row) for row in rows]

    def segna_inviati(self, annunci: Iterable[Annuncio]) -> None:
        with self.conn:
            self.conn.executemany(
                "UPDATE annunci SET inviato_il = ? WHERE id = ?",
                [(_adesso(), a.id) for a in annunci],
            )

    def url_recenti(self, limite: int = 100) -> list[str]:
        """Ultimi URL già noti: li passiamo a Claude perché non li riproponga."""
        rows = self.conn.execute(
            "SELECT url FROM annunci ORDER BY trovato_il DESC, id DESC LIMIT ?", (limite,)
        )
        return [row["url"] for row in rows]


def _blob(gcs_uri: str):
    from google.cloud import storage  # import lazy: serve solo con il bucket

    if not gcs_uri.startswith("gs://") or "/" not in gcs_uri.removeprefix("gs://"):
        raise ValueError(f"JOBIST_DB_GCS_URI non valido: {gcs_uri!r} (atteso gs://bucket/file)")
    bucket, _, name = gcs_uri.removeprefix("gs://").partition("/")
    return storage.Client().bucket(bucket).blob(name)


@contextmanager
def apri_archivio(db_path: str, gcs_uri: str = "") -> Iterator[Archivio]:
    """Apre l'archivio; con `gcs_uri` lo scarica prima e lo ricarica dopo (anche in caso di
    errore, così gli annunci già trovati non vanno persi)."""
    path = Path(db_path)
    blob = _blob(gcs_uri) if gcs_uri else None
    generation = 0  # 0 = "il file non deve ancora esistere" per la precondizione

    if blob is not None:
        if blob.exists():
            blob.reload()
            generation = blob.generation
            blob.download_to_filename(path)
            logger.info("Database scaricato da %s (generation %s)", gcs_uri, generation)
        else:
            path.unlink(missing_ok=True)
            logger.info("Nessun database su %s: ne creo uno nuovo", gcs_uri)

    try:
        with closing(sqlite3.connect(path)) as conn:
            yield Archivio(conn)
    finally:
        if blob is not None:
            blob.upload_from_filename(path, if_generation_match=generation)
            logger.info("Database caricato su %s", gcs_uri)
