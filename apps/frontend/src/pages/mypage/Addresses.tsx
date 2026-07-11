import type { CSSProperties, FormEvent } from "react";
import { useCallback, useEffect, useState } from "react";
import { createAddress, deleteAddress, getAddresses, updateAddress } from "../../lib/addressApi";
import type { UserAddress, UserAddressCreateRequest } from "../../types/address";
import { MyPageLayout, PageTitle } from "./MyPageShell";

type AddressForm = Omit<UserAddressCreateRequest, "is_default"> & { is_default: boolean };
const emptyForm: AddressForm = { recipient_name: "", phone: "", postal_code: "", address1: "", address2: "", delivery_memo: "", is_default: false };

const toForm = (address: UserAddress): AddressForm => ({
  recipient_name: address.recipient_name,
  phone: address.phone,
  postal_code: address.postal_code,
  address1: address.address1,
  address2: address.address2 ?? "",
  delivery_memo: address.delivery_memo ?? "",
  is_default: address.is_default
});

export default function Addresses() {
  const [addresses, setAddresses] = useState<UserAddress[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");
  const [formMode, setFormMode] = useState<"closed" | "create" | "edit">("closed");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<AddressForm>(emptyForm);
  const [isSaving, setIsSaving] = useState(false);
  const [actionId, setActionId] = useState<number | null>(null);

  const loadAddresses = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage("");
    try {
      const response = await getAddresses();
      setAddresses(response.items);
    } catch {
      setErrorMessage("배송지 목록을 불러오지 못했습니다.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { void loadAddresses(); }, [loadAddresses]);

  const openCreate = () => {
    setEditingId(null);
    setForm(emptyForm);
    setFormMode("create");
  };

  const openEdit = (address: UserAddress) => {
    setEditingId(address.id);
    setForm(toForm(address));
    setFormMode("edit");
  };

  const saveForm = async (event: FormEvent) => {
    event.preventDefault();
    if (!form.recipient_name.trim() || !form.phone.trim() || !form.postal_code.trim() || !form.address1.trim()) {
      setErrorMessage("받는 분, 연락처, 우편번호, 주소를 입력해주세요.");
      return;
    }
    setIsSaving(true);
    setErrorMessage("");
    const payload: UserAddressCreateRequest = {
      recipient_name: form.recipient_name.trim(), phone: form.phone.trim(), postal_code: form.postal_code.trim(),
      address1: form.address1.trim(), address2: form.address2?.trim() || null,
      delivery_memo: form.delivery_memo?.trim() || null, is_default: form.is_default
    };
    try {
      if (formMode === "edit" && editingId !== null) await updateAddress(editingId, payload);
      else await createAddress(payload);
      setFormMode("closed");
      await loadAddresses();
    } catch {
      setErrorMessage("배송지 저장에 실패했습니다.");
    } finally {
      setIsSaving(false);
    }
  };

  const setDefault = async (address: UserAddress) => {
    setActionId(address.id);
    try { await updateAddress(address.id, { is_default: true }); await loadAddresses(); }
    catch { setErrorMessage("기본 배송지 설정에 실패했습니다."); }
    finally { setActionId(null); }
  };

  const remove = async (address: UserAddress) => {
    if (!window.confirm("이 배송지를 삭제할까요?")) return;
    setActionId(address.id);
    try { await deleteAddress(address.id); await loadAddresses(); }
    catch { setErrorMessage("배송지 삭제에 실패했습니다."); }
    finally { setActionId(null); }
  };

  return (
    <MyPageLayout activePath="/mypage/addresses">
      <PageTitle title="배송지 관리" />
      {errorMessage ? <p style={styles.error} role="alert">{errorMessage}</p> : null}
      <section style={styles.card} aria-label="배송지 목록">
        <div style={styles.cardHeader}><h2 style={styles.title}>저장된 배송지</h2><button onClick={openCreate} style={styles.primaryButton} type="button">+ 배송지 추가</button></div>
        {isLoading ? <p style={styles.state}>배송지 목록을 불러오는 중입니다.</p> : addresses.length === 0 ? <p style={styles.state}>저장된 배송지가 없습니다.</p> : (
          <div style={styles.list}>
            {addresses.map((address) => (
              <article key={address.id} style={styles.item}>
                <div><div style={styles.itemTitle}>{address.recipient_name} {address.is_default ? <span style={styles.badge}>기본 배송지</span> : null}</div><p style={styles.text}>{address.phone}</p><p style={styles.text}>[{address.postal_code}] {address.address1} {address.address2 ?? ""}</p></div>
                <div style={styles.actions}><button onClick={() => openEdit(address)} style={styles.secondaryButton} type="button">수정</button>{!address.is_default ? <button disabled={actionId === address.id} onClick={() => void setDefault(address)} style={styles.secondaryButton} type="button">기본 설정</button> : null}<button disabled={actionId === address.id} onClick={() => void remove(address)} style={styles.deleteButton} type="button">삭제</button></div>
              </article>
            ))}
          </div>
        )}
      </section>
      {formMode !== "closed" ? <form onSubmit={saveForm} style={styles.form}><div style={styles.cardHeader}><h2 style={styles.title}>{formMode === "edit" ? "배송지 수정" : "새 배송지 추가"}</h2><button onClick={() => setFormMode("closed")} style={styles.closeButton} type="button">닫기</button></div>{(["recipient_name", "phone", "postal_code", "address1", "address2", "delivery_memo"] as const).map((field) => <label key={field} style={styles.field}>{({ recipient_name: "받는 분", phone: "연락처", postal_code: "우편번호", address1: "주소", address2: "상세 주소", delivery_memo: "배송 메모" } as Record<string, string>)[field]}<input required={["recipient_name", "phone", "postal_code", "address1"].includes(field)} value={form[field] ?? ""} onChange={(event) => setForm((current) => ({ ...current, [field]: event.target.value }))} style={styles.input} /></label>)}<label style={styles.checkbox}><input checked={form.is_default} onChange={(event) => setForm((current) => ({ ...current, is_default: event.target.checked }))} type="checkbox" /> 기본 배송지로 설정</label><button disabled={isSaving} style={styles.saveButton} type="submit">{isSaving ? "저장 중" : "저장하기"}</button></form> : null}
    </MyPageLayout>
  );
}

const styles: Record<string, CSSProperties> = {
  card: { padding: 28, border: "1px solid #e6e9ee", borderRadius: 14, background: "#fff" },
  form: { display: "grid", gap: 14, marginTop: 20, padding: 28, border: "1px solid #e6e9ee", borderRadius: 14, background: "#fafbfc" },
  cardHeader: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, marginBottom: 20 },
  title: { margin: 0, color: "#222", fontSize: 18, fontWeight: 700 },
  list: { display: "grid", gap: 12 },
  item: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 20, padding: 18, border: "1px solid #edf0f2", borderRadius: 10 },
  itemTitle: { color: "#222", fontSize: 15, fontWeight: 700 },
  text: { margin: "6px 0 0", color: "#6b7280", fontSize: 13 },
  badge: { marginLeft: 8, padding: "4px 8px", borderRadius: 999, background: "rgba(148,224,248,.2)", color: "#12617a", fontSize: 11 },
  actions: { display: "flex", flexWrap: "wrap" as const, justifyContent: "flex-end", gap: 6 },
  field: { display: "grid", gap: 7, color: "#444", fontSize: 13, fontWeight: 600 },
  input: { minHeight: 42, padding: "0 12px", border: "1px solid #dfe4e8", borderRadius: 8, background: "#fff", font: "inherit" },
  state: { margin: 0, padding: "44px 0", color: "#8b929b", textAlign: "center" as const, fontSize: 14 },
  error: { margin: "0 0 14px", color: "#b42318", fontSize: 13 },
  checkbox: { display: "flex", alignItems: "center", gap: 8, color: "#555", fontSize: 13 },
  primaryButton: { minHeight: 38, padding: "0 14px", border: 0, borderRadius: 8, background: "#0c1117", color: "#fff", fontWeight: 700, cursor: "pointer" },
  saveButton: { minHeight: 44, border: 0, borderRadius: 8, background: "#0c1117", color: "#fff", fontWeight: 700, cursor: "pointer" },
  secondaryButton: { minHeight: 34, padding: "0 10px", border: "1px solid #dfe4e8", borderRadius: 7, background: "#fff", color: "#444", cursor: "pointer" },
  deleteButton: { minHeight: 34, padding: "0 10px", border: "0", borderRadius: 7, background: "#fff1f0", color: "#b42318", cursor: "pointer" },
  closeButton: { border: 0, background: "transparent", color: "#777", cursor: "pointer" }
};
