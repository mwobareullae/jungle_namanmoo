# Product Image Response Contract

## Rule

Backend product-card APIs must not expose source image URLs such as Olive Young image URLs.

For MVP, product image values come from `product_images.storage_key`.

Frontend composes the final public image URL with:

```text
VITE_IMAGE_CDN_BASE_URL + "/resized/w400/" + storage_key
```

## Current API Fields

Some existing response fields are still named `thumbnail_url` for compatibility.

Despite the name, these fields must contain a storage key, not an absolute URL.

Examples:

```json
{
  "thumbnail_url": "products/prod_001/thumbnail.jpg"
}
```

Do not return:

```json
{
  "thumbnail_url": "https://image.oliveyoung.co.kr/..."
}
```

## Applied Endpoints

- `GET /api/home/sections`
- `POST /api/recommendations`
- `GET /api/recommendations/{recommendation_id}`
- `GET /api/products/{product_id}`

## Source Priority

1. `product_images` row where `image_type=thumbnail`
2. First `product_images` row by `display_order`
3. Empty string, so frontend can show a placeholder

`products.thumbnail_url` is treated as a source collection value and is not used as a service image
response.
