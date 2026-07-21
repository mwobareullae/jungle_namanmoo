export type PhoneParts = {
  first: string;
  middle: string;
  last: string;
};

export const emptyPhoneParts: PhoneParts = {
  first: "",
  middle: "",
  last: ""
};

export const digitsOnly = (value: string) => value.replace(/\D/g, "");

export const sanitizeRecipientName = (value: string) => value.replace(/[^\p{L} ·'-]/gu, "");

export const splitPhone = (value: string): PhoneParts => {
  const digits = digitsOnly(value);
  const isTenDigitPhone = digits.length === 10;
  return {
    first: digits.slice(0, 3),
    middle: isTenDigitPhone ? digits.slice(3, 6) : digits.slice(3, 7),
    last: isTenDigitPhone ? digits.slice(6, 10) : digits.slice(7, 11)
  };
};

export const joinPhone = ({ first, middle, last }: PhoneParts) => `${first}${middle}${last}`;

export const isCompletePhone = ({ first, middle, last }: PhoneParts) =>
  first.length === 3 && middle.length >= 3 && middle.length <= 4 && last.length === 4;

export const hasText = (value: string) => Boolean(value.trim());
