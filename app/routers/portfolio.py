"""Public portfolio and master-only portfolio management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import admin_only
from app.database import get_db
from app.models import PortfolioItem
from app.schemas import (
    PortfolioItemAdminOut,
    PortfolioItemCreate,
    PortfolioItemOut,
    PortfolioItemUpdate,
)

router = APIRouter(tags=["portfolio"])
MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


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
    return select(PortfolioItem).order_by(
        PortfolioItem.sort_order.asc(), PortfolioItem.id.asc()
    )


def _admin_out(item: PortfolioItem) -> PortfolioItemAdminOut:
    return PortfolioItemAdminOut(
        **PortfolioItemOut.model_validate(item).model_dump(),
        has_uploaded_image=item.image_data is not None,
        image_content_type=item.image_content_type,
    )


@router.get("/portfolio", response_model=list[PortfolioItemOut])
async def list_public_portfolio(session: AsyncSession = Depends(get_db)):
    result = await session.execute(_public_query())
    return result.scalars().all()


@router.get("/portfolio/{item_id}/image")
async def get_portfolio_image(item_id: int, session: AsyncSession = Depends(get_db)):
    item = await session.get(PortfolioItem, item_id)
    if item is None or not item.is_published or item.image_data is None:
        raise HTTPException(status_code=404, detail="Изображение не найдено")
    return Response(content=item.image_data, media_type=item.image_content_type or "image/jpeg")


@router.get("/admin/portfolio", response_model=list[PortfolioItemAdminOut])
async def list_admin_portfolio(
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    result = await session.execute(_admin_query())
    return [_admin_out(item) for item in result.scalars().all()]


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
    for key, value in data.model_dump(exclude_unset=True).items():
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
