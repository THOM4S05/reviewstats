from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ImportedReview:
    provider_id: str
    reviewer_display_name: str | None
    rating: int
    comment: str | None
    create_time: datetime
    update_time: datetime


class ReviewProvider(ABC):
    provider_name: str

    @abstractmethod
    async def get_reviews(self) -> list[ImportedReview]:
        raise NotImplementedError
