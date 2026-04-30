from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import HTTPException

from p4p_core import utc_now

from registry.config import RegistryConfig
from registry.models import RegistrySourceResponse, RegistrySyncResponse, RegistrySyncUpstreamResult
from registry.store import MirrorSyncState, RegistryStore
from registry.validation import require_registry_capability, require_valid_registry_source


async def sync_registry_source_from_upstream(
    upstream,
    client: httpx.AsyncClient,
    *,
    config: RegistryConfig,
    store: RegistryStore,
) -> RegistrySyncUpstreamResult:
    upstream_url = str(upstream.url).rstrip("/")
    self_url = config.registry_url.rstrip("/") if config.registry_url else None
    if self_url and upstream_url == self_url:
        return RegistrySyncUpstreamResult(
            registry_url=upstream.url,
            status="skipped",
            detail="Skipped self mirror source",
        )

    try:
        response = await client.get(f"{upstream_url}/registry-source")
        response.raise_for_status()
        snapshot = RegistrySourceResponse(**response.json())
        verified_signature = require_valid_registry_source(snapshot)
        imported = store.import_source(snapshot, verified_signature=verified_signature)
        return RegistrySyncUpstreamResult(
            registry_url=upstream.url,
            status="imported",
            verified_signature=imported.verified_signature,
            imported_nodes=imported.imported_nodes,
            imported_manifests=imported.imported_manifests,
            latest_identity_event_id=imported.latest_identity_event_id,
        )
    except HTTPException as exc:
        return RegistrySyncUpstreamResult(
            registry_url=upstream.url,
            status="error",
            detail=str(exc.detail),
        )
    except httpx.HTTPError as exc:
        return RegistrySyncUpstreamResult(
            registry_url=upstream.url,
            status="error",
            detail=str(exc),
        )
    except Exception as exc:
        return RegistrySyncUpstreamResult(
            registry_url=upstream.url,
            status="error",
            detail=str(exc),
        )


async def run_mirror_sync_once(
    *,
    config: RegistryConfig,
    store: RegistryStore,
    mirror_sync_state: MirrorSyncState,
) -> RegistrySyncResponse:
    require_registry_capability(
        config.registry_metadata.capabilities.can_relay_sources,
        detail="This registry is not allowed to relay upstream sources",
    )
    started_at = utc_now()
    results: list[RegistrySyncUpstreamResult] = []

    if config.mirror_upstreams:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for upstream in config.mirror_upstreams:
                results.append(
                    await sync_registry_source_from_upstream(
                        upstream,
                        client,
                        config=config,
                        store=store,
                    )
                )

    response = RegistrySyncResponse(
        run_started_at=started_at,
        run_completed_at=utc_now(),
        upstreams=results,
    )
    mirror_sync_state.record(results)
    return response


def build_mirror_lifespan(
    *,
    config: RegistryConfig,
    store: RegistryStore,
    mirror_sync_state: MirrorSyncState,
):
    @asynccontextmanager
    async def app_lifespan(_):
        task: asyncio.Task[None] | None = None
        stop_event: asyncio.Event | None = None

        if (
            config.mirror_upstreams
            and config.mirror_sync_interval_seconds > 0
            and config.registry_metadata.capabilities.can_relay_sources
        ):
            stop_event = asyncio.Event()

            async def sync_loop() -> None:
                while True:
                    await run_mirror_sync_once(
                        config=config,
                        store=store,
                        mirror_sync_state=mirror_sync_state,
                    )
                    try:
                        assert stop_event is not None
                        await asyncio.wait_for(
                            stop_event.wait(),
                            timeout=config.mirror_sync_interval_seconds,
                        )
                        return
                    except asyncio.TimeoutError:
                        continue

            task = asyncio.create_task(sync_loop())

        try:
            yield
        finally:
            if stop_event is not None:
                stop_event.set()
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            store.close()

    return app_lifespan


__all__ = [
    "build_mirror_lifespan",
    "run_mirror_sync_once",
    "sync_registry_source_from_upstream",
]
