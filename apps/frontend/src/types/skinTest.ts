export type SkinTestTypeCode =
  | "OSNT"
  | "OSNW"
  | "OSPT"
  | "OSPW"
  | "ORNT"
  | "ORNW"
  | "ORPT"
  | "ORPW"
  | "DSNT"
  | "DSNW"
  | "DSPT"
  | "DSPW"
  | "DRNT"
  | "DRNW"
  | "DRPT"
  | "DRPW";

export type SkinTestOption = {
  id: number | string;
  text: string;
};

export type SkinTestQuestion = {
  id: number | string;
  text: string;
  options: SkinTestOption[];
  skip_conditions?: unknown;
};

export type SkinTestQuestionsResponse = {
  version: string;
  questions: SkinTestQuestion[];
};

export type SkinTestAnswer = {
  question_id: number | string;
  option_id: number | string;
};

export type SkinTestSubmitRequest = {
  version: string;
  answers: SkinTestAnswer[];
};

export type SkinTestResult = {
  result_id: number;
  skin_type: string;
  sensitivity: string;
  recommended_effects: string[];
  avoid_hint?: string[];
  concern_tags?: string[];
  type_code?: SkinTestTypeCode | string;
  title?: string;
  subtitle?: string;
  image_storage_key?: string;
};

export type SkinTestSubmitResponse = SkinTestResult;

export type SkinTestResultResponse = {
  result: SkinTestResult;
};

export type ApplySkinTestResultRequest = {
  result_id: number;
};

export type ApplySkinTestResultResponse = {
  success?: boolean;
  skin_profile?: {
    skin_type?: string | null;
    sensitivity?: string | null;
    latest_skin_test_result_id?: number | null;
  };
};
