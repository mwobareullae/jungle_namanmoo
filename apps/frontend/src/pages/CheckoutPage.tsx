import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { ANONYMOUS, loadTossPayments, type TossPaymentsSDK } from "@tosspayments/tosspayments-sdk";
import { useLocation, useNavigate } from "react-router-dom";
import CommercePageHeader from "../components/CommercePageHeader";
import HomeHeader from "../components/HomeHeader";
import { Dialog, DialogClose, DialogRawContent } from "../components/ui/dialog";
import { useAuth } from "../contexts/useAuth";
import { useCartQuery } from "../hooks/useCartQuery";
import { api } from "../lib/api";
import { createAddress, deleteAddress, getAddresses, updateAddress } from "../lib/addressApi";
import {
  digitsOnly,
  emptyPhoneParts,
  hasText,
  isCompletePhone,
  joinPhone,
  sanitizeRecipientName,
  splitPhone
} from "../lib/addressValidation";
import { previewCheckout } from "../lib/cartApi";
import { getProductImageUrl } from "../lib/imageUrls";
import { navigateWithinApp } from "../lib/navigation";
import { cancelOrder, createOrder } from "../lib/orderApi";
import type { UserAddress, UserAddressCreateRequest } from "../types/address";
import type { CartItem, CheckoutPreviewResponse } from "../types/cart";
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
  quantity: number;
};

type ProductLoadState = "idle" | "loading" | "success" | "fallback";
type AddressFormMode = "closed" | "create" | "edit";
type CashReceiptMode = "personal" | "business";

type AddressFormState = {
  recipient_name: string;
  phone_first: string;
  phone_middle: string;
  phone_last: string;
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
  recipient_name: "",
  phone_first: emptyPhoneParts.first,
  phone_middle: emptyPhoneParts.middle,
  phone_last: emptyPhoneParts.last,
  postal_code: "",
  address1: "",
  address2: "",
  delivery_memo: "",
  is_default: false,
};

const PAYMENT_COMPLETE_SNAPSHOT_KEY = "payment_complete_snapshot";
const PENDING_CHECKOUT_PREVIEW_KEY = "pending_checkout_preview";
const CARD_COMPANIES = [
  "KB카드",
  "현대카드",
  "삼성카드",
  "신한카드",
  "롯데카드",
  "BC카드",
  "하나(외환)카드",
  "NH카드",
  "우리카드",
  "카카오뱅크",
  "씨티카드",
  "광주비자",
  "전북카드",
  "신협카드",
  "수협카드",
  "제주카드",
];
const INSTALLMENT_OPTIONS = [
  "일시불",
  "2개월",
  "3개월",
  "4개월",
  "5개월",
  "6개월",
  "7개월",
  "8개월",
  "9개월",
  "10개월",
  "11개월",
  "12개월",
];
const BANK_OPTIONS = [
  "우리은행",
  "신한은행",
  "하나은행",
  "SC은행",
  "국민은행",
  "우체국",
  "기업은행",
  "농협",
  "외환은행",
  "부산은행",
];
const CASH_RECEIPT_PERSONAL_METHODS = ["휴대폰 번호로 발급", "현금영수증 카드로 발급"];
const CASH_RECEIPT_BUSINESS_METHODS = ["사업자등록번호로 발급"];
const DELIVERY_MEMO_OPTIONS = [
  "배송시 요청사항을 선택해 주세요.",
  "직접 수령하겠습니다.",
  "배송 전 연락바랍니다.",
  "부재 시 경비실에 맡겨주세요.",
  "부재 시 문 앞에 놓아주세요.",
  "부재 시 택배함에 넣어주세요.",
  "직접 입력",
];
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
    quantity: 1,
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
    quantity: 1,
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
    quantity: 1,
  },
];

const formatWon = (value: number) => `${value.toLocaleString("ko-KR")}원`;

const getTossCustomerKey = (userId?: number) => {
  return userId ? `mwb_user_${userId}` : ANONYMOUS;
};

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
    agentOrderCode: params.get("agent_order_code") ?? "",
    agentAmount: Number(params.get("agent_amount") ?? 0),
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
  quantity: 1,
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
  quantity: item.quantity,
});

const mapAddressToForm = (address: UserAddress): AddressFormState => ({
  recipient_name: address.recipient_name,
  phone_first: splitPhone(address.phone).first,
  phone_middle: splitPhone(address.phone).middle,
  phone_last: splitPhone(address.phone).last,
  postal_code: address.postal_code,
  address1: address.address1,
  address2: address.address2 ?? "",
  delivery_memo: address.delivery_memo ?? "",
  is_default: address.is_default,
});

function CheckoutPage() {
  const [{ selectedId, mode, recommendationId, skinType, sensitivity, cartItemIds: requestedCartItemIds }] =
    useState(getCheckoutParams);
  const location = useLocation();
  const navigate = useNavigate();
  const agentPaymentParams = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const agentOrderCode = agentPaymentParams.get("agent_order_code") ?? "";
  const agentAmount = Number(agentPaymentParams.get("agent_amount") ?? 0);
  const { isAuthLoading, user } = useAuth();
  const cartQuery = useCartQuery(user?.id ?? null);
  const [apiProduct, setApiProduct] = useState<OrderProduct | null>(null);
  const [productLoadState, setProductLoadState] = useState<ProductLoadState>(selectedId ? "loading" : "idle");
  const [checkoutPreview, setCheckoutPreview] = useState<CheckoutPreviewResponse | null>(null);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [isCompletingPayment, setIsCompletingPayment] = useState(false);
  const [previewErrorMessage, setPreviewErrorMessage] = useState("");
  const [orderErrorMessage, setOrderErrorMessage] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("간편결제");
  const [selectedCardCompany, setSelectedCardCompany] = useState("");
  const [selectedInstallment, setSelectedInstallment] = useState("일시불");
  const [selectedBank, setSelectedBank] = useState("");
  const [cashReceiptEnabled, setCashReceiptEnabled] = useState(true);
  const [cashReceiptMode, setCashReceiptMode] = useState<CashReceiptMode>("personal");
  const [isCashReceiptEditing, setIsCashReceiptEditing] = useState(false);
  const [cashReceiptIssueMethod, setCashReceiptIssueMethod] = useState(CASH_RECEIPT_PERSONAL_METHODS[0]);
  const [cashReceiptPhonePrefix, setCashReceiptPhonePrefix] = useState("010");
  const [cashReceiptPhoneMiddle, setCashReceiptPhoneMiddle] = useState("5670");
  const [cashReceiptPhoneLast, setCashReceiptPhoneLast] = useState("2965");
  const [cashReceiptBusinessPart1, setCashReceiptBusinessPart1] = useState("");
  const [cashReceiptBusinessPart2, setCashReceiptBusinessPart2] = useState("");
  const [cashReceiptBusinessPart3, setCashReceiptBusinessPart3] = useState("");
  const [isCashReceiptGuideOpen, setIsCashReceiptGuideOpen] = useState(false);
  const [tossPayments, setTossPayments] = useState<TossPaymentsSDK | null>(null);
  const [isTossSdkLoading, setIsTossSdkLoading] = useState(false);
  const [tossSdkErrorMessage, setTossSdkErrorMessage] = useState("");
  const [hasAgreedPayment, setHasAgreedPayment] = useState(false);
  const agentPaymentStartedRef = useRef(false);
  const [addresses, setAddresses] = useState<UserAddress[]>([]);
  const [selectedAddressId, setSelectedAddressId] = useState<number | null>(null);
  const [isAddressLoading, setIsAddressLoading] = useState(false);
  const [addressErrorMessage, setAddressErrorMessage] = useState("");
  const [isPostcodeLoading, setIsPostcodeLoading] = useState(false);
  const [postcodeErrorMessage, setPostcodeErrorMessage] = useState("");
  const [isAddressManagerOpen, setIsAddressManagerOpen] = useState(false);
  const [deliveryMemoOption, setDeliveryMemoOption] = useState("부재 시 문 앞에 놓아주세요.");
  const [directDeliveryMemo, setDirectDeliveryMemo] = useState("");
  const [addressFormMode, setAddressFormMode] = useState<AddressFormMode>("closed");
  const [editingAddressId, setEditingAddressId] = useState<number | null>(null);
  const [addressForm, setAddressForm] = useState<AddressFormState>(emptyAddressForm);
  const [isSavingAddress, setIsSavingAddress] = useState(false);
  const [deletingAddressId, setDeletingAddressId] = useState<number | null>(null);
  const [defaultingAddressId, setDefaultingAddressId] = useState<number | null>(null);
  const [addressFormErrorMessage, setAddressFormErrorMessage] = useState("");
  const tossClientKey = import.meta.env.VITE_TOSS_CLIENT_KEY ?? "";

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
    if (!tossClientKey) {
      return;
    }

    let isMounted = true;

    const loadTossSdk = async () => {
      setIsTossSdkLoading(true);
      setTossSdkErrorMessage("");

      try {
        const loadedTossPayments = await loadTossPayments(tossClientKey);

        if (isMounted) {
          setTossPayments(loadedTossPayments);
        }
      } catch (error) {
        if (isMounted) {
          setTossPayments(null);
          setTossSdkErrorMessage(error instanceof Error ? error.message : "토스페이먼츠 SDK를 불러오지 못했습니다.");
        }
      } finally {
        if (isMounted) {
          setIsTossSdkLoading(false);
        }
      }
    };

    void loadTossSdk();

    return () => {
      isMounted = false;
    };
  }, [tossClientKey]);

  useEffect(() => {
    if (!agentOrderCode || agentAmount <= 0 || !tossPayments || !user || agentPaymentStartedRef.current) {
      return;
    }
    agentPaymentStartedRef.current = true;
    setIsCompletingPayment(true);
    setOrderErrorMessage("");
    const successParams = new URLSearchParams({ provider: "toss", order_code: agentOrderCode });
    const failParams = new URLSearchParams({ payment_failed: "1", order_code: agentOrderCode });
    const payment = tossPayments.payment({ customerKey: getTossCustomerKey(user.id) });
    payment.requestPayment({
      method: "CARD",
      amount: { currency: "KRW", value: agentAmount },
      orderId: agentOrderCode,
      orderName: "뭐바를래 주문",
      successUrl: `${window.location.origin}/payment-complete?${successParams.toString()}`,
      failUrl: `${window.location.origin}/payment-complete?${failParams.toString()}`,
      customerEmail: user.email,
      customerName: user.nickname ?? user.email,
      card: { flowMode: "DIRECT", easyPay: "TOSSPAY" },
    }).catch((error) => {
      agentPaymentStartedRef.current = false;
      setOrderErrorMessage(error instanceof Error ? error.message : "Toss 결제창을 열지 못했습니다.");
      setIsCompletingPayment(false);
    });
  }, [agentAmount, agentOrderCode, tossPayments, user]);

  useEffect(() => {
    if (agentOrderCode) {
      return;
    }
    if (selectedId) {
      return;
    }
    if (requestedCartItemIds.length === 0 && cartQuery.isLoading) {
      return;
    }

    let isMounted = true;

    const loadCartForPreview = async () => {
      setIsPreviewLoading(true);
      setPreviewErrorMessage("");

      try {
        const cartItemIds = requestedCartItemIds.length > 0
          ? requestedCartItemIds
          : (cartQuery.data?.items ?? []).map((item) => item.id);

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
  }, [agentOrderCode, cartQuery.data, cartQuery.isLoading, requestedCartItemIds, selectedAddressId, selectedId]);

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
  const shippingAddressText = selectedAddress?.address1 ?? "";
  const isCartCheckout = !selectedId;
  const isCheckoutResolving = isResolvingProduct || isPreviewLoading;
  const itemOriginalSubtotal = items.reduce((sum, item) => sum + item.original, 0);
  const itemPayableSubtotal = items.reduce((sum, item) => sum + item.price, 0);
  const subtotal = isCartCheckout && checkoutPreview
    ? checkoutPreview.subtotal
    : itemOriginalSubtotal;
  const shippingFee = isCartCheckout && checkoutPreview
    ? checkoutPreview.shipping_fee
    : getEstimatedShippingFee(itemPayableSubtotal, shippingAddressText);
  const total = isCartCheckout && checkoutPreview
    ? checkoutPreview.total
    : itemPayableSubtotal + shippingFee;
  const discount = isCartCheckout && checkoutPreview ? 0 : subtotal - itemPayableSubtotal;
  const itemCount = selectedId ? items.length : checkoutPreview?.items.length ?? 0;
  const title = mode === "buy" ? "바로 구매 주문서" : "장바구니 주문서";
  const subtotalLabel = isCheckoutResolving ? "확인 중" : formatWon(subtotal);
  const shippingFeeLabel = isCheckoutResolving ? "확인 중" : shippingFee === 0 ? "무료" : formatWon(shippingFee);
  const discountLabel = isCheckoutResolving ? "확인 중" : discount > 0 ? `-${formatWon(discount)}` : formatWon(0);
  const totalLabel = isCheckoutResolving ? "확인 중" : formatWon(total);
  const expectedPointAmount = Math.floor(total * 0.01);
  const pointEarnNote = isCheckoutResolving ? "" : `결제 후 최대 ${expectedPointAmount.toLocaleString("ko-KR")}원 적립`;
  const isCardPaymentReady = paymentMethod !== "신용카드" || Boolean(selectedCardCompany);
  const isBankTransferReady = paymentMethod !== "무통장입금" || Boolean(selectedBank);
  const cashReceiptDisplayType = cashReceiptMode === "personal" ? "개인소득공제" : "사업자 지출증빙";
  const cashReceiptDisplayNumber = cashReceiptMode === "personal"
    ? [cashReceiptPhonePrefix, cashReceiptPhoneMiddle, cashReceiptPhoneLast].filter(Boolean).join("-")
    : [cashReceiptBusinessPart1, cashReceiptBusinessPart2, cashReceiptBusinessPart3].filter(Boolean).join("-");
  const selectedPaymentLabel = paymentMethod === "신용카드"
    ? `신용카드${selectedCardCompany ? ` (${selectedCardCompany}, ${selectedInstallment})` : ""}`
    : paymentMethod === "간편결제"
      ? "토스페이먼츠"
      : paymentMethod === "무통장입금" && selectedBank
        ? `무통장입금 (${selectedBank})`
        : paymentMethod;
  const isCheckoutBlocked = Boolean(isCartCheckout && checkoutPreview && !checkoutPreview.can_checkout);
  const hasBlockingWarning = Boolean(
    isCartCheckout && checkoutPreview?.warnings.some((warning) => warning.severity === "BLOCKING"),
  );
  const isPaymentDisabled =
    isCheckoutResolving
    || isAddressLoading
    || items.length === 0
    || !selectedAddress
    || !hasAgreedPayment
    || !isCardPaymentReady
    || !isBankTransferReady
    || Boolean(previewErrorMessage)
    || isCheckoutBlocked
    || hasBlockingWarning;
  const paymentButtonDisabled = isPaymentDisabled || isCompletingPayment || isAuthLoading;

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
    const isTossPayment = true;

    try {
      if (isTossPayment && !tossPayments) {
        throw new Error("토스페이먼츠 SDK가 아직 준비되지 않았습니다. 잠시 후 다시 시도해주세요.");
      }

      if (agentOrderCode && agentAmount > 0 && tossPayments) {
        const successParams = new URLSearchParams({ provider: "toss", order_code: agentOrderCode });
        const failParams = new URLSearchParams({ payment_failed: "1", order_code: agentOrderCode });
        const payment = tossPayments.payment({ customerKey: getTossCustomerKey(user.id) });
        await payment.requestPayment({
          method: "CARD",
          amount: { currency: "KRW", value: agentAmount },
          orderId: agentOrderCode,
          orderName: items.length > 1 ? `${representative.name} 외 ${items.length - 1}개` : representative.name,
          successUrl: `${window.location.origin}/payment-complete?${successParams.toString()}`,
          failUrl: `${window.location.origin}/payment-complete?${failParams.toString()}`,
          customerEmail: user.email,
          customerName: user.nickname ?? user.email,
          card: { flowMode: "DIRECT", easyPay: "TOSSPAY" },
        });
        return;
      }

      const orderCartItemIds = requestedCartItemIds.length > 0
        ? requestedCartItemIds
        : checkoutPreview?.items.map((item) => item.id) ?? [];

      if (orderCartItemIds.length === 0) {
        throw new Error("주문할 장바구니 상품이 없습니다.");
      }

      if (!selectedAddress) {
        throw new Error("배송지를 추가하거나 선택해주세요.");
      }

      const order = await createOrder({
        cart_item_ids: orderCartItemIds,
        address_id: selectedAddress.id,
        payment_provider: "TOSS",
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
        products: items.map((item) => ({
          id: item.productId,
          brand: item.brand,
          name: item.name,
          image: item.image,
          price: item.price,
          quantity: item.quantity,
          option: item.chips[0] ?? "",
        })),
        total: order.total,
        count: items.length,
        paymentMethod: selectedPaymentLabel,
        shippingAddress: [selectedAddress.address1, selectedAddress.address2].filter(Boolean).join(" "),
        createdAt: Date.now(),
      }));

      const params = new URLSearchParams();
      if (recommendationId) params.set("recommendation_id", recommendationId);
      if (skinType) params.set("skin_type", skinType);
      if (sensitivity) params.set("sensitivity", sensitivity);

      if (isTossPayment) {
        const readyTossPayments = tossPayments;
        if (!readyTossPayments) {
          throw new Error("토스페이먼츠 SDK가 아직 준비되지 않았습니다. 잠시 후 다시 시도해주세요.");
        }

        const successParams = new URLSearchParams(params);
        successParams.set("provider", "toss");
        successParams.set("order_code", order.order_code);

        const failParams = new URLSearchParams(params);
        failParams.set("payment_failed", "1");
        failParams.set("order_code", order.order_code);

        const payment = readyTossPayments.payment({
          customerKey: getTossCustomerKey(user.id),
        });

        try {
          await payment.requestPayment({
            method: "CARD",
            amount: {
              currency: "KRW",
              value: order.total,
            },
            orderId: order.order_code,
            orderName: items.length > 1 ? `${representative.name} 외 ${items.length - 1}개` : representative.name,
            successUrl: `${window.location.origin}/payment-complete?${successParams.toString()}`,
            failUrl: `${window.location.origin}/payment-complete?${failParams.toString()}`,
            customerEmail: user.email,
            customerName: user.nickname ?? user.email,
            card: {
              flowMode: "DIRECT",
              easyPay: "TOSSPAY",
            },
          });
        } catch (paymentError) {
          sessionStorage.removeItem(PAYMENT_COMPLETE_SNAPSHOT_KEY);
          try {
            await cancelOrder(order.order_code);
            window.dispatchEvent(new Event("cart:updated"));
            navigateWithinApp("/cart");
            return;
          } catch {
            throw paymentError;
          }
        }
        return;
      }

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

  const openAddressManager = () => {
    setIsAddressManagerOpen(true);
    setAddressErrorMessage("");
  };

  const closeAddressManager = () => {
    setIsAddressManagerOpen(false);
    closeAddressForm();
  };

  const handleSelectAddress = (addressId: number) => {
    setSelectedAddressId(addressId);
    setIsAddressManagerOpen(false);
    closeAddressForm();
  };

  const handleSetDefaultAddress = async (address: UserAddress) => {
    setDefaultingAddressId(address.id);
    setAddressErrorMessage("");
    setAddressFormErrorMessage("");

    try {
      const savedAddress = await updateAddress(address.id, { is_default: true });
      const response = await getAddresses();
      setAddresses(response.items);
      setSelectedAddressId(savedAddress.id);
    } catch (error) {
      setAddressErrorMessage(error instanceof Error ? error.message : "기본 배송지 설정에 실패했습니다.");
    } finally {
      setDefaultingAddressId(null);
    }
  };

  const updateAddressFormField = <Field extends keyof AddressFormState>(
    field: Field,
    value: AddressFormState[Field],
  ) => {
    const normalizedValue = typeof value === "string"
      ? field === "recipient_name"
        ? sanitizeRecipientName(value)
        : field === "phone_first" || field === "phone_middle" || field === "phone_last" || field === "postal_code"
          ? digitsOnly(value)
          : value
      : value;
    setAddressForm((currentForm) => ({
      ...currentForm,
      [field]: normalizedValue,
    }));
  };

  const buildAddressRequest = (): UserAddressCreateRequest => ({
    recipient_name: addressForm.recipient_name.trim(),
    phone: joinPhone({
      first: addressForm.phone_first,
      middle: addressForm.phone_middle,
      last: addressForm.phone_last
    }),
    postal_code: addressForm.postal_code.trim(),
    address1: addressForm.address1.trim(),
    address2: addressForm.address2.trim() || null,
    delivery_memo: addressForm.delivery_memo.trim() || null,
    is_default: addressForm.is_default,
  });

  const validateAddressForm = () => {
    if (!hasText(addressForm.recipient_name)) return "받는 분을 입력해주세요.";
    if (!isCompletePhone({
      first: addressForm.phone_first,
      middle: addressForm.phone_middle,
      last: addressForm.phone_last
    })) return "연락처를 입력해주세요.";
    if (!hasText(addressForm.postal_code)) return "우편번호를 입력해주세요.";
    if (!hasText(addressForm.address1)) return "주소를 입력해주세요.";
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
                  <h2>
                    주문 상품
                    <span className="checkout-card-title-count" id="cartCountLabel">
                      {isResolvingProduct || isPreviewLoading ? "상품 확인 중" : `상품 ${itemCount}개`}
                    </span>
                  </h2>
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
                          <span className="cart-qty">수량 {item.quantity}개</span>
                        </div>
                      </div>
                      <div>
                        <div className="cart-price">{formatWon(item.price)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="checkout-card">
                <div className="checkout-card-head">
                  <h2>배송지</h2>
                  {selectedAddress ? (
                    <button className="checkout-address-change-button" type="button" onClick={openAddressManager}>
                      변경
                    </button>
                  ) : null}
                </div>
                {isAddressLoading ? (
                  <div className="checkout-address-summary muted">배송지를 불러오는 중입니다.</div>
                ) : null}
                {addressErrorMessage ? (
                  <p className="checkout-address-error" role="alert">{addressErrorMessage}</p>
                ) : null}
                {!isAddressLoading && selectedAddress ? (
                  <div className="checkout-address-summary">
                    <div className="checkout-address-recipient">
                      <strong>{selectedAddress.recipient_name}</strong>
                      {selectedAddress.is_default ? <span>기본 배송지</span> : null}
                    </div>
                    <p>{[selectedAddress.address1, selectedAddress.address2].filter(Boolean).join(", ")}</p>
                    <p>{selectedAddress.phone}</p>
                    <select
                      id="memo"
                      value={deliveryMemoOption}
                      onChange={(event) => setDeliveryMemoOption(event.target.value)}
                    >
                      {DELIVERY_MEMO_OPTIONS.map((option) => (
                        <option value={option} key={option}>{option}</option>
                      ))}
                    </select>
                    {deliveryMemoOption === "직접 입력" ? (
                      <input
                        id="directMemo"
                        className="checkout-direct-memo-input"
                        value={directDeliveryMemo}
                        onChange={(event) => setDirectDeliveryMemo(event.target.value.slice(0, 50))}
                        maxLength={50}
                        placeholder="부재 시 문 앞에 놓아주세요."
                      />
                    ) : null}
                  </div>
                ) : null}
                {!isAddressLoading && !selectedAddress ? (
                  <div className="checkout-address-summary muted">
                    <strong>아직 등록된 배송지가 없어요</strong>
                    <button className="checkout-address-add-button" type="button" onClick={openAddressManager}>
                      + 배송지 추가
                    </button>
                  </div>
                ) : null}
              </section>

              <section className="checkout-card">
                <div className="checkout-card-head">
                  <h2>결제 수단</h2>
                </div>
                <div className="payment-options">
                  {["간편결제"].map((method) => (
                    <button
                      aria-pressed={paymentMethod === method}
                      className={`payment-option${paymentMethod === method ? " active" : ""}`}
                      onClick={() => setPaymentMethod(method)}
                      type="button"
                      key={method}
                    >
                      {method}
                    </button>
                  ))}
                </div>
                {paymentMethod === "간편결제" ? (
                  <div className="checkout-payment-detail">
                    <div className="checkout-payment-info">
                      {!tossClientKey ? (
                        <p>프론트 환경변수 VITE_TOSS_CLIENT_KEY 설정 후 결제창 연동을 진행할 수 있습니다.</p>
                      ) : null}
                      {tossClientKey && isTossSdkLoading ? (
                        <p>결제창을 준비하고 있습니다.</p>
                      ) : null}
                      {tossClientKey && !isTossSdkLoading && tossSdkErrorMessage ? (
                        <p role="alert">{tossSdkErrorMessage}</p>
                      ) : null}
                      {tossClientKey && !isTossSdkLoading && !tossSdkErrorMessage ? (
                        <p>결제하기를 누르면 토스페이먼츠 통합 결제창에서 간편결제를 선택할 수 있습니다.</p>
                      ) : null}
                    </div>
                  </div>
                ) : null}
                {paymentMethod === "신용카드" ? (
                  <div className="checkout-card-payment-fields">
                    <label htmlFor="cardCompany">카드종류</label>
                    <select
                      id="cardCompany"
                      value={selectedCardCompany}
                      onChange={(event) => setSelectedCardCompany(event.target.value)}
                    >
                      <option value="">카드를 선택해주세요.</option>
                      {CARD_COMPANIES.map((cardCompany) => (
                        <option value={cardCompany} key={cardCompany}>{cardCompany}</option>
                      ))}
                    </select>
                    <label htmlFor="installmentPlan">할부종류</label>
                    <select
                      id="installmentPlan"
                      value={selectedInstallment}
                      onChange={(event) => setSelectedInstallment(event.target.value)}
                    >
                      {INSTALLMENT_OPTIONS.map((installment) => (
                        <option value={installment} key={installment}>{installment}</option>
                      ))}
                    </select>
                  </div>
                ) : null}
                {paymentMethod === "무통장입금" ? (
                  <>
                    <div className="checkout-card-payment-fields checkout-bank-payment-fields">
                      <label htmlFor="bankName">은행 선택</label>
                      <select
                        id="bankName"
                        value={selectedBank}
                        onChange={(event) => setSelectedBank(event.target.value)}
                      >
                        <option value="">은행을 선택해주세요.</option>
                        {BANK_OPTIONS.map((bank) => (
                          <option value={bank} key={bank}>{bank}</option>
                        ))}
                      </select>
                    </div>

                    <section className={`checkout-cash-receipt${isCashReceiptEditing ? " editing" : ""}`}>
                      {!isCashReceiptEditing ? (
                        <div className="checkout-cash-receipt-summary">
                          <label className="checkout-cash-receipt-check">
                            <input
                              type="checkbox"
                              checked={cashReceiptEnabled}
                              onChange={(event) => setCashReceiptEnabled(event.target.checked)}
                            />
                            <span>현금영수증 신청</span>
                            <button
                              className="checkout-cash-receipt-help"
                              type="button"
                              aria-label="현금영수증 안내 보기"
                              onClick={(event) => {
                                event.preventDefault();
                                setIsCashReceiptGuideOpen(true);
                              }}
                            >
                              i
                            </button>
                          </label>
                          {cashReceiptEnabled ? (
                            <>
                              <strong>{cashReceiptDisplayType}</strong>
                              <span>{cashReceiptDisplayNumber || "번호 미입력"}</span>
                            </>
                          ) : (
                            <span className="checkout-cash-receipt-muted">신청 안 함</span>
                          )}
                          <button type="button" onClick={() => setIsCashReceiptEditing(true)}>
                            수정
                          </button>
                        </div>
                      ) : (
                        <div className="checkout-cash-receipt-editor">
                          <div className="checkout-cash-receipt-head">
                            <label className="checkout-cash-receipt-check">
                              <input
                                type="checkbox"
                                checked={cashReceiptEnabled}
                                onChange={(event) => setCashReceiptEnabled(event.target.checked)}
                              />
                              <span>현금영수증 신청</span>
                              <button
                                className="checkout-cash-receipt-help"
                                type="button"
                                aria-label="현금영수증 안내 보기"
                                onClick={(event) => {
                                  event.preventDefault();
                                  setIsCashReceiptGuideOpen(true);
                                }}
                              >
                                i
                              </button>
                            </label>
                            <div className="checkout-cash-receipt-actions">
                              <button type="button" onClick={() => setIsCashReceiptEditing(false)}>
                                취소
                              </button>
                              <button type="button" onClick={() => setIsCashReceiptEditing(false)}>
                                확인
                              </button>
                            </div>
                          </div>

                          {cashReceiptEnabled ? (
                            <>
                              <div className="checkout-cash-receipt-radios">
                                <label>
                                  <input
                                    type="radio"
                                    checked={cashReceiptMode === "personal"}
                                    onChange={() => {
                                      setCashReceiptMode("personal");
                                      setCashReceiptIssueMethod(CASH_RECEIPT_PERSONAL_METHODS[0]);
                                    }}
                                  />
                                  개인소득공제
                                </label>
                                <label>
                                  <input
                                    type="radio"
                                    checked={cashReceiptMode === "business"}
                                    onChange={() => {
                                      setCashReceiptMode("business");
                                      setCashReceiptIssueMethod(CASH_RECEIPT_BUSINESS_METHODS[0]);
                                    }}
                                  />
                                  사업자 지출증빙
                                </label>
                              </div>

                              <select
                                className="checkout-cash-receipt-select"
                                value={cashReceiptIssueMethod}
                                onChange={(event) => setCashReceiptIssueMethod(event.target.value)}
                              >
                                {(cashReceiptMode === "personal"
                                  ? CASH_RECEIPT_PERSONAL_METHODS
                                  : CASH_RECEIPT_BUSINESS_METHODS).map((method) => (
                                    <option value={method} key={method}>{method}</option>
                                  ))}
                              </select>

                              {cashReceiptMode === "personal" ? (
                                <div className="checkout-cash-receipt-inputs">
                                  <select
                                    value={cashReceiptPhonePrefix}
                                    onChange={(event) => setCashReceiptPhonePrefix(event.target.value)}
                                    aria-label="현금영수증 휴대폰 앞자리"
                                  >
                                    <option value="010">010</option>
                                    <option value="011">011</option>
                                    <option value="016">016</option>
                                    <option value="017">017</option>
                                    <option value="018">018</option>
                                    <option value="019">019</option>
                                  </select>
                                  <input
                                    value={cashReceiptPhoneMiddle}
                                    onChange={(event) => setCashReceiptPhoneMiddle(event.target.value)}
                                    inputMode="numeric"
                                    aria-label="현금영수증 휴대폰 중간자리"
                                  />
                                  <input
                                    value={cashReceiptPhoneLast}
                                    onChange={(event) => setCashReceiptPhoneLast(event.target.value)}
                                    inputMode="numeric"
                                    aria-label="현금영수증 휴대폰 끝자리"
                                  />
                                </div>
                              ) : (
                                <div className="checkout-cash-receipt-inputs">
                                  <input
                                    value={cashReceiptBusinessPart1}
                                    onChange={(event) => setCashReceiptBusinessPart1(event.target.value)}
                                    inputMode="numeric"
                                    aria-label="사업자등록번호 첫 번째 입력"
                                  />
                                  <input
                                    value={cashReceiptBusinessPart2}
                                    onChange={(event) => setCashReceiptBusinessPart2(event.target.value)}
                                    inputMode="numeric"
                                    aria-label="사업자등록번호 두 번째 입력"
                                  />
                                  <input
                                    value={cashReceiptBusinessPart3}
                                    onChange={(event) => setCashReceiptBusinessPart3(event.target.value)}
                                    inputMode="numeric"
                                    aria-label="사업자등록번호 세 번째 입력"
                                  />
                                </div>
                              )}
                            </>
                          ) : null}
                        </div>
                      )}
                    </section>
                  </>
                ) : null}
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
              {pointEarnNote ? <p className="checkout-point-note">{pointEarnNote}</p> : null}
              {orderErrorMessage ? (
                <p className="summary-note" role="alert">{orderErrorMessage}</p>
              ) : null}
              <button
                aria-pressed={hasAgreedPayment}
                className={`checkout-agree-button${hasAgreedPayment ? " active" : ""}`}
                type="button"
                onClick={() => setHasAgreedPayment((current) => !current)}
              >
                <span aria-hidden="true" />
                <em>주문 내용을 확인했으며 결제에 동의합니다. (필수)</em>
              </button>
              <button className="checkout-btn-main" type="button" onClick={handlePayment} disabled={paymentButtonDisabled}>
                {isCompletingPayment ? "결제 처리 중" : "결제하기"}
              </button>
            </aside>
          </div>
        </section>
      </main>

      <Dialog onOpenChange={(open) => { if (!open) closeAddressManager(); }} open={isAddressManagerOpen}>
        <DialogRawContent
          aria-labelledby="checkoutAddressModalTitle"
          className="checkout-address-modal-content-wrap"
          overlayClassName="checkout-address-modal-backdrop"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              closeAddressManager();
            }
          }}
        >
          <section className="checkout-address-modal">
            <div className="checkout-address-modal-head">
              <div>
                <h2 id="checkoutAddressModalTitle">배송지 관리</h2>
                <p>주문에 사용할 배송지를 선택하거나 새 배송지를 추가해주세요.</p>
              </div>
              <DialogClose aria-label="배송지 관리 닫기" asChild>
                <button type="button">×</button>
              </DialogClose>
            </div>

            <div className="checkout-address-modal-body">
              {isAddressLoading ? (
                <p className="checkout-address-modal-message">배송지를 불러오는 중입니다.</p>
              ) : null}
              {addressErrorMessage ? (
                <p className="checkout-address-modal-message error" role="alert">{addressErrorMessage}</p>
              ) : null}
              {!isAddressLoading && !addressErrorMessage && addresses.length === 0 ? (
                <p className="checkout-address-modal-message">저장된 배송지가 없습니다.</p>
              ) : null}

              {!isAddressLoading && !addressErrorMessage && addresses.length > 0 ? (
                <div className="checkout-address-manager-list">
                  {addresses.map((address) => (
                    <article
                      className={`checkout-address-manager-item${selectedAddressId === address.id ? " selected" : ""}`}
                      key={address.id}
                    >
                      <div>
                        <div className="checkout-address-manager-name">
                          <strong>{address.recipient_name}</strong>
                          {address.is_default ? <span>기본 배송지</span> : null}
                        </div>
                        <p>{[address.postal_code, address.address1, address.address2].filter(Boolean).join(" ")}</p>
                        <p>{address.phone}</p>
                      </div>
                      <div className="checkout-address-manager-actions">
                        <button type="button" onClick={() => handleSelectAddress(address.id)}>
                          선택
                        </button>
                        <button type="button" onClick={() => openEditAddressForm(address)}>
                          수정
                        </button>
                        {!address.is_default ? (
                          <button
                            type="button"
                            disabled={defaultingAddressId === address.id}
                            onClick={() => {
                              void handleSetDefaultAddress(address);
                            }}
                          >
                            {defaultingAddressId === address.id ? "설정 중" : "기본 설정"}
                          </button>
                        ) : null}
                        <button
                          type="button"
                          disabled={deletingAddressId === address.id || defaultingAddressId === address.id}
                          onClick={() => {
                            void handleDeleteAddress(address.id);
                          }}
                        >
                          {deletingAddressId === address.id ? "삭제 중" : "삭제"}
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              ) : null}

              {addressFormMode === "closed" ? (
                <button className="checkout-address-create-button" type="button" onClick={openCreateAddressForm}>
                  + 새 배송지 추가
                </button>
              ) : null}

              {addressFormMode !== "closed" ? (
                <form className="checkout-address-form" onSubmit={handleSaveAddress}>
                  <div className="checkout-address-form-head">
                    <strong>{addressFormMode === "edit" && editingAddressId ? "배송지 수정" : "새 배송지 추가"}</strong>
                    <button type="button" onClick={closeAddressForm}>
                      취소
                    </button>
                  </div>
                  {addressFormErrorMessage ? (
                    <p role="alert">{addressFormErrorMessage}</p>
                  ) : null}
                  <div className="checkout-address-form-grid">
                    <label>
                      받는 분
                      <input
                        value={addressForm.recipient_name}
                        onChange={(event) => updateAddressFormField("recipient_name", event.target.value)}
                        placeholder="지우"
                      />
                    </label>
                    <label>
                      연락처
                      <div className="checkout-phone-row">
                        <input
                          aria-label="연락처 앞자리"
                          inputMode="numeric"
                          maxLength={3}
                          onChange={(event) => updateAddressFormField("phone_first", event.target.value)}
                          placeholder="010"
                          value={addressForm.phone_first}
                        />
                        <span aria-hidden="true">-</span>
                        <input
                          aria-label="연락처 가운데 자리"
                          inputMode="numeric"
                          maxLength={4}
                          onChange={(event) => updateAddressFormField("phone_middle", event.target.value)}
                          placeholder="1234"
                          value={addressForm.phone_middle}
                        />
                        <span aria-hidden="true">-</span>
                        <input
                          aria-label="연락처 뒷자리"
                          inputMode="numeric"
                          maxLength={4}
                          onChange={(event) => updateAddressFormField("phone_last", event.target.value)}
                          placeholder="5678"
                          value={addressForm.phone_last}
                        />
                      </div>
                    </label>
                    <label>
                      우편번호
                      <div className="checkout-postcode-row">
                        <input
                          inputMode="numeric"
                          maxLength={5}
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
                      {postcodeErrorMessage ? (
                        <small className="checkout-postcode-error" role="alert">{postcodeErrorMessage}</small>
                      ) : null}
                    </label>
                    <label className="full">
                      주소
                      <input
                        value={addressForm.address1}
                        onChange={(event) => updateAddressFormField("address1", event.target.value)}
                        placeholder="서울시 마포구 양화로 45"
                      />
                    </label>
                    <label className="full">
                      상세 주소 (선택)
                      <input
                        id="addressFormDetail"
                        value={addressForm.address2}
                        onChange={(event) => updateAddressFormField("address2", event.target.value)}
                        placeholder="3층 302호"
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
          </section>
        </DialogRawContent>
      </Dialog>

      <Dialog onOpenChange={setIsCashReceiptGuideOpen} open={isCashReceiptGuideOpen}>
        <DialogRawContent
          aria-labelledby="cashReceiptGuideTitle"
          className="checkout-cash-receipt-modal-content-wrap"
          overlayClassName="checkout-modal-backdrop"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              setIsCashReceiptGuideOpen(false);
            }
          }}
        >
          <section className="checkout-cash-receipt-modal">
            <div className="checkout-cash-receipt-modal-head">
              <h2 id="cashReceiptGuideTitle">현금영수증 안내</h2>
              <DialogClose aria-label="현금영수증 안내 닫기" asChild>
                <button type="button">×</button>
              </DialogClose>
            </div>
            <div className="checkout-cash-receipt-modal-body">
              <ul>
                <li>무통장입금으로 결제한 주문은 입금 확인 후 현금영수증 발급 대상이 됩니다.</li>
                <li>현금영수증 신청 정보는 결제 전 주문서에서 수정할 수 있습니다.</li>
                <li>개인소득공제는 휴대폰 번호 또는 현금영수증 카드 번호 기준으로 신청할 수 있습니다.</li>
                <li>사업자 지출증빙은 사업자등록번호 기준으로 신청할 수 있습니다.</li>
                <li>쿠폰, 적립금, 할인 금액은 현금영수증 발급 금액에서 제외될 수 있습니다.</li>
                <li>주문 취소나 환불이 발생하면 발급된 현금영수증도 취소 또는 정정될 수 있습니다.</li>
                <li>발급 내역은 국세청 현금영수증 서비스에서 확인할 수 있습니다.</li>
                <li>일부 결제수단 또는 주문 상태에 따라 현금영수증 발급이 제한될 수 있습니다.</li>
              </ul>
            </div>
          </section>
        </DialogRawContent>
      </Dialog>

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
