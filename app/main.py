from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import dashboard
from app.db import init_db
from app.site import site
from app.tenancy import CustomerDomainMiddleware


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Helpdock", lifespan=lifespan)
# Instead of TrustedHostMiddleware: your own hostnames reach `app`,
# active customer domains reach `site`, everything else gets a 404.
app.add_middleware(CustomerDomainMiddleware, site=site)
app.include_router(dashboard.router)


@app.get("/up")
def up():
    """Health check for Docker and load balancers."""
    return {"status": "ok"}
