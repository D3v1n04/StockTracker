from contextlib import asynccontextmanager
import hmac
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from backend.app.analytics import get_stock_metrics, get_stock_analytics_series
from backend.app.database import (
    DatabaseConfigurationError,
    check_database_connection,
    reset_engine,
)

from backend.app.data_access import (
    get_all_symbols,
    get_latest_price,
    get_stock_history,
)
from backend.app.auth import (
    AuthenticationMiddleware,
    clear_session_cookie,
    client_key,
    login_throttle,
    read_credentials,
    set_session_cookie,
    valid_session,
    verify_password,
)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        reset_engine()


app = FastAPI(title="StockTracker API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthenticationMiddleware)


@app.get("/health")
def health_check():
    return {"status": "ok"}


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
LOGIN_TEMPLATE = (FRONTEND_DIR / "login.html").read_text(encoding="utf-8")


def login_page(message: str = "", status_code: int = 200) -> HTMLResponse:
    message_html = f'<p class="error" role="alert">{message}</p>' if message else ""
    return HTMLResponse(LOGIN_TEMPLATE.replace("{message}", message_html), status_code=status_code)


@app.get("/login", response_class=HTMLResponse)
def show_login(request: Request):
    config = request.state.auth_config
    if valid_session(request.cookies.get("stocktracker_session"), config):
        return RedirectResponse("/", status_code=303)
    return login_page()


@app.post("/login")
async def log_in(request: Request):
    config = request.state.auth_config
    key = client_key(request)
    retry_after = login_throttle.retry_after(key)
    if retry_after:
        response = login_page("Too many attempts. Please try again shortly.", 429)
        response.headers["Retry-After"] = str(retry_after)
        return response

    credentials = await read_credentials(request)
    if credentials is None:
        login_throttle.fail(key)
        return login_page("Invalid username or password.", 401)
    username, password = credentials
    username_matches = hmac.compare_digest(
        username.encode("utf-8"), config.username.encode("utf-8")
    )
    password_matches = verify_password(password, config.password_hash)
    if not (username_matches and password_matches):
        login_throttle.fail(key)
        return login_page("Invalid username or password.", 401)

    login_throttle.clear(key)
    response = RedirectResponse("/", status_code=303)
    set_session_cookie(response, config)
    return response


@app.post("/logout")
def log_out(request: Request):
    response = RedirectResponse("/login", status_code=303)
    clear_session_cookie(response, request.state.auth_config)
    return response


@app.get("/ready")
def readiness_check():
    try:
        check_database_connection()
    except DatabaseConfigurationError as error:
        logger.error("Database configuration error: %s", error)
        raise HTTPException(status_code=503, detail="Database unavailable")
    except (OSError, SQLAlchemyError):
        logger.warning("Database readiness check failed")
        raise HTTPException(status_code=503, detail="Database unavailable")

    return {"status": "ready"}


@app.get("/symbols")
def read_symbols():
    return {"symbols": get_all_symbols()}


@app.get("/stocks/{symbol}")
def read_stock_history(symbol: str):
    symbol = symbol.upper()
    data = get_stock_history(symbol)

    if not data:
        raise HTTPException(status_code=404, detail=f"No data found for {symbol}")

    return {
        "symbol": symbol,
        "count": len(data),
        "data": data,
    }


@app.get("/latest/{symbol}")
def read_latest_price(symbol: str):
    symbol = symbol.upper()
    latest = get_latest_price(symbol)

    if latest is None:
        raise HTTPException(status_code=404, detail=f"No data found for {symbol}")

    return latest

@app.get("/analytics/{symbol}")
def read_stock_metrics(symbol: str):
    symbol = symbol.upper()

    metrics = get_stock_metrics(symbol)

    if metrics is None:
        return {
            "error": f"No data found for {symbol}"
        }

    return metrics

@app.get("/analytics/{symbol}/series")
def read_stock_analytics_series(symbol: str):
    symbol = symbol.upper()

    series = get_stock_analytics_series(symbol)

    if series is None:
        return {
            "error": f"No data found for {symbol}"
        }

    return series


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
