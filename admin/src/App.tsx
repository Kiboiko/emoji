import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './context/AuthContext';
import { ToastProvider } from './components/ui/Toast';
import { Login } from './pages/Login';
import { AdminLayout } from './layouts/AdminLayout';
import { Dashboard } from './pages/Dashboard';
import { Categories } from './pages/Categories';
import { Products } from './pages/Products';
import { Users } from './pages/Users';
import { Orders } from './pages/Orders';
import { Withdrawals } from './pages/Withdrawals';
import { Reviews } from './pages/Reviews';
import ProcessingPage from './pages/ProcessingPage';
import { Settings } from './pages/Settings';
import { Moderation } from './pages/Moderation';
import { Deals } from './pages/Deals';
import { Subscriptions } from './pages/Subscriptions';
import { Finance } from './pages/Finance';
import { Referrals } from './pages/Referrals';
const queryClient = new QueryClient();

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
      <AuthProvider>
        <BrowserRouter basename="/admin">
          <Routes>
            <Route path="/login" element={<Login />} />

            <Route path="/" element={<AdminLayout />}>
              <Route index element={<Dashboard />} />
              <Route path="processing" element={<ProcessingPage />} />
              <Route path="products" element={<Products />} />
              <Route path="categories" element={<Categories />} />
              <Route path="orders" element={<Orders />} />
              <Route path="users" element={<Users />} />
              <Route path="reviews" element={<Reviews />} />
              <Route path="withdrawals" element={<Withdrawals />} />
              <Route path="moderation" element={<Moderation />} />
              <Route path="deals" element={<Deals />} />
              <Route path="subscriptions" element={<Subscriptions />} />
              <Route path="finance" element={<Finance />} />
              <Route path="referrals" element={<Referrals />} />
              <Route path="settings" element={<Settings />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default App;
