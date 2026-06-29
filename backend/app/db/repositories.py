"""Repository layer — the only place app code touches the ORM.

Repositories take an ``AsyncSession`` and speak in domain objects
(``app.domain``), never leaking ORM rows to callers. Transaction control is the
caller's responsibility (use ``session_scope`` or commit explicitly), so
repositories ``flush`` but do not ``commit``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import mappers
from app.db.models import CallerORM, CallORM, EventORM
from app.domain.models import Call, Caller, TranscriptTurn


class CallerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_phone(self, phone: str) -> Caller | None:
        orm = await self.session.scalar(
            select(CallerORM).where(CallerORM.phone == phone)
        )
        return mappers.caller_from_orm(orm) if orm else None

    async def get(self, caller_id: uuid.UUID) -> Caller | None:
        orm = await self.session.get(CallerORM, caller_id)
        return mappers.caller_from_orm(orm) if orm else None

    async def get_or_create(self, phone: str) -> Caller:
        """Return the existing caller for ``phone`` or insert a fresh one."""
        existing = await self.session.scalar(
            select(CallerORM).where(CallerORM.phone == phone)
        )
        if existing:
            return mappers.caller_from_orm(existing)
        caller = Caller(phone=phone, total_calls=0)
        orm = mappers.caller_to_orm(caller)
        self.session.add(orm)
        await self.session.flush()
        return mappers.caller_from_orm(orm)

    async def save(self, caller: Caller) -> Caller:
        """Upsert a caller's reputation fields by id."""
        orm = await self.session.get(CallerORM, caller.id)
        orm = mappers.caller_to_orm(caller, orm)
        self.session.add(orm)
        await self.session.flush()
        return mappers.caller_from_orm(orm)

    async def set_reputation(
        self,
        phone: str,
        *,
        is_blacklisted: bool | None = None,
        flagged_prank: bool | None = None,
    ) -> Caller:
        """Set/clear a number's blacklist & flagged-prank flags by phone.

        The Phase 6 blacklist/greylist admin path: blacklisting a number (or
        flagging it as a known prank) feeds the live :class:`CallerContext` so
        the junk scorer weights it on the *next* call. Creates the caller row if
        the number hasn't been seen yet. Flags left as ``None`` are untouched.
        """
        orm = await self.session.scalar(
            select(CallerORM).where(CallerORM.phone == phone)
        )
        if orm is None:
            orm = mappers.caller_to_orm(Caller(phone=phone, total_calls=0))
            self.session.add(orm)
        if is_blacklisted is not None:
            orm.is_blacklisted = is_blacklisted
        if flagged_prank is not None:
            orm.flagged_prank = flagged_prank
        await self.session.flush()
        return mappers.caller_from_orm(orm)


class CallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, call: Call) -> Call:
        """Persist a new call plus any transcript turns it already carries."""
        orm = mappers.call_to_orm(call)
        self.session.add(orm)
        await self.session.flush()
        for turn in call.transcript:
            self.session.add(mappers.turn_to_orm(turn, orm.id))
        await self.session.flush()
        return await self.get(call.id)  # type: ignore[return-value]

    async def get(self, call_id: uuid.UUID) -> Call | None:
        orm = await self.session.scalar(
            select(CallORM)
            .where(CallORM.id == call_id)
            .options(selectinload(CallORM.turns))
        )
        return mappers.call_from_orm(orm) if orm else None

    async def update(self, call: Call) -> Call:
        """Persist scalar/incident/route changes and append any new turns.

        New transcript turns are detected by id (turns already in the DB are
        left untouched — turns are append-only), so callers can mutate the
        in-memory ``Call`` freely and call ``update`` to flush the delta.
        """
        orm = await self.session.scalar(
            select(CallORM)
            .where(CallORM.id == call.id)
            .options(selectinload(CallORM.turns))
        )
        if orm is None:
            raise KeyError(f"Call {call.id} not found")
        mappers.call_to_orm(call, orm)

        # Append only genuinely new turns. We append onto the loaded relationship
        # collection (rather than session.add) so the in-session view stays
        # consistent and the subsequent reload reflects the new turns.
        existing_ids = {t.id for t in orm.turns}
        for turn in call.transcript:
            if turn.id not in existing_ids:
                orm.turns.append(mappers.turn_to_orm(turn, orm.id))
        await self.session.flush()
        return await self.get(call.id)  # type: ignore[return-value]

    async def append_turn(self, call_id: uuid.UUID, turn: TranscriptTurn) -> None:
        """Persist a single transcript turn (streaming-friendly fast path)."""
        self.session.add(mappers.turn_to_orm(turn, call_id))
        await self.session.flush()

    async def log_event(
        self, call_id: uuid.UUID, kind: str, payload: dict | None = None
    ) -> None:
        """Append an audit/event row for analytics + replay."""
        self.session.add(
            EventORM(id=uuid.uuid4(), call_id=call_id, kind=kind, payload=payload or {})
        )
        await self.session.flush()

    async def list_for_caller(self, caller_id: uuid.UUID) -> list[Call]:
        rows = await self.session.scalars(
            select(CallORM)
            .where(CallORM.caller_id == caller_id)
            .options(selectinload(CallORM.turns))
            .order_by(CallORM.started_at)
        )
        return [mappers.call_from_orm(r) for r in rows]
