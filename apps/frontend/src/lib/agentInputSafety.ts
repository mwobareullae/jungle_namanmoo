const secretPatterns = [
  /\bsk-[A-Za-z0-9_-]{16,}\b/,
  /\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b/i,
  /\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/,
  /(?:비밀번호|password|passwd|pwd)\s*(?:[:=]|은|는)\s*\S{4,}/i,
  /(?:api[ _-]?key|access[ _-]?token|refresh[ _-]?token)\s*(?:[:=]|은|는)\s*\S{8,}/i,
];
const cardHintPattern = /(?:카드(?:번호)?|card(?: number)?|cvc|cvv)/i;
const cardNumberPattern = /(?:\d[ -]?){13,19}/;

export const getSensitiveAgentInputMessage = (value: string): string | null => {
  if (secretPatterns.some((pattern) => pattern.test(value))) {
    return "비밀번호·토큰·API 키는 채팅에 입력할 수 없어요.";
  }

  if (cardHintPattern.test(value) && cardNumberPattern.test(value)) {
    return "카드 정보는 채팅에 입력할 수 없어요.";
  }

  return null;
};
