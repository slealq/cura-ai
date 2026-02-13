import EvaluationResultsPage from './EvaluationResultsPage';

export async function generateStaticParams() {
  return [{ id: '_', evalId: '_' }];
}

export default function Page() {
  return <EvaluationResultsPage />;
}
