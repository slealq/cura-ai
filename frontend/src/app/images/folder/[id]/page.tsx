import FolderDetailPage from './FolderDetailPage';

export async function generateStaticParams() {
  return [{ id: '_' }];
}

export default function Page() {
  return <FolderDetailPage />;
}
