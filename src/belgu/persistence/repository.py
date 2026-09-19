from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session, sessionmaker


class Repository:
    def __init__(self, factory: sessionmaker[Session]):
        self.factory = factory

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self.factory() as session, session.begin():
            yield session
