export default function Notice({ children }: { children: React.ReactNode }) {
  if (!children) return null;

  return (
    <p role="status" className="border-l-2 border-blue-500 py-0.5 pl-2 text-[12.5px]">
      {children}
    </p>
  );
}
