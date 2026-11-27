"""Public portfolio and master-only portfolio management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.auth import admin_only
from app.database import get_db
from app.models import PortfolioItem
from app.schemas import (
    PortfolioItemAdminOut,
    PortfolioItemCreate,
    PortfolioItemOut,
    PortfolioItemUpdate,
    PortfolioFolderRename,
)

router = APIRouter(tags=["portfolio"])
MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
PUBLISH_IMAGE_REQUIRED = (
    "Чтобы опубликовать работу, добавьте изображение или укажите его URL."
)


def _image_signature_matches(content_type: str, content: bytes) -> bool:
    signatures = {
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
    }
    return signatures.get(content_type, False)


def _public_query():
    return (
        select(PortfolioItem)
        .where(PortfolioItem.is_published.is_(True))
        .order_by(PortfolioItem.sort_order.asc(), PortfolioItem.id.asc())
    )


def _admin_query():
    return (
        select(PortfolioItem)
        .options(undefer(PortfolioItem.image_data))
        .order_by(PortfolioItem.sort_order.asc(), PortfolioItem.id.asc())
    )


def _admin_out(item: PortfolioItem) -> PortfolioItemAdminOut:
    image_loaded = "image_data" in item.__dict__
    return PortfolioItemAdminOut(
        **PortfolioItemOut.model_validate(item).model_dump(),
        has_uploaded_image=bool(
            item.image_content_type
            or (image_loaded and item.__dict__.get("image_data") is not None)
        ),
        image_content_type=item.image_content_type,
    )


def _ensure_publishable(
    is_published: bool,
    image_url: str | None,
    has_uploaded_image: bool = False,
) -> None:
    if is_published and not ((image_url or "").strip() or has_uploaded_image):
        raise HTTPException(status_code=422, detail=PUBLISH_IMAGE_REQUIRED)


@router.get("/portfolio", response_model=list[PortfolioItemOut])
async def list_public_portfolio(session: AsyncSession = Depends(get_db)):
    result = await session.execute(_public_query())
    return result.scalars().all()


@router.get("/portfolio/{item_id}/image")
async def get_portfolio_image(item_id: int, session: AsyncSession = Depends(get_db)):
    item = (
        await session.execute(
            select(PortfolioItem)
            .where(PortfolioItem.id == item_id)
            .options(undefer(PortfolioItem.image_data))
        )
    ).scalar_one_or_none()
    if item is None or not item.is_published or item.image_data is None:
        raise HTTPException(status_code=404, detail="Изображение не найдено")
    return Response(
        content=item.image_data,
        media_type=item.image_content_type or "image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/admin/portfolio/{item_id}/image")
async def get_admin_portfolio_image(
    item_id: int,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    item = (
        await session.execute(
            select(PortfolioItem)
            .where(PortfolioItem.id == item_id)
            .options(undefer(PortfolioItem.image_data))
        )
    ).scalar_one_or_none()
    if item is None or item.image_data is None:
        raise HTTPException(status_code=404, detail="Изображение не найдено")
    return Response(
        content=item.image_data,
        media_type=item.image_content_type or "image/jpeg",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/admin/portfolio", response_model=list[PortfolioItemAdminOut])
async def list_admin_portfolio(
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    result = await session.execute(_admin_query())
    return [_admin_out(item) for item in result.scalars().all()]


@router.get("/admin/portfolio/folders", response_model=list[str])
async def list_portfolio_folders(
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    result = await session.execute(
        select(PortfolioItem.folder).distinct().order_by(PortfolioItem.folder.asc())
    )
    return result.scalars().all()


@router.patch("/admin/portfolio/folders/rename", response_model=list[str])
async def rename_portfolio_folder(
    data: PortfolioFolderRename,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    if data.old_folder == data.new_folder:
        return await list_portfolio_folders(session, _admin)
    existing = await session.scalar(
        select(PortfolioItem.id).where(PortfolioItem.folder == data.new_folder).limit(1)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Папка с таким названием уже есть")
    items = (
        await session.execute(
            select(PortfolioItem).where(PortfolioItem.folder == data.old_folder)
        )
    ).scalars().all()
    if not items:
        raise HTTPException(status_code=404, detail="Папка не найдена")
    for item in items:
        item.folder = data.new_folder
    await session.commit()
    return await list_portfolio_folders(session, _admin)


@router.post(
    "/admin/portfolio",
    response_model=PortfolioItemAdminOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_portfolio_item(
    data: PortfolioItemCreate,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    _ensure_publishable(data.is_published, data.image_url)
    item = PortfolioItem(**data.model_dump())
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return _admin_out(item)


@router.patch("/admin/portfolio/{item_id}", response_model=PortfolioItemAdminOut)
async def update_portfolio_item(
    item_id: int,
    data: PortfolioItemUpdate,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    item = await session.get(PortfolioItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Работа не найдена")
    changes = data.model_dump(exclude_unset=True)
    next_is_published = changes.get("is_published", item.is_published)
    next_image_url = changes.get("image_url", item.image_url)
    has_uploaded_image = False
    if next_is_published and not (next_image_url or "").strip():
        uploaded_image_id = await session.scalar(
            select(PortfolioItem.id).where(
                PortfolioItem.id == item_id,
                PortfolioItem.image_data.is_not(None),
                PortfolioItem.image_content_type.is_not(None),
            )
        )
        has_uploaded_image = uploaded_image_id is not None
    _ensure_publishable(next_is_published, next_image_url, has_uploaded_image)
    for key, value in changes.items():
        setattr(item, key, value)
    await session.commit()
    await session.refresh(item)
    return _admin_out(item)


@router.post("/admin/portfolio/{item_id}/image", response_model=PortfolioItemAdminOut)
async def upload_portfolio_image(
    item_id: int,
    image: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    item = await session.get(PortfolioItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Работа не найдена")
    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Поддерживаются JPEG, PNG и WebP")
    content = await image.read(MAX_IMAGE_BYTES + 1)
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Изображение слишком большое")
    if not content:
        raise HTTPException(status_code=400, detail="Файл пустой")
    if not _image_signature_matches(image.content_type, content):
        raise HTTPException(status_code=415, detail="Файл не похож на изображение заявленного формата")
    item.image_data = content
    item.image_content_type = image.content_type
    item.image_url = f"/api/v1/portfolio/{item.id}/image"
    await session.commit()
    await session.refresh(item)
    return _admin_out(item)


@router.delete("/admin/portfolio/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portfolio_item(
    item_id: int,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    item = await session.get(PortfolioItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Работа не найдена")
    await session.delete(item)
    await session.commit()
