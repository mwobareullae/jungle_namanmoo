import { useContext, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AuthContext } from "../../contexts/authContextValue";
import { Checkbox } from "../../components/ui/checkbox";
import { getMarketingConsent, updateMarketingConsent } from "../../lib/consentApi";
import { MyPageLayout, MypageToastMessage, PageTitle } from "./MyPageShell";

type SettingRowProps = {
  label: string;
  value: string;
  description?: string;
};

function SettingRow({ label, value, description }: SettingRowProps) {
  return (
    <div style={styles.settingRow}>
      <div>
        <strong style={styles.settingLabel}>{label}</strong>
        {description ? <p style={styles.settingDescription}>{description}</p> : null}
      </div>
      <span style={styles.settingValue}>{value}</span>
    </div>
  );
}

export default function MyPageSettings() {
  const authContext = useContext(AuthContext);
  const navigate = useNavigate();
  const [toastMessage, setToastMessage] = useState("");
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  // null: 아직 안 불러왔거나 API가 없어서(백엔드 미구현) 못 불러온 상태 — 이땐 안내 문구로 대체
  const [marketingConsent, setMarketingConsent] = useState<boolean | null>(null);
  const [isMarketingConsentSaving, setIsMarketingConsentSaving] = useState(false);
  const user = authContext?.user ?? null;

  useEffect(() => {
    if (!user) {
      return;
    }

    let isMounted = true;

    getMarketingConsent()
      .then((agreed) => {
        if (isMounted) {
          setMarketingConsent(agreed);
        }
      })
      .catch(() => {
        // 백엔드 API가 아직 없거나 실패하면 조용히 안내 문구 상태 유지
      });

    return () => {
      isMounted = false;
    };
  }, [user]);

  const handleToggleMarketingConsent = async () => {
    if (marketingConsent === null || isMarketingConsentSaving) {
      return;
    }

    const nextValue = !marketingConsent;
    setIsMarketingConsentSaving(true);

    try {
      const savedValue = await updateMarketingConsent(nextValue);
      setMarketingConsent(savedValue);
      setToastMessage(savedValue ? "마케팅 알림 수신에 동의했습니다." : "마케팅 알림 수신을 거부했습니다.");
    } catch {
      setToastMessage("마케팅 알림 설정을 저장하지 못했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setIsMarketingConsentSaving(false);
    }
  };

  const handleLogout = async () => {
    if (!authContext || isLoggingOut) {
      return;
    }

    setIsLoggingOut(true);
    try {
      await authContext.logout();
      navigate("/login", { replace: true });
    } catch {
      setToastMessage("로그아웃에 실패했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setIsLoggingOut(false);
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
              <SettingRow label="닉네임" value={user?.nickname?.trim() || "미설정"} />
            </div>
          </div>
        </section>

        <section aria-labelledby="securitySettingsTitle" style={styles.card}>
          <div style={styles.cardHeader}>
            <h2 id="securitySettingsTitle" style={styles.cardTitle}>보안</h2>
            <p style={styles.cardDescription}>비밀번호 재설정과 세션 관리를 진행할 수 있어요.</p>
          </div>

          <div style={styles.cardBody}>
            <div style={styles.actionRow}>
              <div>
                <strong style={styles.settingLabel}>비밀번호</strong>
                <p style={styles.settingDescription}>가입 이메일로 재설정 안내를 받아 변경합니다.</p>
              </div>
              <Link className="bg-white hover:bg-[#FAFAFA]" style={styles.secondaryButton} to="/password-reset">
                재설정
              </Link>
            </div>

          <div style={styles.actionRow}>
            <div>
              <strong style={styles.settingLabel}>로그아웃</strong>
            </div>
            <button
                className="bg-white hover:bg-[#fff5f3]"
                disabled={isLoggingOut}
                onClick={() => void handleLogout()}
                style={styles.dangerButton}
                type="button"
              >
                {isLoggingOut ? "처리 중" : "로그아웃"}
              </button>
            </div>
          </div>
        </section>

        <section aria-labelledby="preferenceSettingsTitle" style={styles.card}>
          <div style={styles.cardHeader}>
            <h2 id="preferenceSettingsTitle" style={styles.cardTitle}>알림 및 맞춤 설정</h2>
            <p style={styles.cardDescription}>세부 수신 설정은 API 확정 후 이 화면에서 연결합니다.</p>
          </div>

          <div style={styles.cardBody}>
            <div style={styles.settingList}>
              <SettingRow
                description="추천 결과와 피부 프로필 기반 화면은 현재 저장된 프로필을 기준으로 표시됩니다."
                label="맞춤 추천"
                value="사용 중"
              />
              {marketingConsent === null ? (
                <SettingRow
                  description="마케팅 수신 동의 상태는 추후 약관/회원 API와 함께 연동됩니다."
                  label="마케팅 알림"
                  value="연동 예정"
                />
              ) : (
                <div style={styles.settingRow}>
                  <div>
                    <strong style={styles.settingLabel}>마케팅 알림</strong>
                    <p style={styles.settingDescription}>
                      이벤트·할인 정보를 이메일/문자로 받아볼 수 있어요. 언제든 끌 수 있어요.
                    </p>
                  </div>
                  <label style={styles.consentToggle}>
                    <Checkbox
                      checked={marketingConsent}
                      disabled={isMarketingConsentSaving}
                      onCheckedChange={() => void handleToggleMarketingConsent()}
                    />
                    <span style={styles.consentToggleLabel}>
                      {marketingConsent ? "수신 동의" : "수신 거부"}
                    </span>
                  </label>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>

      {toastMessage ? <MypageToastMessage message={toastMessage} /> : null}
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
  consentToggle: {
    display: "inline-flex",
    flex: "0 0 auto",
    alignItems: "center",
    gap: 8,
    cursor: "pointer"
  },
  consentToggleLabel: {
    color: "#3D3D3D",
    fontSize: 14,
    fontWeight: 600
  },
  actionRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 20,
    minHeight: 76,
    borderBottom: "1px solid #f2f4f6"
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
