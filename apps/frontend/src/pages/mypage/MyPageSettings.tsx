import { useContext, useState } from "react";
import type { CSSProperties } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AuthContext } from "../../contexts/authContextValue";
import ActivityToast from "../../components/ui/ActivityToast";
import ConfirmModal from "../../components/ui/ConfirmModal";
import { Input } from "../../components/ui/input";
import { useActivityToast } from "../../hooks/useActivityToast";
import { deleteAccount, updateNickname } from "../../lib/accountApi";
import { MyPageLayout, PageTitle } from "./MyPageShell";

type SettingRowProps = {
  label: string;
  value: string;
};

function SettingRow({ label, value }: SettingRowProps) {
  return (
    <div style={styles.settingRow}>
      <div>
        <strong style={styles.settingLabel}>{label}</strong>
      </div>
      <span style={styles.settingValue}>{value}</span>
    </div>
  );
}

export default function MyPageSettings() {
  const authContext = useContext(AuthContext);
  const navigate = useNavigate();
  const { message: toastMessage, showToast } = useActivityToast();
  const [isEditingNickname, setIsEditingNickname] = useState(false);
  const [nicknameDraft, setNicknameDraft] = useState("");
  const [nicknameError, setNicknameError] = useState("");
  const [isSavingNickname, setIsSavingNickname] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [isDeletingAccount, setIsDeletingAccount] = useState(false);
  const user = authContext?.user ?? null;

  const handleNicknameSave = async () => {
    if (!authContext || isSavingNickname) {
      return;
    }

    const normalized = nicknameDraft.trim();
    if (!normalized) {
      setNicknameError("닉네임을 입력해 주세요.");
      return;
    }
    if (normalized.length > 100) {
      setNicknameError("닉네임은 100자 이하로 입력해 주세요.");
      return;
    }

    if (normalized === user?.nickname?.trim()) {
      setIsEditingNickname(false);
      return;
    }

    setIsSavingNickname(true);
    setNicknameError("");
    try {
      const updatedUser = await updateNickname(normalized);
      authContext.setAuthenticatedUser(updatedUser);
      setNicknameDraft(updatedUser.nickname?.trim() ?? "");
      setIsEditingNickname(false);
      showToast("닉네임을 변경했습니다.");
    } catch (error) {
      setNicknameError(error instanceof Error ? error.message : "닉네임을 변경하지 못했습니다.");
    } finally {
      setIsSavingNickname(false);
    }
  };

  const handleDeleteAccount = async () => {
    if (!authContext || isDeletingAccount) {
      return;
    }

    setIsDeletingAccount(true);
    try {
      await deleteAccount();
      await authContext.logout();
      navigate("/", { replace: true });
    } catch (error) {
      const message = error instanceof Error ? error.message : "회원탈퇴에 실패했습니다.";
      showToast(message);
      setIsDeleteModalOpen(false);
    } finally {
      setIsDeletingAccount(false);
    }
  };

  return (
    <MyPageLayout activePath="/mypage/settings">
      <PageTitle title="개인정보 설정" />

      <div style={styles.stack}>
        <section aria-labelledby="accountSettingsTitle" style={styles.card}>
          <div style={styles.cardHeader}>
            <h2 id="accountSettingsTitle" style={styles.cardTitle}>계정 정보</h2>
            <p style={styles.cardDescription}>로그인 계정과 기본 회원 정보를 확인할 수 있어요.</p>
          </div>

          <div style={styles.cardBody}>
            <div style={styles.settingList}>
              <SettingRow label="이메일" value={user?.email ?? "-"} />
              <div style={{ ...styles.actionRow, ...styles.lastRow }}>
                <div>
                  <strong style={styles.settingLabel}>닉네임</strong>
                  {nicknameError ? <p role="alert" style={styles.errorText}>{nicknameError}</p> : null}
                </div>
                {isEditingNickname ? (
                  <div style={styles.nicknameEditor}>
                    <Input
                      aria-label="새 닉네임"
                      disabled={isSavingNickname}
                      maxLength={100}
                      onChange={(event) => {
                        setNicknameDraft(event.target.value);
                        setNicknameError("");
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          void handleNicknameSave();
                        }
                      }}
                      placeholder="새 닉네임"
                      style={styles.nicknameInput}
                      value={nicknameDraft}
                    />
                    <button
                      className="bg-white hover:bg-[#FAFAFA]"
                      disabled={isSavingNickname}
                      onClick={() => {
                        setNicknameDraft(user?.nickname?.trim() ?? "");
                        setNicknameError("");
                        setIsEditingNickname(false);
                      }}
                      style={styles.compactButton}
                      type="button"
                    >
                      취소
                    </button>
                    <button
                      className="bg-[#1A1A1A] hover:bg-[#333333]"
                      disabled={isSavingNickname}
                      onClick={() => void handleNicknameSave()}
                      style={styles.saveButton}
                      type="button"
                    >
                      {isSavingNickname ? "저장 중" : "저장"}
                    </button>
                  </div>
                ) : (
                  <div style={styles.nicknameValueGroup}>
                    <span style={styles.settingValue}>{user?.nickname?.trim() || "미설정"}</span>
                    <button
                      className="bg-white hover:bg-[#FAFAFA]"
                      onClick={() => {
                        setNicknameDraft(user?.nickname?.trim() ?? "");
                        setNicknameError("");
                        setIsEditingNickname(true);
                      }}
                      style={styles.compactButton}
                      type="button"
                    >
                      변경
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </section>

        <section aria-labelledby="securitySettingsTitle" style={styles.card}>
          <div style={styles.cardHeader}>
            <h2 id="securitySettingsTitle" style={styles.cardTitle}>보안</h2>
            <p style={styles.cardDescription}>가입 이메일을 통해 비밀번호를 안전하게 변경할 수 있어요.</p>
          </div>

          <div style={styles.cardBody}>
            <div style={{ ...styles.actionRow, ...styles.lastRow }}>
              <div>
                <strong style={styles.settingLabel}>비밀번호</strong>
                <p style={styles.settingDescription}>가입 이메일로 재설정 안내를 받아 변경합니다.</p>
              </div>
              <Link className="bg-white hover:bg-[#FAFAFA]" style={styles.secondaryButton} to="/password-reset">
                재설정
              </Link>
            </div>

          </div>
        </section>

        <section aria-labelledby="membershipSettingsTitle" style={styles.card}>
          <div style={styles.cardHeader}>
            <h2 id="membershipSettingsTitle" style={styles.cardTitle}>회원 관리</h2>
            <p style={styles.cardDescription}>탈퇴하면 계정과 개인화 정보를 복구할 수 없습니다.</p>
          </div>

          <div style={styles.cardBody}>
            <div style={{ ...styles.actionRow, ...styles.lastRow }}>
              <div>
                <strong style={styles.settingLabel}>회원탈퇴</strong>
                <p style={styles.settingDescription}>
                  개인정보와 저장 활동은 삭제되며 주문·결제 내역은 관련 정책에 따라 보관됩니다.
                </p>
              </div>
              <button
                className="bg-white hover:bg-[#fff5f3]"
                disabled={isDeletingAccount}
                onClick={() => setIsDeleteModalOpen(true)}
                style={styles.dangerButton}
                type="button"
              >
                회원탈퇴
              </button>
            </div>
          </div>
        </section>
      </div>

      <ActivityToast message={toastMessage} />
      <ConfirmModal
        cancelLabel="계속 이용하기"
        confirmLabel={isDeletingAccount ? "처리 중" : "탈퇴하기"}
        message="탈퇴하면 개인정보와 맞춤 정보가 삭제되며 복구할 수 없습니다. 정말 탈퇴하시겠어요?"
        onCancel={() => {
          if (!isDeletingAccount) {
            setIsDeleteModalOpen(false);
          }
        }}
        onConfirm={() => void handleDeleteAccount()}
        open={isDeleteModalOpen}
        title="회원탈퇴"
      />
    </MyPageLayout>
  );
}

const styles: Record<string, CSSProperties> = {
  stack: {
    display: "grid",
    gap: 18
  },
  card: {
    border: "1px solid rgba(0, 0, 0, 0.07)",
    borderRadius: 8,
    background: "#ffffff",
    overflow: "hidden"
  },
  cardHeader: {
    padding: "18px 26px",
    background: "#FAFAFA",
    borderBottom: "1px solid rgba(0, 0, 0, 0.06)"
  },
  cardTitle: {
    margin: 0,
    color: "#1A1A1A",
    fontSize: 17,
    fontWeight: 700,
    lineHeight: 1.35
  },
  cardDescription: {
    margin: "6px 0 0",
    color: "#6B7280",
    fontSize: 13,
    fontWeight: 500,
    lineHeight: 1.55
  },
  cardBody: {
    padding: "4px 26px 8px"
  },
  settingList: {
    display: "grid",
    gap: 0
  },
  settingRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 20,
    minHeight: 64,
    borderBottom: "1px solid #f2f4f6"
  },
  settingLabel: {
    display: "block",
    color: "#1A1A1A",
    fontSize: 14,
    fontWeight: 600,
    lineHeight: 1.4
  },
  settingDescription: {
    margin: "5px 0 0",
    color: "#6B7280",
    fontSize: 13,
    fontWeight: 500,
    lineHeight: 1.5
  },
  settingValue: {
    flex: "0 0 auto",
    color: "#3D3D3D",
    fontSize: 14,
    fontWeight: 600,
    textAlign: "right"
  },
  nicknameValueGroup: {
    display: "inline-flex",
    alignItems: "center",
    gap: 12
  },
  nicknameEditor: {
    display: "flex",
    flex: "1 1 360px",
    alignItems: "center",
    justifyContent: "flex-end",
    gap: 8,
    maxWidth: 440
  },
  nicknameInput: {
    flex: "1 1 220px",
    minWidth: 0
  },
  errorText: {
    margin: "5px 0 0",
    color: "#D92D20",
    fontSize: 13,
    fontWeight: 500,
    lineHeight: 1.45
  },
  actionRow: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 20,
    minHeight: 76,
    borderBottom: "1px solid #f2f4f6"
  },
  lastRow: {
    borderBottom: "none"
  },
  secondaryButton: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: 40,
    minWidth: 82,
    padding: "0 18px",
    border: "1px solid #e1e5e8",
    borderRadius: 999,
    color: "#1A1A1A",
    fontSize: 14,
    fontWeight: 600,
    textDecoration: "none"
  },
  compactButton: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: 36,
    minWidth: 62,
    padding: "0 14px",
    border: "1px solid #e1e5e8",
    borderRadius: 999,
    color: "#1A1A1A",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer"
  },
  saveButton: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: 36,
    minWidth: 62,
    padding: "0 14px",
    border: "1px solid #1A1A1A",
    borderRadius: 999,
    color: "#FFFFFF",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer"
  },
  dangerButton: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: 40,
    minWidth: 92,
    padding: "0 18px",
    border: "1px solid rgba(255, 107, 82, 0.36)",
    borderRadius: 999,
    color: "#FF6B52",
    fontSize: 14,
    fontWeight: 600,
    cursor: "pointer"
  }
};
