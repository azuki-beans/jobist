"""Riga di comando: `jobist run` è il comando del Cloud Run Job."""

import argparse
import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from jobist import __version__
from jobist.config import get_settings
from jobist.notify import componi_digest, invia
from jobist.search import cerca_annunci
from jobist.store import apri_archivio

logger = logging.getLogger("jobist")


def _oggi() -> str:
    return datetime.now(ZoneInfo(get_settings().timezone)).strftime("%d/%m/%Y")


def cmd_run(args: argparse.Namespace) -> int:
    """Cerca nuovi annunci, li salva e invia quelli non ancora inviati."""
    s = get_settings()
    with apri_archivio(s.jobist_db_path, s.jobist_db_gcs_uri) as archivio:
        if not args.solo_invio:
            trovati = cerca_annunci(s, gia_visti=archivio.url_recenti())
            nuovi = archivio.aggiungi(trovati)
            logger.info("Annunci trovati: %d, nuovi: %d", len(trovati), nuovi)

        da_inviare = archivio.da_inviare()
        if not da_inviare:
            logger.info("Niente da inviare")
            return 0

        titolo, corpo = componi_digest(da_inviare, _oggi())
        if args.dry_run:
            print(f"{titolo}\n\n{corpo}")
            return 0

        if not invia(s.notify_urls.get_secret_value(), titolo, corpo):
            # Gli annunci restano "da inviare": ci si riprova alla prossima esecuzione.
            logger.error("Invio del digest fallito")
            return 1

        archivio.segna_inviati(da_inviare)
        logger.info("Digest inviato con %d annunci", len(da_inviare))
    return 0


def cmd_test_notifica(args: argparse.Namespace) -> int:
    """Manda un messaggio di prova per verificare NOTIFY_URLS."""
    ok = invia(
        get_settings().notify_urls.get_secret_value(),
        "Jobist: notifica di prova",
        "<p>Se leggi questo messaggio, NOTIFY_URLS è configurato correttamente.</p>",
    )
    logger.info("Notifica di prova %s", "inviata" if ok else "FALLITA")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobist", description=__doc__)
    parser.add_argument("--version", action="version", version=f"jobist {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="log di debug")
    sub = parser.add_subparsers(dest="comando", required=True)

    run = sub.add_parser("run", help="cerca gli annunci e invia il digest")
    run.add_argument("--dry-run", action="store_true",
                     help="stampa il digest invece di inviarlo (gli annunci restano da inviare)")
    run.add_argument("--solo-invio", action="store_true",
                     help="non cerca: invia solo gli annunci in attesa")
    run.set_defaults(func=cmd_run)

    test = sub.add_parser("test-notifica", help="invia una notifica di prova")
    test.set_defaults(func=cmd_test_notifica)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        return args.func(args)
    except Exception:
        logger.exception("Esecuzione fallita")
        return 1
