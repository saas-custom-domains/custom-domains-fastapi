"""The help center each customer serves on their own domain."""

from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.db import SessionDep
from app.models import Article, Feedback, Tenant
from app.templating import templates
from app.tenancy import CurrentTenant, current_tenant

# Every route needs an active customer domain; anything else is a 404.
site = FastAPI(
    dependencies=[Depends(current_tenant)],
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def get_article(session: Session, tenant: Tenant, slug: str) -> Article:
    article = session.exec(
        select(Article).where(
            Article.tenant_id == tenant.id, Article.slug == slug
        )
    ).first()
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@site.get("/", response_class=HTMLResponse, name="help_center")
def help_center(
    request: Request, tenant: CurrentTenant, session: SessionDep
):
    articles = session.exec(
        select(Article)
        .where(Article.tenant_id == tenant.id)
        .order_by(Article.id)
    ).all()
    return templates.TemplateResponse(
        request,
        "help_center.html",
        {"tenant": tenant, "articles": articles},
    )


@site.get(
    "/articles/{slug}", response_class=HTMLResponse, name="article"
)
def article_page(
    request: Request,
    slug: str,
    tenant: CurrentTenant,
    session: SessionDep,
    thanks: bool = False,
):
    article = get_article(session, tenant, slug)
    return templates.TemplateResponse(
        request,
        "article.html",
        {"tenant": tenant, "article": article, "thanks": thanks},
    )


@site.post("/articles/{slug}/feedback", name="article_feedback")
def article_feedback(
    request: Request,
    slug: str,
    helpful: Annotated[Literal["yes", "no"], Form()],
    tenant: CurrentTenant,
    session: SessionDep,
):
    # The tenant comes from the domain, never from the form.
    article = get_article(session, tenant, slug)
    session.add(
        Feedback(
            article_id=article.id,
            helpful=helpful == "yes",
            client_ip=request.client.host if request.client else None,
        )
    )
    session.commit()
    # A relative Location keeps the visitor on the domain they used.
    path = site.url_path_for("article", slug=slug)
    return RedirectResponse(f"{path}?thanks=true", status_code=303)


class ArticleOut(BaseModel):
    slug: str
    title: str
    url: str


class ArticleDetail(ArticleOut):
    body: str
    helpful: int
    not_helpful: int


@site.get("/api/articles", response_model=list[ArticleOut])
def list_articles(
    request: Request, tenant: CurrentTenant, session: SessionDep
):
    articles = session.exec(
        select(Article)
        .where(Article.tenant_id == tenant.id)
        .order_by(Article.id)
    ).all()
    return [
        ArticleOut(
            slug=a.slug,
            title=a.title,
            url=str(request.url_for("article", slug=a.slug)),
        )
        for a in articles
    ]


@site.get("/api/articles/{slug}", response_model=ArticleDetail)
def show_article(
    request: Request,
    slug: str,
    tenant: CurrentTenant,
    session: SessionDep,
):
    article = get_article(session, tenant, slug)
    votes = dict(
        session.exec(
            select(Feedback.helpful, func.count())
            .where(Feedback.article_id == article.id)
            .group_by(Feedback.helpful)
        ).all()
    )
    return ArticleDetail(
        slug=article.slug,
        title=article.title,
        body=article.body,
        url=str(request.url_for("article", slug=article.slug)),
        helpful=votes.get(True, 0),
        not_helpful=votes.get(False, 0),
    )
