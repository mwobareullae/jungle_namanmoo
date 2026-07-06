import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import CommercePageHeader from "../components/CommercePageHeader";
import HomeHeader from "../components/HomeHeader";
import { useAuth } from "../contexts/useAuth";
import { api } from "../lib/api";
import { createAddress, deleteAddress, getAddresses, updateAddress } from "../lib/addressApi";
import { getCart, previewCheckout } from "../lib/cartApi";
import { getProductImageUrl } from "../lib/imageUrls";
import { navigateWithinApp } from "../lib/navigation";
import { createOrder } from "../lib/orderApi";
import type { UserAddress, UserAddressCreateRequest } from "../types/address";
import type { CartItem, CheckoutPreviewResponse } from "../types/cart";
import type { CreateOrderShippingAddress } from "../types/order";
import type { ProductDetail } from "../types/recommendation";

type OrderProduct = {
  id: string;
  productId: string;
  brand: string;
  name: string;
  image: string;
  price: number;
  original: number;
  chips: string[];
};

type ProductLoadState = "idle" | "loading" | "success" | "fallback";
type AddressFormMode = "closed" | "create" | "edit";

type AddressFormState = {
  address_name: string;
  recipient_name: string;
  phone: string;
  postal_code: string;
  address1: string;
  address2: string;
  delivery_memo: string;
  is_default: boolean;
};

type DaumPostcodeData = {
  zonecode: string;
  roadAddress: string;
  jibunAddress: string;
  address: string;
};

type DaumPostcodeInstance = {
  open: () => void;
};

type DaumPostcodeConstructor = new (options: {
  oncomplete: (data: DaumPostcodeData) => void;
}) => DaumPostcodeInstance;

declare global {
  interface Window {
    daum?: {
      Postcode?: DaumPostcodeConstructor;
    };
  }
}

const emptyAddressForm: AddressFormState = {
  address_name: "",
  recipient_name: "",
  phone: "",
  postal_code: "",
  address1: "",
  address2: "",
  delivery_memo: "",
  is_default: false,
};

const PAYMENT_COMPLETE_SNAPSHOT_KEY = "payment_complete_snapshot";
const PENDING_CHECKOUT_PREVIEW_KEY = "pending_checkout_preview";
const FREE_SHIPPING_THRESHOLD = 30000;
const DEFAULT_SHIPPING_FEE = 3000;
const REMOTE_SHIPPING_SURCHARGE = 1500;
const daumPostcodeScriptSrc = "https://t1.daumcdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js";
const remoteShippingKeywords = ["제주", "jeju", "해외", "overseas", "international"];
let daumPostcodeScriptPromise: Promise<void> | null = null;

const isRemoteShippingAddress = (address: string) => {
  const normalizedAddress = address.toLowerCase();
  return remoteShippingKeywords.some((keyword) => normalizedAddress.includes(keyword));
};

const getEstimatedShippingFee = (amount: number, address = "") => {
  if (amount <= 0) return 0;
  const baseShippingFee = amount >= FREE_SHIPPING_THRESHOLD ? 0 : DEFAULT_SHIPPING_FEE;
  return baseShippingFee + (isRemoteShippingAddress(address) ? REMOTE_SHIPPING_SURCHARGE : 0);
};

const loadDaumPostcodeScript = () => {
  if (window.daum?.Postcode) {
    return Promise.resolve();
  }

  if (daumPostcodeScriptPromise) {
    return daumPostcodeScriptPromise;
  }

  daumPostcodeScriptPromise = new Promise<void>((resolve, reject) => {
    const existingScript = document.querySelector<HTMLScriptElement>(
      `script[src="${daumPostcodeScriptSrc}"]`,
    );

    if (existingScript) {
      existingScript.addEventListener("load", () => resolve(), { once: true });
      existingScript.addEventListener("error", () => reject(new Error("주소 찾기 스크립트를 불러오지 못했습니다.")), {
        once: true,
      });
      return;
    }

    const script = document.createElement("script");
    script.src = daumPostcodeScriptSrc;
    script.async = true;
    script.addEventListener("load", () => resolve(), { once: true });
    script.addEventListener("error", () => reject(new Error("주소 찾기 스크립트를 불러오지 못했습니다.")), {
      once: true,
    });
    document.head.appendChild(script);
  });

  return daumPostcodeScriptPromise;
};

const fallbackProducts: OrderProduct[] = [
  {
    id: "10",
    productId: "10",
    brand: "라로슈포제",
    name: "라로슈포제 시카플라스트 밤 B5+ 100ml 기획 (+3ml 추가증정)",
    image: "",
    price: 34850,
    original: 41000,
    chips: ["판테놀", "마데카소사이드", "글리세린"],
  },
  {
    id: "12",
    productId: "12",
    brand: "웰라쥬",
    name: "[속건조필수템] 웰라쥬 리얼 히알루로닉 블루 100 앰플 75ml 2입 기획",
    image: "",
    price: 29800,
    original: 50000,
    chips: ["판테놀", "히알루론산", "글리세린"],
  },
  {
    id: "15",
    productId: "15",
    brand: "라운드랩",
    name: "[6월올영픽/총200ml] 라운드랩 자작나무 수분 크림 80ml+80ml 더블 기획 (+40ml)",
    image: "",
    price: 24600,
    original: 44000,
    chips: ["판테놀", "히알루론산", "글리세린"],
  },
];

const formatWon = (value: number) => `${value.toLocaleString("ko-KR")}원`;
const getCheckoutParams = () => {
  const params = new URLSearchParams(window.location.search);
  const cartItemIds = params
    .getAll("cart_item_ids")
    .map((itemId) => Number(itemId))
    .filter((itemId) => Number.isInteger(itemId) && itemId > 0);

  return {
    selectedId: params.get("id") ?? "",
    mode: params.get("mode") ?? "cart",
    recommendationId: params.get("recommendation_id") ?? undefined,
    skinType: params.get("skin_type") ?? "",
    sensitivity: params.get("sensitivity") ?? "",
    cartItemIds,
  };
};

const getStoredCheckoutPreview = () => {
  try {
    const storedPreview = sessionStorage.getItem(PENDING_CHECKOUT_PREVIEW_KEY);
    if (!storedPreview) return null;

    const parsedPreview = JSON.parse(storedPreview) as CheckoutPreviewResponse;
    if (!Array.isArray(parsedPreview.items) || typeof parsedPreview.total !== "number") {
      return null;
    }

    return parsedPreview;
  } catch {
    return null;
  }
};

const mapDetailToOrderProduct = (product: ProductDetail): OrderProduct => ({
  id: product.product_id,
  productId: product.product_id,
  brand: product.brand,
  name: product.name,
  image: product.thumbnail_url ?? product.image_urls[0] ?? "",
  price: product.lowest_price ?? product.prices[0]?.price ?? 0,
  original: product.lowest_price ?? product.prices[0]?.price ?? 0,
  chips: product.evidence_tags.length > 0 ? product.evidence_tags.slice(0, 3) : product.key_ingredients.slice(0, 3),
});

const mapCartItemToOrderProduct = (item: CartItem): OrderProduct => ({
  id: String(item.id),
  productId: item.product.product_id,
  brand: item.product.brand,
  name: item.product.name,
  image: getProductImageUrl(item.product.thumbnail_url, "w400"),
  price: item.line_subtotal,
  original: item.line_subtotal,
  chips: [],
});

const getCheckoutFieldValue = (id: string) => {
  const element = document.getElementById(id) as HTMLInputElement | HTMLSelectElement | null;
  return element?.value.trim() ?? "";
};

const mapAddressToForm = (address: UserAddress): AddressFormState => ({
  address_name: address.address_name ?? "",
  recipient_name: address.recipient_name,
  phone: address.phone,
  postal_code: address.postal_code,
  address1: address.address1,
  address2: address.address2 ?? "",
  delivery_memo: address.delivery_memo ?? "",
  is_default: address.is_default,
});

function CheckoutPage() {
  const [{ selectedId, mode, recommendationId, skinType, sensitivity, cartItemIds: requestedCartItemIds }] =
    useState(getCheckoutParams);
  const navigate = useNavigate();
  const { isAuthLoading, user } = useAuth();
  const [apiProduct, setApiProduct] = useState<OrderProduct | null>(null);
  const [productLoadState, setProductLoadState] = useState<ProductLoadState>(selectedId ? "loading" : "idle");
  const [checkoutPreview, setCheckoutPreview] = useState<CheckoutPreviewResponse | null>(null);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [isCompletingPayment, setIsCompletingPayment] = useState(false);
  const [previewErrorMessage, setPreviewErrorMessage] = useState("");
  const [orderErrorMessage, setOrderErrorMessage] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("간편결제");
  const [addresses, setAddresses] = useState<UserAddress[]>([]);
  const [selectedAddressId, setSelectedAddressId] = useState<number | null>(null);
  const [isAddressLoading, setIsAddressLoading] = useState(false);
  const [addressErrorMessage, setAddressErrorMessage] = useState("");
  const [directShippingAddressText, setDirectShippingAddressText] = useState("서울특별시 성분구 피부로 12");
  const [directPostalCode, setDirectPostalCode] = useState("");
  const [directAddressDetail, setDirectAddressDetail] = useState("");
  const [isPostcodeLoading, setIsPostcodeLoading] = useState(false);
  const [postcodeErrorMessage, setPostcodeErrorMessage] = useState("");
  const [addressFormMode, setAddressFormMode] = useState<AddressFormMode>("closed");
  const [editingAddressId, setEditingAddressId] = useState<number | null>(null);
  const [addressForm, setAddressForm] = useState<AddressFormState>(emptyAddressForm);
  const [isSavingAddress, setIsSavingAddress] = useState(false);
  const [deletingAddressId, setDeletingAddressId] = useState<number | null>(null);
  const [addressFormErrorMessage, setAddressFormErrorMessage] = useState("");

  useEffect(() => {
    if (!selectedId) {
      return;
    }

    let isMounted = true;

    const loadProduct = async () => {
      setProductLoadState("loading");

      try {
        const product = await api.getProduct(selectedId, recommendationId);
        if (!isMounted) return;
        setApiProduct(mapDetailToOrderProduct(product));
        setProductLoadState("success");
      } catch {
        if (!isMounted) return;
        setApiProduct(null);
        setProductLoadState("fallback");
      }
    };

    loadProduct();

    return () => {
      isMounted = false;
    };
  }, [recommendationId, selectedId]);

  useEffect(() => {
    if (isAuthLoading) {
      return;
    }

    if (!user) {
      navigate("/login", { replace: true, state: { from: "/cart" } });
    }
  }, [isAuthLoading, navigate, user]);

  useEffect(() => {
    if (isAuthLoading) {
      return;
    }

    if (!user) {
      setAddresses([]);
      setSelectedAddressId(null);
      setAddressErrorMessage("");
      setIsAddressLoading(false);
      return;
    }

    let isMounted = true;

    const loadAddresses = async () => {
      setIsAddressLoading(true);
      setAddressErrorMessage("");

      try {
        const response = await getAddresses();
        if (!isMounted) return;

        setAddresses(response.items);
        const defaultAddress = response.items.find((address) => address.is_default) ?? response.items[0] ?? null;
        setSelectedAddressId(defaultAddress?.id ?? null);
      } catch (error) {
        if (!isMounted) return;
        setAddresses([]);
        setSelectedAddressId(null);
        setAddressErrorMessage(error instanceof Error ? error.message : "배송지 목록을 불러오지 못했습니다.");
      } finally {
        if (isMounted) {
          setIsAddressLoading(false);
        }
      }
    };

    void loadAddresses();

    return () => {
      isMounted = false;
    };
  }, [isAuthLoading, user]);

  useEffect(() => {
    if (selectedId) {
      return;
    }

    let isMounted = true;

    const loadCartForPreview = async () => {
      setIsPreviewLoading(true);
      setPreviewErrorMessage("");

      try {
        const cartItemIds = requestedCartItemIds.length > 0
          ? requestedCartItemIds
          : (await getCart()).items.map((item) => item.id);

        if (!isMounted) return;

        if (cartItemIds.length === 0) {
          setCheckoutPreview(null);
          setPreviewErrorMessage("checkout할 장바구니 상품이 없습니다.");
          return;
        }

        const preview = await previewCheckout({
          cart_item_ids: cartItemIds,
          address_id: selectedAddressId,
        });

        if (!isMounted) return;

        setCheckoutPreview(preview);
        sessionStorage.removeItem(PENDING_CHECKOUT_PREVIEW_KEY);
      } catch (error) {
        if (!isMounted) return;
        const storedPreview = requestedCartItemIds.length > 0 ? getStoredCheckoutPreview() : null;
        if (storedPreview) {
          setCheckoutPreview(storedPreview);
          setPreviewErrorMessage("");
          return;
        }

        setCheckoutPreview(null);
        setPreviewErrorMessage(error instanceof Error ? error.message : "checkout 정보를 불러오지 못했습니다.");
      } finally {
        if (isMounted) {
          setIsPreviewLoading(false);
        }
      }
    };

    void loadCartForPreview();

    return () => {
      isMounted = false;
    };
  }, [requestedCartItemIds, selectedAddressId, selectedId]);

  const isResolvingProduct = Boolean(selectedId) && productLoadState === "loading";
  const items = useMemo(() => {
    if (isResolvingProduct || isPreviewLoading) return [];
    if (selectedId) {
      const fallback = fallbackProducts.find((product) => product.id === selectedId);
      return [apiProduct ?? fallback ?? fallbackProducts[0]];
    }
    if (checkoutPreview) {
      return checkoutPreview.items.map(mapCartItemToOrderProduct);
    }
    return [];
  }, [apiProduct, checkoutPreview, isPreviewLoading, isResolvingProduct, selectedId]);

  const selectedAddress = addresses.find((address) => address.id === selectedAddressId) ?? null;
  const selectedAddressLine = selectedAddress ? selectedAddress.address1 : "";
  const shippingAddressText = selectedAddressLine || directShippingAddressText;
  const shippingPostalCode = selectedAddress?.postal_code ?? directPostalCode;
  const shippingAddressDetail = selectedAddress?.address2 ?? directAddressDetail;
  const isCartCheckout = !selectedId;
  const isCheckoutResolving = isResolvingProduct || isPreviewLoading;
  const itemOriginalSubtotal = items.reduce((sum, item) => sum + item.original, 0);
  const itemPayableSubtotal = items.reduce((sum, item) => sum + item.price, 0);
  const subtotal = isCartCheckout && checkoutPreview
    ? checkoutPreview.subtotal
    : itemOriginalSubtotal;
  const shippingBaseAmount = isCartCheckout && checkoutPreview ? checkoutPreview.subtotal : itemPayableSubtotal;
  const shippingFee = getEstimatedShippingFee(shippingBaseAmount, shippingAddressText);
  const total = isCartCheckout && checkoutPreview
    ? checkoutPreview.subtotal + shippingFee
    : itemPayableSubtotal + shippingFee;
  const discount = isCartCheckout && checkoutPreview ? 0 : subtotal - itemPayableSubtotal;
  const itemCount = selectedId ? items.length : checkoutPreview?.items.length ?? 0;
  const title = mode === "buy" ? "바로 구매 주문서" : "장바구니 주문서";
  const subtotalLabel = isCheckoutResolving ? "확인 중" : formatWon(subtotal);
  const shippingFeeLabel = isCheckoutResolving ? "확인 중" : shippingFee === 0 ? "무료" : formatWon(shippingFee);
  const discountLabel = isCheckoutResolving ? "확인 중" : discount > 0 ? `-${formatWon(discount)}` : formatWon(0);
  const totalLabel = isCheckoutResolving ? "확인 중" : formatWon(total);
  const previewStatusText = isPreviewLoading
    ? "주문서 정보를 확인하는 중입니다."
    : previewErrorMessage;
  const previewStatusClassName = `checkout-preview-status${previewErrorMessage ? " error" : ""}`;
  const isCheckoutBlocked = Boolean(isCartCheckout && checkoutPreview && !checkoutPreview.can_checkout);
  const hasBlockingWarning = Boolean(
    isCartCheckout && checkoutPreview?.warnings.some((warning) => warning.severity === "BLOCKING"),
  );
  const checkoutBlockMessage = previewErrorMessage
    || (isCheckoutBlocked
      ? "구매할 수 없는 상품이 포함되어 있습니다. 장바구니에서 상품 상태를 확인해주세요."
      : "")
    || (hasBlockingWarning
      ? "재고 부족 또는 구매 불가 상품이 포함되어 있습니다. 장바구니에서 정리해주세요."
      : "");
  const isPaymentDisabled =
    isCheckoutResolving
    || items.length === 0
    || Boolean(previewErrorMessage)
    || isCheckoutBlocked
    || hasBlockingWarning;
  const paymentButtonDisabled = isPaymentDisabled || isCompletingPayment || isAuthLoading;

  const switchToDirectAddressInput = () => {
    if (selectedAddress) {
      setDirectPostalCode(selectedAddress.postal_code);
      setDirectShippingAddressText(selectedAddress.address1);
      setDirectAddressDetail(selectedAddress.address2 ?? "");
    }

    setSelectedAddressId(null);
  };

  const openDaumPostcode = async (onComplete: (data: DaumPostcodeData) => void) => {
    setIsPostcodeLoading(true);
    setPostcodeErrorMessage("");

    try {
      await loadDaumPostcodeScript();

      if (!window.daum?.Postcode) {
        throw new Error("주소 찾기를 실행할 수 없습니다.");
      }

      new window.daum.Postcode({
        oncomplete: onComplete,
      }).open();
    } catch (error) {
      setPostcodeErrorMessage(error instanceof Error ? error.message : "주소 찾기를 실행하지 못했습니다.");
    } finally {
      setIsPostcodeLoading(false);
    }
  };

  const handleFindDirectAddress = () => {
    void openDaumPostcode((data) => {
      const nextAddress = data.roadAddress || data.jibunAddress || data.address;
      setSelectedAddressId(null);
      setDirectPostalCode(data.zonecode);
      setDirectShippingAddressText(nextAddress);
      setDirectAddressDetail("");

      window.setTimeout(() => {
        document.getElementById("addressDetail")?.focus();
      }, 0);
    });
  };

  const handleFindAddressFormAddress = () => {
    void openDaumPostcode((data) => {
      const nextAddress = data.roadAddress || data.jibunAddress || data.address;
      setAddressForm((currentForm) => ({
        ...currentForm,
        postal_code: data.zonecode,
        address1: nextAddress,
        address2: "",
      }));

      window.setTimeout(() => {
        document.getElementById("addressFormDetail")?.focus();
      }, 0);
    });
  };

  const buildDirectOrderShippingAddress = (): CreateOrderShippingAddress => ({
    address_name: getCheckoutFieldValue("addressName") || null,
    recipient_name: getCheckoutFieldValue("receiverName"),
    phone: getCheckoutFieldValue("receiverPhone"),
    postal_code: getCheckoutFieldValue("postalCode"),
    address1: getCheckoutFieldValue("address"),
    address2: getCheckoutFieldValue("addressDetail") || null,
    delivery_memo: getCheckoutFieldValue("memo") || null,
    save_to_address_book: false,
    set_as_default: false,
  });

  const validateDirectOrderShippingAddress = (shippingAddress: CreateOrderShippingAddress) => {
    if (!shippingAddress.recipient_name) return "받는 분을 입력해주세요.";
    if (!shippingAddress.phone) return "연락처를 입력해주세요.";
    if (!shippingAddress.postal_code) return "우편번호를 입력해주세요.";
    if (!shippingAddress.address1) return "주소를 입력해주세요.";
    return "";
  };

  const handlePayment = async () => {
    if (paymentButtonDisabled) {
      return;
    }

    if (!user) {
      return;
    }

    setIsCompletingPayment(true);
    setOrderErrorMessage("");

    const representative = items[0] ?? fallbackProducts[0];

    try {
      const orderCartItemIds = requestedCartItemIds.length > 0
        ? requestedCartItemIds
        : checkoutPreview?.items.map((item) => item.id) ?? [];

      if (orderCartItemIds.length === 0) {
        throw new Error("주문할 장바구니 상품이 없습니다.");
      }

      const directShippingAddress = selectedAddressId ? null : buildDirectOrderShippingAddress();
      const directAddressValidationMessage = directShippingAddress
        ? validateDirectOrderShippingAddress(directShippingAddress)
        : "";

      if (directAddressValidationMessage) {
        throw new Error(directAddressValidationMessage);
      }

      const order = await createOrder({
        cart_item_ids: orderCartItemIds,
        ...(selectedAddressId
          ? { address_id: selectedAddressId }
          : { shipping_address: directShippingAddress as CreateOrderShippingAddress }),
        payment_provider: "MOCK",
      });

      sessionStorage.removeItem(PENDING_CHECKOUT_PREVIEW_KEY);
      sessionStorage.setItem(PAYMENT_COMPLETE_SNAPSHOT_KEY, JSON.stringify({
        orderCode: order.order_code,
        product: {
          id: representative.productId,
          brand: representative.brand,
          name: representative.name,
          image: representative.image,
        },
        total: order.total,
        count: items.length,
        paymentMethod,
        createdAt: Date.now(),
      }));

      window.dispatchEvent(new Event("cart:updated"));

      const params = new URLSearchParams();
      if (recommendationId) params.set("recommendation_id", recommendationId);
      if (skinType) params.set("skin_type", skinType);
      if (sensitivity) params.set("sensitivity", sensitivity);
      navigateWithinApp(`/payment-complete${params.toString() ? `?${params.toString()}` : ""}`);
    } catch (error) {
      setOrderErrorMessage(error instanceof Error ? error.message : "주문 생성에 실패했습니다.");
    } finally {
      setIsCompletingPayment(false);
    }
  };

  const openCreateAddressForm = () => {
    setAddressFormMode("create");
    setEditingAddressId(null);
    setAddressForm(emptyAddressForm);
    setAddressFormErrorMessage("");
  };

  const openEditAddressForm = (address: UserAddress) => {
    setAddressFormMode("edit");
    setEditingAddressId(address.id);
    setAddressForm(mapAddressToForm(address));
    setAddressFormErrorMessage("");
  };

  const closeAddressForm = () => {
    setAddressFormMode("closed");
    setEditingAddressId(null);
    setAddressForm(emptyAddressForm);
    setIsSavingAddress(false);
    setAddressFormErrorMessage("");
  };

  const updateAddressFormField = <Field extends keyof AddressFormState>(
    field: Field,
    value: AddressFormState[Field],
  ) => {
    setAddressForm((currentForm) => ({
      ...currentForm,
      [field]: value,
    }));
  };

  const buildAddressRequest = (): UserAddressCreateRequest => ({
    address_name: addressForm.address_name.trim() || null,
    recipient_name: addressForm.recipient_name.trim(),
    phone: addressForm.phone.trim(),
    postal_code: addressForm.postal_code.trim(),
    address1: addressForm.address1.trim(),
    address2: addressForm.address2.trim() || null,
    delivery_memo: addressForm.delivery_memo.trim() || null,
    is_default: addressForm.is_default,
  });

  const validateAddressForm = () => {
    if (!addressForm.recipient_name.trim()) return "받는 분을 입력해주세요.";
    if (!addressForm.phone.trim()) return "연락처를 입력해주세요.";
    if (!addressForm.postal_code.trim()) return "우편번호를 입력해주세요.";
    if (!addressForm.address1.trim()) return "주소를 입력해주세요.";
    return "";
  };

  const handleSaveAddress = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const validationMessage = validateAddressForm();
    if (validationMessage) {
      setAddressFormErrorMessage(validationMessage);
      return;
    }

    setIsSavingAddress(true);
    setAddressFormErrorMessage("");

    try {
      const request = buildAddressRequest();
      const savedAddress = addressFormMode === "create"
        ? await createAddress(request)
        : editingAddressId
          ? await updateAddress(editingAddressId, request)
          : null;

      if (!savedAddress) {
        throw new Error("수정할 배송지를 찾을 수 없습니다.");
      }

      const response = await getAddresses();
      setAddresses(response.items);

      const nextSelectedAddress =
        response.items.find((address) => address.id === savedAddress.id)
        ?? response.items.find((address) => address.is_default)
        ?? response.items[0]
        ?? null;

      setSelectedAddressId(nextSelectedAddress?.id ?? null);
      setAddressFormMode("closed");
      setEditingAddressId(null);
      setAddressForm(emptyAddressForm);
    } catch (error) {
      setAddressFormErrorMessage(error instanceof Error ? error.message : "배송지 저장에 실패했습니다.");
    } finally {
      setIsSavingAddress(false);
    }
  };

  const handleDeleteAddress = async (addressId: number) => {
    setDeletingAddressId(addressId);
    setAddressErrorMessage("");
    setAddressFormErrorMessage("");

    try {
      await deleteAddress(addressId);

      const response = await getAddresses();
      setAddresses(response.items);

      const nextSelectedAddress =
        response.items.find((address) => address.id === selectedAddressId)
        ?? response.items.find((address) => address.is_default)
        ?? response.items[0]
        ?? null;

      setSelectedAddressId(nextSelectedAddress?.id ?? null);

      if (editingAddressId === addressId) {
        closeAddressForm();
      }
    } catch (error) {
      setAddressErrorMessage(error instanceof Error ? error.message : "배송지 삭제에 실패했습니다.");
    } finally {
      setDeletingAddressId(null);
    }
  };

  return (
    <>
      <HomeHeader />
      <main className="checkout-page">
        <section className="checkout-shell">
          <CommercePageHeader
            currentStep="checkout"
            description="성분 근거로 고른 상품을 확인하고 배송·결제 정보를 입력해주세요."
            title={title}
          />

          {isCartCheckout && checkoutPreview && checkoutPreview.warnings.length > 0 ? (
            <div className="checkout-warning-list">
              {checkoutPreview.warnings.map((warning) => (
                <div
                  className={`checkout-warning${warning.severity === "BLOCKING" ? " blocking" : ""}`}
                  key={`${warning.code}-${warning.item_id ?? warning.product_id ?? warning.message}`}
                >
                  <strong>{warning.severity === "BLOCKING" ? "구매 불가" : "확인 필요"}</strong>
                  <p>{warning.message}</p>
                </div>
              ))}
            </div>
          ) : null}

          <div className="checkout-layout">
            <div className="checkout-main">
              <section className="checkout-card">
                <div className="checkout-card-head">
                  <h2>주문 상품</h2>
                  <span id="cartCountLabel">
                    {isResolvingProduct || isPreviewLoading ? "상품 확인 중" : `상품 ${itemCount}개`}
                  </span>
                </div>
                <div id="cartItems">
                  {isCheckoutResolving ? (
                    <div className="checkout-empty-state">주문 상품 정보를 불러오는 중입니다.</div>
                  ) : null}
                  {!isResolvingProduct && productLoadState === "fallback" ? (
                    <div className="checkout-empty-state">API 응답 전 원본 샘플 상품으로 주문서를 표시 중입니다.</div>
                  ) : null}
                  {items.map((item) => (
                    <div className="cart-line" key={item.id}>
                      {item.image ? (
                        <img src={item.image} alt={`${item.brand} ${item.name}`} />
                      ) : (
                        <div className="cart-image-empty" aria-label={`${item.brand} ${item.name} 이미지 준비중`}>
                          이미지 준비중
                        </div>
                      )}
                      <div>
                        <div className="cart-brand">{item.brand}</div>
                        <a
                          className="cart-name checkout-product-link"
                          href={`/product-detail?id=${item.productId}`}
                          onClick={(event) => {
                            event.preventDefault();
                            navigateWithinApp(`/product-detail?id=${item.productId}`);
                          }}
                        >
                          {item.name}
                        </a>
                        <div className="cart-meta">
                          {item.chips.map((chip) => <span className="cart-chip" key={chip}>{chip}</span>)}
                        </div>
                      </div>
                      <div>
                        <div className="cart-price">{formatWon(item.price)}</div>
                        <div className="cart-qty">수량 1개</div>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="checkout-card">
                <div className="checkout-card-head">
                  <h2>배송 정보</h2>
                  <span>필수 입력</span>
                </div>
                {user ? (
                  <div className="checkout-address-list">
                    {isAddressLoading ? (
                      <p>배송지를 불러오는 중입니다.</p>
                    ) : null}
                    {addressErrorMessage ? (
                      <p role="alert">{addressErrorMessage}</p>
                    ) : null}
                    {!isAddressLoading && !addressErrorMessage && addresses.length === 0 ? (
                      <p>저장된 배송지가 없습니다. 아래 배송 정보를 직접 입력해주세요.</p>
                    ) : null}
                    {!isAddressLoading && !addressErrorMessage ? (
                      <button className="checkout-address-add-button" type="button" onClick={openCreateAddressForm}>
                        + 새 배송지 추가
                      </button>
                    ) : null}
                    {!isAddressLoading && !addressErrorMessage && addresses.length > 0 ? (
                      addresses.map((address) => (
                        <div
                          className={`checkout-address-option${selectedAddressId === address.id ? " active" : ""}`}
                          key={address.id}
                        >
                          <label className="checkout-address-choice">
                            <input
                              checked={selectedAddressId === address.id}
                              onChange={() => setSelectedAddressId(address.id)}
                              type="radio"
                              name="shippingAddress"
                            />
                            <span>
                              <strong>
                                {address.address_name ? `${address.address_name} · ` : ""}
                                {address.recipient_name}
                                {address.is_default ? " · 기본 배송지" : ""}
                              </strong>
                              <small>{address.phone}</small>
                              <small>{[address.postal_code, address.address1, address.address2].filter(Boolean).join(" ")}</small>
                            </span>
                          </label>
                          <div className="checkout-address-actions">
                            <button
                              type="button"
                              aria-label={`${address.recipient_name} 배송지 수정`}
                              onClick={() => openEditAddressForm(address)}
                            >
                              수정
                            </button>
                            <button
                              type="button"
                              aria-label={`${address.recipient_name} 배송지 삭제`}
                              disabled={deletingAddressId === address.id}
                              onClick={() => {
                                void handleDeleteAddress(address.id);
                              }}
                            >
                              {deletingAddressId === address.id ? "삭제 중" : "삭제"}
                            </button>
                          </div>
                        </div>
                      ))
                    ) : null}
                    {addressFormMode !== "closed" ? (
                      <form
                        className="checkout-address-form"
                        onSubmit={handleSaveAddress}
                      >
                        <div className="checkout-address-form-head">
                          <strong>
                            {addressFormMode === "edit" && editingAddressId ? "배송지 수정" : "새 배송지 추가"}
                          </strong>
                          <button type="button" onClick={closeAddressForm}>
                            취소
                          </button>
                        </div>
                        {addressFormErrorMessage ? (
                          <p role="alert">{addressFormErrorMessage}</p>
                        ) : null}
                        <div className="checkout-address-form-grid">
                          <label>
                            배송지명
                            <input
                              value={addressForm.address_name}
                              onChange={(event) => updateAddressFormField("address_name", event.target.value)}
                              placeholder="집"
                            />
                          </label>
                          <label>
                            받는 분
                            <input
                              value={addressForm.recipient_name}
                              onChange={(event) => updateAddressFormField("recipient_name", event.target.value)}
                              placeholder="나코"
                            />
                          </label>
                          <label>
                            연락처
                            <input
                              value={addressForm.phone}
                              onChange={(event) => updateAddressFormField("phone", event.target.value)}
                              placeholder="010-0000-0000"
                            />
                          </label>
                          <label>
                            우편번호
                            <div className="checkout-postcode-row">
                              <input
                                value={addressForm.postal_code}
                                onChange={(event) => updateAddressFormField("postal_code", event.target.value)}
                                placeholder="12345"
                              />
                              <button
                                type="button"
                                onClick={handleFindAddressFormAddress}
                                disabled={isPostcodeLoading}
                              >
                                주소 찾기
                              </button>
                            </div>
                          </label>
                          <label className="full">
                            주소
                            <input
                              value={addressForm.address1}
                              onChange={(event) => updateAddressFormField("address1", event.target.value)}
                              placeholder="서울특별시 성분구 피부로 12"
                            />
                          </label>
                          <label className="full">
                            상세주소
                            <input
                              id="addressFormDetail"
                              value={addressForm.address2}
                              onChange={(event) => updateAddressFormField("address2", event.target.value)}
                              placeholder="101호"
                            />
                          </label>
                          <label className="full">
                            배송 요청사항
                            <input
                              value={addressForm.delivery_memo}
                              onChange={(event) => updateAddressFormField("delivery_memo", event.target.value)}
                              placeholder="문 앞에 놓아주세요"
                            />
                          </label>
                          <label className="checkout-address-default-check">
                            <input
                              checked={addressForm.is_default}
                              onChange={(event) => updateAddressFormField("is_default", event.target.checked)}
                              type="checkbox"
                            />
                            기본 배송지로 설정
                          </label>
                        </div>
                        <div className="checkout-address-form-actions">
                          <button type="button" onClick={closeAddressForm}>
                            취소
                          </button>
                          <button type="submit" disabled={isSavingAddress}>
                            {isSavingAddress ? "저장 중" : "저장"}
                          </button>
                        </div>
                      </form>
                    ) : null}
                  </div>
                ) : null}
                <div className="form-grid" key={selectedAddressId ?? "manual"}>
                  <div className="form-field">
                    <label htmlFor="addressName">배송지명</label>
                    <input id="addressName" defaultValue={selectedAddress?.address_name ?? "집"} autoComplete="off" />
                  </div>
                  <div className="form-field">
                    <label htmlFor="receiverName">받는 분</label>
                    <input id="receiverName" defaultValue={selectedAddress?.recipient_name ?? "나코"} autoComplete="name" />
                  </div>
                  <div className="form-field">
                    <label htmlFor="receiverPhone">연락처</label>
                    <input id="receiverPhone" defaultValue={selectedAddress?.phone ?? "010-0000-0000"} autoComplete="tel" />
                  </div>
                  <div className="form-field">
                    <label htmlFor="postalCode">우편번호</label>
                    <div className="checkout-postcode-row">
                      <input
                        id="postalCode"
                        value={shippingPostalCode}
                        onChange={(event) => {
                          switchToDirectAddressInput();
                          setDirectPostalCode(event.target.value);
                        }}
                        autoComplete="postal-code"
                      />
                      <button
                        type="button"
                        onClick={handleFindDirectAddress}
                        disabled={isPostcodeLoading}
                      >
                        {isPostcodeLoading ? "검색 중" : "주소 찾기"}
                      </button>
                    </div>
                    {postcodeErrorMessage ? (
                      <small className="checkout-postcode-error" role="alert">{postcodeErrorMessage}</small>
                    ) : null}
                  </div>
                  <div className="form-field full">
                    <label htmlFor="address">주소</label>
                    <input
                      id="address"
                      value={shippingAddressText}
                      onChange={(event) => {
                        switchToDirectAddressInput();
                        setDirectShippingAddressText(event.target.value);
                      }}
                      autoComplete="street-address"
                    />
                  </div>
                  <div className="form-field full">
                    <label htmlFor="addressDetail">상세주소</label>
                    <input
                      id="addressDetail"
                      value={shippingAddressDetail}
                      onChange={(event) => {
                        switchToDirectAddressInput();
                        setDirectAddressDetail(event.target.value);
                      }}
                      autoComplete="address-line2"
                    />
                  </div>
                  <div className="form-field full">
                    <label htmlFor="memo">배송 요청사항</label>
                    <select id="memo" defaultValue={selectedAddress?.delivery_memo ?? "문 앞에 놓아주세요"}>
                      <option>문 앞에 놓아주세요</option>
                      <option>경비실에 맡겨주세요</option>
                      <option>배송 전 연락주세요</option>
                    </select>
                  </div>
                </div>
              </section>

              <section className="checkout-card">
                <div className="checkout-card-head">
                  <h2>결제 수단</h2>
                  <span>선택 1개</span>
                </div>
                <div className="payment-options">
                  {["간편결제", "신용카드", "무통장입금"].map((method) => (
                    <button
                      className={`payment-option${paymentMethod === method ? " active" : ""}`}
                      onClick={() => setPaymentMethod(method)}
                      type="button"
                      key={method}
                    >
                      {method}
                    </button>
                  ))}
                </div>
              </section>
            </div>

            <aside className="order-summary">
              <h2>결제 금액</h2>
              <div className="summary-row">
                <span>상품 금액</span>
                <strong id="summarySubtotal">{subtotalLabel}</strong>
              </div>
              <div className="summary-row">
                <span>상품 할인</span>
                <strong id="summaryDiscount">{discountLabel}</strong>
              </div>
              <div className="summary-row">
                <span>배송비</span>
                <strong>{shippingFeeLabel}</strong>
              </div>
              <div className="summary-divider" />
              <div className="summary-total">
                <span>총 결제금액</span>
                <strong id="summaryTotal">{totalLabel}</strong>
              </div>
              {false && checkoutBlockMessage ? (
                <div className="summary-blocking-note">
                  <p>{checkoutBlockMessage}</p>
                  <button type="button" onClick={() => navigateWithinApp("/cart")}>
                    장바구니로 돌아가기
                  </button>
                </div>
              ) : null}
              {orderErrorMessage ? (
                <p className="summary-note" role="alert">{orderErrorMessage}</p>
              ) : null}
              <button className="checkout-btn-main" type="button" onClick={handlePayment} disabled={paymentButtonDisabled}>
                {isCompletingPayment ? "결제 처리 중" : "결제하기"}
              </button>
              <p className="summary-note">결제하기를 누르면 주문 내용을 확인한 것으로 간주됩니다. 실제 결제는 연결되지 않은 시안 화면입니다.</p>
            </aside>
          </div>
        </section>
      </main>

      <div className="mobile-pay-bar">
        <div className="mobile-pay-total">
          <span>총 결제금액</span>
          <strong id="mobileTotal">{totalLabel}</strong>
        </div>
        <button className="checkout-btn-main" type="button" onClick={handlePayment} disabled={paymentButtonDisabled}>
          {isCompletingPayment ? "결제 처리 중" : "결제하기"}
        </button>
      </div>
    </>
  );
}

export default CheckoutPage;
