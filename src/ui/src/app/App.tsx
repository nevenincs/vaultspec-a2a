import '../styles/index.css';
import { QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { queryClient } from './queries/query-client';
import { AppShell } from './components/layout/app-shell';

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppShell />
      {import.meta.env.DEV && <ReactQueryDevtools initialIsOpen={false} />}
    </QueryClientProvider>
  );
}
