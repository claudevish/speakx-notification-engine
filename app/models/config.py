from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AppConfig(Base):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(50))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
