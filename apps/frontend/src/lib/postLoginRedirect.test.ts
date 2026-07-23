import { describe, expect, it } from "vitest";
import { getPostLoginRedirectPath } from "./postLoginRedirect";

describe("getPostLoginRedirectPath", () => {
  it("redirects admins to the admin dashboard", () => {
    expect(getPostLoginRedirectPath("/", "ADMIN")).toBe("/admin");
    expect(getPostLoginRedirectPath("/cart", "ADMIN")).toBe("/admin");
  });

  it("keeps customer redirects", () => {
    expect(getPostLoginRedirectPath("/products/popular", "USER")).toBe("/products/popular");
    expect(getPostLoginRedirectPath("/checkout?cart_item_ids=1", "USER")).toBe("/cart");
  });
});
