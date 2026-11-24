"""Knowledge base endpoints: see what the AIs know, add a website, remove a source."""

from fastapi import APIRouter, Depends, Response
from pydantic import Field
from sqlalchemy.orm import Session

from app.auth import current_user, current_user_ro
from app.db import get_db
from app.errors import bad_request
from app.models import User
from app.schemas import _In
from app.services import knowledge as kn

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class UrlIn(_In):
    url: str = Field(min_length=8, max_length=500)


@router.get("")
def list_knowledge(user: User = Depends(current_user_ro), db: Session = Depends(get_db)) -> dict:
    return {"sources": kn.sources(db)}


@router.post("/url", status_code=201)
def add_website(body: UrlIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    try:
        docs = kn.fetch_site(body.url.strip())
    except ValueError as e:
        raise bad_request(str(e)) from None
    n = kn.save_docs(db, docs)
    return {"added": n, "source": docs[0]["source"], "sources": kn.sources(db)}


@router.delete("/{source}", status_code=204)
def remove(source: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    kn.remove_source(db, source)
    return Response(status_code=204)
