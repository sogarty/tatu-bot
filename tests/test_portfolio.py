"""Regression tests for server-side portfolio management."""

from __future__ import annotations

import asyncio
from io import BytesIO

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import Headers
from starlette.responses import Response

from app.auth import admin_only
from app.database import get_db
from app.models import Base, PortfolioItem
from app.routers.portfolio import router
from app.routers.portfolio import (
    create_portfolio_item,
    delete_portfolio_item,
    get_portfolio_image,
    list_public_portfolio,
    update_portfolio_item,
    upload_portfolio_image,
)
from app.schemas import PortfolioItemCreate, PortfolioItemUpdate


def run(coro):
    return asyncio.run(coro)


async def make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_public_portfolio_hides_unpublished_and_crud_persists():
    async def scenario():
        engine, factory = await make_session()
        admin = {"user_id": 42, "is_admin": True}
        async with factory() as session:
            created = await create_portfolio_item(
                PortfolioItemCreate(
                    title="Новая работа",
                    place="Плечо",
                    image_url="assets/portfolio/new.jpg",
                    tags=["graphic"],
                ),
                session,
                admin,
            )
            assert created.id > 0

            public = await list_public_portfolio(session)
            assert [item.id for item in public] == [created.id]

            updated = await update_portfolio_item(
                created.id,
                PortfolioItemUpdate(is_published=False, title="Скрытая работа"),
                session,
                admin,
            )
            assert updated.is_published is False
            assert updated.title == "Скрытая работа"
            assert await list_public_portfolio(session) == []

            await delete_portfolio_item(created.id, session, admin)
            assert await session.get(PortfolioItem, created.id) is None
        await engine.dispose()

    run(scenario())


def test_uploaded_image_is_saved_and_served_only_when_published():
    async def scenario():
        engine, factory = await make_session()
        admin = {"user_id": 42, "is_admin": True}
        async with factory() as session:
            created = await create_portfolio_item(
                PortfolioItemCreate(title="Файл", place="Рука"), session, admin
            )
            upload = UploadFile(
                file=BytesIO(b"\xff\xd8\xff\xe0fake-image-bytes"),
                filename="work.jpg",
                headers=Headers({"content-type": "image/jpeg"}),
            )
            uploaded = await upload_portfolio_image(created.id, upload, session, admin)
            assert uploaded.has_uploaded_image is True
            assert uploaded.image_url == f"/api/v1/portfolio/{created.id}/image"

            image = await get_portfolio_image(created.id, session)
            assert isinstance(image, Response)
            assert image.body == b"\xff\xd8\xff\xe0fake-image-bytes"
            assert image.media_type == "image/jpeg"

            await update_portfolio_item(
                created.id,
                PortfolioItemUpdate(is_published=False),
                session,
                admin,
            )
            try:
                await get_portfolio_image(created.id, session)
            except Exception as error:
                assert getattr(error, "status_code", None) == 404
            else:
                raise AssertionError("hidden image must not be publicly served")
        await engine.dispose()

    run(scenario())


def test_portfolio_admin_dependency_is_enforced():
    """The router dependencies must reject a non-master before DB mutation."""
    async def scenario():
        try:
            await admin_only({"user_id": 7, "is_admin": False})
        except HTTPException as error:
            assert error.status_code == 403
        else:
            raise AssertionError("non-admin user reached portfolio management")

    run(scenario())


def test_portfolio_http_routes_and_admin_auth():
    async def scenario():
        engine, factory = await make_session()
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        async def override_db():
            async with factory() as session:
                yield session

        async def override_admin():
            return {"user_id": 42, "is_admin": True}

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[admin_only] = override_admin
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/v1/admin/portfolio",
                json={
                    "title": "HTTP работа",
                    "place": "Предплечье",
                    "tags": ["graphic"],
                    "is_published": False,
                },
            )
            assert created.status_code == 201, created.text
            item_id = created.json()["id"]
            assert (await client.get("/api/v1/portfolio")).json() == []

            published = await client.patch(
                f"/api/v1/admin/portfolio/{item_id}",
                json={"is_published": True},
            )
            assert published.status_code == 200
            assert len((await client.get("/api/v1/portfolio")).json()) == 1

            image = await client.post(
                f"/api/v1/admin/portfolio/{item_id}/image",
                files={"image": ("work.jpg", b"\xff\xd8\xff\xe0image-data", "image/jpeg")},
            )
            assert image.status_code == 200, image.text
            image_response = await client.get(image.json()["image_url"])
            assert image_response.status_code == 200
            assert image_response.content == b"\xff\xd8\xff\xe0image-data"

            hidden = await client.patch(
                f"/api/v1/admin/portfolio/{item_id}",
                json={"is_published": False},
            )
            assert hidden.status_code == 200
            assert (await client.get("/api/v1/portfolio")).json() == []
            assert (await client.get(image.json()["image_url"])).status_code == 404

            deleted = await client.delete(f"/api/v1/admin/portfolio/{item_id}")
            assert deleted.status_code == 204

        unauthorized_app = FastAPI()
        unauthorized_app.include_router(router, prefix="/api/v1")
        unauthorized_app.dependency_overrides[get_db] = override_db
        async with AsyncClient(
            transport=ASGITransport(app=unauthorized_app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/admin/portfolio")
            assert response.status_code == 401

        await engine.dispose()

    run(scenario())


def test_portfolio_schema_rejects_protocol_relative_image_urls_and_bad_tags():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PortfolioItemCreate(
            title="Работа", place="Рука", image_url="//external.example/image.jpg"
        )
    with pytest.raises(ValidationError):
        PortfolioItemCreate(title="Работа", place="Рука", tags=[" "])
