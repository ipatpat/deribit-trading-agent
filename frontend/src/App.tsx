import { Routes, Route } from 'react-router-dom';
import Layout from './components/layout/Layout';
import ToastContainer from './components/common/ToastContainer';
import Dashboard from './pages/Dashboard';
import Options from './pages/Options';
import Futures from './pages/Futures';
import SmartOrders from './pages/SmartOrders';
import Risk from './pages/Risk';
import Settings from './pages/Settings';

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/options" element={<Options />} />
        <Route path="/futures" element={<Futures />} />
        <Route path="/smart-orders" element={<SmartOrders />} />
        <Route path="/risk" element={<Risk />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
      <ToastContainer />
    </Layout>
  );
}

export default App;
