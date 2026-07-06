import { useState } from "react";

const fallbackProductImageUrl = "/spa-assets/product-image-fallback.png";

const hasUsableProductImageUrl = (url: string | null) =>
  Boolean(url && !/(^|\/)(noimg|no-image|no_image|placeholder)[^/]*\.(gif|png|jpe?g|webp)(\?|$)/i.test(url));

type ProductThumbnailProps = {
  src: string | null;
  alt: string;
  className?: string;
};

function ProductThumbnail({ src, alt, className }: ProductThumbnailProps) {
  const [imageFailed, setImageFailed] = useState(false);
  const useFallback = imageFailed || !hasUsableProductImageUrl(src);
  const imageClassName = [className, useFallback ? "product-image-fallback" : ""].filter(Boolean).join(" ");

  return (
    <img
      className={imageClassName}
      src={useFallback ? fallbackProductImageUrl : src ?? ""}
      alt={useFallback ? "" : alt}
      loading="lazy"
      onError={useFallback ? undefined : () => setImageFailed(true)}
    />
  );
}

export default ProductThumbnail;
