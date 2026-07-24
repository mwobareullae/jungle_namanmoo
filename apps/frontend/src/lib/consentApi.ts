import { API_BASE_URL, fetchWithTimeout, parseJson } from "./api";

type MarketingConsentResponse = {
  agreed: boolean;
};

export const getMarketingConsent = async (): Promise<boolean> => {
  const response = await fetchWithTimeout(`${API_BASE_URL}/me/marketing-consent`);
  const data = await parseJson<MarketingConsentResponse>(response);
  return data.agreed;
};

export const updateMarketingConsent = async (agreed: boolean): Promise<boolean> => {
  const response = await fetchWithTimeout(`${API_BASE_URL}/me/marketing-consent`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ agreed })
  });
  const data = await parseJson<MarketingConsentResponse>(response);
  return data.agreed;
};
