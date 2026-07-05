from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import addresses, auth, cart, health, home, orders, payments, products, recommendations, skin, user_activity
from app.core.config import settings
from app.core.logging import configure_logging
from app.middleware.request_logging import request_logging_middleware
from app.schemas.common import ApiError, build_error_response, dump_model
from app.services.auth_service import AuthServiceError


configure_logging(settings.log_level)

app = FastAPI(title=f"{settings.app_name} API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if settings.enable_request_logging:
    app.middleware("http")(request_logging_middleware)

app.include_router(health.router, prefix=settings.api_base_path)
app.include_router(auth.router, prefix=settings.api_base_path)
app.include_router(skin.router, prefix=settings.api_base_path)
app.include_router(home.router, prefix=settings.api_base_path)
app.include_router(recommendations.router, prefix=settings.api_base_path)
app.include_router(products.router, prefix=settings.api_base_path)
app.include_router(user_activity.router, prefix=settings.api_base_path)
app.include_router(cart.router, prefix=settings.api_base_path)
app.include_router(addresses.router, prefix=settings.api_base_path)
app.include_router(orders.router, prefix=settings.api_base_path)
app.include_router(payments.router, prefix=settings.api_base_path)


@app.exception_handler(ApiError)
async def api_error_handler(_, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=dump_model(build_error_response(exc)),
    )


@app.exception_handler(AuthServiceError)
async def auth_service_error_handler(_, exc: AuthServiceError) -> JSONResponse:
    error = ApiError(exc.status_code, exc.code, exc.message)
    content = dump_model(build_error_response(error))
    content["code"] = exc.code
    content["message"] = exc.message
    return JSONResponse(
        status_code=error.status_code,
        content=content,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_, __: RequestValidationError) -> JSONResponse:
    error = ApiError(400, "INVALID_INPUT", "요청 형식이 올바르지 않습니다.")
    return JSONResponse(
        status_code=error.status_code,
        content=dump_model(build_error_response(error)),
    )


@app.get("/")
def root():
    return {
        "service": settings.app_name,
        "message": "hello from mwobareullae backend",
        "health": f"{settings.api_base_path}/health",
    }
