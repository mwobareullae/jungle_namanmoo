import { useEffect } from "react";
import { Link } from "react-router-dom";
import HomeHeader from "../components/HomeHeader";
import { privacyPolicy, termsOfService } from "../content/terms";
import { renderTermBody } from "./SignupTermsPage";

type LegalDocumentPageProps = {
  documentType: "terms" | "privacy";
};

const documents = {
  terms: {
    title: "이용약관",
    body: termsOfService
  },
  privacy: {
    title: "개인정보처리방침",
    body: privacyPolicy
  }
} as const;

function LegalDocumentPage({ documentType }: LegalDocumentPageProps) {
  const document = documents[documentType];

  useEffect(() => {
    const previousTitle = window.document.title;
    window.document.title = `${document.title} | 뭐바를래`;
    return () => {
      window.document.title = previousTitle;
    };
  }, [document.title]);

  return (
    <div className="category-page legal-document-page">
      <HomeHeader />
      <main className="category-page__main legal-document-page__main">
        <nav className="category-page__breadcrumb" aria-label={`${document.title} 경로`}>
          <Link to="/">홈</Link>
          <span aria-hidden="true">&gt;</span>
          <span>{document.title}</span>
        </nav>
        <h1 className="category-page__title">{document.title}</h1>
        <article className="legal-document-page__content">
          {renderTermBody(document.body)}
        </article>
      </main>
    </div>
  );
}

export default LegalDocumentPage;
