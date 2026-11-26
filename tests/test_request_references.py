"""Mini App reference image upload and access tests."""

from __future__ import annotations

import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import Headers

from app.models import Base, TattooRequest, TgUser
from app.routers.requests import (
    get_request_reference_image,
    upload_request_reference,
)


def run(coro):
    return asyncio.run(coro)


def test_reference_upload_limit_validation_and_image_access():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        client = {"user_id": 1001, "is_admin": False}

        async with factory() as session:
            session.add(TgUser(tg_id=1001, first_name="Client"))
            await session.flush()
            request = TattooRequest(
                user_id=1001,
                created_by=1001,
                description="A detailed tattoo idea for testing",
                location="Forearm",
                size="10 cm",
                color_mode="bw",
                status="new",
            )
            session.add(request)
            await session.commit()
            request_id = request.id

            uploaded = await upload_request_reference(
                request_id,
                UploadFile(
                    file=BytesIO(b"\xff\xd8\xff\xe0test-jpeg"),
                    filename="reference.jpg",
                    headers=Headers({"content-type": "image/jpeg"}),
                ),
                session,
                client,
            )
            reference = uploaded.references[0]
            assert reference.has_uploaded_image is True

            image_response = await get_request_reference_image(
                request_id, reference.id, session, client
            )
            assert image_response.body == b"\xff\xd8\xff\xe0test-jpeg"
            assert image_response.media_type == "image/jpeg"

            for index in range(1, 5):
                await upload_request_reference(
                    request_id,
                    UploadFile(
                        file=BytesIO(b"\x89PNG\r\n\x1a\n" + bytes([index])),
                        filename=f"reference-{index}.png",
                        headers=Headers({"content-type": "image/png"}),
                    ),
                    session,
                    client,
                )

            with pytest.raises(HTTPException) as limit_error:
                await upload_request_reference(
                    request_id,
                    UploadFile(
                        file=BytesIO(b"\xff\xd8\xff\xe0too-many"),
                        filename="sixth.jpg",
                        headers=Headers({"content-type": "image/jpeg"}),
                    ),
                    session,
                    client,
                )
            assert limit_error.value.status_code == 400

            with pytest.raises(HTTPException) as forbidden_error:
                await upload_request_reference(
                    request_id,
                    UploadFile(
                        file=BytesIO(b"\xff\xd8\xff\xe0admin"),
                        filename="admin.jpg",
                        headers=Headers({"content-type": "image/jpeg"}),
                    ),
                    session,
                    {"user_id": 42, "is_admin": True},
                )
            assert forbidden_error.value.status_code == 403

        await engine.dispose()

    run(scenario())


def test_reference_upload_rejects_mismatched_content():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add(TgUser(tg_id=1002, first_name="Client"))
            await session.flush()
            request = TattooRequest(
                user_id=1002,
                created_by=1002,
                description="Another detailed tattoo idea",
                location="Shoulder",
                size="5 cm",
                color_mode="color",
                status="new",
            )
            session.add(request)
            await session.commit()

            with pytest.raises(HTTPException) as error:
                await upload_request_reference(
                    request.id,
                    UploadFile(
                        file=BytesIO(b"not an image"),
                        filename="fake.png",
                        headers=Headers({"content-type": "image/png"}),
                    ),
                    session,
                    {"user_id": 1002, "is_admin": False},
                )
            assert error.value.status_code == 415
        await engine.dispose()

    run(scenario())
