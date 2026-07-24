export const getPostLoginRedirectPath = (redirectPath: string, role?: string) => {
  if (role === "ADMIN") {
    return "/admin";
  }

  if (redirectPath.startsWith("/checkout")) {
    return "/cart";
  }

  return redirectPath;
};
