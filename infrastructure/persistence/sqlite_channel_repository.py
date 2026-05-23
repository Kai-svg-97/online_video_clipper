from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from domain.monitoring.aggregates import ChannelMonitorAggregate
from domain.monitoring.entities import ChannelSubscription
from domain.monitoring.repositories import IChannelRepository
from domain.monitoring.value_objects import MonitoringRule
from domain.download.value_objects import DownloadSettings, MediaFormat, Quality
from infrastructure.persistence.database import Database


class SqliteChannelRepository(IChannelRepository):
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, aggregate: ChannelMonitorAggregate) -> None:
        s = aggregate.subscription
        r = s.rule
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO channel_subscriptions
                    (id, channel_id, channel_name, channel_url,
                     keywords, min_duration_sec, max_duration_sec,
                     auto_download, dl_quality, dl_format,
                     is_active, last_checked_at, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    channel_name=excluded.channel_name,
                    keywords=excluded.keywords,
                    min_duration_sec=excluded.min_duration_sec,
                    max_duration_sec=excluded.max_duration_sec,
                    auto_download=excluded.auto_download,
                    dl_quality=excluded.dl_quality,
                    dl_format=excluded.dl_format,
                    is_active=excluded.is_active,
                    last_checked_at=excluded.last_checked_at
                """,
                (
                    str(s.id), s.channel_id, s.channel_name, s.channel_url,
                    json.dumps(list(r.keywords)),
                    r.min_duration_sec, r.max_duration_sec,
                    int(r.auto_download),
                    r.download_settings.quality.value,
                    r.download_settings.format.value,
                    int(s.is_active),
                    s.last_checked_at.isoformat() if s.last_checked_at else None,
                    s.created_at.isoformat(),
                ),
            )

    def get_by_id(self, subscription_id: UUID) -> ChannelMonitorAggregate | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM channel_subscriptions WHERE id=?",
                (str(subscription_id),),
            ).fetchone()
        return ChannelMonitorAggregate(self._row_to_sub(row)) if row else None

    def get_by_channel_id(self, channel_id: str) -> ChannelMonitorAggregate | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM channel_subscriptions WHERE channel_id=?",
                (channel_id,),
            ).fetchone()
        return ChannelMonitorAggregate(self._row_to_sub(row)) if row else None

    def list_active(self) -> list[ChannelMonitorAggregate]:
        results: list[ChannelMonitorAggregate] = []
        with self._db.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM channel_subscriptions WHERE is_active=1"
            )
            for row in cursor:
                results.append(ChannelMonitorAggregate(self._row_to_sub(row)))
        return results

    def delete(self, subscription_id: UUID) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "DELETE FROM channel_subscriptions WHERE id=?", (str(subscription_id),)
            )

    @staticmethod
    def _row_to_sub(row) -> ChannelSubscription:
        dl_settings = DownloadSettings(
            quality=Quality(row["dl_quality"]),
            fmt=MediaFormat(row["dl_format"]),
        )
        rule = MonitoringRule(
            keywords=tuple(json.loads(row["keywords"] or "[]")),
            min_duration_sec=row["min_duration_sec"],
            max_duration_sec=row["max_duration_sec"],
            auto_download=bool(row["auto_download"]),
            download_settings=dl_settings,
        )
        return ChannelSubscription(
            id=UUID(row["id"]),
            channel_id=row["channel_id"],
            channel_name=row["channel_name"],
            channel_url=row["channel_url"],
            rule=rule,
            is_active=bool(row["is_active"]),
            last_checked_at=(
                datetime.fromisoformat(row["last_checked_at"])
                if row["last_checked_at"]
                else None
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
