from __future__ import annotations

import argparse
import csv
import ipaddress
import io
import json
import mimetypes
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DEFAULT_INPUT = DATA_DIR / "product_image_assets.csv"
DEFAULT_BATCH_DIR = DATA_DIR / "batch_runs"

REQUIRED_COLUMNS = {
    "product_id",
    "image_type",
    "display_order",
    "source_image_url",
    "storage_key",
}

SUCCESS_FIELDS = [
    "run_id",
    "row_no",
    "product_id",
    "image_type",
    "display_order",
    "source_image_url",
    "original_key",
    "resized_key",
    "target_width",
    "source_width",
    "source_height",
    "resized_width",
    "resized_height",
    "original_bytes",
    "resized_bytes",
    "resize_applied",
    "jpeg_reencoded",
    "download_attempts",
    "finished_at",
]

FAILED_FIELDS = [
    "run_id",
    "row_no",
    "product_id",
    "image_type",
    "display_order",
    "source_image_url",
    "storage_key",
    "error_type",
    "error_message",
    "failed_at",
]

SKIPPED_FIELDS = [
    "run_id",
    "row_no",
    "product_id",
    "image_type",
    "display_order",
    "source_image_url",
    "original_key",
    "resized_key",
    "reason",
    "finished_at",
]

PLANNED_FIELDS = [
    "run_id",
    "row_no",
    "product_id",
    "image_type",
    "display_order",
    "source_image_url",
    "original_key",
    "resized_key",
    "target_width",
]


class ImageBatchError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AssetRow:
    row_no: int
    product_id: str
    image_type: str
    display_order: str
    source_image_url: str
    storage_key: str
    original_key: str
    resized_key: str
    target_width: int


@dataclass(frozen=True)
class DownloadedImage:
    body: bytes
    content_type: str
    attempts: int


@dataclass(frozen=True)
class ResizedImage:
    body: bytes
    source_width: int
    source_height: int
    resized_width: int
    resized_height: int
    resize_applied: bool
    jpeg_reencoded: bool


class ObjectStore:
    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def put_bytes(self, key: str, body: bytes, *, content_type: str, cache_control: str | None) -> None:
        raise NotImplementedError


class LocalObjectStore(ObjectStore):
    def __init__(self, root: Path) -> None:
        self.root = root

    def exists(self, key: str) -> bool:
        return (self.root / key).is_file() and (self.root / key).stat().st_size > 0

    def put_bytes(self, key: str, body: bytes, *, content_type: str, cache_control: str | None) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


class S3ObjectStore(ObjectStore):
    def __init__(self, *, bucket: str, region: str | None, sse: str | None) -> None:
        try:
            import boto3
            from botocore.exceptions import ClientError
        except ImportError as exc:
            raise ImageBatchError(
                "MISSING_DEPENDENCY",
                "boto3 is required for S3 upload. Install data/scripts/requirements-image-batch.txt.",
            ) from exc

        self.bucket = bucket
        self.sse = sse
        self.client_error = ClientError
        self.client = boto3.client("s3", region_name=region)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except self.client_error as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def put_bytes(self, key: str, body: bytes, *, content_type: str, cache_control: str | None) -> None:
        kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": body,
            "ContentType": content_type,
        }
        if cache_control:
            kwargs["CacheControl"] = cache_control
        if self.sse:
            kwargs["ServerSideEncryption"] = self.sse
        self.client.put_object(**kwargs)


def main() -> None:
    args = parse_args()
    run_id = args.run_id or f"images_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    run_dir = args.run_dir or DEFAULT_BATCH_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    rows = load_asset_rows(args, run_id)
    store = None if args.dry_run else build_store(args)

    started_at = utc_now()
    started = time.perf_counter()
    results = run_batch(rows, args=args, run_id=run_id, run_dir=run_dir, store=store)
    elapsed_sec = round(time.perf_counter() - started, 3)

    write_outputs(run_dir, results)
    db_sync_summary = None
    if args.sync_db and not args.dry_run:
        db_sync_summary = sync_db(rows=rows, results=results, args=args)
        write_json(run_dir / "db_sync.json", db_sync_summary)

    summary = build_summary(
        args=args,
        run_id=run_id,
        run_dir=run_dir,
        rows=rows,
        results=results,
        started_at=started_at,
        elapsed_sec=elapsed_sec,
        db_sync_summary=db_sync_summary,
    )
    write_json(run_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download product images from product_image_assets.csv and upload originals plus resized variants.",
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input product_image_assets.csv path.")
    parser.add_argument("--run-dir", type=Path, default=None, help="Directory for success/failed/skipped outputs.")
    parser.add_argument("--run-id", default=None, help="Stable run id. Defaults to images_YYYYmmdd_HHMMSS.")
    parser.add_argument("--limit", type=int, default=None, help="Limit rows after filtering.")
    parser.add_argument(
        "--image-type",
        choices=("all", "thumbnail", "detail"),
        default="all",
        help="Filter rows by image_type.",
    )
    parser.add_argument(
        "--include-status",
        nargs="+",
        default=["PENDING_UPLOAD"],
        help="Optional CSV upload_status values to process. If the column is missing, all rows are processed. Use ALL to process every status.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only calculate target keys and planned rows.")
    parser.add_argument("--force", action="store_true", help="Upload again even when target objects already exist.")
    parser.add_argument(
        "--no-head-check",
        action="store_true",
        help="Skip object existence checks before upload. Use for the first full load into an empty bucket.",
    )
    parser.add_argument("--workers", type=int, default=4, help="Concurrent download/upload workers.")
    parser.add_argument("--timeout-sec", type=float, default=20.0, help="HTTP download timeout per request.")
    parser.add_argument(
        "--download-retries",
        type=int,
        default=3,
        help="Additional retry count for transient download errors.",
    )
    parser.add_argument(
        "--retry-base-delay-sec",
        type=float,
        default=0.5,
        help="Initial exponential backoff delay for download retries.",
    )
    parser.add_argument(
        "--retry-max-delay-sec",
        type=float,
        default=5.0,
        help="Maximum exponential backoff delay for download retries.",
    )
    parser.add_argument("--max-bytes", type=int, default=25 * 1024 * 1024, help="Maximum downloaded object size.")
    parser.add_argument(
        "--allow-private-source-urls",
        action="store_true",
        help="Allow source_image_url hosts that resolve to private/link-local/loopback IPs. Keep disabled on EC2.",
    )
    parser.add_argument("--thumbnail-width", type=int, default=400, help="Public width for thumbnail rows.")
    parser.add_argument("--detail-width", type=int, default=1200, help="Public width for detail rows.")
    parser.add_argument("--jpeg-quality", type=int, default=85, help="JPEG quality for resized public images.")
    parser.add_argument("--original-prefix", default="original", help="S3/local prefix for original assets.")
    parser.add_argument("--resized-prefix", default="resized", help="S3/local prefix for resized assets.")
    parser.add_argument(
        "--cache-control",
        default="public, max-age=31536000, immutable",
        help="Cache-Control header for resized public images.",
    )
    parser.add_argument(
        "--storage",
        choices=("s3", "local"),
        default="s3",
        help="Upload target. Use local for local smoke tests.",
    )
    parser.add_argument("--bucket", default=None, help="S3 bucket name when --storage=s3.")
    parser.add_argument("--aws-region", default=None, help="AWS region for boto3 client.")
    parser.add_argument(
        "--sse",
        default=None,
        help="Optional S3 server-side encryption value, e.g. AES256.",
    )
    parser.add_argument(
        "--local-output-root",
        type=Path,
        default=Path("/tmp/mwobareullae-image-assets"),
        help="Local output root when --storage=local.",
    )
    parser.add_argument(
        "--sync-db",
        action="store_true",
        help="Upsert successful or skipped image rows into the local product_images table.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="Database URL for --sync-db. Defaults to DATABASE_URL or local Docker Compose Postgres.",
    )
    parser.add_argument(
        "--db-image-base-url",
        default=None,
        help="Base URL stored in legacy product_images.image_url. Defaults to /image-assets for local storage.",
    )
    parser.add_argument(
        "--db-batch-size",
        type=int,
        default=500,
        help="Commit --sync-db rows in batches to avoid one huge transaction.",
    )
    return parser.parse_args()


def build_store(args: argparse.Namespace) -> ObjectStore:
    if args.storage == "local":
        return LocalObjectStore(args.local_output_root)
    if not args.bucket:
        raise SystemExit("--bucket is required when --storage=s3.")
    return S3ObjectStore(bucket=args.bucket, region=args.aws_region, sse=args.sse)


def load_asset_rows(args: argparse.Namespace, run_id: str) -> list[AssetRow]:
    with args.input.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - fieldnames)
        if missing:
            raise SystemExit(f"{args.input} is missing required columns: {', '.join(missing)}")

        selected: list[AssetRow] = []
        for row_no, row in enumerate(reader, start=2):
            image_type = normalized(row["image_type"])
            if args.image_type != "all" and image_type != args.image_type:
                continue
            upload_status = (row.get("upload_status") or "").strip()
            if "upload_status" in fieldnames and not should_process_status(upload_status, args.include_status):
                continue
            selected.append(parse_asset_row(row, row_no=row_no, args=args))
            if args.limit is not None and len(selected) >= args.limit:
                break
    return selected


def parse_asset_row(row: dict[str, str], *, row_no: int, args: argparse.Namespace) -> AssetRow:
    image_type = normalized(row["image_type"])
    if image_type == "thumbnail":
        target_width = args.thumbnail_width
    elif image_type == "detail":
        target_width = args.detail_width
    else:
        raise ImageBatchError("UNSUPPORTED_IMAGE_TYPE", f"Unsupported image_type={row['image_type']!r}")

    storage_key = clean_storage_key(row["storage_key"])
    original_key = join_s3_key(args.original_prefix, storage_key)
    resized_key = build_resized_key(args.resized_prefix, target_width, storage_key)

    return AssetRow(
        row_no=row_no,
        product_id=row["product_id"].strip(),
        image_type=image_type,
        display_order=row["display_order"].strip(),
        source_image_url=row["source_image_url"].strip(),
        storage_key=storage_key,
        original_key=original_key,
        resized_key=resized_key,
        target_width=target_width,
    )


def run_batch(
    rows: list[AssetRow],
    *,
    args: argparse.Namespace,
    run_id: str,
    run_dir: Path,
    store: ObjectStore | None,
) -> list[dict[str, Any]]:
    progress_path = run_dir / "progress.jsonl"
    results: list[dict[str, Any]] = []

    if args.dry_run:
        for row in rows:
            result = planned_result(row, run_id)
            results.append(result)
            append_jsonl(progress_path, result)
        return results

    assert store is not None
    max_workers = max(1, args.workers)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(process_asset_row, row, args=args, run_id=run_id, store=store): row
            for row in rows
        }
        for index, future in enumerate(as_completed(future_map), start=1):
            try:
                result = future.result()
            except Exception as exc:  # defensive guard for unexpected worker failures
                row = future_map[future]
                result = failed_result(row, run_id, "UNEXPECTED_ERROR", str(exc))
            result["processed_count"] = index
            result["total_count"] = len(rows)
            results.append(result)
            append_jsonl(progress_path, result)
    return results


def process_asset_row(
    row: AssetRow,
    *,
    args: argparse.Namespace,
    run_id: str,
    store: ObjectStore,
) -> dict[str, Any]:
    try:
        check_existing = not args.force and not args.no_head_check
        original_exists = store.exists(row.original_key) if check_existing else False
        resized_exists = store.exists(row.resized_key) if check_existing else False
        if original_exists and resized_exists:
            return skipped_result(row, run_id, "already_exists")

        downloaded = download_image(
            row.source_image_url,
            timeout_sec=args.timeout_sec,
            max_bytes=args.max_bytes,
            retry_attempts=args.download_retries,
            retry_base_delay_sec=args.retry_base_delay_sec,
            retry_max_delay_sec=args.retry_max_delay_sec,
            allow_private_urls=args.allow_private_source_urls,
        )
        resized = resize_to_jpeg(downloaded.body, row.target_width, quality=args.jpeg_quality)

        if args.force or not original_exists:
            store.put_bytes(
                row.original_key,
                downloaded.body,
                content_type=downloaded.content_type,
                cache_control=None,
            )
        if args.force or not resized_exists:
            store.put_bytes(
                row.resized_key,
                resized.body,
                content_type="image/jpeg",
                cache_control=args.cache_control,
            )

        return {
            "status": "success",
            "run_id": run_id,
            "row_no": row.row_no,
            "product_id": row.product_id,
            "image_type": row.image_type,
            "display_order": row.display_order,
            "source_image_url": row.source_image_url,
            "original_key": row.original_key,
            "resized_key": row.resized_key,
            "target_width": row.target_width,
            "source_width": resized.source_width,
            "source_height": resized.source_height,
            "resized_width": resized.resized_width,
            "resized_height": resized.resized_height,
            "original_bytes": len(downloaded.body),
            "resized_bytes": len(resized.body),
            "resize_applied": resized.resize_applied,
            "jpeg_reencoded": resized.jpeg_reencoded,
            "download_attempts": downloaded.attempts,
            "finished_at": utc_now(),
        }
    except ImageBatchError as exc:
        return failed_result(row, run_id, exc.code, exc.message)
    except Exception as exc:
        return failed_result(row, run_id, exc.__class__.__name__, str(exc))


def download_image(
    url: str,
    *,
    timeout_sec: float,
    max_bytes: int,
    retry_attempts: int,
    retry_base_delay_sec: float,
    retry_max_delay_sec: float,
    allow_private_urls: bool,
) -> DownloadedImage:
    parsed_url = validate_source_url(url, allow_private_urls=allow_private_urls)
    max_attempts = max(1, retry_attempts + 1)
    last_error: ImageBatchError | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            body, content_type = download_image_once(
                parsed_url.geturl(),
                timeout_sec=timeout_sec,
                max_bytes=max_bytes,
            )
            return DownloadedImage(body=body, content_type=content_type, attempts=attempt)
        except ImageBatchError as exc:
            last_error = exc
            if attempt >= max_attempts or not is_retryable_download_error(exc):
                raise
            time.sleep(retry_delay(attempt, base_delay_sec=retry_base_delay_sec, max_delay_sec=retry_max_delay_sec))

    assert last_error is not None
    raise last_error


def validate_source_url(url: str, *, allow_private_urls: bool) -> urllib.parse.ParseResult:
    if not url:
        raise ImageBatchError("EMPTY_URL", "source_image_url is empty.")

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ImageBatchError("INVALID_URL_SCHEME", f"source_image_url must use http or https: {url}")
    if not parsed.hostname:
        raise ImageBatchError("INVALID_URL_HOST", f"source_image_url host is missing: {url}")
    if parsed.username or parsed.password:
        raise ImageBatchError("INVALID_URL_AUTH", "source_image_url must not include userinfo.")

    if not allow_private_urls:
        assert_public_hostname(parsed.hostname, parsed.port, parsed.scheme)
    return parsed


def assert_public_hostname(hostname: str, port: int | None, scheme: str) -> None:
    lookup_port = port or (443 if scheme == "https" else 80)
    try:
        addrinfos = socket.getaddrinfo(hostname, lookup_port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ImageBatchError("URL_RESOLVE_ERROR", f"Cannot resolve source_image_url host: {hostname}") from exc

    if not addrinfos:
        raise ImageBatchError("URL_RESOLVE_ERROR", f"Cannot resolve source_image_url host: {hostname}")

    for addrinfo in addrinfos:
        ip_text = addrinfo[4][0]
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError as exc:
            raise ImageBatchError("URL_RESOLVE_ERROR", f"Invalid resolved IP for {hostname}: {ip_text}") from exc
        if is_blocked_source_ip(ip):
            raise ImageBatchError(
                "BLOCKED_SOURCE_HOST",
                f"source_image_url host resolves to a non-public IP: {hostname} -> {ip_text}",
            )


def is_blocked_source_ip(ip: Any) -> bool:
    return any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def download_image_once(url: str, *, timeout_sec: float, max_bytes: int) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "mwobareullae-image-batch/1.0",
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and safe_int(content_length) > max_bytes:
                raise ImageBatchError("CONTENT_TOO_LARGE", f"Content-Length exceeds max_bytes: {content_length}")
            content_type = response.headers.get("Content-Type") or guess_content_type(url)
            body = read_limited(response, max_bytes=max_bytes)
    except urllib.error.HTTPError as exc:
        raise ImageBatchError(f"HTTP_{exc.code}", exc.reason or str(exc)) from exc
    except urllib.error.URLError as exc:
        raise ImageBatchError("URL_ERROR", str(exc.reason or exc)) from exc
    except TimeoutError as exc:
        raise ImageBatchError("TIMEOUT", str(exc)) from exc

    if not body:
        raise ImageBatchError("EMPTY_RESPONSE", "Downloaded body is empty.")
    return body, content_type


def is_retryable_download_error(exc: ImageBatchError) -> bool:
    retryable_codes = {
        "HTTP_408",
        "HTTP_429",
        "HTTP_500",
        "HTTP_502",
        "HTTP_503",
        "HTTP_504",
        "TIMEOUT",
        "URL_ERROR",
        "EMPTY_RESPONSE",
    }
    return exc.code in retryable_codes


def retry_delay(attempt: int, *, base_delay_sec: float, max_delay_sec: float) -> float:
    base = max(0.0, base_delay_sec)
    cap = max(base, max_delay_sec)
    return min(cap, base * (2 ** max(0, attempt - 1)))


def read_limited(response: Any, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ImageBatchError("CONTENT_TOO_LARGE", f"Downloaded bytes exceed max_bytes: {max_bytes}")
        chunks.append(chunk)
    return b"".join(chunks)


def resize_to_jpeg(body: bytes, target_width: int, *, quality: int) -> ResizedImage:
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as exc:
        raise ImageBatchError(
            "MISSING_DEPENDENCY",
            "Pillow is required for image resizing. Install data/scripts/requirements-image-batch.txt.",
        ) from exc

    try:
        image = Image.open(io.BytesIO(body))
        image.seek(0)
    except UnidentifiedImageError as exc:
        raise ImageBatchError("UNIDENTIFIED_IMAGE", "Downloaded file is not a readable image.") from exc
    except EOFError as exc:
        raise ImageBatchError("BROKEN_IMAGE", "Downloaded image is incomplete.") from exc

    source_width, source_height = image.size
    if source_width <= 0 or source_height <= 0:
        raise ImageBatchError("INVALID_IMAGE_SIZE", f"Invalid image size: {image.size}")

    resize_applied = source_width > target_width
    image = ImageOps.exif_transpose(image)
    image = image_to_rgb(image)
    if resize_applied:
        ratio = target_width / source_width
        next_size = (target_width, max(1, round(source_height * ratio)))
        image = image.resize(next_size, Image.Resampling.LANCZOS)

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=quality, optimize=True, progressive=True)
    resized_width, resized_height = image.size
    return ResizedImage(
        body=output.getvalue(),
        source_width=source_width,
        source_height=source_height,
        resized_width=resized_width,
        resized_height=resized_height,
        resize_applied=resize_applied,
        jpeg_reencoded=True,
    )


def image_to_rgb(image: Any) -> Any:
    from PIL import Image

    if image.mode == "RGB":
        return image
    if image.mode in {"RGBA", "LA"} or ("transparency" in image.info):
        background = image.convert("RGBA")
        white = Image.new("RGBA", background.size, (255, 255, 255, 255))
        return Image.alpha_composite(white, background).convert("RGB")
    return image.convert("RGB")


def planned_result(row: AssetRow, run_id: str) -> dict[str, Any]:
    return {
        "status": "planned",
        "run_id": run_id,
        "row_no": row.row_no,
        "product_id": row.product_id,
        "image_type": row.image_type,
        "display_order": row.display_order,
        "source_image_url": row.source_image_url,
        "original_key": row.original_key,
        "resized_key": row.resized_key,
        "target_width": row.target_width,
    }


def skipped_result(row: AssetRow, run_id: str, reason: str) -> dict[str, Any]:
    return {
        "status": "skipped",
        "run_id": run_id,
        "row_no": row.row_no,
        "product_id": row.product_id,
        "image_type": row.image_type,
        "display_order": row.display_order,
        "source_image_url": row.source_image_url,
        "original_key": row.original_key,
        "resized_key": row.resized_key,
        "reason": reason,
        "finished_at": utc_now(),
    }


def failed_result(row: AssetRow, run_id: str, error_type: str, error_message: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "run_id": run_id,
        "row_no": row.row_no,
        "product_id": row.product_id,
        "image_type": row.image_type,
        "display_order": row.display_order,
        "source_image_url": row.source_image_url,
        "storage_key": row.storage_key,
        "error_type": error_type,
        "error_message": error_message[:500],
        "failed_at": utc_now(),
    }


def write_outputs(run_dir: Path, results: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {
        "success": [],
        "failed": [],
        "skipped": [],
        "planned": [],
    }
    for result in results:
        status = str(result.get("status"))
        if status in grouped:
            grouped[status].append(result)

    write_csv(run_dir / "success.csv", SUCCESS_FIELDS, grouped["success"])
    write_csv(run_dir / "failed_image_urls.csv", FAILED_FIELDS, grouped["failed"])
    write_csv(run_dir / "skipped.csv", SKIPPED_FIELDS, grouped["skipped"])
    write_csv(run_dir / "planned.csv", PLANNED_FIELDS, grouped["planned"])


def sync_db(
    *,
    rows: list[AssetRow],
    results: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    try:
        from sqlalchemy import create_engine, inspect, text
    except ImportError as exc:
        raise ImageBatchError(
            "MISSING_DEPENDENCY",
            "SQLAlchemy is required for --sync-db. Install apps/backend/requirements.txt or data/scripts/requirements-image-batch.txt.",
        ) from exc

    database_url = normalize_database_url(args.database_url or default_local_database_url())
    engine = create_engine(database_url, pool_pre_ping=True)
    inspector = inspect(engine)
    product_image_columns = {column["name"] for column in inspector.get_columns("product_images")}

    if "storage_key" in product_image_columns:
        mode = "storage_key"
    elif "image_url" in product_image_columns:
        mode = "legacy_image_url"
    else:
        raise ImageBatchError(
            "UNSUPPORTED_DB_SCHEMA",
            "product_images must have either storage_key or image_url.",
        )

    rows_by_row_no = {row.row_no: row for row in rows}
    eligible_results = [
        result
        for result in results
        if result.get("status") in {"success", "skipped"} and int(result["row_no"]) in rows_by_row_no
    ]

    synced = 0
    updated = 0
    inserted = 0
    missing_products: list[str] = []
    batch_size = max(1, args.db_batch_size)

    for batch in chunked(eligible_results, batch_size):
        with engine.begin() as conn:
            for result in batch:
                row = rows_by_row_no[int(result["row_no"])]
                product_db_id = conn.execute(
                    text("SELECT id FROM products WHERE product_code = :product_code"),
                    {"product_code": row.product_id},
                ).scalar_one_or_none()
                if product_db_id is None:
                    missing_products.append(row.product_id)
                    continue

                display_order = db_display_order(row)
                if mode == "storage_key":
                    changed = upsert_storage_key_image(
                        conn,
                        columns=product_image_columns,
                        product_db_id=product_db_id,
                        row=row,
                        display_order=display_order,
                        image_url=build_db_image_url(row, args),
                    )
                else:
                    changed = upsert_legacy_image_url(
                        conn,
                        product_db_id=product_db_id,
                        image_url=build_db_image_url(row, args),
                        display_order=display_order,
                    )

                synced += 1
                if changed == "inserted":
                    inserted += 1
                else:
                    updated += 1

    return {
        "mode": mode,
        "database_url": redact_database_url(database_url),
        "image_url_base": db_image_base_url(args),
        "batch_size": batch_size,
        "eligible_rows": len(eligible_results),
        "synced": synced,
        "inserted": inserted,
        "updated": updated,
        "missing_products": sorted(set(missing_products)),
    }


def chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def upsert_storage_key_image(
    conn: Any,
    *,
    columns: set[str],
    product_db_id: int,
    row: AssetRow,
    display_order: int,
    image_url: str,
) -> str:
    from sqlalchemy import text

    existing_id = conn.execute(
        text(
            "SELECT id FROM product_images "
            "WHERE product_id = :product_id AND storage_key = :storage_key "
            "LIMIT 1"
        ),
        {"product_id": product_db_id, "storage_key": row.storage_key},
    ).scalar_one_or_none()

    values: dict[str, Any] = {
        "product_id": product_db_id,
        "storage_key": row.storage_key,
        "display_order": display_order,
    }
    if "image_type" in columns:
        values["image_type"] = row.image_type
    if "image_url" in columns:
        values["image_url"] = image_url

    if existing_id is not None:
        update_values = {key: value for key, value in values.items() if key != "product_id"}
        assignments = ", ".join(f"{key} = :{key}" for key in update_values)
        conn.execute(
            text(f"UPDATE product_images SET {assignments} WHERE id = :id"),
            {**update_values, "id": existing_id},
        )
        return "updated"

    column_names = ", ".join(values)
    placeholders = ", ".join(f":{key}" for key in values)
    conn.execute(
        text(f"INSERT INTO product_images ({column_names}) VALUES ({placeholders})"),
        values,
    )
    return "inserted"


def upsert_legacy_image_url(
    conn: Any,
    *,
    product_db_id: int,
    image_url: str,
    display_order: int,
) -> str:
    from sqlalchemy import text

    existing_id = conn.execute(
        text(
            "SELECT id FROM product_images "
            "WHERE product_id = :product_id AND image_url = :image_url "
            "LIMIT 1"
        ),
        {"product_id": product_db_id, "image_url": image_url},
    ).scalar_one_or_none()
    if existing_id is not None:
        conn.execute(
            text("UPDATE product_images SET display_order = :display_order WHERE id = :id"),
            {"id": existing_id, "display_order": display_order},
        )
        return "updated"

    conn.execute(
        text(
            "INSERT INTO product_images (product_id, image_url, display_order) "
            "VALUES (:product_id, :image_url, :display_order)"
        ),
        {"product_id": product_db_id, "image_url": image_url, "display_order": display_order},
    )
    return "inserted"


def build_db_image_url(row: AssetRow, args: argparse.Namespace) -> str:
    return join_url(db_image_base_url(args), row.resized_key)


def db_image_base_url(args: argparse.Namespace) -> str:
    if args.db_image_base_url is not None:
        return args.db_image_base_url
    if args.storage == "local":
        return "/image-assets"
    return ""


def db_display_order(row: AssetRow) -> int:
    if row.image_type == "thumbnail":
        return 0
    return safe_int(row.display_order) or row.row_no


def join_url(base_url: str, key: str) -> str:
    clean_key = key.strip().lstrip("/")
    clean_base = base_url.strip().rstrip("/")
    if not clean_base:
        return clean_key
    return f"{clean_base}/{clean_key}"


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def default_local_database_url() -> str:
    return "postgresql+psycopg://mwobareullae:change-me@localhost:5432/mwobareullae"


def redact_database_url(database_url: str) -> str:
    if "://" not in database_url or "@" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.split("@", 1)
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def build_summary(
    *,
    args: argparse.Namespace,
    run_id: str,
    run_dir: Path,
    rows: list[AssetRow],
    results: list[dict[str, Any]],
    started_at: str,
    elapsed_sec: float,
    db_sync_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    counts: dict[str, int] = {"planned": 0, "success": 0, "failed": 0, "skipped": 0}
    for result in results:
        status = str(result.get("status"))
        counts[status] = counts.get(status, 0) + 1

    summary = {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": utc_now(),
        "elapsed_sec": elapsed_sec,
        "dry_run": args.dry_run,
        "storage": args.storage,
        "no_head_check": args.no_head_check,
        "download_retries": args.download_retries,
        "allow_private_source_urls": args.allow_private_source_urls,
        "input": str(args.input),
        "run_dir": str(run_dir),
        "selected_rows": len(rows),
        "counts": counts,
        "thumbnail_width": args.thumbnail_width,
        "detail_width": args.detail_width,
        "original_prefix": args.original_prefix,
        "resized_prefix": args.resized_prefix,
        "cache_control": args.cache_control,
    }
    if db_sync_summary is not None:
        summary["db_sync"] = db_sync_summary
    return summary


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def should_process_status(value: str, include_status: list[str]) -> bool:
    normalized_values = {item.strip().upper() for item in include_status}
    if "ALL" in normalized_values:
        return True
    return value.strip().upper() in normalized_values


def normalized(value: str) -> str:
    return value.strip().lower()


def clean_storage_key(value: str) -> str:
    key = value.strip().replace("\\", "/").lstrip("/")
    if not key:
        raise ImageBatchError("EMPTY_STORAGE_KEY", "storage_key is empty.")
    if key.startswith(("http://", "https://", "s3://")):
        raise ImageBatchError("INVALID_STORAGE_KEY", f"storage_key must be relative: {value}")
    parts = PurePosixPath(key).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ImageBatchError("INVALID_STORAGE_KEY", f"storage_key has unsafe path segments: {value}")
    return str(PurePosixPath(*parts))


def join_s3_key(prefix: str, key: str) -> str:
    clean_prefix = prefix.strip().strip("/")
    return f"{clean_prefix}/{key}" if clean_prefix else key


def build_resized_key(prefix: str, width: int, storage_key: str) -> str:
    path = PurePosixPath(storage_key)
    jpg_path = path.with_suffix(".jpg")
    return join_s3_key(prefix, f"w{width}/{jpg_path}")


def guess_content_type(url: str) -> str:
    guessed, _ = mimetypes.guess_type(url)
    if guessed:
        return guessed
    return "application/octet-stream"


def safe_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    main()
