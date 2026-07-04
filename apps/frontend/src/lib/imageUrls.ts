const imageCdnBaseUrl = (import.meta.env.VITE_IMAGE_CDN_BASE_URL ?? "").replace(/\/$/, "");
const absoluteUrlPattern = /^[a-z][a-z\d+.-]*:\/\//i;

export type ProductImageSize = "w400" | "w1200";

const normalizeStorageKey = (storageKey: string) => storageKey.trim().replace(/^\/+/, "");

const resolveCdnUrl = (path: string) => (imageCdnBaseUrl ? `${imageCdnBaseUrl}/${path}` : path);

export const getStaticAssetUrl = (storageKey?: string | null) => {
  const key = storageKey?.trim();

  if (!key) {
    return "";
  }

  if (absoluteUrlPattern.test(key)) {
    return key;
  }

  return resolveCdnUrl(normalizeStorageKey(key));
};

export const getProductImageUrl = (
  storageKey?: string | null,
  size: ProductImageSize = "w400",
) => {
  const key = storageKey?.trim();

  if (!key) {
    return "";
  }

  if (absoluteUrlPattern.test(key)) {
    return key;
  }

  const normalizedKey = normalizeStorageKey(key);
  const resizedPath = normalizedKey.startsWith("resized/")
    ? normalizedKey
    : `resized/${size}/${normalizedKey}`;

  return resolveCdnUrl(resizedPath);
};
