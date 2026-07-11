import { useNavigate } from "react-router-dom";
import ConfirmModal from "./ui/ConfirmModal";

type LoginRequiredDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  redirectTo?: string;
};

const getCurrentRedirectPath = () => `${window.location.pathname}${window.location.search}${window.location.hash}`;

function LoginRequiredDialog({ open, onOpenChange, redirectTo }: LoginRequiredDialogProps) {
  const navigate = useNavigate();

  const handleLoginClick = () => {
    onOpenChange(false);
    navigate("/login", {
      state: {
        from: redirectTo ?? getCurrentRedirectPath(),
      },
    });
  };

  return (
    <ConfirmModal
      cancelLabel="닫기"
      confirmLabel="로그인 하기"
      message="로그인 하시겠습니까?"
      onCancel={() => onOpenChange(false)}
      onConfirm={handleLoginClick}
      open={open}
      title="로그인이 필요한 서비스입니다."
    />
  );
}

export default LoginRequiredDialog;
