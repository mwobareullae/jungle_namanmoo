import { useCallback, useEffect, useRef, useState } from "react";

import type { ApiError } from "../../../types/recommendation";
import {
  AdminProductCreateInput,
  AdminProductDetail,
  AdminProductMasterOption,
  AdminProductUpdateInput,
  createAdminProduct,
  getAdminProductBrands,
  getAdminProductCategories,
  getAdminProductDetail,
  updateAdminProduct
} from "../api/adminProductApi";

export type AdminProductFormValues = {
  name: string;
  brandCode: string;
  categoryCode: string;
  price: string;
  description: string;
  thumbnailStorageKey: string;
  isActive: boolean;
};

const EMPTY_VALUES: AdminProductFormValues = {
  name: "",
  brandCode: "",
  categoryCode: "",
  price: "",
  description: "",
  thumbnailStorageKey: "",
  isActive: false
};

const describeApiError = (caughtError: unknown, fallbackMessage: string): string => {
  const apiError = caughtError as Partial<ApiError> | undefined;
  if (apiError?.status === 401) return "로그인이 필요합니다. 다시 로그인해 주세요.";
  if (apiError?.status === 403) return "관리자 권한이 필요합니다.";
  return apiError?.message ?? fallbackMessage;
};

const valuesFromDetail = (detail: AdminProductDetail): AdminProductFormValues => ({
  name: detail.name,
  brandCode: detail.brandCode,
  categoryCode: detail.categoryCode,
  price: detail.price === null ? "" : String(detail.price),
  description: detail.description ?? "",
  thumbnailStorageKey: detail.thumbnailStorageKey,
  isActive: detail.isActive
});

export function useAdminProductForm({ enabled, productCode }: { enabled: boolean; productCode: string | null }) {
  const [brands, setBrands] = useState<AdminProductMasterOption[]>([]);
  const [categories, setCategories] = useState<AdminProductMasterOption[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminProductDetail | null>(null);
  const [values, setValues] = useState<AdminProductFormValues>(EMPTY_VALUES);
  const [originalValues, setOriginalValues] = useState<AdminProductFormValues>(EMPTY_VALUES);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const loadRequestIdRef = useRef(0);

  useEffect(() => {
    if (!enabled || (brands.length > 0 && categories.length > 0)) return;
    let current = true;
    void Promise.resolve().then(async () => {
      if (!current) return;
      setOptionsLoading(true);
      setOptionsError(null);
      try {
        const [nextBrands, nextCategories] = await Promise.all([
          getAdminProductBrands(),
          getAdminProductCategories()
        ]);
        if (!current) return;
        setBrands(nextBrands);
        setCategories(nextCategories);
      } catch (caughtError: unknown) {
        if (!current) return;
        setOptionsError(describeApiError(caughtError, "브랜드·카테고리 목록을 불러오지 못했습니다."));
      } finally {
        if (current) setOptionsLoading(false);
      }
    });
    return () => {
      current = false;
    };
  }, [enabled, brands.length, categories.length]);

  useEffect(() => {
    if (!enabled) return;
    const requestId = ++loadRequestIdRef.current;
    void Promise.resolve().then(async () => {
      if (requestId !== loadRequestIdRef.current) return;
      setError(null);
      setSavedMessage(null);
      if (productCode === null) {
        setDetail(null);
        setValues(EMPTY_VALUES);
        setOriginalValues(EMPTY_VALUES);
        setLoading(false);
        return;
      }

      setLoading(true);
      try {
        const nextDetail = await getAdminProductDetail(productCode);
        if (requestId !== loadRequestIdRef.current) return;
        const nextValues = valuesFromDetail(nextDetail);
        setDetail(nextDetail);
        setValues(nextValues);
        setOriginalValues(nextValues);
      } catch (caughtError: unknown) {
        if (requestId !== loadRequestIdRef.current) return;
        setDetail(null);
        setError(describeApiError(caughtError, "상품 정보를 불러오지 못했습니다."));
      } finally {
        if (requestId === loadRequestIdRef.current) setLoading(false);
      }
    });
  }, [enabled, productCode]);

  const patchValues = useCallback((patch: Partial<AdminProductFormValues>) => {
    setValues((current) => ({ ...current, ...patch }));
    setSavedMessage(null);
    setError(null);
  }, []);

  const reset = useCallback(() => {
    setValues(originalValues);
    setError(null);
    setSavedMessage(null);
  }, [originalValues]);

  const submit = useCallback(async (): Promise<AdminProductDetail | null> => {
    const name = values.name.trim();
    const price = Number(values.price);
    if (!name) {
      setError("상품명을 입력해 주세요.");
      return null;
    }
    if (!values.brandCode || !values.categoryCode) {
      setError("브랜드와 카테고리를 선택해 주세요.");
      return null;
    }
    if (!Number.isInteger(price) || price <= 0) {
      setError("판매가는 1원 이상의 정수로 입력해 주세요.");
      return null;
    }

    setSubmitting(true);
    setError(null);
    setSavedMessage(null);
    try {
      let result: AdminProductDetail;
      if (productCode === null) {
        const input: AdminProductCreateInput = {
          name,
          brandCode: values.brandCode,
          categoryCode: values.categoryCode,
          price,
          description: values.description.trim() || null,
          thumbnailStorageKey: values.thumbnailStorageKey.trim() || null
        };
        result = await createAdminProduct(input);
      } else {
        const input: AdminProductUpdateInput = {};
        if (name !== originalValues.name.trim()) input.name = name;
        if (values.brandCode !== originalValues.brandCode) input.brandCode = values.brandCode;
        if (values.categoryCode !== originalValues.categoryCode) input.categoryCode = values.categoryCode;
        if (price !== Number(originalValues.price)) input.price = price;
        if (values.description.trim() !== originalValues.description.trim()) {
          input.description = values.description.trim() || null;
        }
        if (values.thumbnailStorageKey.trim() !== originalValues.thumbnailStorageKey.trim()) {
          input.thumbnailStorageKey = values.thumbnailStorageKey.trim() || null;
        }
        if (values.isActive !== originalValues.isActive) input.isActive = values.isActive;
        if (Object.keys(input).length === 0) {
          setSavedMessage("변경된 내용이 없습니다.");
          return null;
        }
        result = await updateAdminProduct(productCode, input);
      }

      const nextValues = valuesFromDetail(result);
      setDetail(result);
      setValues(nextValues);
      setOriginalValues(nextValues);
      setSavedMessage(productCode === null ? "상품을 등록했습니다." : "상품 정보를 수정했습니다.");
      return result;
    } catch (caughtError: unknown) {
      setError(describeApiError(caughtError, "상품을 저장하지 못했습니다."));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, [originalValues, productCode, values]);

  return {
    brands,
    categories,
    optionsLoading,
    optionsError,
    detail,
    values,
    originalValues,
    loading,
    submitting,
    error,
    savedMessage,
    dirty: JSON.stringify(values) !== JSON.stringify(originalValues),
    patchValues,
    reset,
    submit
  };
}
