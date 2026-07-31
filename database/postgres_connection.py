"""🗄️ Engine, per-task sessions, and the declarative base.

There is NO global Session. A SQLAlchemy ``Session`` is not thread-safe:
sharing one across the event loop and ``asyncio.to_thread`` workers corrupts
its transaction state machine (the old global session produced
``ResourceClosedError`` / ``IllegalStateChangeError`` when two threads
committed/rolled back concurrently). Instead every unit of work -- a tool
call, a route handler, a graph-node helper -- opens its own session via
``db_session()`` and closes it when the task ends.
"""
from contextlib import contextmanager
from logging import getLogger
from typing import Iterator

from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session as OrmSession, sessionmaker

from hephaestus.settings import settings

logger = getLogger(__name__)

BASEURL = settings.PG_CONNECTION_STRING

ALCHEMY_CONNECTION_STRING = BASEURL + settings.ALCHEMY_DB

engine = create_engine(ALCHEMY_CONNECTION_STRING)
# expire_on_commit=False: rows returned from a per-task session stay readable
# after the session closes (detached, not expired). Only relationships that
# were never loaded remain off-limits on a detached object.
Session = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def db_session() -> Iterator[OrmSession]:
    """🗄️ One short-lived Session per unit of work.

    Commits on clean exit. On a SQLAlchemy error: roll back, log the trace,
    and re-raise -- the boundary that owns the task (tool, route, graph
    node) catches it and turns it into a user-facing error. Re-raising is
    deliberate fail-secure behaviour: swallowing here would pretend a failed
    write succeeded. Any other exception propagates untouched; ``close()``
    in the finally clause rolls the session back on the way out.
    """
    s = Session()
    try:
        yield s
        s.commit()
    except SQLAlchemyError:
        s.rollback()
        logger.exception("💥 DB write failed; session rolled back")
        raise
    finally:
        s.close()


class Base(DeclarativeBase):
    """🗄️ Declarative base with per-task-session convenience helpers.

    Every helper opens its own ``db_session`` so no Session is ever shared
    across threads. Returned instances are DETACHED: their loaded columns
    and eagerly-loaded relationships stay readable, but touching a
    relationship that was never loaded raises -- fetch everything the caller
    needs inside one task instead.

    ``save``/``delete``/``wipe_campaign`` never raise: a failed write is
    logged by ``db_session`` and reported as ``None``/``False``/``0``.
    """

    @classmethod
    def get(cls, **filters):
        """🔍 First row matching exact column values, or None (detached)."""
        with db_session() as s:
            return s.query(cls).filter_by(**filters).first()

    @classmethod
    def wipe_campaign(cls, campaign_id: int) -> int:
        """🗑️ Delete all rows of a campaign-scoped model; returns the count."""
        try:
            with db_session() as s:
                return s.query(cls).filter(cls.campaign_id == campaign_id).delete(synchronize_session=False)
        except SQLAlchemyError:
            logger.error(f"❌ wipe_campaign failed for {cls.__name__} (campaign {campaign_id})")
            return 0

    def save(self):
        """💾 Insert or update this (possibly detached) object.

        ``merge`` handles both transient and detached instances; the primary
        key is synced back onto ``self`` so callers can log it after a
        create. Returns self, or None if the write failed (already logged).
        """
        try:
            with db_session() as s:
                merged = s.merge(self)
                s.flush()  # assign PKs before the session closes
                for pk in inspect(type(self)).primary_key:
                    setattr(self, pk.name, getattr(merged, pk.name))
            return self
        except SQLAlchemyError:
            logger.error(f"❌ save failed for {type(self).__name__}")
            return None

    def delete(self) -> bool:
        """🗑️ Delete this (possibly detached) object; False if it failed."""
        try:
            with db_session() as s:
                s.delete(s.merge(self))
            return True
        except SQLAlchemyError:
            logger.error(f"❌ delete failed for {type(self).__name__}")
            return False

    @classmethod
    def get_or_create(cls, **filters):
        """🔍 First row matching exact column values, or create it (detached)."""
        with db_session() as s:
            row = s.query(cls).filter_by(**filters).first()
            if row is not None:
                logger.info(f"🔍 Found existing row for {cls.__name__} with filters {filters}")
                return row
            row = cls(**filters)
            s.add(row)
            s.flush()
            logger.info(f"✨ Created new row for {cls.__name__} with filters {filters}")
            return row
