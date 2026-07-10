import { useNavigate } from "react-router-dom";
import { Dialog, DialogClose, DialogRawContent } from "./ui/dialog";

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
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogRawContent
        aria-describedby="loginRequiredDialogDescription"
        aria-labelledby="loginRequiredDialogTitle"
        className="login-required-dialog"
        overlayClassName="login-required-dialog-backdrop"
      >
        <div className="login-required-dialog__body">
          <h2 id="loginRequiredDialogTitle">로그인이 필요한 서비스입니다.</h2>
          <p id="loginRequiredDialogDescription">로그인 하시겠습니까?</p>
        </div>
        <div className="login-required-dialog__actions">
          <DialogClose asChild>
            <button className="login-required-dialog__button" type="button">
              닫기
            </button>
          </DialogClose>
          <button
            className="login-required-dialog__button login-required-dialog__button--primary"
            onClick={handleLoginClick}
            type="button"
          >
            로그인 하기
          </button>
        </div>
      </DialogRawContent>
    </Dialog>
  );
}

export default LoginRequiredDialog;
